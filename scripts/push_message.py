from __future__ import annotations

import json
from typing import Any

from utils import CONFIG_DIR, load_json, now_iso


def push_message(content: str, user_platform_id: str = "wechat_self", channel: str = "clawbot", meta: dict[str, Any] | None = None) -> dict[str, Any]:
    users = load_json(CONFIG_DIR / "users.json", {})
    allowed = users.get("allow_unknown_users", False) or any(
        item.get("platform_user_id") == user_platform_id and item.get("is_allowed", True)
        for item in users.get("users", [])
    )
    if not allowed:
        return {"ok": False, "error": "用户不在白名单"}
    # OpenClaw / ClawBot 的实际主动推送通常由宿主接管，这里保留统一出口和可观测返回。
    payload = {"channel": channel, "to": user_platform_id, "content": content, "meta": meta or {}, "created_at": now_iso()}
    return {"ok": True, "payload": payload, "debug": json.dumps(payload, ensure_ascii=False)}
