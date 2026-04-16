from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from SQL_Controller.sensor_data import ALLOWED_METRICS
from methods.config.settings import settings

try:
    TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")
except Exception:
    TAIPEI_TIMEZONE = timezone(timedelta(hours=8))

METRIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "do_mg_l": ("溶氧", "溶解氧", "do", "dissolved oxygen", "oxygen"),
    "ph": ("ph", "酸鹼值", "酸碱值"),
    "temp_deep": ("深水溫", "深層水溫", "深層溫度", "deep temperature"),
    "temp_shallow": ("淺水溫", "表層水溫", "表層溫度", "surface temperature"),
    "turbidity_ntu": ("濁度", "ntu", "turbidity"),
    "orp_mv": ("orp", "氧化還原", "redox"),
}

DEFAULT_TIME_WINDOW_METRICS = ["do_mg_l", "ph", "temp_deep", "temp_shallow"]
COMPARE_KEYWORDS = ("比較", "比對", "相比", "前", "上一")
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


def now_taipei() -> datetime:
    return datetime.now(TAIPEI_TIMEZONE)


def as_taipei(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TAIPEI_TIMEZONE)
    return dt.astimezone(TAIPEI_TIMEZONE)


def start_of_day(dt: datetime) -> datetime:
    dt = as_taipei(dt)
    return datetime.combine(dt.date(), time.min, tzinfo=TAIPEI_TIMEZONE)


def end_of_day(dt: datetime) -> datetime:
    dt = as_taipei(dt)
    return datetime.combine(dt.date(), time.max, tzinfo=TAIPEI_TIMEZONE)


def normalize_unit(unit: str) -> str:
    normalized = unit.strip().lower()
    if normalized in {"小時", "小时", "hr", "hrs", "hour", "hours"}:
        return "hour"
    if normalized in {"天", "day", "days"}:
        return "day"
    if normalized in {"週", "周", "week", "weeks"}:
        return "week"
    if normalized in {"月", "month", "months"}:
        return "month"
    raise ValueError(f"不支援的時間單位: {unit}")


def delta_for_amount_unit(amount: int, unit: str) -> timedelta:
    normalized = normalize_unit(unit)
    if normalized == "hour":
        return timedelta(hours=amount)
    if normalized == "day":
        return timedelta(days=amount)
    if normalized == "week":
        return timedelta(weeks=amount)
    if normalized == "month":
        return timedelta(days=30 * amount)
    raise ValueError(f"不支援的時間單位: {unit}")


def detect_metrics(message: str) -> list[str]:
    lowered = (message or "").lower()
    metrics: list[str] = []
    for metric, keywords in METRIC_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            metrics.append(metric)
    return metrics or DEFAULT_TIME_WINDOW_METRICS.copy()


def choose_bucket(hours: float, metric_count: int, compare_previous_window: bool) -> tuple[str, str | None]:
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

    estimated_total_points = estimated_points_per_metric * max(metric_count, 1)
    if compare_previous_window:
        estimated_total_points *= 2

    if estimated_total_points <= settings.time_window_max_points:
        return requested, requested
    if requested == "10m":
        return "hour", requested
    return "day", requested


def normalize_range(from_at: datetime, to_at: datetime) -> tuple[datetime, datetime, float, float, bool]:
    normalized_from = as_taipei(from_at)
    normalized_to = as_taipei(to_at)
    if normalized_from >= normalized_to:
        raise ValueError("時間區間起點必須早於終點。")

    original_days = (normalized_to - normalized_from).total_seconds() / 86400
    was_capped = False
    if original_days > settings.time_window_max_days:
        normalized_from = normalized_to - timedelta(days=settings.time_window_max_days)
        was_capped = True

    adjusted_days = (normalized_to - normalized_from).total_seconds() / 86400
    return normalized_from, normalized_to, original_days, adjusted_days, was_capped


