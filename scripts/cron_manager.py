from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from followup import add as add_followup
from utils import BASE_DIR, env


CRON_MARKER = "# lotto-agent automation"
LEGACY_CRON_MARKERS = ["# RandomDrawAgent automation"]
CRON_INTERVAL_MINUTES = 30


def cron_command() -> str:
    python_bin = "python3"
    skill_dir = str(BASE_DIR)
    data_dir = env("LOTTO_AGENT_DATA_DIR")
    prefix = f"LOTTO_AGENT_DATA_DIR={shell_quote(data_dir)} " if data_dir else ""
    return f"*/{CRON_INTERVAL_MINUTES} * * * * cd {shell_quote(skill_dir)} && {prefix}{python_bin} scripts/main.py schedule --push {CRON_MARKER}"


def cron_status() -> dict[str, Any]:
    if not has_crontab():
        return {"ok": True, "installed": False, "available": False, "command": cron_command(), "message_text": guidance_text(False)}
    listing = read_crontab()
    installed = any(marker in listing for marker in all_cron_markers())
    return {"ok": True, "installed": installed, "available": True, "command": cron_command(), "message_text": guidance_text(installed)}


def install_cron(confirm: bool = False) -> dict[str, Any]:
    status = cron_status()
    if not confirm:
        return {
            "ok": False,
            "requires_confirmation": True,
            "installed": status.get("installed", False),
            "command": cron_command(),
            "message_text": "我需要在服务器 crontab 增加一条每30分钟唤醒任务。回复“确认开启自动化”后我再安装。",
        }
    if not has_crontab():
        return {"ok": False, "error": "当前环境没有 crontab 命令", "command": cron_command(), "message_text": guidance_text(False)}
    listing = read_crontab()
    if any(marker in listing for marker in all_cron_markers()):
        if cron_command() in listing:
            result = {"ok": True, "installed": True, "message_text": "自动化唤醒器已经开启。"}
            add_followup(result, "cron_installed", "already")
            return result
        new_listing = replace_cron_listing(listing)
        proc = subprocess.run(["crontab", "-"], input=new_listing, text=True, capture_output=True, check=False)
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr.strip() or "crontab 更新失败", "command": cron_command()}
        result = {"ok": True, "installed": True, "message_text": "自动化唤醒器已更新：每30分钟检查一次到期任务。"}
        add_followup(result, "cron_installed", "updated")
        return result
    new_listing = (listing.rstrip() + "\n" if listing.strip() else "") + cron_command() + "\n"
    proc = subprocess.run(["crontab", "-"], input=new_listing, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr.strip() or "crontab 写入失败", "command": cron_command()}
    result = {"ok": True, "installed": True, "message_text": "自动化唤醒器已开启：每30分钟检查一次到期任务。"}
    add_followup(result, "cron_installed", "new")
    return result


def uninstall_cron(confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        return {"ok": False, "requires_confirmation": True, "message_text": "确认要停止 lotto-agent 自动化唤醒器吗？回复“确认停止自动化”后我再执行。"}
    if not has_crontab():
        return {"ok": False, "error": "当前环境没有 crontab 命令"}
    markers = all_cron_markers()
    lines = [line for line in read_crontab().splitlines() if not any(marker in line for marker in markers)]
    proc = subprocess.run(["crontab", "-"], input="\n".join(lines).rstrip() + "\n", text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr.strip() or "crontab 写入失败"}
    return {"ok": True, "installed": False, "message_text": "自动化唤醒器已停止，已保存的任务不会被自动执行。"}


def has_crontab() -> bool:
    return platform.system().lower() != "windows" and shutil.which("crontab") is not None


def read_crontab() -> str:
    proc = subprocess.run(["crontab", "-l"], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return ""
    return proc.stdout


def guidance_text(installed: bool) -> str:
    if installed:
        return "自动化唤醒器已开启。"
    return "自动化唤醒器未开启。可以回复“确认开启自动化”，或在服务器执行：" + "\n" + cron_command()


def all_cron_markers() -> list[str]:
    return [CRON_MARKER, *LEGACY_CRON_MARKERS]


def replace_cron_listing(listing: str) -> str:
    markers = all_cron_markers()
    lines = [line for line in listing.splitlines() if not any(marker in line for marker in markers)]
    lines.append(cron_command())
    return "\n".join(line for line in lines if line.strip()).rstrip() + "\n"


def shell_quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"
