import json
import os
import smtplib
import ssl
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests
from dateutil import parser as dtparser

HF_API_URL = "https://huggingface.co/api/models"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


def load_config() -> Dict[str, Any]:
    config_path = Path("config.json")
    if not config_path.exists():
        return {
            "user_name": "User",
            "interests": ["agent", "llm", "coding"],
            "new_model_limit": 5,
            "hot_model_limit": 3,
            "news_limit": 5,
            "news_query": "artificial intelligence OR AI OR OpenAI OR Anthropic OR Google DeepMind OR Hugging Face",
            "global_summary": True,
        }
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_state() -> Dict[str, Any]:
    state_path = Path(".ai_daily_radar_state.json")
    if not state_path.exists():
        return {"models": {}}
    with state_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: Dict[str, Any]) -> None:
    state_path = Path(".ai_daily_radar_state.json")
    with state_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def safe_get(url: str, params: Dict[str, Any] = None, timeout: int = 30) -> Any:
    headers = {"User-Agent": "AI-Daily-Radar/1.0"}
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp


def parse_hf_datetime(value: str) -> datetime:
    return dtparser.parse(value).astimezone(timezone.utc)


def get_hf_models(limit: int = 100) -> List[Dict[str, Any]]:
    params = {
        "limit": limit,
        "sort": "lastModified",
        "direction": -1,
        "full": "true",
    }
    resp = safe_get(HF_API_URL, params=params)
    data = resp.json()
    if not isinstance(data, list):
        return []
    return data


def score_text(text: str, interests: List[str]) -> int:
    text_lower = (text or "").lower()
    score = 0
    for kw in interests:
        kw_lower = kw.lower()
        if kw_lower in text_lower:
            score += 3

    keyword_groups = {
        "agent": ["agent", "tool use", "function calling", "workflow", "reasoning"],
        "llm": ["llm", "language model", "text-generation", "chat", "instruction"],
        "coding": ["code", "coder", "coding", "programming", "copilot"],
        "multimodal": ["multimodal", "vision-language", "vlm", "image-text"],
        "image": ["image", "diffusion", "text-to-image", "vision"],
        "video": ["video", "text-to-video"],
        "speech": ["speech", "audio", "asr", "tts"],
        "finance ai": ["finance", "financial", "trading", "stock", "market"],
        "web3": ["web3", "crypto", "blockchain"],
    }

    for interest in interests:
        for related in keyword_groups.get(interest.lower(), []):
            if related in text_lower:
                score += 1

    return score


def simplify_model(model: Dict[str, Any]) -> Dict[str, Any]:
    model_id = model.get("id", "")
    tags = model.get("tags", []) or []
    downloads = int(model.get("downloads", 0) or 0)
    likes = int(model.get("likes", 0) or 0)
    last_modified_raw = model.get("lastModified")
    created_at_raw = model.get("createdAt") or last_modified_raw

    last_modified = parse_hf_datetime(last_modified_raw) if last_modified_raw else None
    created_at = parse_hf_datetime(created_at_raw) if created_at_raw else None

    return {
        "id": model_id,
        "downloads": downloads,
        "likes": likes,
        "tags": tags,
        "pipeline_tag": model.get("pipeline_tag", ""),
        "last_modified": last_modified,
        "created_at": created_at,
        "card_data": model.get("cardData") or {},
    }


def classify_model_reason(item: Dict[str, Any]) -> str:
    tags_text = " ".join(item.get("tags", []))
    pipeline = item.get("pipeline_tag", "")
    joined = f"{tags_text} {pipeline}".lower()

    if "agent" in joined:
        return "Agent 相关"
    if "text-generation" in joined or "llm" in joined or "chat" in joined:
        return "LLM / 文本生成"
    if "text-to-image" in joined or "diffusion" in joined:
        return "图像生成"
    if "image" in joined or "vision" in joined:
        return "视觉模型"
    if "audio" in joined or "speech" in joined:
        return "语音 / 音频"
    if "text-to-video" in joined or "video" in joined:
        return "视频方向"
    if pipeline:
        return pipeline
    return "通用模型"


def get_new_models(
    models: List[Dict[str, Any]],
    hours: int,
    limit: int,
    interests: List[str],
) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    candidates = []
    for raw in models:
        item = simplify_model(raw)
        ref_time = item["created_at"] or item["last_modified"]
        if ref_time and ref_time >= cutoff:
            text = f"{item['id']} {' '.join(item['tags'])} {item['pipeline_tag']}"
            item["interest_score"] = score_text(text, interests)
            candidates.append(item)

    candidates.sort(
        key=lambda x: (x["interest_score"], x["likes"], x["downloads"]),
        reverse=True,
    )
    return candidates[:limit]


