from methods.base.serializer import row_to_jsonable, to_jsonable
from methods.infra.database import fetchrow_main


async def get_user_pond_by_id(user_id: int, pond_id: int) -> dict | None:
    row = await fetchrow_main(
        """
        SELECT
            id,
            user_id,
            pond_name,
            pond_length,
            pond_width,
            pond_height,
            total_fish_count,
            total_fish_weight,
            feeding_growth_rate,
            created_at,
            updated_at
        FROM ponds
        WHERE id = $1 AND user_id = $2
        """,
        pond_id,
        user_id,
    )

    return row_to_jsonable(row) if row else None


