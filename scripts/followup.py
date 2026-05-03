from __future__ import annotations

import hashlib
from typing import Any


TEMPLATES: dict[str, list[str]] = {
    "generate_purchased": [
        "已按已购买记录，开奖后会自动纳入兑奖。",
        "号码已入库并计入成本，后面兑奖会自动跟上。",
        "这组已记录为已购买，我会盯着对应开奖日。",
    ],
    "generate_preview": [
        "这组只是看看，不计入成本，也不会参与自动兑奖。",
        "已按参考号码处理，账本里不会把它算成投入。",
        "这组先放在参考位，不会影响后面的盈亏统计。",
    ],
    "date_adjusted": [
        "{note}",
        "{note} 我已经按修正后的开奖日记录。",
        "{note} 后续兑奖会跟着新的开奖日走。",
    ],
    "manual_ticket": [
        "已按已购买记录，后续会参与成本统计和自动兑奖。",
        "号码已记到账本里，开奖后会自动检查。",
        "这几注已经入库，后面报表也会一起统计。",
    ],
    "replace": [
        "上一组已标记为已替换，不再计入成本或兑奖。",
        "旧号码已经移出统计，新号码接上。",
        "替换完成，账本会只认这次的新号码。",
    ],
    "cancel": [
        "已取消统计，这些号码不会计入成本或参与兑奖。",
        "这组已从投入里拿掉，后面不会拿它兑奖。",
        "取消完成，账本不会再算这几注。",
    ],
    "confirm": [
        "已改为已购买，后续会参与成本统计和兑奖。",
        "确认好了，开奖后会自动核对这几注。",
        "已接入统计，后面报表会把它算进去。",
    ],
    "fetch_ok": [
        "开奖数据已同步到本地数据库。",
        "开奖信息已入库，后面查询和兑奖都会读本地数据。",
        "数据同步完成，奖项明细也会一起保存。",
    ],
    "fetch_partial": [
        "部分开奖数据暂时没同步成功，窗口期里还会继续尝试。",
        "有些彩种还没拿到新数据，我会等 GitHub 更新后再抓。",
        "同步不是全量成功，后续轮询会继续补。",
    ],
    "prize_empty": [
        "当前没有匹配到可兑奖的已购买号码。",
        "这次没有可兑奖记录，所以没有写入兑奖结果。",
        "还没找到能对应本期开奖的已购买号码。",
    ],
    "prize_no_win": [
        "兑奖结果已写入，这期没有中奖记录。",
        "核对完成，没有命中奖项，账本已更新。",
        "这期没中，记录已经更新到本地。",
    ],
    "prize_win": [
        "中奖结果已写入，后续报表会统计这笔回报。",
        "有命中奖项，金额已进入本地回报统计。",
        "这次有收获，兑奖结果已经落库。",
    ],
    "automation_created": [
        "自动任务已保存，到点会由服务器唤醒器执行。",
        "任务已经排上队了，后面按这个时间自动跑。",
        "自动化规则已入库，之后交给调度器盯着。",
    ],
    "cron_needed": [
        "自动化唤醒器还没开启，回复“确认开启自动化”即可安装。",
        "还差一个服务器唤醒器，回“确认开启自动化”就能接上。",
        "任务已保存；要让它自动跑，还需要确认开启自动化。",
    ],
    "cron_installed": [
        "自动化唤醒器已开启，后续任务会按时间自动执行。",
        "定时唤醒已经接上，之后它会每 30 分钟检查一次。",
        "自动化通道打开了，后面的任务会自己醒来干活。",
    ],
    "config_updated": [
        "配置已保存，并自动做了备份。",
        "设置已经更新，旧配置也留了备份。",
        "偏好已写入，后面会按新的规则来。",
    ],
    "report": [
        "报表已生成，统计口径只包含有效已购买记录。",
        "这份统计已按本地账本生成。",
        "报表整理好了，盈亏会继续随着兑奖结果更新。",
    ],
}

