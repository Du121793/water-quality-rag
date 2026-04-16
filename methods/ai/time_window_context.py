from __future__ import annotations

from datetime import datetime

from SQL_Controller.sensor_data import (
    get_multi_metric_range_summary_by_pond,
    get_multi_metric_trend_range_by_pond,
)
from methods.ai.time_window_query import (
    TimeWindowQuery,
    build_time_window_query,
    parse_time_window_query,
)
from methods.base.serializer import to_jsonable


def build_metric_comparison(current_summary: dict, previous_summary: dict) -> dict:
    current_avg = current_summary.get("avg_value")
    previous_avg = previous_summary.get("avg_value")
    delta = None
    percent_change = None

    if current_avg is not None and previous_avg is not None:
        delta = round(float(current_avg) - float(previous_avg), 2)
        if float(previous_avg) != 0:
            percent_change = round((delta / float(previous_avg)) * 100, 2)

    return {
        "current": current_summary,
        "previous": previous_summary,
        "delta_avg": delta,
        "percent_change_avg": percent_change,
    }


async def build_time_window_context_from_query(pond_id: int, query: TimeWindowQuery) -> dict:
    current_summaries = await get_multi_metric_range_summary_by_pond(
        pond_id=pond_id,
        metrics=query.metrics,
        from_at=query.from_at,
        to_at=query.to_at,
    )
    current_series = await get_multi_metric_trend_range_by_pond(
        pond_id=pond_id,
        metrics=query.metrics,
        from_at=query.from_at,
        to_at=query.to_at,
        bucket=query.bucket,
    )

    payload: dict = {
        "mode": "single",
        "requested": True,
        "matched_by": query.matched_by,
        "from_at": query.from_at,
        "to_at": query.to_at,
        "metrics": query.metrics,
        "bucket": query.bucket,
        "requested_bucket": query.requested_bucket,
        "was_capped": query.was_capped,
        "original_days": query.original_days,
        "adjusted_days": query.adjusted_days,
        "summary": current_summaries,
        "series": current_series,
    }

    if query.compare_previous_window and query.previous_from_at and query.previous_to_at:
        previous_summaries = await get_multi_metric_range_summary_by_pond(
            pond_id=pond_id,
            metrics=query.metrics,
            from_at=query.previous_from_at,
            to_at=query.previous_to_at,
        )
        previous_series = await get_multi_metric_trend_range_by_pond(
            pond_id=pond_id,
            metrics=query.metrics,
            from_at=query.previous_from_at,
            to_at=query.previous_to_at,
            bucket=query.bucket,
        )
        comparison: dict[str, dict] = {}
        for metric in query.metrics:
            comparison[metric] = build_metric_comparison(
                current_summaries.get(metric, {}),
                previous_summaries.get(metric, {}),
            )

        payload = {
            "mode": "comparison",
            "requested": True,
            "matched_by": query.matched_by,
            "comparison_matched_by": query.comparison_matched_by,
            "from_at": query.from_at,
            "to_at": query.to_at,
            "previous_from_at": query.previous_from_at,
            "previous_to_at": query.previous_to_at,
            "metrics": query.metrics,
            "bucket": query.bucket,
            "requested_bucket": query.requested_bucket,
            "was_capped": query.was_capped,
            "original_days": query.original_days,
            "adjusted_days": query.adjusted_days,
            "current": {
                "summary": current_summaries,
                "series": current_series,
            },
            "previous": {
                "summary": previous_summaries,
                "series": previous_series,
            },
            "comparison": comparison,
        }

    return to_jsonable(payload)


async def build_explicit_time_window_context(
    pond_id: int,
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
) -> dict:
    query = build_time_window_query(
        from_at=from_at,
        to_at=to_at,
        metrics=metrics,
        bucket=bucket,
        compare_previous_window=compare_previous_window,
        previous_from_at=previous_from_at,
        previous_to_at=previous_to_at,
        matched_by=matched_by,
        comparison_matched_by=comparison_matched_by,
    )
    return await build_time_window_context_from_query(pond_id, query)


async def build_time_window_context(
    pond_id: int,
    message: str,
    explicit_from: datetime | None = None,
    explicit_to: datetime | None = None,
    compare_previous_window: bool = False,
    session_summary_state: dict | None = None,
) -> dict | None:
    parsed = parse_time_window_query(
        message=message,
        explicit_from=explicit_from,
        explicit_to=explicit_to,
        compare_previous_window=compare_previous_window,
        session_summary_state=session_summary_state,
    )
    if parsed is None:
        return None
    return await build_time_window_context_from_query(pond_id, parsed)
