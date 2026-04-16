from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from SQL_Controller.pond_daily_logs import get_recent_daily_logs_by_pond_id
from SQL_Controller.ponds import get_user_pond_by_id
from SQL_Controller.sensor_data import get_latest_sensor_status_by_pond, get_metric_trend_by_pond
from methods.ai.time_window_context import build_time_window_context
from methods.ai.time_window_query import parse_time_window_query
from methods.base.serializer import to_jsonable
from methods.config.settings import settings
from methods.infra.redis_client import redis_client
from methods.rag.citation_formatter import format_citations
from methods.rag.rag_search import search_related_paper_context

try:
    TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")
except Exception:
    TAIPEI_TIMEZONE = timezone(timedelta(hours=8))


def cache_key(
    user_id: int,
    pond_id: int,
    message: str,
    use_rag: bool,
    time_window_from: datetime | None,
    time_window_to: datetime | None,
    compare_previous_window: bool,
) -> str:
    time_window_part = (
        f"{time_window_from.isoformat() if time_window_from else ''}:"
        f"{time_window_to.isoformat() if time_window_to else ''}:"
        f"{compare_previous_window}"
    )
    message_hash = hashlib.sha1(f"{use_rag}:{time_window_part}:{message}".encode("utf-8")).hexdigest()[:16]
    return f"{settings.redis_key_prefix}:pond-context:{user_id}:{pond_id}:{message_hash}"


