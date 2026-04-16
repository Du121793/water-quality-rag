from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from methods.config.settings import settings

try:
    TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")
except Exception:
    TAIPEI_TIMEZONE = timezone(timedelta(hours=8))

METRIC_KEYWORDS = {
    "do_mg_l": ["溶氧", "溶氧量", "do", "dissolved oxygen", "oxygen", "缺氧", "低氧"],
    "ph": ["ph", "酸鹼值", "酸鹼"],
    "temp_deep": ["深水溫", "深層水溫", "深層溫度", "底部溫度", "deep temperature"],
    "temp_shallow": ["淺水溫", "淺層水溫", "表層水溫", "表層溫度", "surface temperature"],
    "turbidity_ntu": ["濁度", "ntu", "turbidity"],
    "orp_mv": ["orp", "氧化還原", "redox", "oxidation reduction"],
}

DEFAULT_TIME_WINDOW_METRICS = ["do_mg_l", "ph", "temp_deep", "temp_shallow"]

COMPARE_KEYWORDS = ("比較", "相比", "對比", "跟前", "和前", "比前", "上一段")
DEICTIC_DAY_KEYWORDS = ("那一天", "那天", "當天", "那日")


@dataclass
class TimeWindowQuery:
    from_at: datetime
    to_at: datetime
    metrics: list[str]
    bucket: str
    requested_bucket: str | None
    matched_by: str
    original_days: float
    adjusted_days: float
    was_capped: bool
    compare_previous_window: bool = False
    previous_from_at: datetime | None = None
    previous_to_at: datetime | None = None
    comparison_matched_by: str | None = None


def _now_taipei() -> datetime:
    return datetime.now(TAIPEI_TIMEZONE)


def _start_of_day(dt: datetime) -> datetime:
    return datetime.combine(dt.date(), time.min, tzinfo=TAIPEI_TIMEZONE)


def _end_of_day(dt: datetime) -> datetime:
    return datetime.combine(dt.date(), time.max, tzinfo=TAIPEI_TIMEZONE)


def _as_taipei(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TAIPEI_TIMEZONE)
    return dt.astimezone(TAIPEI_TIMEZONE)


def _normalize_unit(unit: str) -> str:
    unit = unit.strip().lower()
    if unit in {"小時", "小时", "時", "hr", "hrs", "hour", "hours"}:
        return "hour"
    if unit in {"天", "日", "day", "days"}:
        return "day"
    if unit in {"週", "周", "星期", "week", "weeks"}:
        return "week"
    if unit in {"月", "month", "months"}:
        return "month"
    return unit


def _delta_for_amount_unit(amount: int, unit: str) -> timedelta:
    normalized = _normalize_unit(unit)
    if normalized == "hour":
        return timedelta(hours=amount)
    if normalized == "day":
        return timedelta(days=amount)
    if normalized == "week":
        return timedelta(weeks=amount)
    if normalized == "month":
        return timedelta(days=30 * amount)
    raise ValueError(f"不支援的時間單位: {unit}")


def _detect_metrics(message: str) -> list[str]:
    lowered = (message or "").lower()
    metrics: list[str] = []
    for metric, keywords in METRIC_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            metrics.append(metric)
    return metrics or DEFAULT_TIME_WINDOW_METRICS.copy()


def _choose_bucket(hours: float, metric_count: int, compare_previous_window: bool) -> tuple[str, str | None]:
    if hours <= 24:
        requested = "10m"
    elif hours <= 24 * 7:
        requested = "hour"
    else:
        requested = "day"

    if requested == "10m":
        estimated_points_per_metric = max(int(hours * 6), 1)
    elif requested == "hour":
        estimated_points_per_metric = max(int(hours), 1)
    else:
        estimated_points_per_metric = max(int(hours / 24), 1)

    estimated_total_points = estimated_points_per_metric * metric_count
    if compare_previous_window:
        estimated_total_points *= 2

    if estimated_total_points <= settings.time_window_max_points:
        return requested, requested

    if requested == "10m":
        return "hour", requested
    return "day", requested


