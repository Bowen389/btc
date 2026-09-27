#!/usr/bin/env python3
"""Email the latest signal. Usage: python send_mail.py <success|failure> [--dry-run]
SMTP settings from env: MAIL_SERVER, MAIL_PORT (465=SSL, 587=STARTTLS), MAIL_USERNAME, MAIL_PASSWORD, MAIL_TO, [MAIL_FROM]"""
import html, json, os, smtplib, ssl, sys
from email.message import EmailMessage
from email.utils import formatdate

status = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "success"
dry = "--dry-run" in sys.argv

if status == "success" and os.path.exists("signal_latest.json"):
    S = json.load(open("signal_latest.json")); body = open("signal_latest.txt", encoding="utf-8").read()
    subject = f"[BTC日线] {S['headline']}"
else:
    log = open("run.log", encoding="utf-8", errors="replace").read()[-8000:] if os.path.exists("run.log") else "(no run.log)"
    subject = "[BTC日线] ⚠ 今日信号生成失败，请到 GitHub Actions 查看日志"
    body = "信号脚本运行失败，最后的日志：\n\n" + log

msg = EmailMessage()
msg["Subject"] = subject; msg["Date"] = formatdate(localtime=True)
msg["From"] = os.environ.get("MAIL_FROM") or os.environ.get("MAIL_USERNAME", "")
msg["To"] = os.environ.get("MAIL_TO", "")
msg.set_content(body)
msg.add_alternative(f"<html><body><pre style='font-family:Menlo,Consolas,\"Courier New\",monospace;font-size:13px;line-height:1.35'>{html.escape(body)}</pre></body></html>", subtype="html")

if dry:
    print("SUBJECT:", subject); print(body); sys.exit(0)

server = os.environ["MAIL_SERVER"]; port = int(os.environ.get("MAIL_PORT", "465"))
user = os.environ["MAIL_USERNAME"]; pwd = os.environ["MAIL_PASSWORD"]
ctx = ssl.create_default_context()
if port == 465:
    with smtplib.SMTP_SSL(server, port, context=ctx, timeout=60) as smtp:
        smtp.login(user, pwd); smtp.send_message(msg)
else:
    with smtplib.SMTP(server, port, timeout=60) as smtp:
        smtp.ehlo(); smtp.starttls(context=ctx); smtp.ehlo(); smtp.login(user, pwd); smtp.send_message(msg)
print("mail sent:", subject)
