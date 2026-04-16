from methods.base.serializer import row_to_jsonable, to_jsonable
from methods.infra.database import fetch_main


async def get_recent_daily_logs_by_pond_id(pond_id: int, days: int = 7) -> list[dict]:
    rows = await fetch_main(
        """
        SELECT
            id,
            pond_id,
            feeding_amount,
            death_count,
            notes,
            log_date,
            created_at,
            updated_at
        FROM pond_daily_logs
        WHERE pond_id = $1
          AND log_date >= CURRENT_DATE - $2::int
        ORDER BY log_date DESC
        """,
        pond_id,
        days,
    )

    return [row_to_jsonable(row) for row in rows]


