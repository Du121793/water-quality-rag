from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from methods.base.serializer import to_jsonable

try:
    TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")
except Exception:
    TAIPEI_TIMEZONE = timezone.utc


SESSION_SUMMARY_VERSION = 1
DEFAULT_HISTORY_MESSAGE_BUDGET = 4000
DEFAULT_SESSION_SUMMARY_BUDGET = 1200

FOLLOW_UP_HINTS = (
    "繼續",
    "接續",
    "剛剛",
    "那個",
    "這個",
    "上一段",
    "前面",
    "同上",
    "再看",
    "再幫我",
    "比較",
)

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "魚池": ("魚池", "魚塭", "pond"),
    "水質": ("水質", "water quality"),
    "溶氧": ("do", "dissolved oxygen", "溶氧", "缺氧", "氧氣", "oxygen"),
    "pH": ("ph", "酸鹼", "氫離子"),
    "水溫": ("temp", "水溫", "溫度", "temperature"),
    "濁度": ("turbidity", "濁度"),
    "ORP": ("orp", "氧化還原", "redox"),
    "日夜差": ("白天", "晚上", "日夜", "夜間"),
    "比較": ("比較", "前 7 天", "前7天", "前 7 日", "前7日", "上週", "對照"),
    "論文": ("論文", "文獻", "研究", "paper", "citation"),
    "網路搜尋": ("網路", "搜尋", "web search", "google search"),
}


def _now_iso() -> str:
    return datetime.now(TAIPEI_TIMEZONE).isoformat()


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _clip_text(value: str, max_chars: int) -> str:
    text = _normalize_text(value)
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _coerce_dict(value: object) -> dict | None:
    if isinstance(value, dict):
        normalized = to_jsonable(value)
        return normalized if isinstance(normalized, dict) else None

    if hasattr(value, "items"):
        try:
            normalized = to_jsonable(dict(value.items()))
            return normalized if isinstance(normalized, dict) else None
        except Exception:
            return None

    if isinstance(value, (list, tuple)):
        try:
            normalized = to_jsonable(dict(value))
            return normalized if isinstance(normalized, dict) else None
        except Exception:
            return None

    return None


