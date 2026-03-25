import html
import os
import smtplib
import ssl
import xml.etree.ElementTree as ET
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

HF_API = "https://huggingface.co/api/models"


# =====================
# 基础能力
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
# 模型逻辑
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
# LLM 洞察
# =====================
def generate_insight_with_openai(models, news):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    model_lines = []
    for m in models[:5]:
        model_lines.append(
            f"- {m['id']} | likes={m.get('likes', 0)} | downloads={m.get('downloads', 0)} | explain={explain_model(m)}"
        )

    news_lines = []
    for n in news[:5]:
        news_lines.append(f"- {n['title']} | summary={n['summary']} | why={n['why_it_matters']}")

    prompt = f"""
你是一个AI行业分析师。请基于下面的信息，生成1句中文“今日洞察”。

要求：
1. 只输出一句话，不要分点
2. 风格像产品战略/行业分析
3. 不要空泛，要尽量指出今天变化的重点方向
4. 30-60字以内

模型信息：
{chr(10).join(model_lines)}

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


def fallback_insight(news):
    if any("agent" in n["title"].lower() for n in news):
        return "AI 正在从模型能力竞争，逐步转向 Agent 和应用层竞争。"
    if any("coder" in n["title"].lower() or "code" in n["title"].lower() for n in news):
        return "AI coding 仍是最清晰的落地方向之一，模型竞争正在快速传导到应用层。"
    if any("sora" in n["title"].lower() for n in news):
        return "视频生成赛道正在从“展示能力”走向“产品化与合规”阶段。"
    return "AI 行业仍在快速演进，模型、产品与产业侧变化正在同时发生。"


# =====================
# 数据整理
# =====================
def build_data():
    models_raw = fetch_models()
    news_raw = fetch_news()

    models = [m for m in models_raw if is_good_model(m)]
    models.sort(key=model_score, reverse=True)
    models = models[:5]

    news = []
    for item in news_raw:
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        source = item.findtext("source") or ""
        summary, why_it_matters = summarize_news(title)

        news.append({
            "title": title,
            "link": link,
            "source": source,
            "summary": summary,
            "why_it_matters": why_it_matters,
        })

    news = dedupe_news(news)[:5]

    insight = generate_insight_with_openai(models, news) or fallback_insight(news)

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "models": models,
        "news": news,
        "insight": insight,
    }


# =====================
# 文本版邮件
# =====================
def render_plain(data):
    lines = []
    lines.append(f"AI Daily Radar | {data['date']}")
    lines.append("")

    lines.append("🔥 今日值得关注模型")
    for m in data["models"]:
        lines.append(f"- {m['id']}")
        lines.append(f"  {explain_model(m)}")
        lines.append(f"  likes={m.get('likes', 0)} | downloads={m.get('downloads', 0)}")
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

    return "\n".join(lines)


# =====================
# HTML 邮件
# =====================
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

    html_content = f"""
    <html>
      <body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif;">
        <div style="max-width:760px;margin:0 auto;padding:24px 16px;">
          <div style="background:#111827;color:#ffffff;border-radius:16px;padding:24px 24px 20px 24px;">
            <div style="font-size:28px;font-weight:800;">AI Daily Radar</div>
            <div style="font-size:14px;color:#d1d5db;margin-top:8px;">{esc(data['date'])}</div>
          </div>

          <div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:16px;padding:18px 20px;margin-top:16px;">
            <div style="font-size:18px;font-weight:800;color:#9a3412;">🧠 今日洞察</div>
            <div style="font-size:15px;color:#7c2d12;line-height:1.8;margin-top:10px;">{esc(data['insight'])}</div>
          </div>

          <div style="margin-top:20px;">
            <div style="font-size:20px;font-weight:800;color:#111827;margin-bottom:12px;">🔥 今日值得关注模型</div>
            {''.join(model_cards) if model_cards else '<div style="color:#6b7280;">今天没有筛到高质量模型</div>'}
          </div>

          <div style="margin-top:20px;">
            <div style="font-size:20px;font-weight:800;color:#111827;margin-bottom:12px;">📰 AI 热点新闻</div>
            {''.join(news_cards) if news_cards else '<div style="color:#6b7280;">今天没有抓到新闻</div>'}
          </div>

          <div style="font-size:12px;color:#9ca3af;text-align:center;margin-top:28px;">
            Generated by AI Daily Radar
          </div>
        </div>
      </body>
    </html>
    """
    return html_content


# =====================
# 邮件发送
# =====================
def send_email(data):
    email_from = os.environ["EMAIL_FROM"]
    email_to = os.environ["EMAIL_TO"]

    plain_content = render_plain(data)
    html_content = render_html(data)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"AI Daily Radar | {data['date']}"
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
