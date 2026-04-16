from __future__ import annotations

import json
from typing import Any

from methods.base.serializer import row_to_jsonable, to_jsonable
from methods.infra.database import execute_ai, fetch_ai, fetchrow_ai, fetchval_ai

_CHAT_SESSIONS_HAS_SUMMARY_JSON: bool | None = None


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


async def _supports_summary_json() -> bool:
    """
    ?澆捆??鞈?摨恬?
    - ?澈?芣? `summary`
    - ?啣澈?? `summary_json`

    ?亙銝甈∪?敹怠?嚗??甈∟?瘙??information_schema??    """

    global _CHAT_SESSIONS_HAS_SUMMARY_JSON
    if _CHAT_SESSIONS_HAS_SUMMARY_JSON is not None:
        return _CHAT_SESSIONS_HAS_SUMMARY_JSON

    row = await fetchrow_ai(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'chat_sessions'
              AND column_name = 'summary_json'
        ) AS has_column
        """
    )
    _CHAT_SESSIONS_HAS_SUMMARY_JSON = bool(row["has_column"]) if row else False
    return _CHAT_SESSIONS_HAS_SUMMARY_JSON


def _session_select_columns(has_summary_json: bool) -> str:
    summary_json_expr = "summary_json" if has_summary_json else "'{}'::jsonb AS summary_json"
    return f"""
        id,
        session_id,
        user_id,
        pond_id,
        title,
        summary,
        {summary_json_expr},
        created_at,
        updated_at
    """


async def get_chat_session(session_id: str) -> dict | None:
    has_summary_json = await _supports_summary_json()
    row = await fetchrow_ai(
        f"""
        SELECT
            {_session_select_columns(has_summary_json)}
        FROM chat_sessions
        WHERE session_id = $1
        """,
        session_id,
    )
    return row_to_jsonable(row) if row else None


async def list_chat_sessions_by_user(user_id: int, limit: int = 50) -> list[dict]:
    has_summary_json = await _supports_summary_json()
    rows = await fetch_ai(
        f"""
        SELECT
            {_session_select_columns(has_summary_json)}
        FROM chat_sessions
        WHERE user_id = $1
        ORDER BY updated_at DESC, id DESC
        LIMIT $2
        """,
        user_id,
        limit,
    )
    return [row_to_jsonable(row) for row in rows]


async def create_chat_session(
    *,
    session_id: str,
    user_id: int,
    pond_id: int,
    title: str | None = None,
    summary: str = "",
    summary_json: dict[str, Any] | None = None,
) -> int:
    has_summary_json = await _supports_summary_json()
    normalized_title = _normalize_text(title)

    if has_summary_json:
        row = await fetchrow_ai(
            """
            INSERT INTO chat_sessions (
                session_id,
                user_id,
                pond_id,
                title,
                summary,
                summary_json,
                updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, NOW())
            ON CONFLICT (session_id) DO NOTHING
            RETURNING id
            """,
            session_id,
            user_id,
            pond_id,
            normalized_title,
            summary,
            json.dumps(summary_json or {}, ensure_ascii=False),
        )
    else:
        row = await fetchrow_ai(
            """
            INSERT INTO chat_sessions (
                session_id,
                user_id,
                pond_id,
                title,
                summary,
                updated_at
            )
            VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (session_id) DO NOTHING
            RETURNING id
            """,
            session_id,
            user_id,
            pond_id,
            normalized_title,
            summary,
        )

    if row is not None:
        return int(row["id"])

    existing = await fetchrow_ai(
        """
        SELECT id
        FROM chat_sessions
        WHERE session_id = $1
        """,
        session_id,
    )
    if existing is None:
        raise RuntimeError("?⊥?撱箇???敺?閰?session")
    return int(existing["id"])


async def ensure_chat_session(
    *,
    session_id: str,
    user_id: int,
    pond_id: int,
    title: str | None = None,
) -> dict:
    session = await get_chat_session(session_id)
    normalized_title = _normalize_text(title)

    if session is not None:
        current_title = _normalize_text(session.get("title"))
        if normalized_title and not current_title:
            await execute_ai(
                """
                UPDATE chat_sessions
                SET title = $2, updated_at = NOW()
                WHERE session_id = $1
                """,
                session_id,
                normalized_title,
            )
            session["title"] = normalized_title
        return session

    await create_chat_session(
        session_id=session_id,
        user_id=user_id,
        pond_id=pond_id,
        title=normalized_title,
        summary="",
        summary_json={},
    )
    session = await get_chat_session(session_id)
    if session is None:
        raise RuntimeError("撠店 session 撱箇?憭望?")
    return session


async def update_chat_session_summary(
    session_id: str,
    summary_text: str,
    summary_json: dict[str, Any] | None = None,
) -> None:
    has_summary_json = await _supports_summary_json()
    if has_summary_json:
        await execute_ai(
            """
            UPDATE chat_sessions
            SET
                summary = $2,
                summary_json = $3::jsonb,
                updated_at = NOW()
            WHERE session_id = $1
            """,
            session_id,
            summary_text,
            json.dumps(summary_json or {}, ensure_ascii=False),
        )
        return

    await execute_ai(
        """
        UPDATE chat_sessions
        SET
            summary = $2,
            updated_at = NOW()
        WHERE session_id = $1
        """,
        session_id,
        summary_text,
    )


async def list_chat_messages(session_id: str) -> list[dict]:
    rows = await fetch_ai(
        """
        SELECT
            id,
            session_id,
            role,
            message,
            metadata,
            created_at
        FROM chat_messages
        WHERE session_id = $1
        ORDER BY created_at ASC, id ASC
        """,
        session_id,
    )
    return [row_to_jsonable(row) for row in rows]


async def list_recent_chat_messages(session_id: str, limit: int = 12) -> list[dict]:
    if limit <= 0:
        return []

    rows = await fetch_ai(
        """
        SELECT
            id,
            session_id,
            role,
            message,
            metadata,
            created_at
        FROM (
            SELECT
                id,
                session_id,
                role,
                message,
                metadata,
                created_at
            FROM chat_messages
            WHERE session_id = $1
            ORDER BY created_at DESC, id DESC
            LIMIT $2
        ) AS recent_messages
        ORDER BY created_at ASC, id ASC
        """,
        session_id,
        limit,
    )
    return [row_to_jsonable(row) for row in rows]


async def insert_chat_message(
    *,
    session_id: str,
    role: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> int:
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
    row = await fetchrow_ai(
        """
        INSERT INTO chat_messages (
            session_id,
            role,
            message,
            metadata
        )
        VALUES ($1, $2, $3, $4::jsonb)
        RETURNING id
        """,
        session_id,
        role,
        message,
        metadata_json,
    )

    await execute_ai(
        """
        UPDATE chat_sessions
        SET updated_at = NOW()
        WHERE session_id = $1
        """,
        session_id,
    )

    return int(row["id"])


async def delete_chat_session(session_id: str) -> None:
    await execute_ai(
        """
        DELETE FROM chat_messages
        WHERE session_id = $1
        """,
        session_id,
    )
    await execute_ai(
        """
        DELETE FROM chat_sessions
        WHERE session_id = $1
        """,
        session_id,
    )