def build_previous_window(from_at: datetime, to_at: datetime) -> tuple[datetime, datetime]:
    duration = to_at - from_at
    previous_to_at = from_at
    previous_from_at = from_at - duration
    return previous_from_at, previous_to_at


def parse_absolute_date_range(message: str) -> tuple[datetime, datetime] | None:
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
    return start_of_day(start_dt), end_of_day(end_dt)


def extract_last_selected_window(session_summary_state: dict | None) -> tuple[datetime, datetime] | None:
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

    return as_taipei(from_at), as_taipei(to_at)


def parse_relative_range(message: str, session_summary_state: dict | None = None) -> tuple[datetime, datetime, str] | None:
    now = now_taipei()

    if any(keyword in message for keyword in DEICTIC_DAY_KEYWORDS):
        selected_window = extract_last_selected_window(session_summary_state)
        if selected_window is not None:
            selected_from_at, _ = selected_window
            return start_of_day(selected_from_at), end_of_day(selected_from_at), "session_selected_day"
        fallback_day = now - timedelta(days=1)
        return start_of_day(fallback_day), end_of_day(fallback_day), "fallback_previous_day"

    if "一天內" in message or "24小時內" in message or "最近 24 小時" in message or "最近24小時" in message:
        return now - timedelta(days=1), now, "last_24_hours"

    if "昨天晚上" in message:
        yesterday = now - timedelta(days=1)
        return (
            datetime.combine(yesterday.date(), time(18, 0), tzinfo=TAIPEI_TIMEZONE),
            datetime.combine(yesterday.date(), time.max, tzinfo=TAIPEI_TIMEZONE),
            "yesterday_evening",
        )

    if "昨天" in message:
        yesterday = now - timedelta(days=1)
        return start_of_day(yesterday), end_of_day(yesterday), "yesterday"

    if "今天" in message:
        return start_of_day(now), now, "today"

    if "上週" in message or "上周" in message:
        weekday = now.weekday()
        start_this_week = start_of_day(now - timedelta(days=weekday))
        start_last_week = start_this_week - timedelta(days=7)
        end_last_week = start_this_week - timedelta(microseconds=1)
        return start_last_week, end_last_week, "last_week"

    if "上個月" in message or "上个月" in message:
        first_day_this_month = datetime(now.year, now.month, 1, tzinfo=TAIPEI_TIMEZONE)
        last_day_last_month = first_day_this_month - timedelta(days=1)
        first_day_last_month = datetime(last_day_last_month.year, last_day_last_month.month, 1, tzinfo=TAIPEI_TIMEZONE)
        return start_of_day(first_day_last_month), end_of_day(last_day_last_month), "last_month"

    if "最近 30 天" in message or "最近30天" in message:
        return now - timedelta(days=30), now, "last_30_days"

    if "最近 7 天" in message or "最近7天" in message:
        return now - timedelta(days=7), now, "last_7_days"

    match = re.search(r"(最近|前)\s*(\d+)\s*(小時|小时|hr|hrs|hour|hours|天|day|days|週|周|week|weeks|月|month|months)", message)
    if match:
        amount = int(match.group(2))
        unit = match.group(3)
        return now - delta_for_amount_unit(amount, unit), now, f"relative_{normalize_unit(unit)}"

    return None


def parse_comparison_query(message: str) -> tuple[tuple[datetime, datetime], tuple[datetime, datetime], str] | None:
    if not any(keyword in message for keyword in COMPARE_KEYWORDS):
        return None

    match = re.search(
        r"最近\s*(\d+)\s*(小時|小时|hr|hrs|hour|hours|天|day|days|週|周|week|weeks|月|month|months)"
        r".{0,16}?"
        r"(前|上一|上)\s*(\d+)\s*(小時|小时|hr|hrs|hour|hours|天|day|days|週|周|week|weeks|月|month|months)",
        message,
    )
    if not match:
        return None

    current_amount = int(match.group(1))
    current_unit = match.group(2)
    previous_amount = int(match.group(4))
    previous_unit = match.group(5)

    now = now_taipei()
    current_delta = delta_for_amount_unit(current_amount, current_unit)
    previous_delta = delta_for_amount_unit(previous_amount, previous_unit)

    current_to_at = now
    current_from_at = now - current_delta
    previous_to_at = current_from_at
    previous_from_at = previous_to_at - previous_delta
    return (current_from_at, current_to_at), (previous_from_at, previous_to_at), "relative_comparison"


