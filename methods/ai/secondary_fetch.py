from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from SQL_Controller.sensor_data import ALLOWED_METRICS
from methods.ai.llm_stream import generate_json
from methods.ai.time_window_context import build_explicit_time_window_context
from methods.ai.time_window_query import as_taipei, build_time_window_query
from methods.base.serializer import to_jsonable
from methods.config.settings import settings

ALLOWED_BUCKETS = {"10m", "hour", "day"}


def build_secondary_fetch_prompt() -> str:
    return (
        "你是感測資料查詢規劃器。你的工作不是回答問題，而是判斷是否需要再查一次額外的感測資料時間窗。\n"
        "你必須只輸出 JSON，不能輸出任何多餘文字。\n"
        "輸出格式：\n"
        "{\n"
        '  "need_more_time_window_data": true 或 false,\n'
        '  "reason": "簡短原因",\n'
        '  "query": {\n'
        '    "from_at": "ISO 8601",\n'
        '    "to_at": "ISO 8601",\n'
        '    "metrics": ["do_mg_l", "ph"],\n'
        '    "bucket": "10m 或 hour 或 day",\n'
        '    "compare_previous_window": false\n'
        "  }\n"
        "}\n"
        "規則：\n"
        "1. 只有在目前 context 不足以回答感測趨勢問題時，才要求補查。\n"
        "2. 若 context.time_window_trend 或 context.autonomous_time_window_trend 已經包含足夠時間窗，應回傳 need_more_time_window_data=false。\n"
        "3. 只可查感測資料，不可查論文、不可查任意 SQL。\n"
        "4. metrics 只能從 do_mg_l、ph、temp_deep、temp_shallow、turbidity_ntu、orp_mv 中選。\n"
        "5. 24 小時內優先用 10m；7 天內優先用 hour；更長用 day。\n"
        "6. 若問題包含『那一天、那天、當天、白天、晚上、日夜差』，可要求更精細的日內區間。\n"
        "7. 若根本不需要額外資料，query 應為 null。"
    )


def build_secondary_fetch_user_prompt(message: str, context: dict) -> str:
    planning_context = {
        "question": message,
        "pond": context.get("pond"),
        "latest_status": context.get("latest_status"),
        "trend_summary": {
            "dissolved_oxygen": context.get("trend", {}).get("dissolved_oxygen", {}).get("summary", {}),
            "ph": context.get("trend", {}).get("ph", {}).get("summary", {}),
        },
        "time_window_trend": context.get("time_window_trend"),
        "autonomous_time_window_trend": context.get("autonomous_time_window_trend"),
        "time_window_suggestions": context.get("time_window_suggestions", []),
        "session_summary_json": context.get("session_summary_json"),
        "conversation_history": context.get("conversation_history", [])[-6:],
    }
    return (
        "請判斷是否需要再查額外時間段的感測資料。\n"
        f"使用者問題：{message}\n"
        f"context：{to_jsonable(planning_context)}"
    )


def normalize_secondary_fetch_plan(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(plan, dict):
        return None

    if not bool(plan.get("need_more_time_window_data")):
        return None

    query = plan.get("query")
    if not isinstance(query, dict):
        return None

    try:
        from_at = as_taipei(datetime.fromisoformat(str(query.get("from_at"))))
        to_at = as_taipei(datetime.fromisoformat(str(query.get("to_at"))))
    except Exception:
        return None

    metrics = [metric for metric in query.get("metrics", []) if metric in ALLOWED_METRICS]
    if not metrics:
        metrics = ["do_mg_l", "ph"]
    metrics = metrics[: max(settings.autonomous_time_window_max_metrics, 1)]

    bucket = str(query.get("bucket") or "").strip()
    if bucket not in ALLOWED_BUCKETS:
        bucket = None

    compare_previous_window = bool(query.get("compare_previous_window", False))
    normalized_query = build_time_window_query(
        from_at=from_at,
        to_at=to_at,
        metrics=metrics,
        bucket=bucket,
        compare_previous_window=compare_previous_window,
        matched_by="autonomous_secondary_fetch",
    )

    return {
        "reason": str(plan.get("reason") or "").strip(),
        "query": normalized_query,
    }


def build_secondary_fetch_signature(query: Any) -> str:
    return "|".join(
        [
            query.from_at.isoformat(),
            query.to_at.isoformat(),
            ",".join(query.metrics),
            query.bucket,
            str(query.compare_previous_window),
        ]
    )


async def maybe_run_autonomous_time_window_fetch(
    *,
    message: str,
    pond_id: int,
    context: dict,
) -> tuple[dict, dict]:
    if not settings.autonomous_time_window_fetch_enabled:
        return context, {"enabled": False, "executed_rounds": 0, "plans": [], "stopped_reason": "disabled"}

    updated_context = deepcopy(context)
    summary = {
        "enabled": True,
        "executed_rounds": 0,
        "plans": [],
        "stopped_reason": "no_fetch_needed",
    }
    seen_signatures: set[str] = set()

    for round_index in range(1, max(settings.autonomous_time_window_max_rounds, 0) + 1):
        plan = await generate_json(
            system_prompt=build_secondary_fetch_prompt(),
            user_prompt=build_secondary_fetch_user_prompt(message, updated_context),
        )
        normalized_plan = normalize_secondary_fetch_plan(plan)
        if normalized_plan is None:
            summary["stopped_reason"] = "planner_returned_none"
            break

        query = normalized_plan["query"]
        signature = build_secondary_fetch_signature(query)
        if signature in seen_signatures:
            summary["stopped_reason"] = "duplicate_plan"
            break
        seen_signatures.add(signature)

        fetched_context = await build_explicit_time_window_context(
            pond_id,
            from_at=query.from_at,
            to_at=query.to_at,
            metrics=query.metrics,
            bucket=query.bucket,
            compare_previous_window=query.compare_previous_window,
            previous_from_at=query.previous_from_at,
            previous_to_at=query.previous_to_at,
            matched_by=query.matched_by,
            comparison_matched_by=query.comparison_matched_by,
        )

        updated_context["autonomous_time_window_trend"] = fetched_context
        updated_context["autonomous_time_window_fetch"] = {
            "requested": True,
            "round": round_index,
            "reason": normalized_plan["reason"],
            "query": {
                "from_at": query.from_at.isoformat(),
                "to_at": query.to_at.isoformat(),
                "metrics": query.metrics,
                "bucket": query.bucket,
                "requested_bucket": query.requested_bucket,
                "compare_previous_window": query.compare_previous_window,
            },
        }

        summary["executed_rounds"] += 1
        summary["plans"].append(
            {
                "round": round_index,
                "reason": normalized_plan["reason"],
                "query": {
                    "from_at": query.from_at.isoformat(),
                    "to_at": query.to_at.isoformat(),
                    "metrics": query.metrics,
                    "bucket": query.bucket,
                    "requested_bucket": query.requested_bucket,
                    "compare_previous_window": query.compare_previous_window,
                },
            }
        )
        summary["stopped_reason"] = "max_rounds_reached"

    return to_jsonable(updated_context), to_jsonable(summary)