def _normalize_range(from_at: datetime, to_at: datetime) -> tuple[datetime, datetime, float, float, bool]:
    from_at = _as_taipei(from_at)
    to_at = _as_taipei(to_at)
    if from_at >= to_at:
        raise ValueError("時間區間起點必須早於終點。")

    original_days = (to_at - from_at).total_seconds() / 86400
    was_capped = False
    if original_days > settings.time_window_max_days:
        from_at = to_at - timedelta(days=settings.time_window_max_days)
        was_capped = True

    adjusted_days = (to_at - from_at).total_seconds() / 86400
    return from_at, to_at, original_days, adjusted_days, was_capped


def _build_previous_window(from_at: datetime, to_at: datetime) -> tuple[datetime, datetime]:
    duration = to_at - from_at
    previous_to_at = from_at
    previous_from_at = from_at - duration
    return previous_from_at, previous_to_at


def _parse_absolute_date_range(message: str) -> tuple[datetime, datetime] | None:
    match = re.search(
        r"(?P<start>\d{4}[-/]\d{1,2}[-/]\d{1,2})\s*(?:到|至|~|-)\s*(?P<end>\d{4}[-/]\d{1,2}[-/]\d{1,2})",
        message,
    )
    if not match:
        return None

    start_raw = match.group("start").replace("/", "-")
    end_raw = match.group("end").replace("/", "-")
    start_dt = datetime.strptime(start_raw, "%Y-%m-%d").replace(tzinfo=TAIPEI_TIMEZONE)
    end_dt = datetime.strptime(end_raw, "%Y-%m-%d").replace(tzinfo=TAIPEI_TIMEZONE)
    return _start_of_day(start_dt), _end_of_day(end_dt)


def _extract_last_selected_window(session_summary_state: dict | None) -> tuple[datetime, datetime] | None:
    if not isinstance(session_summary_state, dict):
        return None

    time_preferences = session_summary_state.get("time_preferences")
    if not isinstance(time_preferences, dict):
        return None

    last_window = time_preferences.get("last_selected_window")
    if not isinstance(last_window, dict):
        return None

    try:
        from_at = datetime.fromisoformat(str(last_window.get("from_at")))
        to_at = datetime.fromisoformat(str(last_window.get("to_at")))
    except Exception:
        return None

    return _as_taipei(from_at), _as_taipei(to_at)


def _parse_relative_range(message: str, session_summary_state: dict | None = None) -> tuple[datetime, datetime, str] | None:
    now = _now_taipei()
    lowered = (message or "").lower()

    if any(keyword in message for keyword in DEICTIC_DAY_KEYWORDS):
        selected_window = _extract_last_selected_window(session_summary_state)
        if selected_window is not None:
            from_at, _ = selected_window
            return _start_of_day(from_at), _end_of_day(from_at), "session_selected_day"
        fallback_day = now - timedelta(days=1)
        return _start_of_day(fallback_day), _end_of_day(fallback_day), "fallback_previous_day"

    if "一天內" in message or "24小時內" in message or "24 小時內" in message:
        return now - timedelta(days=1), now, "last_24_hours"

    if "昨天晚上" in message or "昨晚" in message:
        yesterday = now - timedelta(days=1)
        return (
            datetime.combine(yesterday.date(), time(18, 0), tzinfo=TAIPEI_TIMEZONE),
            datetime.combine(now.date(), time.min, tzinfo=TAIPEI_TIMEZONE),
            "yesterday_evening",
        )

    if "昨天" in message:
        yesterday = now - timedelta(days=1)
        return _start_of_day(yesterday), _end_of_day(yesterday), "yesterday"

    if "今天" in message:
        return _start_of_day(now), now, "today"

    if "上週" in message or "上周" in message:
        weekday = now.weekday()
        start_this_week = _start_of_day(now - timedelta(days=weekday))
        start_last_week = start_this_week - timedelta(days=7)
        end_last_week = start_this_week - timedelta(microseconds=1)
        return start_last_week, end_last_week, "last_week"

    if "上個月" in message or "上个月" in message:
        first_day_this_month = datetime(now.year, now.month, 1, tzinfo=TAIPEI_TIMEZONE)
        last_day_last_month = first_day_this_month - timedelta(days=1)
        first_day_last_month = datetime(last_day_last_month.year, last_day_last_month.month, 1, tzinfo=TAIPEI_TIMEZONE)
        return _start_of_day(first_day_last_month), _end_of_day(last_day_last_month), "last_month"

    if "最近30天" in lowered or "最近 30 天" in message:
        return now - timedelta(days=30), now, "last_30_days"

    if "最近7天" in lowered or "最近 7 天" in message:
        return now - timedelta(days=7), now, "last_7_days"

    match = re.search(r"(最近|過去|前)\s*(\d+)\s*(小時|小时|時|天|日|週|周|星期|月)", message)
    if match:
        amount = int(match.group(2))
        unit = match.group(3)
        return now - _delta_for_amount_unit(amount, unit), now, f"relative_{_normalize_unit(unit)}"

    return None


