from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from utils import CONFIG_DIR, dump_json, load_json, now_iso


NOTIFICATIONS_FILE = CONFIG_DIR / "notifications.json"
SUPPORTED_PROVIDERS = {"dry_run", "host_payload", "openclaw_cli"}

# 固定 OpenClaw 命令：在进程启动时按 PATH 解析一次。
# 不允许通过 notifications.json 或任何 API 配置可执行路径，
# 以避免 prompt injection 把 command 改成任意可执行程序导致 RCE。
OPENCLAW_COMMAND = shutil.which("openclaw")


DEFAULT_NOTIFICATIONS = {
    "enabled": False,
    "provider": "dry_run",
    "default_recipient": "self",
    "recipients": {
        "self": {
            "display_name": "我",
            "target": "",
            "chat_id": "",
            "account_id": "",
            "channel": "",
            "bound": False,
            "updated_at": "",
        }
    },
    "providers": {
        "dry_run": {},
        "host_payload": {},
        "openclaw_cli": {
            "channel": "",
        },
    },
}


def push_message(
    content: str,
    user_platform_id: str = "self",
    channel: str | None = None,
    meta: dict[str, Any] | None = None,
    delivery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    notifications = notification_config()
    allowed_error = None if user_platform_id in (notifications.get("recipients") or {}) else validate_allowed_user(user_platform_id)
    provider = str(notifications.get("provider") or "dry_run")
    recipient = recipient_config(notifications, user_platform_id)
    delivery_route = normalize_delivery(delivery)
    resolved_channel = channel or delivery_route.get("channel") or recipient.get("channel") or provider_config(notifications).get("channel") or ""
    resolved_target = delivery_route.get("chat_id") or recipient_target(recipient) or (user_platform_id if provider in {"dry_run", "host_payload"} else "")
    resolved_account_id = delivery_route.get("account_id") or recipient.get("account_id") or ""
    payload = {
        "provider": provider,
        "channel": resolved_channel,
        "to": resolved_target,
        "target": resolved_target,
        "chat_id": resolved_target,
        "account_id": resolved_account_id,
        "recipient": user_platform_id,
        "content": content,
        "meta": meta or {},
        "created_at": now_iso(),
    }
    if allowed_error:
        return {**allowed_error, "sent": False, "payload": payload}
    if not notifications.get("enabled", False):
        return {
            "ok": False,
            "sent": False,
            "requires_configuration": True,
            "payload": payload,
            "message_text": notification_guidance(notifications),
        }

    if not (delivery_ready(payload, provider) if delivery_route else recipient_ready(notifications, user_platform_id)):
        return {
            "ok": False,
            "sent": False,
            "requires_binding": True,
            "payload": payload,
            "message_text": delivery_binding_guidance() if delivery_route else notification_binding_guidance(notifications, user_platform_id),
        }
    if provider == "dry_run":
        return {"ok": True, "sent": False, "dry_run": True, "payload": payload}
    if provider == "host_payload":
        return {"ok": True, "sent": False, "handed_to_host": True, "payload": payload, "debug": json.dumps(payload, ensure_ascii=False)}
    if provider == "openclaw_cli":
        return send_openclaw_cli(payload)
    return {"ok": False, "sent": False, "error": f"不支持的通知 provider: {provider}", "payload": payload}


def notification_status() -> dict[str, Any]:
    config = notification_config()
    provider = str(config.get("provider") or "dry_run")
    configured = notification_ready(config)
    default_recipient = str(config.get("default_recipient") or "self")
    binding = notification_binding_status(default_recipient, config=config)
    status = "已启用" if config.get("enabled") else "未启用"
    ready_text = "配置完整" if configured else "配置未完整"
    binding_text = "目标已绑定" if binding.get("bound_ready") else "目标未绑定"
    return {
        "ok": True,
        "enabled": bool(config.get("enabled", False)),
        "provider": provider,
        "configured": configured,
        "default_recipient": default_recipient,
        "binding": binding,
        "config": public_notification_config(config),
        "message_text": f"消息推送：{status}｜{provider}｜{ready_text}｜{binding_text}",
    }


def configure_notification(
    provider: str,
    recipient: str = "self",
    target: str | None = None,
    chat_id: str | None = None,
    account_id: str | None = None,
    channel: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    provider = normalize_provider(provider)
    if provider not in SUPPORTED_PROVIDERS:
        return {"ok": False, "error": f"不支持的通知 provider: {provider}"}
    config = notification_config()
    config["provider"] = provider
    config["default_recipient"] = recipient
    config.setdefault("recipients", {}).setdefault(recipient, {"display_name": recipient, "target": "", "chat_id": "", "account_id": "", "channel": ""})
    resolved_target = chat_id if chat_id is not None else target
    if resolved_target is not None:
        config["recipients"][recipient]["target"] = resolved_target
        config["recipients"][recipient]["chat_id"] = resolved_target
    if account_id is not None:
        config["recipients"][recipient]["account_id"] = account_id
    if channel is not None:
        config["recipients"][recipient]["channel"] = channel
    if resolved_target is not None or channel is not None:
        config["recipients"][recipient]["bound"] = bool(
            confirm
            and
            recipient_target(config["recipients"][recipient])
            and (config["recipients"][recipient].get("channel") or providers_channel(config, provider))
        )
        config["recipients"][recipient]["updated_at"] = now_iso()
    providers = config.setdefault("providers", {})
    providers.setdefault(provider, {})
    if channel is not None and provider == "openclaw_cli":
        providers[provider]["channel"] = channel
    config["enabled"] = bool(confirm)
    dump_json(NOTIFICATIONS_FILE, config)
    if not confirm:
        return {
            "ok": True,
            "enabled": False,
            "requires_confirmation": True,
            "config": public_notification_config(config),
            "message_text": "消息推送配置已保存，但尚未启用。确认无误后回复“确认开启消息推送”。",
        }
    return enable_notification(confirm=True)


def bind_notification_target(
    provider: str = "openclaw_cli",
    recipient: str = "self",
    target: str | None = None,
    chat_id: str | None = None,
    account_id: str | None = None,
    channel: str | None = None,
    display_name: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    provider = normalize_provider(provider)
    if provider not in SUPPORTED_PROVIDERS:
        return {"ok": False, "error": f"不支持的通知 provider: {provider}"}
    config = notification_config()
    config["provider"] = provider
    config["default_recipient"] = recipient
    recipients = config.setdefault("recipients", {})
    current = recipients.setdefault(recipient, {"display_name": display_name or recipient, "target": "", "chat_id": "", "account_id": "", "channel": "", "bound": False})
    if display_name is not None:
        current["display_name"] = display_name
    if channel is not None:
        current["channel"] = channel
    resolved_target = chat_id if chat_id is not None else target
    if resolved_target is not None:
        current["target"] = resolved_target
        current["chat_id"] = resolved_target
    if account_id is not None:
        current["account_id"] = account_id
    if provider == "openclaw_cli" and channel is not None:
        config.setdefault("providers", {}).setdefault(provider, {})["channel"] = channel

    missing = missing_required_binding_fields(config, recipient)
    if missing:
        return {
            "ok": False,
            "requires_configuration": True,
            "missing": missing,
            "config": public_notification_config(config),
            "message_text": notification_binding_guidance(config, recipient),
        }
    if not confirm:
        current["bound"] = False
        current["updated_at"] = now_iso()
        dump_json(NOTIFICATIONS_FILE, config)
        return {
            "ok": False,
            "requires_confirmation": True,
            "config": public_notification_config(config),
            "message_text": "已识别到通知目标信息。确认要把后续自动化消息发到这个目标，请回复“确认绑定当前通知目标”。",
        }

    current["bound"] = True
    current["updated_at"] = now_iso()
    dump_json(NOTIFICATIONS_FILE, config)
    return {
        "ok": True,
        "bound": True,
        "recipient": recipient,
        "config": public_notification_config(config),
        "message_text": f"已绑定通知目标：{recipient}。后续自动化任务会优先按这个 recipient 推送。",
    }


def list_notification_targets() -> dict[str, Any]:
    config = notification_config()
    recipients = []
    default_recipient = str(config.get("default_recipient") or "self")
    for key, item in sorted((config.get("recipients") or {}).items()):
        binding = notification_binding_status(str(key), config=config)
        recipients.append(
            {
                "recipient": key,
                "display_name": item.get("display_name") or key,
                "default": key == default_recipient,
                "bound_ready": binding.get("bound_ready", False),
                "channel": item.get("channel") or "",
                "target": recipient_target(item),
                "chat_id": item.get("chat_id") or item.get("target") or "",
                "account_id": item.get("account_id") or "",
                "updated_at": item.get("updated_at") or "",
            }
        )
    if not recipients:
        return {"ok": True, "recipients": [], "message_text": "还没有通知目标。"}
    lines = ["通知目标"]
    for item in recipients:
        marker = "默认" if item["default"] else "可选"
        state = "已绑定" if item["bound_ready"] else "未绑定"
        account_text = f"｜account_id={item['account_id']}" if item["account_id"] else ""
        lines.append(f"- {item['recipient']}｜{marker}｜{state}｜channel={item['channel'] or '-'}｜chat_id={item['chat_id'] or '-'}{account_text}")
    return {"ok": True, "recipients": recipients, "message_text": "\n".join(lines)}


def notification_binding_status(recipient: str = "self", config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or notification_config()
    recipient_data = recipient_config(config, recipient)
    return {
        "recipient": recipient,
        "provider": str(config.get("provider") or "dry_run"),
        "bound": bool(recipient_data.get("bound", False)),
        "bound_ready": recipient_ready(config, recipient),
        "channel": recipient_data.get("channel") or provider_config(config).get("channel") or "",
        "target": recipient_target(recipient_data),
        "chat_id": recipient_data.get("chat_id") or recipient_data.get("target") or "",
        "account_id": recipient_data.get("account_id") or "",
        "missing": missing_binding_fields(config, recipient),
    }


def enable_notification(confirm: bool = False) -> dict[str, Any]:
    config = notification_config()
    if not confirm:
        return {
            "ok": False,
            "requires_confirmation": True,
            "config": public_notification_config(config),
            "message_text": "开启主动消息推送前需要确认配置。确认无误后回复“确认开启消息推送”。",
        }
    if not notification_ready(config):
        return {
            "ok": False,
            "requires_configuration": True,
            "config": public_notification_config(config),
            "message_text": notification_guidance(config),
        }
    config["enabled"] = True
    dump_json(NOTIFICATIONS_FILE, config)
    return {
        "ok": True,
        "enabled": True,
        "config": public_notification_config(config),
        "message_text": f"消息推送已开启：{config.get('provider')}",
    }


def notification_config() -> dict[str, Any]:
    config = load_json(NOTIFICATIONS_FILE, {})
    merged = deep_merge(DEFAULT_NOTIFICATIONS, config if isinstance(config, dict) else {})
    return sanitize_config(merged)


def sanitize_config(config: dict[str, Any]) -> dict[str, Any]:
    # 已废弃的 provider 名称（如 webhook）一律降级为 dry_run，
    # 并丢弃旧文件中残留的 webhook / openclaw_cli.command 字段，
    # 避免被加载后再次写回磁盘。
    provider = str(config.get("provider") or "dry_run")
    if provider not in SUPPORTED_PROVIDERS:
        config["provider"] = "dry_run"
        config["enabled"] = False
    providers = config.get("providers")
    if isinstance(providers, dict):
        providers.pop("webhook", None)
        openclaw_cfg = providers.get("openclaw_cli")
        if isinstance(openclaw_cfg, dict):
            openclaw_cfg.pop("command", None)
    return config


def validate_allowed_user(user_platform_id: str) -> dict[str, Any] | None:
    users = load_json(CONFIG_DIR / "users.json", {})
    allowed = users.get("allow_unknown_users", False) or any(
        item.get("platform_user_id") == user_platform_id and item.get("is_allowed", True)
        for item in users.get("users", [])
    )
    if allowed:
        return None
    return {"ok": False, "error": "用户不在白名单"}


def recipient_config(config: dict[str, Any], recipient: str) -> dict[str, Any]:
    recipients = config.get("recipients", {})
    default_key = config.get("default_recipient", "self")
    current = dict(recipients.get(recipient) or recipients.get(default_key) or {})
    current.setdefault("display_name", recipient)
    current.setdefault("target", "")
    current.setdefault("chat_id", current.get("target") or "")
    current.setdefault("account_id", "")
    current.setdefault("channel", "")
    current.setdefault("bound", False)
    current.setdefault("updated_at", "")
    return current


def recipient_target(recipient: dict[str, Any]) -> str:
    return str(recipient.get("chat_id") or recipient.get("target") or "")


def normalize_delivery(delivery: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(delivery, dict):
        return {}
    channel = str(delivery.get("channel") or delivery.get("source") or "")
    chat_id = str(delivery.get("chat_id") or delivery.get("to") or delivery.get("target") or delivery.get("delivery_to") or "")
    account_id = str(delivery.get("account_id") or delivery.get("accountId") or delivery.get("account") or "")
    return {key: value for key, value in {"channel": channel, "chat_id": chat_id, "account_id": account_id}.items() if value}


def provider_config(config: dict[str, Any]) -> dict[str, Any]:
    provider = str(config.get("provider") or "dry_run")
    return dict(config.get("providers", {}).get(provider, {}))


def providers_channel(config: dict[str, Any], provider: str) -> str:
    return str(config.get("providers", {}).get(provider, {}).get("channel") or "")


def notification_ready(config: dict[str, Any]) -> bool:
    provider = str(config.get("provider") or "dry_run")
    if provider == "dry_run":
        return False
    if provider == "host_payload":
        return True
    if provider == "openclaw_cli":
        if not OPENCLAW_COMMAND:
            return False
        default_recipient = str(config.get("default_recipient") or "self")
        return recipient_ready(config, default_recipient)
    return False


def recipient_ready(config: dict[str, Any], recipient: str) -> bool:
    provider = str(config.get("provider") or "dry_run")
    if provider == "host_payload":
        return True
    if provider == "dry_run":
        return False
    if provider == "openclaw_cli":
        data = recipient_config(config, recipient)
        return bool(data.get("bound") and recipient_target(data) and (data.get("channel") or provider_config(config).get("channel")))
    return False


def delivery_ready(payload: dict[str, Any], provider: str) -> bool:
    if provider == "host_payload":
        return True
    if provider == "openclaw_cli":
        return bool(payload.get("channel") and payload.get("chat_id"))
    return False


def missing_binding_fields(config: dict[str, Any], recipient: str) -> list[str]:
    missing = missing_required_binding_fields(config, recipient)
    provider = str(config.get("provider") or "dry_run")
    if provider == "openclaw_cli" and not recipient_config(config, recipient).get("bound"):
        missing.append("confirm_binding")
    return missing


def missing_required_binding_fields(config: dict[str, Any], recipient: str) -> list[str]:
    provider = str(config.get("provider") or "dry_run")
    if provider != "openclaw_cli":
        return []
    data = recipient_config(config, recipient)
    missing = []
    if not recipient_target(data):
        missing.append("chat_id")
    if not (data.get("channel") or provider_config(config).get("channel")):
        missing.append("channel")
    return missing


def notification_guidance(config: dict[str, Any]) -> str:
    provider = str(config.get("provider") or "dry_run")
    if provider == "openclaw_cli":
        if not OPENCLAW_COMMAND:
            return "未在 PATH 中找到 openclaw 命令，无法启用 openclaw_cli 推送。请先安装 OpenClaw CLI 并确保 openclaw 可在 PATH 中调用。"
        return "主动消息推送还没配置完整。请先配置 OpenClaw provider 的 channel 和收件人 chat_id，再确认开启消息推送。"
    return "主动消息推送尚未启用。可配置 openclaw_cli 或 host_payload 后，再确认开启消息推送。"


def notification_binding_guidance(config: dict[str, Any], recipient: str = "self") -> str:
    provider = str(config.get("provider") or "dry_run")
    if provider == "openclaw_cli":
        return (
            f"通知目标 {recipient} 还没有完成绑定。请确认当前运行环境能提供 channel、chat_id 和 account_id，"
            "然后执行 bind_notification_target 并带上 --channel、--chat-id、--account-id、--confirm。"
        )
    return notification_guidance(config)


def delivery_binding_guidance() -> str:
    return "这个自动任务保存的 delivery 路由不完整。创建任务时需要提供 channel 和 chat_id；多账号场景建议同时提供 account_id。"


def send_openclaw_cli(payload: dict[str, Any]) -> dict[str, Any]:
    # 固定调用 PATH 中的 openclaw 可执行文件，不读取任何 notifications.json 中的 command 字段。
    if not OPENCLAW_COMMAND:
        return {
            "ok": False,
            "sent": False,
            "requires_configuration": True,
            "error": "未在 PATH 中找到 openclaw 命令",
            "payload": payload,
        }
    channel = str(payload.get("channel") or "")
    target = str(payload.get("chat_id") or payload.get("target") or "")
    account_id = str(payload.get("account_id") or "")
    if not channel or not target:
        return {"ok": False, "sent": False, "requires_configuration": True, "error": "缺少 OpenClaw channel/chat_id", "payload": payload}
    args = [OPENCLAW_COMMAND, "message", "send", "--channel", channel, "--target", target, "--message", str(payload.get("content") or "")]
    if account_id:
        args.extend(["--account", account_id])
    try:
        proc = subprocess.run(
            args,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return {"ok": False, "sent": False, "provider": "openclaw_cli", "error": str(exc), "payload": payload}
    return {
        "ok": proc.returncode == 0,
        "sent": proc.returncode == 0,
        "provider": "openclaw_cli",
        "payload": payload,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "returncode": proc.returncode,
    }


def public_notification_config(config: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(config, ensure_ascii=False))


def normalize_provider(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "openclaw": "openclaw_cli",
        "openclaw_cli": "openclaw_cli",
        "host": "host_payload",
        "payload": "host_payload",
        "dryrun": "dry_run",
    }
    return aliases.get(text, text)


def deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(base, ensure_ascii=False))
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result
