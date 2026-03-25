import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

def get_content():
    return """📅 AI Daily Radar

🧠 今日新模型
- Example Model A
- Example Model B

📈 热度变化
- Model C +200%

📰 AI新闻
- OpenAI发布新模型
- AI行业持续增长

🧾 总结
AI正在快速发展。
"""

def send_email(content):
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = f"AI Daily Radar | {datetime.now().strftime('%Y-%m-%d')}"
    msg["From"] = os.environ["EMAIL_FROM"]
    msg["To"] = os.environ["EMAIL_TO"]

    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ["SMTP_PORT"])
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]

    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
            server.login(username, password)
            server.sendmail(msg["From"], [msg["To"]], msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(username, password)
            server.sendmail(msg["From"], [msg["To"]], msg.as_string())

if __name__ == "__main__":
    send_email(get_content())
