from datetime import datetime

from methods.base.serializer import row_to_jsonable, to_jsonable
from methods.infra.database import fetch_main, fetchrow_main

ALLOWED_METRICS = {
    "do_mg_l": "sd.do_mg_l",
    "ph": "sd.ph",
    "temp_deep": "sd.temp_deep",
    "temp_shallow": "sd.temp_shallow",
    "turbidity_ntu": "sd.turbidity_ntu",
    "orp_mv": "sd.orp_mv",
}

BUCKET_SQL = {
    "hour": "date_trunc('hour', sd.created_at)",
    "day": "date_trunc('day', sd.created_at)",
    "10m": "to_timestamp(floor(extract(epoch from sd.created_at) / 600) * 600)",
}


async def get_latest_sensor_status_by_pond(pond_id: int) -> list[dict]:
    rows = await fetch_main(
        """
        SELECT DISTINCT ON (s.id)
            s.id AS sensor_id,
            s.sensor_name,
            sd.created_at,
            sd.do_mg_l,
            sd.ph,
            sd.temp_deep,
            sd.temp_shallow,
            sd.turbidity_ntu,
            sd.orp_mv
        FROM sensors s
        LEFT JOIN sensor_data sd ON sd.sensor_id = s.id
        WHERE s.pond_id = $1
        ORDER BY s.id, sd.created_at DESC
        """,
        pond_id,
    )
    return [row_to_jsonable(row) for row in rows]


def _validate_metric_and_bucket(metric: str, bucket: str) -> tuple[str, str]:
    if metric not in ALLOWED_METRICS:
        raise ValueError(f"銝?渡??葫??: {metric}")
    if bucket not in BUCKET_SQL:
        raise ValueError(f"銝?渡???獢園??? {bucket}")

    return ALLOWED_METRICS[metric], BUCKET_SQL[bucket]


async def get_metric_trend_by_pond(pond_id: int, metric: str, hours: int = 24, bucket: str = "hour") -> list[dict]:
    metric_sql, bucket_sql = _validate_metric_and_bucket(metric, bucket)

    rows = await fetch_main(
        f"""
        SELECT
            {bucket_sql} AS bucket_at,
            ROUND(AVG({metric_sql})::numeric, 2) AS avg_value,
            ROUND(MIN({metric_sql})::numeric, 2) AS min_value,
            ROUND(MAX({metric_sql})::numeric, 2) AS max_value
        FROM sensor_data sd
        JOIN sensors s ON s.id = sd.sensor_id
        WHERE s.pond_id = $1
          AND sd.created_at >= NOW() - make_interval(hours => $2::int)
          AND {metric_sql} IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        pond_id,
        hours,
    )

    return [row_to_jsonable(row) for row in rows]


async def get_metric_trend_range_by_pond(
    pond_id: int,
    metric: str,
    from_at: datetime,
    to_at: datetime,
    bucket: str = "hour",
) -> list[dict]:
    metric_sql, bucket_sql = _validate_metric_and_bucket(metric, bucket)

    rows = await fetch_main(
        f"""
        SELECT
            {bucket_sql} AS bucket_at,
            ROUND(AVG({metric_sql})::numeric, 2) AS avg_value,
            ROUND(MIN({metric_sql})::numeric, 2) AS min_value,
            ROUND(MAX({metric_sql})::numeric, 2) AS max_value
        FROM sensor_data sd
        JOIN sensors s ON s.id = sd.sensor_id
        WHERE s.pond_id = $1
          AND sd.created_at >= $2
          AND sd.created_at <= $3
          AND {metric_sql} IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        pond_id,
        from_at,
        to_at,
    )

    return [row_to_jsonable(row) for row in rows]


async def get_multi_metric_trend_range_by_pond(
    pond_id: int,
    metrics: list[str],
    from_at: datetime,
    to_at: datetime,
    bucket: str = "hour",
) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for metric in metrics:
        result[metric] = await get_metric_trend_range_by_pond(
            pond_id=pond_id,
            metric=metric,
            from_at=from_at,
            to_at=to_at,
            bucket=bucket,
        )
    return result


async def get_metric_range_summary_by_pond(
    pond_id: int,
    metric: str,
    from_at: datetime,
    to_at: datetime,
) -> dict:
    metric_sql, _ = _validate_metric_and_bucket(metric, "hour")

    row = await fetchrow_main(
        f"""
        SELECT
            COUNT({metric_sql}) AS value_count,
            ROUND(AVG({metric_sql})::numeric, 2) AS avg_value,
            ROUND(MIN({metric_sql})::numeric, 2) AS min_value,
            ROUND(MAX({metric_sql})::numeric, 2) AS max_value
        FROM sensor_data sd
        JOIN sensors s ON s.id = sd.sensor_id
        WHERE s.pond_id = $1
          AND sd.created_at >= $2
          AND sd.created_at <= $3
          AND {metric_sql} IS NOT NULL
        """,
        pond_id,
        from_at,
        to_at,
    )

    return row_to_jsonable(row) if row else {}


async def get_multi_metric_range_summary_by_pond(
    pond_id: int,
    metrics: list[str],
    from_at: datetime,
    to_at: datetime,
) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for metric in metrics:
        result[metric] = await get_metric_range_summary_by_pond(
            pond_id=pond_id,
            metric=metric,
            from_at=from_at,
            to_at=to_at,
        )
    return result


