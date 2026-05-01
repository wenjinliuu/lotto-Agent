from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = BASE_DIR / "backups"


def load_json(path: Path | str, default: Any = None) -> Any:
    target = Path(path)
    if not target.exists():
        return default
    with target.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path: Path | str, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0).isoformat()


def today_date() -> str:
    return now_iso()[:10]


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def normalize_lottery_type(value: str, rules: dict[str, Any] | None = None) -> str:
    text = str(value or "").strip().lower()
    rules = rules or load_json(CONFIG_DIR / "lottery_rules.json", {})
    for key, config in rules.get("lotteries", {}).items():
        if text == key.lower() or text in [str(alias).lower() for alias in config.get("aliases", [])]:
            return key
    raise ValueError(f"不支持的彩种: {value}")


def pad_number(value: int | str, digits: int = 2) -> str:
    return str(value).zfill(digits)


def parse_json_arg(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value