def average_metric(rows: list[dict], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def summarize_trend(rows: list[dict]) -> dict:
    values: list[float] = []
    min_row: dict | None = None
    max_row: dict | None = None

    for row in rows:
        avg_value = row.get("avg_value")
        if avg_value is None:
            continue
        current_value = float(avg_value)
        values.append(current_value)

        if min_row is None or current_value < float(min_row.get("avg_value", current_value)):
            min_row = row
        if max_row is None or current_value > float(max_row.get("avg_value", current_value)):
            max_row = row

    summary = {
        "bucket_count": len(rows),
        "avg_value": round(sum(values) / len(values), 2) if values else None,
        "min_value": round(min(values), 2) if values else None,
        "max_value": round(max(values), 2) if values else None,
        "value_span": round(max(values) - min(values), 2) if values else None,
    }

    if min_row is not None:
        summary["min_bucket_at"] = min_row.get("bucket_at")
        summary["min_bucket_avg"] = round(float(min_row["avg_value"]), 2)
    if max_row is not None:
        summary["max_bucket_at"] = max_row.get("bucket_at")
        summary["max_bucket_avg"] = round(float(max_row["avg_value"]), 2)

    return summary


def needs_time_window_selection(
    message: str,
    explicit_from: datetime | None,
    explicit_to: datetime | None,
    session_summary_state: dict | None,
) -> bool:
    if explicit_from is not None and explicit_to is not None:
        return False

    parsed = parse_time_window_query(message, session_summary_state=session_summary_state)
    if parsed is not None:
        return False

    hint_keywords = (
        "趨勢",
        "變化",
        "波動",
        "比較",
        "一天內",
        "最近",
        "昨天",
        "今天",
        "那天",
        "當天",
        "上週",
        "日夜",
        "白天",
        "晚上",
    )
    lowered = (message or "").lower()
    return any(keyword in message or keyword in lowered for keyword in hint_keywords)


def build_time_window_suggestions() -> list[dict]:
    now = datetime.now(TAIPEI_TIMEZONE)
    return [
        {
            "label": "最近 24 小時",
            "description": "查看日內波動與白天晚上差異。",
            "from_at": (now - timedelta(days=1)).isoformat(),
            "to_at": now.isoformat(),
            "bucket": "10m",
        },
        {
            "label": "最近 7 天",
            "description": "查看近一週趨勢與異常變化。",
            "from_at": (now - timedelta(days=7)).isoformat(),
            "to_at": now.isoformat(),
            "bucket": "hour",
        },
        {
            "label": "最近 30 天",
            "description": "查看較長期趨勢與季節性變化。",
            "from_at": (now - timedelta(days=30)).isoformat(),
            "to_at": now.isoformat(),
            "bucket": "day",
        },
        {
            "label": "自訂時間",
            "description": "由前端日期選擇器指定起訖時間。",
            "requires_user_selection": True,
        },
    ]


async def build_pond_context(
    user_id: int,
    pond_id: int,
    message: str,
    use_rag: bool = True,
    time_window_from: datetime | None = None,
    time_window_to: datetime | None = None,
    compare_previous_window: bool = False,
    session_summary_state: dict | None = None,
) -> dict:
    key = cache_key(
        user_id=user_id,
        pond_id=pond_id,
        message=message,
        use_rag=use_rag,
        time_window_from=time_window_from,
        time_window_to=time_window_to,
        compare_previous_window=compare_previous_window,
    )
    if redis_client is not None:
        cached = await redis_client.get(key)
        if cached:
            return json.loads(cached)

    pond = await get_user_pond_by_id(user_id, pond_id)
    if pond is None:
        raise ValueError("找不到指定魚池，或你沒有權限查看此魚池。")

    latest_rows = await get_latest_sensor_status_by_pond(pond_id)
    do_trend_hour = await get_metric_trend_by_pond(pond_id, "do_mg_l", hours=24, bucket="hour")
    ph_trend_hour = await get_metric_trend_by_pond(pond_id, "ph", hours=24, bucket="hour")
    do_trend_10m = await get_metric_trend_by_pond(pond_id, "do_mg_l", hours=24, bucket="10m")
    ph_trend_10m = await get_metric_trend_by_pond(pond_id, "ph", hours=24, bucket="10m")
    daily_logs = await get_recent_daily_logs_by_pond_id(pond_id, days=7)

    time_window_trend = await build_time_window_context(
        pond_id=pond_id,
        message=message,
        explicit_from=time_window_from,
        explicit_to=time_window_to,
        compare_previous_window=compare_previous_window,
        session_summary_state=session_summary_state,
    )

    time_window_suggestions: list[dict] = []
    if time_window_trend is None and needs_time_window_selection(
        message,
        time_window_from,
        time_window_to,
        session_summary_state,
    ):
        time_window_suggestions = build_time_window_suggestions()

    if use_rag:
        rag_result = await search_related_paper_context(
            message,
            limit=settings.rag_max_context_papers * (settings.rag_max_chunks_per_paper + settings.rag_neighbor_window),
        )
        paper_chunks = rag_result["references"]
        citations = format_citations(paper_chunks, limit=settings.rag_max_context_papers)
        rag_retrieval = rag_result["retrieval"]
    else:
        paper_chunks = []
        citations = []
        rag_retrieval = {
            "enabled": False,
            "rounds": 0,
            "candidate_limit": 0,
            "evidence_sufficient": False,
            "metrics": {
                "distinct_papers": 0,
                "total_chunks": 0,
                "total_characters": 0,
            },
        }

    context = {
        "pond": pond,
        "latest_status": {
            "sensor_count": len(latest_rows),
            "dissolved_oxygen_avg": average_metric(latest_rows, "do_mg_l"),
            "ph_avg": average_metric(latest_rows, "ph"),
            "temp_deep_avg": average_metric(latest_rows, "temp_deep"),
            "temp_shallow_avg": average_metric(latest_rows, "temp_shallow"),
            "rows": latest_rows,
        },
        "trend": {
            "dissolved_oxygen": {
                "hourly": do_trend_hour,
                "ten_minute": do_trend_10m,
                "summary": {
                    "hourly": summarize_trend(do_trend_hour),
                    "ten_minute": summarize_trend(do_trend_10m),
                },
            },
            "ph": {
                "hourly": ph_trend_hour,
                "ten_minute": ph_trend_10m,
                "summary": {
                    "hourly": summarize_trend(ph_trend_hour),
                    "ten_minute": summarize_trend(ph_trend_10m),
                },
            },
        },
        "time_window_trend": time_window_trend or {
            "requested": False,
            "data": {},
        },
        "autonomous_time_window_trend": {
            "requested": False,
        },
        "time_window_suggestions": time_window_suggestions,
        "daily_logs": daily_logs,
        "rag_references": paper_chunks,
        "citations": citations,
        "rag_retrieval": rag_retrieval,
    }

    jsonable_context = to_jsonable(context)
    if redis_client is not None:
        await redis_client.set(
            key,
            json.dumps(jsonable_context, ensure_ascii=False),
            ex=settings.cache_ttl_latest_summary,
        )
    return jsonable_context
