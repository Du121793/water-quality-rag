from methods.infra.database import fetchval_ai, fetchval_main


async def check_main_db_connection() -> bool:
    try:
        return await fetchval_main("SELECT 1;") == 1
    except Exception:
        return False


async def check_ai_db_connection() -> bool:
    try:
        return await fetchval_ai("SELECT 1;") == 1
    except Exception:
        return False
