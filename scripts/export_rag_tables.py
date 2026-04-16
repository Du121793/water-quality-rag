from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from methods.config.settings import settings


EXPORT_TABLES = [
    "paper_sources",
    "paper_chunks",
    "paper_embeddings",
]


def _quote_sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _serialize_array(value: list[Any] | tuple[Any, ...], udt_name: str) -> str:
    inner_type = "text"
    if udt_name == "_int4":
        inner_type = "integer"
    elif udt_name == "_int8":
        inner_type = "bigint"
    elif udt_name == "_float8":
        inner_type = "double precision"

    serialized_items = ",".join(_serialize_value(item, "scalar") for item in value)
    return f"ARRAY[{serialized_items}]::{inner_type}[]"


def _serialize_value(value: Any, udt_name: str) -> str:
    if value is None:
        return "NULL"

    if udt_name.startswith("_") and isinstance(value, (list, tuple)):
        return _serialize_array(value, udt_name)

    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"

    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return str(value)

    if isinstance(value, datetime):
        return f"TIMESTAMPTZ {_quote_sql_string(value.isoformat())}"

    if isinstance(value, date):
        return f"DATE {_quote_sql_string(value.isoformat())}"

    if udt_name == "jsonb":
        if isinstance(value, str):
            json_text = value
        else:
            json_text = json.dumps(value, ensure_ascii=False)
        return f"{_quote_sql_string(json_text)}::jsonb"

    if udt_name == "vector":
        return f"{_quote_sql_string(str(value))}::vector"

    if isinstance(value, str):
        return _quote_sql_string(value)

    if isinstance(value, (list, tuple, dict)):
        return _quote_sql_string(json.dumps(value, ensure_ascii=False))

    return _quote_sql_string(str(value))


async def _get_table_columns(conn: asyncpg.Connection, table_name: str) -> list[dict[str, str]]:
    rows = await conn.fetch(
        """
        SELECT column_name, udt_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = $1
        ORDER BY ordinal_position
        """,
        table_name,
    )
    return [{"column_name": row["column_name"], "udt_name": row["udt_name"]} for row in rows]


async def _write_table_inserts(
    conn: asyncpg.Connection,
    output_lines: list[str],
    table_name: str,
) -> None:
    columns = await _get_table_columns(conn, table_name)
    column_names = [column["column_name"] for column in columns]
    rows = await conn.fetch(f"SELECT * FROM {table_name} ORDER BY id")

    output_lines.append(f"-- {table_name}")
    if not rows:
        output_lines.append(f"-- {table_name} 無資料")
        output_lines.append("")
        return

    joined_columns = ", ".join(column_names)
    for row in rows:
        serialized_values = [
            _serialize_value(row[column["column_name"]], column["udt_name"])
            for column in columns
        ]
        joined_values = ", ".join(serialized_values)
        output_lines.append(f"INSERT INTO {table_name} ({joined_columns}) VALUES ({joined_values});")

    sequence_name = await conn.fetchval("SELECT pg_get_serial_sequence($1, 'id')", table_name)
    if sequence_name:
        output_lines.append(
            f"SELECT setval({_quote_sql_string(sequence_name)}, COALESCE((SELECT MAX(id) FROM {table_name}), 1), true);"
        )

    output_lines.append("")


async def export_rag_tables(output_path: Path) -> None:
    conn = await asyncpg.connect(
        host=settings.ai_database_url,
        port=settings.ai_database_port,
        user=settings.ai_database_user,
        password=settings.ai_database_password,
        database=settings.ai_database_name,
    )

    try:
        output_lines = [
            "-- rag-ai-helper RAG 匯出檔",
            "-- 可直接在目標 AI DB 執行：psql -h <host> -p <port> -U <user> -d <db> -f rag_papers_dump.sql",
            "BEGIN;",
            "TRUNCATE TABLE paper_embeddings, paper_chunks, paper_sources RESTART IDENTITY CASCADE;",
            "",
        ]

        for table_name in EXPORT_TABLES:
            await _write_table_inserts(conn, output_lines, table_name)

        output_lines.append("COMMIT;")
        output_path.write_text("\n".join(output_lines), encoding="utf-8")
    finally:
        await conn.close()


if __name__ == "__main__":
    target_path = Path("rag_papers_dump.sql").resolve()
    asyncio.run(export_rag_tables(target_path))
    print(f"匯出完成: {target_path}")
