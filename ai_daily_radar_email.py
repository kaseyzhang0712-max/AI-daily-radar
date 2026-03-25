import html
import json
import os
import smtplib
import ssl
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

HF_API = "https://huggingface.co/api/models"
PH_TOKEN_URL = "https://api.producthunt.com/v2/oauth/token"
PH_GRAPHQL_URL = "https://api.producthunt.com/v2/api/graphql"

_ph_token_cache = {"access_token": None, "expires_at": 0}


# =====================
# 基础抓取
# =====================
def fetch_models():
    params = {"limit": 100, "sort": "lastModified", "direction": -1}
    resp = requests.get(HF_API, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_news():
    url = "https://news.google.com/rss/search?q=AI&hl=en-US&gl=US&ceid=US:en"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    return root.findall(".//item")


# =====================
# Product Hunt 真实接口
# =====================
def get_product_hunt_token():
    global _ph_token_cache

    now = time.time()
    if _ph_token_cache["access_token"] and now < _ph_token_cache["expires_at"] - 60:
        return _ph_token_cache["access_token"]

    client_id = os.environ.get("PRODUCT_HUNT_CLIENT_ID")
    client_secret = os.environ.get("PRODUCT_HUNT_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise RuntimeError("Missing PRODUCT_HUNT_CLIENT_ID or PRODUCT_HUNT_CLIENT_SECRET")

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }

    resp = requests.post(PH_TOKEN_URL, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    access_token = data["access_token"]
    expires_in = data.get("expires_in", 3600)

    _ph_token_cache = {
        "access_token": access_token,
        "expires_at": now + expires_in,
    }
    return access_token


def fetch_product_hunt_products():
    token = get_product_hunt_token()

    query = """
    query GetPosts {
      posts(first: 10, order: VOTES) {
        edges {
          node {
            id
            name
            tagline
            description
            votesCount
            url
            website
            createdAt
            topics(first: 5) {
              edges {
                node {
                  name
                }
              }
            }
          }
        }
      }
    }
    """

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    resp = requests.post(
        PH_GRAPHQL_URL,
        headers=headers,
        json={"query": query},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if "errors" in data:
        raise RuntimeError(f"Product Hunt GraphQL error: {data['errors']}")

    edges = data["data"]["posts"]["edges"]
    products = []

    for edge in edges:
        node = edge["node"]
        topics = [t["node"]["name"] for t in node.get("topics", {}).get("edges", [])]

        products.append(
            {
                "name": node["name"],
                "tagline": node.get("tagline") or "",
                "description": node.get("description") or "",
                "votes": node.get("votesCount", 0),
                "url": node.get("url") or node.get("website") or "https://www.producthunt.com/",
                "topics": topics,
                "created_at": node.get("createdAt"),
            }
        )

    return products


def safe_fetch_product_hunt_products():
    try:
        return fetch_product_hunt_products()
    except Exception as e:
        print(f"Product Hunt fetch failed: {e}")
        return []


# =====================
# Hugging Face 模型逻辑
# =====================
def is_good_model(m):
    downloads = m.get("downloads", 0) or 0
    likes = m.get("likes", 0) or 0
    return downloads > 20 or likes > 5


def explain_model(m):
    tags = " ".join(m.get("tags", [])).lower()
    pipeline = (m.get("pipeline_tag") or "").lower()
    text = f"{tags} {pipeline}"

    if "agent" in text:
        return "AI Agent 相关模型，可能用于自动执行任务或工作流"
    if "vision" in text or "image" in text or "vl" in text:
        return "多模态模型，可处理图像与文本理解"
    if "code" in text or "coder" in text:
        return "代码生成 / 编程辅助模型，适合 coding 场景"
    if "audio" in text or "speech" in text:
        return "语音 / 音频相关模型"
    if "embedding" in text:
        return "向量表示模型，常用于检索、RAG 和相似度计算"
    if "llm" in text or "text-generation" in text or "chat" in text:
        return "大语言模型，适合文本生成、问答和对话"
    return "通用 AI 模型"


def model_score(m):
    downloads = m.get("downloads", 0) or 0
    likes = m.get("likes", 0) or 0
    return downloads + likes * 20


# =====================
# 新闻逻辑
# =====================
def summarize_news(title: str):
    t = title.lower()

    if "sora" in t:
        return (
            "OpenAI 对视频生成产品线做出调整，说明视频生成赛道在落地和风险控制上仍有挑战。",
            "这表明 AI 竞争不只是模型能力，还包括产品化和合规能力。"
        )
    if "agent" in t:
        return (
            "AI Agent 正在从概念验证走向更复杂的任务执行场景。",
            "说明行业竞争正从底层模型扩展到应用层和任务闭环。"
        )
    if "coder" in t or "code" in t:
        return (
            "AI coding 相关能力持续增强，大厂与开源社区都在加速布局。",
            "编码场景仍是大模型最清晰、最有商业价值的落地方向之一。"
        )
    if "google" in t or "deepmind" in t:
        return (
            "Google / DeepMind 持续推进 AI 技术和产品布局。",
            "头部厂商竞争依旧激烈，技术突破正快速传导到产品层。"
        )
    if "openai" in t or "anthropic" in t:
        return (
            "头部大模型厂商持续发布新动作，竞争仍在升级。",
            "模型能力之外，生态和产品节奏越来越重要。"
        )
    if "nvidia" in t or "chip" in t or "gpu" in t:
        return (
            "AI 基础设施和算力仍是行业关键变量。",
            "算力供给能力会继续影响模型训练和商业化进度。"
        )

    return (
        "AI 行业持续出现模型、产品和产业侧的新变化。",
        "说明 AI 生态仍处于快速演进阶段。"
    )


def news_theme_key(title: str):
    t = title.lower()

    if "sora" in t:
        return "sora"
    if "alphaevolve" in t:
        return "alphaevolve"
    if "qwen" in t or "coder" in t:
        return "coding_model"
    if "google" in t or "deepmind" in t:
        return "google_deepmind"
    if "openai" in t:
        return "openai"
    if "anthropic" in t:
        return "anthropic"
    if "nvidia" in t or "gpu" in t or "chip" in t:
        return "compute"
    if "agent" in t:
        return "agent"
    return " ".join(t.split()[:6])


def dedupe_news(items):
    seen = set()
    deduped = []
    for item in items:
        key = news_theme_key(item["title"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


# =====================
# Product Hunt 分析
# =====================
def fallback_product_analysis(product):
    name = product["name"].lower()
    tagline = product["tagline"].lower()
    desc = product.get("description", "").lower()
    topics = " ".join(product.get("topics", [])).lower()
    text = f"{name} {tagline} {desc} {topics}"

    if "agent" in text:
        return {
            "users": "开发者、自动化场景用户、AI 应用团队",
            "value": "帮助用户搭建或管理 AI Agent 工作流",
            "why_hot": "Agent 仍是当前最受关注的 AI 产品方向之一，兼具想象空间和实际落地场景",
            "category": "AI Agent / Workflow",
        }
    if "code" in text or "coder" in text:
        return {
            "users": "开发者、独立开发者、技术团队",
            "value": "提升代码生成与开发效率",
            "why_hot": "AI coding 是当前大模型最成熟、最容易形成留存的应用场景之一",
            "category": "AI Coding Tool",
        }
    if "monitor" in text or "analytics" in text or "debug" in text:
        return {
            "users": "AI 产品团队、Agent 开发者",
            "value": "解决 AI Agent 上线后的监控、调试和评估问题",
            "why_hot": "随着 Agent 增多，配套基础设施需求同步增长",
            "category": "AI Infra / Dev Tool",
        }

    return {
        "users": "广义 AI 工具用户",
        "value": "通过 AI 提升某一具体任务的效率",
        "why_hot": "AI 工具类产品仍在快速迭代，用户愿意尝试能立即带来效率提升的产品",
        "category": "AI Tool",
    }


def analyze_product_with_openai(product):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    topics_text = ", ".join(product.get("topics", []))

    prompt = f"""
请分析这个 Product Hunt 上的 AI 产品，并输出 JSON：

产品名：{product['name']}
Tagline：{product['tagline']}
Description：{product.get('description', '')}
Topics：{topics_text}
Votes：{product['votes']}

请输出字段：
users: 目标用户
value: 核心价值
why_hot: 为什么会火
category: 产品类型（如 AI Agent / AI Coding / AI Infra / AI Tool）

只输出 JSON，不要加解释。
""".strip()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "你是一个专业、简洁的 AI 产品分析助手。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
    }

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        return json.loads(content)
    except Exception:
        return None


def analyze_product(product):
    return analyze_product_with_openai(product) or fallback_product_analysis(product)


# =====================
# 洞察与机会点
# =====================
def generate_insight_with_openai(models, products, news):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    model_lines = []
    for m in models[:5]:
        model_lines.append(
            f"- {m['id']} | likes={m.get('likes', 0)} | downloads={m.get('downloads', 0)} | explain={explain_model(m)}"
        )

    product_lines = []
    for p in products[:5]:
        product_lines.append(
            f"- {p['name']} | tagline={p['tagline']} | votes={p['votes']} | category={p['analysis']['category']}"
        )

    news_lines = []
    for n in news[:5]:
        news_lines.append(
            f"- {n['title']} | summary={n['summary']} | why={n['why_it_matters']}"
        )

    prompt = f"""
你是一个AI行业分析师。请基于下面三类信息，生成1句中文“今日洞察”。

要求：
1. 只输出一句话，不要分点
2. 风格像产品战略/行业分析
3. 不要空泛，要尽量指出今天变化的重点方向
4. 30-60字以内

模型信息：
{chr(10).join(model_lines)}

产品信息：
{chr(10).join(product_lines)}

新闻信息：
{chr(10).join(news_lines)}
""".strip()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "你是一个简洁、专业的AI行业分析助手。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.5,
    }

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def fallback_insight(products, news):
    categories = [p["analysis"]["category"] for p in products]

    if any("Agent" in c for c in categories):
        return "AI 正在从模型能力竞争，进一步转向 Agent 和工作流产品竞争。"
    if any("Coding" in c for c in categories):
        return "AI coding 依然是最清晰的商业化落地方向之一，产品竞争持续升温。"
    if any("sora" in n["title"].lower() for n in news):
        return "视频生成赛道正在从技术展示走向产品化与风险治理阶段。"
    return "AI 行业正在同时推进模型、产品和应用层创新，竞争焦点逐步上移。"


def generate_product_opportunity(products, news):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        categories = [p["analysis"]["category"] for p in products]
        if any("Agent" in c for c in categories):
            return "可以考虑做一个面向垂直场景的 AI Agent 监控与评估工具。"
        if any("Coding" in c for c in categories):
            return "可以考虑做一个面向非技术用户的 AI coding workflow 产品。"
        return "可以考虑做一个帮助用户理解 AI 产品趋势和机会点的洞察工具。"

    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    product_lines = []
    for p in products[:5]:
        product_lines.append(
            f"- {p['name']} | {p['tagline']} | category={p['analysis']['category']} | why_hot={p['analysis']['why_hot']}"
        )
    news_lines = []
    for n in news[:5]:
        news_lines.append(f"- {n['title']} | {n['why_it_matters']}")

    prompt = f"""
你是一个AI产品经理。请基于今天的 Product Hunt AI 产品和 AI 新闻，输出 1 句话“今日产品机会”。

要求：
1. 只输出一句中文
2. 30-50字
3. 要像真实产品机会，而不是空话

Product Hunt:
{chr(10).join(product_lines)}

News:
{chr(10).join(news_lines)}
""".strip()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "你是一个有产品感的 AI 产品经理。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.6,
    }

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return "可以考虑做一个帮助用户理解 AI 产品趋势和机会点的洞察工具。"


# =====================
# 数据整理
# =====================
def build_data():
    models_raw = fetch_models()
    news_raw = fetch_news()
    products_raw = safe_fetch_product_hunt_products()

    # 模型
    models = [m for m in models_raw if is_good_model(m)]
    models.sort(key=model_score, reverse=True)
    models = models[:5]

    # 新闻
    news = []
    for item in news_raw:
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        source = item.findtext("source") or ""
        summary, why_it_matters = summarize_news(title)

        news.append(
            {
                "title": title,
                "link": link,
                "source": source,
                "summary": summary,
                "why_it_matters": why_it_matters,
            }
        )

    news = dedupe_news(news)[:5]

    # Product Hunt
    products = []
    for p in products_raw[:5]:
        products.append(
            {
                **p,
                "analysis": analyze_product(p),
            }
        )

    # 洞察与机会点
    insight = generate_insight_with_openai(models, products, news) or fallback_insight(products, news)
    product_opportunity = generate_product_opportunity(products, news)

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "models": models,
        "news": news,
        "products": products,
        "insight": insight,
        "product_opportunity": product_opportunity,
    }


# =====================
# 渲染
# =====================
def render_plain(data):
    lines = []
    lines.append(f"AI Intelligence Radar | {data['date']}")
    lines.append("")

    lines.append("🔥 今日值得关注模型")
    for m in data["models"]:
        lines.append(f"- {m['id']}")
        lines.append(f"  {explain_model(m)}")
        lines.append(f"  likes={m.get('likes', 0)} | downloads={m.get('downloads', 0)}")
    lines.append("")

    lines.append("🚀 Product Hunt 热门 AI 产品")
    if data["products"]:
        for p in data["products"]:
            a = p["analysis"]
            lines.append(f"- {p['name']} ({p['votes']} votes)")
            lines.append(f"  tagline: {p['tagline']}")
            lines.append(f"  用户: {a['users']}")
            lines.append(f"  价值: {a['value']}")
            lines.append(f"  为什么火: {a['why_hot']}")
            lines.append(f"  类型: {a['category']}")
            lines.append(f"  链接: {p['url']}")
            lines.append("")
    else:
        lines.append("- 今天没有抓到 Product Hunt 数据")
        lines.append("")

    lines.append("📰 AI 热点新闻")
    for i, n in enumerate(data["news"], start=1):
        source_text = f"（{n['source']}）" if n["source"] else ""
        lines.append(f"{i}. {n['title']} {source_text}")
        lines.append(f"   摘要：{n['summary']}")
        lines.append(f"   意义：{n['why_it_matters']}")
        lines.append(f"   链接：{n['link']}")
        lines.append("")

    lines.append("🧠 今日洞察")
    lines.append(data["insight"])
    lines.append("")
    lines.append("💡 今日产品机会")
    lines.append(data["product_opportunity"])

    return "\n".join(lines)


def esc(text):
    return html.escape(text or "")


def render_html(data):
    model_cards = []
    for m in data["models"]:
        model_cards.append(f"""
        <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;margin-bottom:12px;">
          <div style="font-size:15px;font-weight:700;color:#111827;word-break:break-all;">{esc(m['id'])}</div>
          <div style="font-size:13px;color:#4b5563;margin-top:6px;line-height:1.6;">{esc(explain_model(m))}</div>
          <div style="font-size:12px;color:#6b7280;margin-top:8px;">👍 likes={m.get('likes', 0)} &nbsp;&nbsp; ⬇ downloads={m.get('downloads', 0)}</div>
        </div>
        """)

    product_cards = []
    for p in data["products"]:
        a = p["analysis"]
        product_cards.append(f"""
        <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;margin-bottom:12px;">
          <div style="font-size:15px;font-weight:700;color:#111827;">{esc(p['name'])}</div>
          <div style="font-size:13px;color:#4b5563;margin-top:6px;line-height:1.6;">{esc(p['tagline'])}</div>
          <div style="font-size:12px;color:#6b7280;margin-top:8px;">🔥 {p['votes']} votes &nbsp;&nbsp; | &nbsp;&nbsp; {esc(a['category'])}</div>
          <div style="font-size:13px;color:#374151;margin-top:10px;line-height:1.7;"><strong>用户：</strong>{esc(a['users'])}</div>
          <div style="font-size:13px;color:#374151;margin-top:6px;line-height:1.7;"><strong>价值：</strong>{esc(a['value'])}</div>
          <div style="font-size:13px;color:#374151;margin-top:6px;line-height:1.7;"><strong>为什么火：</strong>{esc(a['why_hot'])}</div>
          <div style="margin-top:10px;">
            <a href="{esc(p['url'])}" style="font-size:13px;color:#2563eb;text-decoration:none;">查看 Product Hunt</a>
          </div>
        </div>
        """)

    news_cards = []
    for i, n in enumerate(data["news"], start=1):
        source_text = f"（{n['source']}）" if n["source"] else ""
        news_cards.append(f"""
        <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;margin-bottom:12px;">
          <div style="font-size:15px;font-weight:700;color:#111827;line-height:1.6;">{i}. {esc(n['title'])} {esc(source_text)}</div>
          <div style="font-size:13px;color:#374151;margin-top:8px;line-height:1.7;"><strong>摘要：</strong>{esc(n['summary'])}</div>
          <div style="font-size:13px;color:#374151;margin-top:6px;line-height:1.7;"><strong>意义：</strong>{esc(n['why_it_matters'])}</div>
          <div style="margin-top:10px;">
            <a href="{esc(n['link'])}" style="font-size:13px;color:#2563eb;text-decoration:none;">查看原文</a>
          </div>
        </div>
        """)

    return f"""
    <html>
      <body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif;">
        <div style="max-width:760px;margin:0 auto;padding:24px 16px;">
          <div style="background:#111827;color:#ffffff;border-radius:16px;padding:24px 24px 20px 24px;">
            <div style="font-size:28px;font-weight:800;">AI Intelligence Radar</div>
            <div style="font-size:14px;color:#d1d5db;margin-top:8px;">{esc(data['date'])}</div>
          </div>

          <div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:16px;padding:18px 20px;margin-top:16px;">
            <div style="font-size:18px;font-weight:800;color:#9a3412;">🧠 今日洞察</div>
            <div style="font-size:15px;color:#7c2d12;line-height:1.8;margin-top:10px;">{esc(data['insight'])}</div>
          </div>

          <div style="background:#ecfeff;border:1px solid #a5f3fc;border-radius:16px;padding:18px 20px;margin-top:16px;">
            <div style="font-size:18px;font-weight:800;color:#155e75;">💡 今日产品机会</div>
            <div style="font-size:15px;color:#164e63;line-height:1.8;margin-top:10px;">{esc(data['product_opportunity'])}</div>
          </div>

          <div style="margin-top:20px;">
            <div style="font-size:20px;font-weight:800;color:#111827;margin-bottom:12px;">🔥 今日值得关注模型</div>
            {''.join(model_cards) if model_cards else '<div style="color:#6b7280;">今天没有筛到高质量模型</div>'}
          </div>

          <div style="margin-top:20px;">
            <div style="font-size:20px;font-weight:800;color:#111827;margin-bottom:12px;">🚀 Product Hunt 热门 AI 产品</div>
            {''.join(product_cards) if product_cards else '<div style="color:#6b7280;">今天没有抓到 Product Hunt 数据</div>'}
          </div>

          <div style="margin-top:20px;">
            <div style="font-size:20px;font-weight:800;color:#111827;margin-bottom:12px;">📰 AI 热点新闻</div>
            {''.join(news_cards) if news_cards else '<div style="color:#6b7280;">今天没有抓到新闻</div>'}
          </div>

          <div style="font-size:12px;color:#9ca3af;text-align:center;margin-top:28px;">
            Generated by AI Intelligence Radar
          </div>
        </div>
      </body>
    </html>
    """


# =====================
# 邮件发送
# =====================
def send_email(data):
    email_from = os.environ["EMAIL_FROM"]
    email_to = os.environ["EMAIL_TO"]

    plain_content = render_plain(data)
    html_content = render_html(data)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"AI Intelligence Radar | {data['date']}"
    msg["From"] = email_from
    msg["To"] = email_to

    msg.attach(MIMEText(plain_content, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(
        os.environ["SMTP_HOST"],
        int(os.environ["SMTP_PORT"]),
        context=context,
        timeout=30,
    ) as server:
        server.login(
            os.environ["SMTP_USERNAME"],
            os.environ["SMTP_PASSWORD"]
        )
        server.sendmail(email_from, [email_to], msg.as_string())


# =====================
# 主函数
# =====================
def main():
    data = build_data()
    send_email(data)


if __name__ == "__main__":
    main()
