import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

def get_content():
    return """AI Daily Radar

New Models:
- Example A
- Example B

Hot Models:
- Model C

News:
- AI news example

Summary:
AI is evolving fast."""

def send_email(content):
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = f"AI Daily Radar {datetime.now().strftime('%Y-%m-%d')}"
    msg["From"] = os.environ["EMAIL_FROM"]
    msg["To"] = os.environ["EMAIL_TO"]

    with smtplib.SMTP_SSL(os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"])) as server:
        server.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        server.sendmail(msg["From"], [msg["To"]], msg.as_string())

if __name__ == "__main__":
    send_email(get_content())