def _parse_comparison_query(message: str) -> tuple[tuple[datetime, datetime], tuple[datetime, datetime], str] | None:
    if not any(keyword in message for keyword in COMPARE_KEYWORDS):
        return None

    match = re.search(
        r"(最近|過去|前)\s*(\d+)\s*(小時|小时|時|天|日|週|周|星期|月)"
        r".{0,24}?"
        r"(前|上一個|上一个)\s*(\d+)\s*(小時|小时|時|天|日|週|周|星期|月)",
        message,
    )
    if not match:
        return None

    current_amount = int(match.group(2))
    current_unit = match.group(3)
    previous_amount = int(match.group(5))
    previous_unit = match.group(6)

    now = _now_taipei()
    current_delta = _delta_for_amount_unit(current_amount, current_unit)
    previous_delta = _delta_for_amount_unit(previous_amount, previous_unit)

    current_to_at = now
    current_from_at = now - current_delta
    previous_to_at = current_from_at
    previous_from_at = previous_to_at - previous_delta

    return (current_from_at, current_to_at), (previous_from_at, previous_to_at), "relative_comparison"


def parse_time_window_query(
    message: str,
    explicit_from: datetime | None = None,
    explicit_to: datetime | None = None,
    compare_previous_window: bool = False,
    session_summary_state: dict | None = None,
) -> TimeWindowQuery | None:
    compare_mode = compare_previous_window
    matched_by = "unknown"
    comparison_matched_by = None
    previous_from_at: datetime | None = None
    previous_to_at: datetime | None = None

    if explicit_from is not None and explicit_to is not None:
        from_at, to_at = explicit_from, explicit_to
        matched_by = "explicit_time_window"
    else:
        comparison = _parse_comparison_query(message)
        if comparison is not None:
            (from_at, to_at), (previous_from_at, previous_to_at), comparison_matched_by = comparison
            compare_mode = True
            matched_by = comparison_matched_by or "relative_comparison"
        else:
            parsed_range = _parse_absolute_date_range(message)
            if parsed_range is not None:
                from_at, to_at = parsed_range
                matched_by = "absolute_date_range"
            else:
                relative = _parse_relative_range(message, session_summary_state=session_summary_state)
                if relative is None:
                    return None
                from_at, to_at, matched_by = relative

    from_at, to_at, original_days, adjusted_days, was_capped = _normalize_range(from_at, to_at)

    if compare_mode:
        if previous_from_at is None or previous_to_at is None:
            previous_from_at, previous_to_at = _build_previous_window(from_at, to_at)
        previous_from_at, previous_to_at, _, _, _ = _normalize_range(previous_from_at, previous_to_at)

    hours = max((to_at - from_at).total_seconds() / 3600, 1)
    metrics = _detect_metrics(message)
    bucket, requested_bucket = _choose_bucket(hours, len(metrics), compare_mode)

    return TimeWindowQuery(
        from_at=from_at,
        to_at=to_at,
        metrics=metrics,
        bucket=bucket,
        requested_bucket=requested_bucket,
        matched_by=matched_by,
        original_days=round(original_days, 2),
        adjusted_days=round(adjusted_days, 2),
        was_capped=was_capped,
        compare_previous_window=compare_mode,
        previous_from_at=previous_from_at,
        previous_to_at=previous_to_at,
        comparison_matched_by=comparison_matched_by,
    )
