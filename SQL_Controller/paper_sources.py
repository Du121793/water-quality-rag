import json

from methods.base.serializer import row_to_jsonable, to_jsonable
from methods.infra.database import execute_ai, fetch_ai, fetchrow_ai, fetchval_ai


async def get_paper_source_by_id(paper_source_id: int) -> dict | None:
    row = await fetchrow_ai(
        """
        SELECT
            id,
            title,
            title_normalized,
            authors,
            journal_name,
            doi,
            source_url,
            local_file_path,
            file_hash,
            content_hash,
            published_at,
            species_tags,
            topic_tags,
            created_at,
            updated_at
        FROM paper_sources
        WHERE id = $1
        """,
        paper_source_id,
    )
    return row_to_jsonable(row) if row else None


async def get_paper_source_by_source_url(source_url: str) -> dict | None:
    row = await fetchrow_ai(
        """
        SELECT id, title, doi, source_url, local_file_path, file_hash, content_hash, created_at, updated_at
        FROM paper_sources
        WHERE source_url = $1
        """,
        source_url,
    )
    return row_to_jsonable(row) if row else None


async def find_duplicate_paper_source(
    *,
    source_url: str | None,
    doi: str | None,
    file_hash: str | None,
    content_hash: str | None,
    title_normalized: str | None,
) -> dict | None:
    checks = [
        ("source_url", source_url, "source_url = $1"),
        ("doi", doi, "lower(doi) = lower($1)"),
        ("file_hash", file_hash, "file_hash = $1"),
        ("content_hash", content_hash, "content_hash = $1"),
        ("title_normalized", title_normalized, "title_normalized = $1"),
    ]

    for matched_by, value, where_clause in checks:
        if not value:
            continue

        row = await fetchrow_ai(
            f"""
            SELECT
                id,
                title,
                title_normalized,
                authors,
                journal_name,
                doi,
                source_url,
                local_file_path,
                file_hash,
                content_hash,
                published_at,
                species_tags,
                topic_tags,
                created_at,
                updated_at
            FROM paper_sources
            WHERE {where_clause}
            ORDER BY id
            LIMIT 1
            """,
            value,
        )
        if row:
            duplicate = row_to_jsonable(row)
            duplicate["matched_by"] = matched_by
            return duplicate

    return None


async def upsert_paper_source(
    *,
    title: str,
    title_normalized: str,
    source_url: str,
    local_file_path: str,
    authors: str | None = None,
    journal_name: str | None = None,
    doi: str | None = None,
    file_hash: str | None = None,
    content_hash: str | None = None,
    published_at: str | None = None,
    species_tags: list[str] | None = None,
    topic_tags: list[str] | None = None,
    existing_paper_source_id: int | None = None,
) -> int:
    target_id = existing_paper_source_id
    if target_id is None:
        existing = await fetchrow_ai(
            """
            SELECT id
            FROM paper_sources
            WHERE source_url = $1
            """,
            source_url,
        )
        target_id = int(existing["id"]) if existing else None

    if target_id is not None:
        await execute_ai(
            """
            UPDATE paper_sources
            SET
                title = $2,
                title_normalized = $3,
                authors = $4,
                journal_name = $5,
                doi = $6,
                source_url = $7,
                local_file_path = $8,
                file_hash = $9,
                content_hash = $10,
                published_at = $11,
                species_tags = $12::text[],
                topic_tags = $13::text[],
                updated_at = NOW()
            WHERE id = $1
            """,
            target_id,
            title,
            title_normalized,
            authors,
            journal_name,
            doi,
            source_url,
            local_file_path,
            file_hash,
            content_hash,
            published_at,
            species_tags or [],
            topic_tags or [],
        )
        return target_id

    return int(
        await fetchval_ai(
            """
            INSERT INTO paper_sources (
                title,
                title_normalized,
                authors,
                journal_name,
                doi,
                source_url,
                local_file_path,
                file_hash,
                content_hash,
                published_at,
                species_tags,
                topic_tags,
                updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::text[], $12::text[], NOW()
            )
            RETURNING id
            """,
            title,
            title_normalized,
            authors,
            journal_name,
            doi,
            source_url,
            local_file_path,
            file_hash,
            content_hash,
            published_at,
            species_tags or [],
            topic_tags or [],
        )
    )


async def list_paper_sources() -> list[dict]:
    rows = await fetch_ai(
        """
        SELECT
            id,
            title,
            title_normalized,
            authors,
            journal_name,
            doi,
            source_url,
            local_file_path,
            file_hash,
            content_hash,
            published_at,
            species_tags,
            topic_tags,
            created_at,
            updated_at
        FROM paper_sources
        ORDER BY id
        """
    )
    return [row_to_jsonable(row) for row in rows]


async def delete_paper_chunks_by_source_id(paper_source_id: int) -> None:
    await execute_ai(
        "DELETE FROM paper_chunks WHERE paper_source_id = $1",
        paper_source_id,
    )


async def insert_paper_chunk(
    paper_source_id: int,
    chunk_index: int,
    chunk_text: str,
    metadata: dict,
) -> int:
    return int(
        await fetchval_ai(
            """
            INSERT INTO paper_chunks (
                paper_source_id,
                chunk_index,
                chunk_text,
                metadata
            )
            VALUES ($1, $2, $3, $4::jsonb)
            RETURNING id
            """,
            paper_source_id,
            chunk_index,
            chunk_text,
            json.dumps(metadata, ensure_ascii=False),
        )
    )


