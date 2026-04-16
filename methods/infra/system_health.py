from SQL_Controller.system_health import check_ai_db_connection, check_main_db_connection
from methods.infra import redis_client as redis_module


async def get_system_health_snapshot() -> dict:
    main_db_ok = await check_main_db_connection()
    ai_db_ok = await check_ai_db_connection()

    redis_ok = False
    if redis_module.redis_client is not None:
        try:
            redis_ok = await redis_module.redis_client.ping()
        except Exception:
            redis_ok = False

    return {
        "main_db": main_db_ok,
        "ai_db": ai_db_ok,
        "redis": redis_ok,
    }
