#!/usr/bin/env python3
"""Publish today's signal as a GitHub Issue -> GitHub emails it to the account's bound mailbox (no SMTP keys).
Usage: python post_issue.py <success|failure> [--dry-run]   (needs GH_TOKEN + GITHUB_REPOSITORY env; uses the preinstalled `gh` CLI)"""
import json, os, subprocess, sys

status = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "success"
dry = "--dry-run" in sys.argv
owner = os.environ.get("OWNER") or os.environ.get("GITHUB_REPOSITORY_OWNER", "")
mention = f"@{owner} " if owner else ""

if status == "success" and os.path.exists("signal_latest.json"):
    S = json.load(open("signal_latest.json")); txt = open("signal_latest.txt", encoding="utf-8").read()
    title = S["headline"]
    body = f"{mention}\n\n### {S['headline']}\n\n```text\n{txt}\n```\n"
else:
    log = open("run.log", encoding="utf-8", errors="replace").read()[-6000:] if os.path.exists("run.log") else "(no run.log)"
    title = "⚠ 今日信号生成失败，请查看 Actions 日志"
    body = f"{mention}\n\n信号脚本运行失败，最后的日志：\n\n```text\n{log}\n```\n"

if dry:
    print("TITLE:", title); print(body[:1200]); sys.exit(0)

def gh(*args, check=True):
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check)

gh("label", "create", "signal", "--color", "0E8A16", "--description", "每日交易信号", "--force", check=False)
# close yesterday's signal issue(s) so only today's stays open
old = gh("issue", "list", "--label", "signal", "--state", "open", "--json", "number", "-q", ".[].number", check=False).stdout.split()
for n in old:
    gh("issue", "close", n, "--comment", "已被新的每日信号取代", check=False)
open("issue_body.md", "w", encoding="utf-8").write(body)
r = gh("issue", "create", "--title", title, "--body-file", "issue_body.md", "--label", "signal")
print("issue created:", r.stdout.strip())
