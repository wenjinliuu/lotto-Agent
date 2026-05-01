from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from urllib.parse import urlencode
from pathlib import Path

import database
from followup import add as add_followup
from parse_draw_api import parse_jisuapi, parse_manual, parse_public_draw
from utils import BASE_DIR, CONFIG_DIR, env, load_json, normalize_lottery_type


API_CONFIG = load_json(CONFIG_DIR / "api_sources.json", {})
RULES = load_json(CONFIG_DIR / "lottery_rules.json", {})


def fetch_draw(lottery_type: str = "all", issue: str | None = None, source: str | None = None) -> dict[str, Any]:
    database.init_db()
    if lottery_type == "all":
        results = []
        for key in RULES.get("lotteries", {}):
            results.append(fetch_draw(key, issue=issue, source=source))
        ok_count = len([item for item in results if item.get("ok")])
        result = {"ok": ok_count == len(results), "results": results, "wechat_text": f"开奖抓取完成：{ok_count}/{len(results)} 成功"}
        add_followup(result, "fetch_ok" if result["ok"] else "fetch_partial", f"all:{ok_count}:{len(results)}")
        return result

    key = normalize_lottery_type(lottery_type, RULES)
    source_name = source or API_CONFIG.get("default_source", "jisuapi")
    source_config = API_CONFIG["sources"][source_name]
    if source_config.get("type") == "static_json":
        return fetch_public_draw(key, issue, source_name, source_config)
    return fetch_api_draw(key, issue, source_name, source_config)


def fetch_public_draw(lottery_type: str, issue: str | None, source_name: str, source_config: dict[str, Any]) -> dict[str, Any]:
    try:
        source_url = public_draw_url(lottery_type, issue, source_config)
        payload = read_json_resource(source_url, int(source_config.get("timeout_seconds", 12)))
        draw_payload = select_public_draw_payload(lottery_type, issue, payload)
        draw = parse_public_draw(lottery_type, draw_payload, source_url=source_url)
        draw_id = database.upsert_draw(draw)
        database.log_api(lottery_type, source_url, "ok", f"public source {source_name} saved issue {draw['issue']}")
        result = {"ok": True, "draw_id": draw_id, "draw": draw, "wechat_text": render_draw(draw)}
        add_followup(result, "fetch_ok", f"{lottery_type}:{draw.get('issue')}")
        return result
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        message = f"公开开奖源读取失败: {exc}"
        database.log_api(lottery_type, source_config.get("public_base_url", ""), "error", message)
        return {"ok": False, "error": message, "lottery_type": lottery_type}


def fetch_api_draw(key: str, issue: str | None, source_name: str, source_config: dict[str, Any]) -> dict[str, Any]:
    appkey = env(source_config.get("appkey_env", "JISU_APPKEY"))
    if not appkey:
        message = f"缺少环境变量 {source_config.get('appkey_env')}"
        database.log_api(key, source_config.get("base_url", ""), "error", message)
        return {"ok": False, "error": message}

    params = {"appkey": appkey, "caipiaoid": source_config["lottery_ids"][key]}
    if issue:
        params["issueno"] = issue
    url = f"{source_config['base_url']}?{urlencode(params)}"
    try:
        lottery_id = source_config["lottery_ids"][key]
        with urlopen(url, timeout=int(source_config.get("timeout_seconds", 12))) as response:
            payload = json.loads(response.read().decode("utf-8"))
        draw = parse_jisuapi(key, payload, source_url=safe_url(url))
        class_info = fetch_class_info(source_config, appkey, lottery_id)
        if class_info:
            draw["next_issue"] = draw.get("next_issue") or str(class_info.get("nextissueno") or "")
            draw["next_draw_date"] = draw.get("next_draw_date") or str(class_info.get("nextopentime") or "")[:10]
            draw["next_open_time"] = draw.get("next_open_time") or str(class_info.get("nextopentime") or "")
            draw["next_buy_end_time"] = draw.get("next_buy_end_time") or str(class_info.get("nextbuyendtime") or "")
            draw["raw"] = {"query": payload, "class_info": class_info}
        draw_id = database.upsert_draw(draw)
        database.log_api(key, safe_url(url), "ok", f"api source {source_name} saved issue {draw['issue']}")
        result = {"ok": True, "draw_id": draw_id, "draw": draw, "wechat_text": render_draw(draw)}
        add_followup(result, "fetch_ok", f"{key}:{draw.get('issue')}")
        return result
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        database.log_api(key, safe_url(url), "error", str(exc))
        return {"ok": False, "error": str(exc), "lottery_type": key}


