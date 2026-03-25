# ======= 重点升级版（产品级） =======

import json
import os
import smtplib
import ssl
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

HF_API = "https://huggingface.co/api/models"


# =====================
# 基础能力
# =====================
def fetch_models():
    params = {"limit": 100, "sort": "lastModified", "direction": -1}
    return requests.get(HF_API, params=params).json()


def fetch_news():
    url = "https://news.google.com/rss/search?q=AI&hl=en-US&gl=US&ceid=US:en"
    root = ET.fromstring(requests.get(url).text)
    return root.findall(".//item")


# =====================
# 产品能力
# =====================

def is_good_model(m):
    return m.get("downloads", 0) > 20 or m.get("likes", 0) > 5


def explain_model(m):
    tags = " ".join(m.get("tags", [])).lower()

    if "agent" in tags:
        return "AI Agent相关模型，可能用于自动执行任务"
    if "vision" in tags or "image" in tags:
        return "多模态模型（图像+文本理解）"
    if "code" in tags:
        return "代码生成模型，类似 Copilot"
    if "llm" in tags or "text-generation" in tags:
        return "大语言模型（文本生成/对话）"

    return "通用AI模型"


def summarize_news(title):
    title = title.lower()

    if "agent" in title:
        return "AI Agent能力持续增强，向复杂任务发展"
    if "openai" in title or "anthropic" in title:
        return "大模型厂商持续竞争升级"
    if "google" in title:
        return "Google加速AI布局"
    if "code" in title:
        return "AI coding能力持续增强"

    return "AI行业持续发展"


# =====================
# 核心逻辑
# =====================

def build_content():
    models_raw = fetch_models()
    news_raw = fetch_news()

    # 过滤模型
    models = [m for m in models_raw if is_good_model(m)][:5]

    # 新闻
    news = []
    for item in news_raw[:5]:
        title = item.findtext("title")
        news.append({
            "title": title,
            "summary": summarize_news(title)
        })

    # ===== 邮件内容 =====
    lines = []

    lines.append(f"📅 AI Daily Radar | {datetime.now().strftime('%Y-%m-%d')}\n")

    # 🔥 模型
    lines.append("🔥 今日值得关注模型")
    for m in models:
        lines.append(f"\n- {m['id']}")
        lines.append(f"  👉 {explain_model(m)}")
        lines.append(f"  👍 likes={m.get('likes',0)} | ⬇ downloads={m.get('downloads',0)}")

    # 📰 新闻
    lines.append("\n📰 AI热点")
    for n in news:
        lines.append(f"\n- {n['title']}")
        lines.append(f"  👉 {n['summary']}")

    # 🧠 洞察（关键）
    lines.append("\n🧠 今日洞察")
    lines.append("👉 AI 正在从模型能力竞争，转向 Agent 和应用层竞争")

    return "\n".join(lines)


# =====================
# 邮件发送
# =====================
def send_email(content):
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = "AI Daily Radar"
    msg["From"] = os.environ["EMAIL_FROM"]
    msg["To"] = os.environ["EMAIL_TO"]

    with smtplib.SMTP_SSL(
        os.environ["SMTP_HOST"],
        int(os.environ["SMTP_PORT"])
    ) as server:
        server.login(
            os.environ["SMTP_USERNAME"],
            os.environ["SMTP_PASSWORD"]
        )
        server.send_message(msg)


# =====================
# 主函数
# =====================
def main():
    content = build_content()
    send_email(content)


if __name__ == "__main__":
    main()