def build_time_window_query(
    *,
    from_at: datetime,
    to_at: datetime,
    metrics: list[str] | None = None,
    bucket: str | None = None,
    compare_previous_window: bool = False,
    previous_from_at: datetime | None = None,
    previous_to_at: datetime | None = None,
    matched_by: str = "explicit_time_window",
    comparison_matched_by: str | None = None,
) -> TimeWindowQuery:
    selected_metrics = [metric for metric in (metrics or DEFAULT_TIME_WINDOW_METRICS) if metric in ALLOWED_METRICS]
    if not selected_metrics:
        selected_metrics = DEFAULT_TIME_WINDOW_METRICS.copy()

    normalized_from, normalized_to, original_days, adjusted_days, was_capped = normalize_range(from_at, to_at)
    compare_mode = compare_previous_window

    if compare_mode:
        if previous_from_at is None or previous_to_at is None:
            previous_from_at, previous_to_at = build_previous_window(normalized_from, normalized_to)
        previous_from_at, previous_to_at, _, _, _ = normalize_range(previous_from_at, previous_to_at)

    hours = max((normalized_to - normalized_from).total_seconds() / 3600, 1)
    auto_bucket, requested_bucket = choose_bucket(hours, len(selected_metrics), compare_mode)

    final_bucket = bucket or auto_bucket
    if final_bucket not in {"10m", "hour", "day"}:
        final_bucket = auto_bucket
    if final_bucket == "10m" and auto_bucket in {"hour", "day"}:
        final_bucket = auto_bucket
    if final_bucket == "hour" and auto_bucket == "day":
        final_bucket = "day"

    return TimeWindowQuery(
        from_at=normalized_from,
        to_at=normalized_to,
        metrics=selected_metrics,
        bucket=final_bucket,
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


def parse_time_window_query(
    message: str,
    explicit_from: datetime | None = None,
    explicit_to: datetime | None = None,
    compare_previous_window: bool = False,
    session_summary_state: dict | None = None,
) -> TimeWindowQuery | None:
    if explicit_from is not None and explicit_to is not None:
        return build_time_window_query(
            from_at=explicit_from,
            to_at=explicit_to,
            metrics=detect_metrics(message),
            compare_previous_window=compare_previous_window,
            matched_by="explicit_time_window",
        )

    comparison = parse_comparison_query(message)
    if comparison is not None:
        (from_at, to_at), (previous_from_at, previous_to_at), comparison_matched_by = comparison
        return build_time_window_query(
            from_at=from_at,
            to_at=to_at,
            metrics=detect_metrics(message),
            compare_previous_window=True,
            previous_from_at=previous_from_at,
            previous_to_at=previous_to_at,
            matched_by=comparison_matched_by,
            comparison_matched_by=comparison_matched_by,
        )

    parsed_range = parse_absolute_date_range(message)
    if parsed_range is not None:
        from_at, to_at = parsed_range
        return build_time_window_query(
            from_at=from_at,
            to_at=to_at,
            metrics=detect_metrics(message),
            matched_by="absolute_date_range",
        )

    relative = parse_relative_range(message, session_summary_state=session_summary_state)
    if relative is None:
        return None

    from_at, to_at, matched_by = relative
    return build_time_window_query(
        from_at=from_at,
        to_at=to_at,
        metrics=detect_metrics(message),
        compare_previous_window=compare_previous_window,
        matched_by=matched_by,
    )
