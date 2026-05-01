from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from followup import add as add_followup
from utils import BACKUP_DIR, CONFIG_DIR, dump_json, load_json, now_iso


ALLOWED_FILES = {"preferences": "preferences.json", "schedule": "schedule.json", "output_format": "output_format.json"}


def update_config(config_name: str, updates: dict[str, Any]) -> dict[str, Any]:
    if config_name not in ALLOWED_FILES:
        return {"ok": False, "error": "只允许修改 preferences、schedule、output_format"}
    path = CONFIG_DIR / ALLOWED_FILES[config_name]
    current = load_json(path, {})
    error = validate_updates(config_name, updates)
    if error:
        return {"ok": False, "error": error}
    backup_path = backup_config(path)
    merged = deep_merge(current, updates)
    dump_json(path, merged)
    result = {"ok": True, "backup": str(backup_path), "config": merged, "wechat_text": "配置已更新，并已备份。"}
    add_followup(result, "config_updated", str(backup_path))
    return result


def validate_updates(config_name: str, updates: dict[str, Any]) -> str:
    if not isinstance(updates, dict):
        return "配置更新必须是 JSON 对象"
    if config_name == "preferences":
        if "default_count" in updates and int(updates["default_count"]) < 1:
            return "默认注数必须大于 0"
        if "default_budget" in updates and float(updates["default_budget"]) < 0:
            return "默认预算不能小于 0"
        for value in updates.get("default_multiple", {}).values():
            if int(value) < 1:
                return "默认倍数必须大于 0"
        subscriptions = updates.get("subscriptions", {})
        if "daily_push_time" in subscriptions and not valid_time(subscriptions["daily_push_time"]):
            return "推送时间格式应为 HH:MM"
    if config_name == "schedule":
        for job in updates.get("jobs", []):
            if "time" in job and not valid_time(job["time"]):
                return "任务时间格式应为 HH:MM"
    if config_name == "output_format":
        if "separator" in updates and not isinstance(updates["separator"], str):
            return "separator 必须是字符串"
    return ""


def valid_time(value: Any) -> bool:
    import re

    match = re.fullmatch(r"\d{2}:\d{2}", str(value))
    if not match:
        return False
    hour, minute = [int(part) for part in str(value).split(":")]
    return 0 <= hour <= 23 and 0 <= minute <= 59


def backup_config(path: Path) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"{path.stem}.{now_iso().replace(':', '').replace('+', '_')}.json"
    shutil.copy2(path, target)
    return target


def deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result