def get_hot_models(
    models: List[Dict[str, Any]],
    state: Dict[str, Any],
    limit: int,
    interests: List[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    prev = state.get("models", {})
    updated_state = {"models": {}}
    scored = []

    for raw in models:
        item = simplify_model(raw)
        model_id = item["id"]
        current_downloads = item["downloads"]
        current_likes = item["likes"]

        old = prev.get(model_id, {})
        delta_downloads = current_downloads - int(old.get("downloads", 0))
        delta_likes = current_likes - int(old.get("likes", 0))

        text = f"{model_id} {' '.join(item['tags'])} {item['pipeline_tag']}"
        interest_score = score_text(text, interests)

        trend_score = delta_downloads + delta_likes * 20 + interest_score * 50

        item["delta_downloads"] = delta_downloads
        item["delta_likes"] = delta_likes
        item["interest_score"] = interest_score
        item["trend_score"] = trend_score

        scored.append(item)

        updated_state["models"][model_id] = {
            "downloads": current_downloads,
            "likes": current_likes,
        }

    scored.sort(key=lambda x: (x["trend_score"], x["likes"], x["downloads"]), reverse=True)
    return scored[:limit], updated_state


def get_ai_news(limit: int, interests: List[str], query: str) -> List[Dict[str, Any]]:
    params = {
        "q": query,
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }
    resp = safe_get(GOOGLE_NEWS_RSS, params=params)
    root = ET.fromstring(resp.text)

    items = []
    for item in root.findall(".//item"):
        title = item.findtext("title", default="")
        link = item.findtext("link", default="")
        pub_date = item.findtext("pubDate", default="")
        source = item.findtext("source", default="")
        text = f"{title} {source}"

        items.append(
            {
                "title": title,
                "link": link,
                "pub_date": pub_date,
                "source": source,
                "interest_score": score_text(text, interests),
            }
        )

    items.sort(key=lambda x: x["interest_score"], reverse=True)
    return items[:limit]


def build_for_you(
    new_models: List[Dict[str, Any]],
    hot_models: List[Dict[str, Any]],
    news_items: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    combined_models = new_models + hot_models
    dedup = {}
    for m in combined_models:
        dedup[m["id"]] = m

    personalized_models = sorted(
        dedup.values(),
        key=lambda x: (x.get("interest_score", 0), x.get("likes", 0), x.get("downloads", 0)),
        reverse=True,
    )[:3]

    personalized_news = sorted(
        news_items,
        key=lambda x: x.get("interest_score", 0),
        reverse=True,
    )[:3]

    return {
        "models": personalized_models,
        "news": personalized_news,
    }


def render_email(
    config: Dict[str, Any],
    for_you: Dict[str, List[Dict[str, Any]]],
    new_models: List[Dict[str, Any]],
    hot_models: List[Dict[str, Any]],
    news_items: List[Dict[str, Any]],
) -> str:
    interests = ", ".join(config.get("interests", []))
    lines = []
    lines.append(f"📅 AI Daily Radar | {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("")

    if interests:
        lines.append(f"🎯 For You ({interests})")
        if for_you["models"]:
            for m in for_you["models"]:
                reason = classify_model_reason(m)
                lines.append(
                    f"- 模型: {m['id']} | {reason} | likes={m['likes']} | downloads={m['downloads']}"
                )
        if for_you["news"]:
            for n in for_you["news"]:
                source = f" ({n['source']})" if n["source"] else ""
                lines.append(f"- 新闻: {n['title']}{source}")
        lines.append("")

    lines.append("🧠 今日新模型")
    if new_models:
        for m in new_models:
            reason = classify_model_reason(m)
            lines.append(
                f"- {m['id']} | {reason} | likes={m['likes']} | downloads={m['downloads']}"
            )
    else:
        lines.append("- 过去24小时未筛到高相关新模型")
    lines.append("")

    lines.append("📈 热度变化模型")
    if hot_models:
        for m in hot_models:
            lines.append(
                f"- {m['id']} | 下载变化={m.get('delta_downloads', 0)} | likes变化={m.get('delta_likes', 0)}"
            )
    else:
        lines.append("- 暂无历史基线，下一次开始显示变化")
    lines.append("")

    lines.append("📰 AI 热点新闻")
    if news_items:
        for i, n in enumerate(news_items, start=1):
            source = f" ({n['source']})" if n["source"] else ""
            lines.append(f"{i}. {n['title']}{source}")
            lines.append(f"   {n['link']}")
    else:
        lines.append("- 暂无新闻")
    lines.append("")

    if config.get("global_summary", True):
        lines.append("🧾 今日总结")
        if new_models or hot_models or news_items:
            summary_parts = []
            if new_models:
                summary_parts.append("Hugging Face 上有新的模型更新")
            if hot_models:
                summary_parts.append("部分模型热度变化明显")
            if news_items:
                summary_parts.append("AI 行业新闻持续密集")
            lines.append("；".join(summary_parts) + "。")
        else:
            lines.append("今天整体变化不多。")

    return "\n".join(lines)


def send_email(content: str) -> None:
    email_from = os.environ["EMAIL_FROM"]
    email_to = os.environ["EMAIL_TO"]

    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = f"AI Daily Radar | {datetime.now().strftime('%Y-%m-%d')}"
    msg["From"] = email_from
    msg["To"] = email_to

    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ["SMTP_PORT"])
    smtp_username = os.environ["SMTP_USERNAME"]
    smtp_password = os.environ["SMTP_PASSWORD"]

    context = ssl.create_default_context()

    with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=30) as server:
        server.login(smtp_username, smtp_password)
        server.sendmail(email_from, [email_to], msg.as_string())


def main() -> None:
    config = load_config()
    state = load_state()

    interests = config.get("interests", [])
    new_limit = int(config.get("new_model_limit", 5))
    hot_limit = int(config.get("hot_model_limit", 3))
    news_limit = int(config.get("news_limit", 5))
    news_query = config.get(
        "news_query",
        "artificial intelligence OR AI OR OpenAI OR Anthropic OR Google DeepMind OR Hugging Face",
    )

    models = get_hf_models(limit=100)
    new_models = get_new_models(models, hours=24, limit=new_limit, interests=interests)
    hot_models, updated_state = get_hot_models(models, state, limit=hot_limit, interests=interests)
    news_items = get_ai_news(limit=news_limit, interests=interests, query=news_query)
    for_you = build_for_you(new_models, hot_models, news_items)

    content = render_email(config, for_you, new_models, hot_models, news_items)
    send_email(content)
    save_state(updated_state)


if __name__ == "__main__":
    main()
