from __future__ import annotations

import asyncpg

from methods.base.logger import info, warn
from methods.config.settings import settings

main_db_pool: asyncpg.Pool | None = None
ai_db_pool: asyncpg.Pool | None = None

def _build_pool_kwargs(
    *,
    dsn: str | None = None,
    host: str | None = None,
    port: int = 5432,
    database: str | None = None,
    user: str | None = None,
    password: str | None = None,
    ssl_enabled: bool = False,
) -> dict:

    import ssl

    ssl_context = False
    if ssl_enabled:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    if dsn:
        return {
            "dsn": dsn,
            "ssl": ssl_context,
            "min_size": 1,
            "max_size": 10,
        }

    if not host or not database or not user:
        return {}

    return {
        "host": host,
        "port": port,
        "database": database,
        "user": user,
        "password": password,
        "ssl": ssl_context,
        "min_size": 1,
        "max_size": 10,
    }


async def initialize_database_pools() -> None:
    """初始化主資料庫與 AI 資料庫連線池。"""

    global main_db_pool, ai_db_pool

    main_kwargs = _build_pool_kwargs(
        dsn=settings.main_db_dsn,
        host=settings.database_url,
        port=settings.database_port_ro,
        database=settings.database_name,
        user=settings.database_user,
        password=settings.database_password,
        ssl_enabled=settings.database_ssl,
    )
    if main_kwargs and main_db_pool is None:
        main_db_pool = await asyncpg.create_pool(**main_kwargs)
        info("主資料庫", "連線池初始化完成")
    else:
        warn("主資料庫", "主資料庫連線設定缺失，或連線池已存在")

    ai_kwargs = _build_pool_kwargs(
        dsn=settings.ai_db_dsn,
        host=settings.ai_database_url,
        port=settings.ai_database_port,
        database=settings.ai_database_name,
        user=settings.ai_database_user,
        password=settings.ai_database_password,
        ssl_enabled=settings.ai_database_ssl,
    )
    if ai_kwargs and ai_db_pool is None:
        ai_db_pool = await asyncpg.create_pool(**ai_kwargs)
        info("AI資料庫", "連線池初始化完成")
    else:
        warn("AI資料庫", "AI 資料庫連線設定缺失，RAG 功能可能無法使用")


async def close_database_pools() -> None:
    global main_db_pool, ai_db_pool

    if main_db_pool is not None:
        await main_db_pool.close()
        main_db_pool = None

    if ai_db_pool is not None:
        await ai_db_pool.close()
        ai_db_pool = None


def require_main_pool() -> asyncpg.Pool:
    if main_db_pool is None:
        raise RuntimeError("主資料庫連線池尚未初始化。")
    return main_db_pool


def require_ai_pool() -> asyncpg.Pool:
    if ai_db_pool is None:
        raise RuntimeError("AI 資料庫連線池尚未初始化。")
    return ai_db_pool


async def fetch_main(query: str, *params):
    async with require_main_pool().acquire() as connection:
        return await connection.fetch(query, *params)


async def fetchrow_main(query: str, *params):
    async with require_main_pool().acquire() as connection:
        return await connection.fetchrow(query, *params)


async def fetchval_main(query: str, *params):
    async with require_main_pool().acquire() as connection:
        return await connection.fetchval(query, *params)


async def execute_ai(query: str, *params):
    async with require_ai_pool().acquire() as connection:
        return await connection.execute(query, *params)


async def fetch_ai(query: str, *params):
    async with require_ai_pool().acquire() as connection:
        return await connection.fetch(query, *params)


async def fetchrow_ai(query: str, *params):
    async with require_ai_pool().acquire() as connection:
        return await connection.fetchrow(query, *params)


async def fetchval_ai(query: str, *params):
    async with require_ai_pool().acquire() as connection:
        return await connection.fetchval(query, *params)
