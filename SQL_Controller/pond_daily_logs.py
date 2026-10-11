from methods.base.serializer import row_to_jsonable, to_jsonable
from methods.infra.database import fetch_main


async def get_recent_daily_logs_by_pond_id(pond_id: int, days: int = 7) -> list[dict]:
    # 使用 LEFT JOIN 與 JSONB_AGG 抓取主表及其關聯的 items (添加物/用藥/改良劑)
    rows = await fetch_main(
        """
        SELECT
            pdl.id,
            pdl.pond_id,
            pdl.feeding_amount,
            pdl.death_count,
            pdl.notes,
            pdl.log_date,
            pdl.created_at,
            pdl.updated_at,
            COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'category', dli.category,
                        'name', dli.item_name_snapshot,
                        'dosage', dli.dosage,
                        'unit', dli.unit
                    )
                ) FILTER (WHERE dli.id IS NOT NULL),
                '[]'::jsonb
            ) as items
        FROM pond_daily_logs pdl
        LEFT JOIN daily_log_items dli ON pdl.id = dli.daily_log_id
        WHERE pdl.pond_id = $1
          AND pdl.log_date >= CURRENT_DATE - $2::int
        GROUP BY pdl.id
        ORDER BY pdl.log_date DESC
        """,
        pond_id,
        days,
    )

    return [row_to_jsonable(row) for row in rows]