def _ensure_list_of_dicts(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []

    result: list[dict] = []
    for item in value:
        normalized = _coerce_dict(item)
        if normalized is not None:
            result.append(normalized)
    return result


def _unique_preserve_order(items: Iterable[str], limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = _normalize_text(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
        if limit is not None and len(result) >= limit:
            break
    return result


def _unique_keyed_facts(items: list[dict], limit: int = 8) -> list[dict]:
    result: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        key = _normalize_text(str(item.get("key", "")))
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _parse_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _trend_direction_from_series(rows: list[dict]) -> str:
    values: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = _parse_float(row.get("avg_value"))
        if value is not None:
            values.append(value)

    if len(values) < 2:
        return "stable"

    delta = round(values[-1] - values[0], 2)
    if abs(delta) < 0.1:
        return "stable"
    return "up" if delta > 0 else "down"


def trim_chat_history_by_budget(messages: list[dict], max_chars: int) -> tuple[list[dict], dict]:
    """
    以字元預算裁切最近對話，保留越新的訊息越優先。
    """

    if max_chars <= 0:
        return [], {
            "requested_max_chars": max_chars,
            "kept_chars": 0,
            "dropped_count": len(messages),
            "dropped_chars": sum(len(str(message.get("message", ""))) for message in messages),
            "kept_count": 0,
        }

    selected_reversed: list[dict] = []
    used_chars = 0

    for message in reversed(messages):
        message_text = str(message.get("message", ""))
        message_cost = len(message_text) + 40
        if selected_reversed and used_chars + message_cost > max_chars:
            break
        if not selected_reversed and message_cost > max_chars:
            selected_reversed.append({**message, "message": _clip_text(message_text, max_chars)})
            used_chars = max_chars
            break

        selected_reversed.append(message)
        used_chars += message_cost

    selected = list(reversed(selected_reversed))
    dropped = max(len(messages) - len(selected), 0)
    dropped_chars = 0
    if dropped > 0:
        dropped_chars = sum(len(str(message.get("message", ""))) for message in messages[:dropped])

    return selected, {
        "requested_max_chars": max_chars,
        "kept_chars": used_chars,
        "dropped_count": dropped,
        "dropped_chars": dropped_chars,
        "kept_count": len(selected),
    }


def _extract_topics(*texts: str) -> list[str]:
    detected: list[str] = []
    joined = " ".join(_normalize_text(text) for text in texts if text)
    lowered = joined.lower()

    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            detected.append(topic)

    return _unique_preserve_order(detected)


def _extract_time_window_topic(time_window_summary: dict | None) -> str | None:
    if not time_window_summary or not time_window_summary.get("requested"):
        return None

    if time_window_summary.get("mode") == "comparison":
        previous = f"{time_window_summary.get('previous_from_at')} ~ {time_window_summary.get('previous_to_at')}"
        current = f"{time_window_summary.get('from_at')} ~ {time_window_summary.get('to_at')}"
        return f"比較 {previous} 與 {current}"

    return f"{time_window_summary.get('from_at')} ~ {time_window_summary.get('to_at')}"


def _derive_current_goal(
    previous_state: dict,
    latest_user_message: str,
    time_window_summary: dict | None,
    recent_topics: list[str],
) -> str:
    previous_goal = _normalize_text(str(previous_state.get("current_goal", "")))
    message = _normalize_text(latest_user_message)

    if time_window_summary and time_window_summary.get("requested"):
        if time_window_summary.get("mode") == "comparison":
            return "比較不同時間窗的魚池水質變化"

        filtered_topics = [topic for topic in recent_topics if topic not in {"比較"}]
        topic_text = "、".join(filtered_topics[:2]) if filtered_topics else "水質"
        window_topic = _extract_time_window_topic(time_window_summary)
        if window_topic:
            return f"觀察 {window_topic} 的 {topic_text} 趨勢"
        return f"觀察指定時間窗的 {topic_text} 趨勢"

    if previous_goal and any(hint in message for hint in FOLLOW_UP_HINTS):
        return previous_goal

    if recent_topics:
        return f"追蹤 { '、'.join(recent_topics[:2]) } 狀況"

    if message:
        return _clip_text(message, 64)

    return previous_goal or "追蹤魚池狀況"


def _merge_confirmed_facts(previous_state: dict, context: dict, time_window_summary: dict | None) -> list[dict]:
    pond = context.get("pond") or {}
    latest_status = context.get("latest_status") or {}
    facts: list[dict] = []

    if pond.get("pond_name") is not None:
        facts.append({"key": "pond_name", "label": "魚池名稱", "value": pond.get("pond_name")})
    if pond.get("id") is not None:
        facts.append({"key": "pond_id", "label": "魚池 ID", "value": pond.get("id")})
    if pond.get("total_fish_count") is not None:
        facts.append({"key": "total_fish_count", "label": "魚隻數量", "value": pond.get("total_fish_count")})
    if pond.get("total_fish_weight") is not None:
        facts.append({"key": "total_fish_weight", "label": "魚隻總重", "value": pond.get("total_fish_weight")})
    if pond.get("feeding_growth_rate") is not None:
        facts.append({"key": "feeding_growth_rate", "label": "飼料增長率", "value": pond.get("feeding_growth_rate")})

    if latest_status.get("dissolved_oxygen_avg") is not None:
        facts.append({"key": "latest_do_mg_l", "label": "最新溶氧平均", "value": latest_status.get("dissolved_oxygen_avg"), "unit": "mg/L"})
    if latest_status.get("ph_avg") is not None:
        facts.append({"key": "latest_ph", "label": "最新 pH 平均", "value": latest_status.get("ph_avg")})
    if latest_status.get("temp_deep_avg") is not None:
        facts.append({"key": "latest_temp_deep", "label": "深層水溫平均", "value": latest_status.get("temp_deep_avg"), "unit": "°C"})
    if latest_status.get("temp_shallow_avg") is not None:
        facts.append({"key": "latest_temp_shallow", "label": "淺層水溫平均", "value": latest_status.get("temp_shallow_avg"), "unit": "°C"})

    if latest_status.get("sensor_count") is not None:
        facts.append({"key": "sensor_count", "label": "可用感測器數量", "value": latest_status.get("sensor_count")})

    if time_window_summary and time_window_summary.get("requested"):
        facts.append(
            {
                "key": "last_selected_window",
                "label": "上次查詢時間窗",
                "value": {
                    "mode": time_window_summary.get("mode"),
                    "from_at": time_window_summary.get("from_at"),
                    "to_at": time_window_summary.get("to_at"),
                    "previous_from_at": time_window_summary.get("previous_from_at"),
                    "previous_to_at": time_window_summary.get("previous_to_at"),
                    "bucket": time_window_summary.get("bucket"),
                    "requested_bucket": time_window_summary.get("requested_bucket"),
                    "matched_by": time_window_summary.get("matched_by"),
                },
            }
        )

    previous_confirmed = _ensure_list_of_dicts(previous_state.get("confirmed_facts"))
    return _unique_keyed_facts(previous_confirmed + facts)


def _build_time_preferences(previous_state: dict, time_window_summary: dict | None, context: dict) -> dict:
    previous_preferences = previous_state.get("time_preferences") or {}
    if not isinstance(previous_preferences, dict):
        previous_preferences = {}

    if time_window_summary and time_window_summary.get("requested"):
        preferred_granularity = time_window_summary.get("requested_bucket") or time_window_summary.get("bucket")
        if preferred_granularity == "10m":
            preferred_granularity = "10m"
        elif preferred_granularity == "hour":
            preferred_granularity = "hour"
        else:
            preferred_granularity = "day"

        return {
            "last_selected_window": {
                "mode": time_window_summary.get("mode"),
                "from_at": time_window_summary.get("from_at"),
                "to_at": time_window_summary.get("to_at"),
                "previous_from_at": time_window_summary.get("previous_from_at"),
                "previous_to_at": time_window_summary.get("previous_to_at"),
                "bucket": time_window_summary.get("bucket"),
                "requested_bucket": time_window_summary.get("requested_bucket"),
                "matched_by": time_window_summary.get("matched_by"),
                "comparison_matched_by": time_window_summary.get("comparison_matched_by"),
                "compare_previous_window": bool(time_window_summary.get("mode") == "comparison"),
            },
            "preferred_granularity": preferred_granularity,
        }

    time_suggestions = context.get("time_window_suggestions") or []
    if time_suggestions:
        previous_preferences.setdefault("preferred_granularity", "hour")
        return previous_preferences

    if "preferred_granularity" not in previous_preferences:
        previous_preferences["preferred_granularity"] = "hour"
    return previous_preferences


def _build_important_metrics(context: dict) -> dict:
    latest_status = context.get("latest_status") or {}
    trend = context.get("trend") or {}

    metric_map = {
        "do_mg_l": {
            "latest_value": latest_status.get("dissolved_oxygen_avg"),
            "hourly": trend.get("dissolved_oxygen", {}).get("summary", {}).get("hourly", {}),
            "ten_minute": trend.get("dissolved_oxygen", {}).get("summary", {}).get("ten_minute", {}),
        },
        "ph": {
            "latest_value": latest_status.get("ph_avg"),
            "hourly": trend.get("ph", {}).get("summary", {}).get("hourly", {}),
            "ten_minute": trend.get("ph", {}).get("summary", {}).get("ten_minute", {}),
        },
    }

    normalized: dict[str, dict] = {}
    observed_times = [row.get("created_at") for row in latest_status.get("rows", []) if isinstance(row, dict) and row.get("created_at")]
    latest_observed_at = max(observed_times) if observed_times else None

    for metric_name, metric_data in metric_map.items():
        hourly_rows = trend.get("dissolved_oxygen", {}).get("hourly", []) if metric_name == "do_mg_l" else trend.get("ph", {}).get("hourly", [])
        ten_minute_rows = trend.get("dissolved_oxygen", {}).get("ten_minute", []) if metric_name == "do_mg_l" else trend.get("ph", {}).get("ten_minute", [])

        normalized[metric_name] = {
            "latest_value": metric_data.get("latest_value"),
            "trend_direction": _trend_direction_from_series(hourly_rows) if hourly_rows else "stable",
            "hourly": {
                "min_value": metric_data["hourly"].get("min_value"),
                "max_value": metric_data["hourly"].get("max_value"),
                "value_span": metric_data["hourly"].get("value_span"),
                "bucket_count": metric_data["hourly"].get("bucket_count"),
            },
            "ten_minute": {
                "min_value": metric_data["ten_minute"].get("min_value"),
                "max_value": metric_data["ten_minute"].get("max_value"),
                "value_span": metric_data["ten_minute"].get("value_span"),
                "bucket_count": metric_data["ten_minute"].get("bucket_count"),
            },
            "latest_observed_at": latest_observed_at,
            "raw_10m_samples": len(ten_minute_rows),
            "raw_hourly_samples": len(hourly_rows),
        }

    return normalized


def _build_open_questions(context: dict, time_window_summary: dict | None, latest_user_message: str) -> list[str]:
    questions: list[str] = []

    if context.get("time_window_suggestions"):
        if not (time_window_summary and time_window_summary.get("requested")):
            questions.append("目前時間窗不明確，請讓使用者選擇要看的區間。")

    rag_retrieval = context.get("rag_retrieval") or {}
    if rag_retrieval and not rag_retrieval.get("evidence_sufficient", True):
        questions.append("論文證據不足，必要時應縮小問題或再補充檢索。")

    message_topics = _extract_topics(latest_user_message)
    if not message_topics and not (time_window_summary and time_window_summary.get("requested")):
        questions.append("目前訊息沒有明確指定指標或時間窗，必要時先確認需求。")

    return _unique_preserve_order(questions, limit=4)


def normalize_session_summary_state(summary_state: object | None, legacy_summary_text: str | None = None) -> dict:
    parsed_summary_state = summary_state
    if isinstance(parsed_summary_state, str):
        try:
            parsed_summary_state = json.loads(parsed_summary_state)
        except Exception:
            parsed_summary_state = {}

    state = _coerce_dict(parsed_summary_state) or {}
    if not isinstance(state, dict):
        state = {}

    normalized = {
        "version": int(state.get("version") or SESSION_SUMMARY_VERSION),
        "updated_at": state.get("updated_at") or _now_iso(),
        "current_goal": _normalize_text(str(state.get("current_goal", ""))),
        "confirmed_facts": _ensure_list_of_dicts(state.get("confirmed_facts")),
        "open_questions": _unique_preserve_order(state.get("open_questions", []), limit=6),
        "recent_topics": _unique_preserve_order(state.get("recent_topics", []), limit=8),
        "time_preferences": state.get("time_preferences") if isinstance(state.get("time_preferences"), dict) else {},
        "important_metrics": state.get("important_metrics") if isinstance(state.get("important_metrics"), dict) else {},
        "assistant_state": state.get("assistant_state") if isinstance(state.get("assistant_state"), dict) else {},
    }

    if legacy_summary_text:
        normalized["legacy_summary_text"] = _normalize_text(legacy_summary_text)
    elif isinstance(state.get("legacy_summary_text"), str) and state.get("legacy_summary_text").strip():
        normalized["legacy_summary_text"] = _normalize_text(str(state.get("legacy_summary_text")))
    else:
        normalized["legacy_summary_text"] = ""

    return normalized


def build_session_summary_state(
    previous_state: object | None,
    recent_messages: list[dict],
    latest_user_message: str,
    latest_assistant_message: str,
    time_window_summary: dict | None = None,
    context: dict | None = None,
    conversation_history_count: int = 0,
    conversation_history_stats: dict | None = None,
) -> dict:
    context = context or {}
    previous = normalize_session_summary_state(previous_state)
    recent_message_texts = [
        str(message.get("message", ""))
        for message in recent_messages[-4:]
        if isinstance(message, dict)
    ]

    message_topics = _extract_topics(
        latest_user_message,
        latest_assistant_message,
        context.get("pond", {}).get("pond_name", ""),
        " ".join(previous.get("recent_topics", [])),
        " ".join(recent_message_texts),
    )

    current_goal = _derive_current_goal(previous, latest_user_message, time_window_summary, message_topics)
    confirmed_facts = _merge_confirmed_facts(previous, context, time_window_summary)
    open_questions = _build_open_questions(context, time_window_summary, latest_user_message)
    time_preferences = _build_time_preferences(previous, time_window_summary, context)
    important_metrics = _build_important_metrics(context)

    assistant_state = previous.get("assistant_state") if isinstance(previous.get("assistant_state"), dict) else {}
    has_rag_sources = bool(context.get("citations"))
    has_web_sources = bool(context.get("web_search_sources"))
    is_time_window_response = bool(time_window_summary and time_window_summary.get("requested"))

    if time_window_summary and time_window_summary.get("mode") == "comparison":
        response_type = "comparison"
    elif is_time_window_response and (has_rag_sources or has_web_sources):
        response_type = "mixed"
    elif is_time_window_response:
        response_type = "trend"
    elif has_rag_sources and has_web_sources:
        response_type = "mixed"
    elif has_rag_sources:
        response_type = "rag"
    elif has_web_sources:
        response_type = "web_search"
    else:
        response_type = "general"

    assistant_state = {
        "last_response_type": response_type,
        "last_sources_count": len(context.get("citations", [])) + len(context.get("web_search_sources", [])),
        "evidence_sufficient": bool((context.get("rag_retrieval") or {}).get("evidence_sufficient", True)),
        "needs_user_time_selection": bool(context.get("time_window_suggestions")) and not bool(
            time_window_summary and time_window_summary.get("requested")
        ),
        "use_rag": bool(context.get("rag_retrieval", {}).get("enabled", True)),
        "enable_web_search": bool(context.get("enable_web_search", False)),
        "enable_assistant_ui": bool(context.get("enable_assistant_ui", True)),
        "conversation_history_count": conversation_history_count,
        "conversation_history_stats": conversation_history_stats or {},
    }

    state = {
        "version": SESSION_SUMMARY_VERSION,
        "updated_at": _now_iso(),
        "current_goal": current_goal,
        "confirmed_facts": confirmed_facts,
        "open_questions": open_questions,
        "recent_topics": message_topics,
        "time_preferences": time_preferences,
        "important_metrics": important_metrics,
        "assistant_state": assistant_state,
    }

    legacy_summary_text = previous.get("legacy_summary_text")
    if legacy_summary_text:
        state["legacy_summary_text"] = legacy_summary_text

    return to_jsonable(state)


def render_session_summary_text(summary_state: dict, max_chars: int = DEFAULT_SESSION_SUMMARY_BUDGET) -> str:
    state = normalize_session_summary_state(summary_state)

    lines: list[str] = []
    if state.get("current_goal"):
        lines.append("會話記憶")
        lines.append(f"目標：{state['current_goal']}")

    confirmed = state.get("confirmed_facts", [])
    if confirmed:
        if not lines:
            lines.append("會話記憶")
        fact_parts: list[str] = []
        for fact in confirmed[:8]:
            label = _normalize_text(str(fact.get("label") or fact.get("key") or ""))
            value = fact.get("value")
            if isinstance(value, dict):
                value_text = ", ".join(f"{k}={v}" for k, v in value.items())
            else:
                value_text = str(value)
            if label:
                fact_parts.append(f"{label}={_clip_text(value_text, 120)}")
        if fact_parts:
            lines.append(f"已確認：{'；'.join(fact_parts)}")

    if state.get("recent_topics"):
        if not lines:
            lines.append("會話記憶")
        lines.append(f"最近主題：{'、'.join(state['recent_topics'][:8])}")

    time_preferences = state.get("time_preferences") or {}
    if isinstance(time_preferences, dict):
        last_window = time_preferences.get("last_selected_window")
        if isinstance(last_window, dict) and last_window:
            if not lines:
                lines.append("會話記憶")
            from_at = last_window.get("from_at")
            to_at = last_window.get("to_at")
            bucket = last_window.get("bucket") or last_window.get("requested_bucket")
            window_bits = [part for part in [from_at, to_at, bucket] if part]
            if window_bits:
                lines.append(f"最近時間窗：{' / '.join(str(part) for part in window_bits)}")
        preferred_granularity = time_preferences.get("preferred_granularity")
        if preferred_granularity:
            if not lines:
                lines.append("會話記憶")
            lines.append(f"偏好粒度：{preferred_granularity}")

    important_metrics = state.get("important_metrics") or {}
    if isinstance(important_metrics, dict) and important_metrics:
        if not lines:
            lines.append("會話記憶")
        metric_bits: list[str] = []
        for metric_name in ("do_mg_l", "ph"):
            metric = important_metrics.get(metric_name)
            if not isinstance(metric, dict):
                continue
            latest_value = metric.get("latest_value")
            trend_direction = metric.get("trend_direction")
            hourly = metric.get("hourly") or {}
            ten_minute = metric.get("ten_minute") or {}
            metric_bits.append(
                (
                    f"{metric_name}={latest_value}"
                    f" ({trend_direction})"
                    f" | 1h span={hourly.get('value_span')}"
                    f" | 10m span={ten_minute.get('value_span')}"
                )
            )
        if metric_bits:
            lines.append(f"指標狀態：{'；'.join(metric_bits)}")

    assistant_state = state.get("assistant_state") or {}
    if isinstance(assistant_state, dict):
        state_bits: list[str] = []
        if assistant_state.get("last_response_type"):
            state_bits.append(f"上次回應型態={assistant_state.get('last_response_type')}")
        if assistant_state.get("last_sources_count") is not None:
            state_bits.append(f"來源數={assistant_state.get('last_sources_count')}")
        if assistant_state.get("needs_user_time_selection") is not None:
            state_bits.append(f"需選時間={assistant_state.get('needs_user_time_selection')}")
        if state_bits:
            if not lines:
                lines.append("會話記憶")
            lines.append(f"助手狀態：{'；'.join(state_bits)}")

    if state.get("open_questions"):
        if not lines:
            lines.append("會話記憶")
        lines.append(f"待確認：{'；'.join(state['open_questions'][:4])}")

    if state.get("legacy_summary_text"):
        if not lines:
            lines.append("會話記憶")
        lines.append(f"舊摘要：{_clip_text(str(state['legacy_summary_text']), 220)}")

    if not lines:
        return ""

    summary = "\n".join(line.strip() for line in lines if _normalize_text(line))
    if len(summary) <= max_chars:
        return summary

    clipped_lines: list[str] = []
    remaining = max_chars
    for line in lines:
        normalized = line.strip()
        if not normalized:
            continue
        if len(normalized) + 1 <= remaining:
            clipped_lines.append(normalized)
            remaining -= len(normalized) + 1
        else:
            clipped_lines.append(_clip_text(normalized, remaining))
            break

    return "\n".join(clipped_lines).strip()


def build_session_summary_text(
    previous_summary: str | dict | None,
    recent_messages: list[dict],
    latest_user_message: str,
    latest_assistant_message: str,
    time_window_summary: dict | None = None,
    max_chars: int = DEFAULT_SESSION_SUMMARY_BUDGET,
    context: dict | None = None,
    conversation_history_count: int = 0,
    conversation_history_stats: dict | None = None,
) -> str:
    """
    相容舊版呼叫點的 wrapper。
    """

    state = build_session_summary_state(
        previous_state=previous_summary,
        recent_messages=recent_messages,
        latest_user_message=latest_user_message,
        latest_assistant_message=latest_assistant_message,
        time_window_summary=time_window_summary,
        context=context,
        conversation_history_count=conversation_history_count,
        conversation_history_stats=conversation_history_stats,
    )
    return render_session_summary_text(state, max_chars=max_chars)