EVENT_DESCRIPTIONS = {
    "generate_purchased": "号码已生成并按已购买记录",
    "generate_preview": "号码仅作为参考预览",
    "date_adjusted": "用户指定日期不是实际开奖日，系统已顺延",
    "manual_ticket": "用户手动录入的号码已记录",
    "replace": "上一组号码已被新号码替换",
    "cancel": "号码或任务已取消/停用",
    "confirm": "号码已确认购买",
    "fetch_ok": "开奖数据已同步",
    "fetch_partial": "开奖数据部分同步失败或暂未完整",
    "prize_empty": "没有匹配到可兑奖的已购买号码",
    "prize_no_win": "兑奖完成但未中奖",
    "prize_win": "兑奖完成且有中奖结果",
    "automation_created": "自动任务已创建",
    "cron_needed": "自动任务已保存但服务器唤醒器尚未开启",
    "cron_installed": "服务器自动化唤醒器已开启",
    "config_updated": "配置已更新并备份",
    "report": "报表已生成",
}

STRICT_EVENTS = {"date_adjusted", "generate_preview", "cancel", "cron_needed", "fetch_partial", "prize_empty"}

DEFAULT_GUARDRAILS = [
    "只写一句中文消息提示，尽量短，口吻自然一点。",
    "不要重复第一条核心结果里的号码、金额明细或长表格。",
    "不要承诺中奖，不要暗示提高中奖率，不要使用预测、必中、稳赚等表达。",
    "不要改动或新增任何号码、期号、开奖日期、金额、状态。",
    "不要给额外选号建议，不要解释随机算法。",
]


def pick(kind: str, seed: Any = "", **kwargs: Any) -> str:
    options = TEMPLATES.get(kind, [])
    if not options:
        return ""
    digest = hashlib.sha256(f"{kind}:{seed}".encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % len(options)
    return options[index].format(**kwargs)


def add(result: dict[str, Any], kind: str, seed: Any = "", **kwargs: Any) -> dict[str, Any]:
    message = pick(kind, seed, **kwargs)
    if not message:
        return result
    messages = list(result.get("followup_messages") or [])
    if message not in messages:
        messages.append(message)
    result["followup_messages"] = messages
    result.setdefault("followup_text", message)
    add_context(result, kind, message, seed=seed, facts=kwargs)
    return result


def add_note(result: dict[str, Any], note: str | None, kind: str = "date_adjusted", seed: Any = "") -> dict[str, Any]:
    if not note:
        return result
    return add(result, kind, seed or note, note=note)


def add_context(result: dict[str, Any], kind: str, fallback: str, seed: Any = "", facts: dict[str, Any] | None = None) -> None:
    contexts = list(result.get("followup_contexts") or [])
    contexts.append(
        {
            "event": kind,
            "event_description": EVENT_DESCRIPTIONS.get(kind, kind),
            "facts": sanitize_facts({**infer_facts(result), **(facts or {})}),
            "fallback_text": fallback,
            "freedom": "high" if kind not in STRICT_EVENTS else "medium",
            "style": {
                "tone": "自然、轻松、像聊天里顺手补一句；可以有一点点个性，但不要油腻。",
                "length": "1 sentence, 8-28 Chinese characters preferred",
                "avoid_template_feel": True,
            },
            "guardrails": DEFAULT_GUARDRAILS,
            "strict_facts": sorted(strict_fact_keys(kind)),
            "seed": str(seed),
        }
    )
    result["followup_contexts"] = contexts


def infer_facts(result: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for key in ("lottery_type", "batch_id", "total_cost", "checked_count", "winning_count", "total_amount", "task_id", "cron_installed"):
        if key in result:
            facts[key] = result[key]
    tracking = result.get("tracking")
    if isinstance(tracking, dict):
        for key in ("issue", "draw_date", "status", "note", "source"):
            if tracking.get(key):
                facts[key] = tracking[key]
    if "notice_text" in result and result.get("notice_text"):
        facts["notice_text"] = result["notice_text"]
    tickets = result.get("tickets")
    if isinstance(tickets, list) and tickets:
        first = tickets[0]
        facts["ticket_count"] = len(tickets)
        facts["is_purchased"] = bool(first.get("is_purchased"))
        if first.get("draw_date"):
            facts["draw_date"] = first["draw_date"]
        if first.get("issue"):
            facts["issue"] = first["issue"]
    return facts


def sanitize_facts(facts: dict[str, Any]) -> dict[str, Any]:
    clean = {}
    for key, value in facts.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (str, int, float, bool)):
            clean[key] = value
        else:
            clean[key] = str(value)
    return clean


def strict_fact_keys(kind: str) -> set[str]:
    common = {"is_purchased", "draw_date", "issue", "checked_count", "winning_count", "total_amount"}
    if kind in STRICT_EVENTS:
        return common | {"notice_text", "note", "cron_installed"}
    return common