def public_draw_url(lottery_type: str, issue: str | None, source_config: dict[str, Any]) -> str:
    base_url = env(source_config.get("public_base_url_env", ""), source_config.get("public_base_url", "")).rstrip("/")
    if not base_url:
        raise ValueError("未配置 LOTTERY_PUBLIC_DATA_BASE_URL 或 public_base_url")
    path = source_config.get("draws_path", "draws/{lottery_type}.json") if issue else source_config.get("latest_path", "latest.json")
    return f"{base_url}/{path.format(lottery_type=lottery_type)}"


def read_json_resource(location: str, timeout: int) -> dict[str, Any]:
    if location.startswith("http://") or location.startswith("https://"):
        with urlopen(location, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    path = Path(location)
    if not path.is_absolute():
        path = BASE_DIR / location
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def select_public_draw_payload(lottery_type: str, issue: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    if issue:
        draws = payload.get("draws", [])
        if isinstance(draws, dict):
            draw = draws.get(issue)
            if draw:
                return draw
        for draw in draws:
            if str(draw.get("issue")) == str(issue):
                return draw
        raise ValueError(f"公开开奖源中找不到 {lottery_type} 第 {issue} 期")
    draw = payload.get("draws", {}).get(lottery_type)
    if not draw:
        raise ValueError(f"公开开奖源 latest.json 中没有 {lottery_type}")
    return draw


def manual_draw_input(lottery_type: str, payload: dict[str, Any] | str) -> dict[str, Any]:
    database.init_db()
    key = normalize_lottery_type(lottery_type, RULES)
    if isinstance(payload, str):
        payload = json.loads(payload)
    draw = parse_manual(key, payload)
    draw_id = database.upsert_draw(draw)
    result = {"ok": True, "draw_id": draw_id, "draw": draw, "wechat_text": render_draw(draw)}
    add_followup(result, "fetch_ok", f"{key}:{draw.get('issue')}")
    return result


def render_draw(draw: dict[str, Any]) -> str:
    name = RULES["lotteries"][draw["lottery_type"]]["name"]
    return "\n".join(
        [
            f"{name} 第{draw['issue']}期开奖",
            format_draw_numbers(draw["lottery_type"], draw.get("numbers", {})),
            f"开奖日期：{draw.get('draw_date') or '-'}",
            f"奖池：{draw.get('prize_pool') or '-'}",
        ]
    )


def fetch_class_info(source_config: dict[str, Any], appkey: str, lottery_id: int) -> dict[str, Any]:
    class_url = source_config.get("class_url")
    if not class_url:
        return {}
    url = f"{class_url}?{urlencode({'appkey': appkey})}"
    try:
        with urlopen(url, timeout=int(source_config.get("timeout_seconds", 12))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return {}
    result = payload.get("result") if isinstance(payload, dict) else None
    if isinstance(result, dict):
        candidates = result.get("list") or result.get("data") or []
    elif isinstance(result, list):
        candidates = result
    else:
        candidates = []
    for item in candidates:
        if int(item.get("caipiaoid") or 0) == int(lottery_id):
            return item
    return {}


def format_draw_numbers(lottery_type: str, numbers: dict[str, Any]) -> str:
    from generate_numbers import format_numbers

    if lottery_type == "qxc":
        return format_numbers(lottery_type, numbers)
    if lottery_type == "qlc":
        text = format_numbers(lottery_type, numbers)
        if numbers.get("special") is not None:
            text += f" + {str(numbers['special']).zfill(2)}"
        return text
    return format_numbers(lottery_type, numbers)


def safe_url(url: str) -> str:
    return url.replace(env("JISU_APPKEY"), "***") if env("JISU_APPKEY") else url
