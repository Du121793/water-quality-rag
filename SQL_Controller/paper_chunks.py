from __future__ import annotations

import re

from methods.base.serializer import row_to_jsonable
from methods.infra.database import fetch_ai


KEYWORD_SYNONYMS: dict[str, list[str]] = {
    "溶氧": ["dissolved oxygen", "oxygen", "hypoxia", "do"],
    "低氧": ["hypoxia", "low oxygen", "oxygen depletion", "dissolved oxygen"],
    "缺氧": ["hypoxia", "oxygen depletion", "dissolved oxygen"],
    "氨氮": ["ammonia", "nitrogen"],
    "氨": ["ammonia"],
    "酸鹼值": ["ph", "acid", "alkaline"],
    "ph": ["ph", "acid", "alkaline"],
    "溫度": ["temperature", "thermal"],
    "水溫": ["temperature", "thermal", "thermal stress"],
    "濁度": ["turbidity"],
    "orp": ["orp", "oxidation reduction potential", "redox"],
    "氧化還原": ["orp", "oxidation reduction potential", "redox"],
    "微生物": ["microbial", "bacterial", "microbiome"],
    "魚類壓力": ["fish stress", "hypoxia", "dissolved oxygen"],
    "浮頭": ["surface breathing", "hypoxia", "dissolved oxygen"],
}


def _expand_keywords(keyword: str) -> list[str]:
    normalized = (keyword or "").strip().lower()
    if not normalized:
        return []

    expanded = {normalized}
    english_tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", normalized)
    expanded.update(token for token in english_tokens if len(token) >= 3)

    if "dissolved" in normalized and "oxygen" in normalized:
        expanded.add("dissolved oxygen")
    if "water" in normalized and "quality" in normalized:
        expanded.add("water quality")

    for source, synonyms in KEYWORD_SYNONYMS.items():
        if source in normalized:
            expanded.update(synonyms)

    return list(expanded)


async def search_paper_chunks_by_keywords(keyword: str, limit: int = 5) -> list[dict]:
    expanded_keywords = _expand_keywords(keyword)
    rows = await fetch_ai(
        """
        SELECT
            pc.id,
            pc.paper_source_id,
            pc.chunk_index,
            pc.chunk_text,
            ps.title,
            ps.source_url,
            ps.doi,
            ps.published_at
        FROM paper_chunks pc
        JOIN paper_sources ps ON ps.id = pc.paper_source_id
        WHERE
            (
                cardinality($1::text[]) = 0
                OR EXISTS (
                    SELECT 1
                    FROM unnest($1::text[]) AS term(keyword)
                    WHERE
                        ps.title ILIKE '%' || keyword || '%'
                        OR pc.chunk_text ILIKE '%' || keyword || '%'
                        OR EXISTS (
                            SELECT 1
                            FROM unnest(ps.topic_tags) AS topic_tag
                            WHERE
                                topic_tag ILIKE '%' || keyword || '%'
                                OR replace(topic_tag, '_', ' ') ILIKE '%' || keyword || '%'
                        )
                )
            )
        ORDER BY ps.published_at DESC NULLS LAST, pc.id DESC
        LIMIT $2
        """,
        expanded_keywords,
        limit,
    )

    return [row_to_jsonable(row) for row in rows]


async def count_paper_chunks() -> int:
    rows = await fetch_ai("SELECT COUNT(*) AS total FROM paper_chunks")
    return int(rows[0]["total"]) if rows else 0


async def list_paper_chunks_by_source_id(paper_source_id: int) -> list[dict]:
    rows = await fetch_ai(
        """
        SELECT
            id,
            paper_source_id,
            chunk_index,
            chunk_text,
            metadata,
            created_at
        FROM paper_chunks
        WHERE paper_source_id = $1
        ORDER BY chunk_index
        """,
        paper_source_id,
    )
    return [row_to_jsonable(row) for row in rows]


async def list_paper_chunks_for_embedding_rebuild(after_chunk_id: int = 0, limit: int = 50) -> list[dict]:
    rows = await fetch_ai(
        """
        SELECT
            id AS chunk_id,
            paper_source_id,
            chunk_index,
            chunk_text
        FROM paper_chunks
        WHERE id > $1
        ORDER BY id
        LIMIT $2
        """,
        after_chunk_id,
        limit,
    )
    return [row_to_jsonable(row) for row in rows]


async def list_neighbor_chunks_by_source(
    paper_source_id: int,
    chunk_indexes: list[int],
    neighbor_window: int = 1,
) -> list[dict]:
    if not chunk_indexes:
        return []

    rows = await fetch_ai(
        """
        WITH requested_indexes AS (
            SELECT unnest($2::int[]) AS chunk_index
        )
        SELECT DISTINCT
            pc.id,
            pc.paper_source_id,
            pc.chunk_index,
            pc.chunk_text,
            ps.title,
            ps.source_url,
            ps.doi,
            ps.published_at
        FROM paper_chunks pc
        JOIN paper_sources ps ON ps.id = pc.paper_source_id
        JOIN requested_indexes ri
          ON pc.chunk_index BETWEEN ri.chunk_index - $3 AND ri.chunk_index + $3
        WHERE pc.paper_source_id = $1
        ORDER BY pc.chunk_index
        """,
        paper_source_id,
        chunk_indexes,
        neighbor_window,
    )
    return [row_to_jsonable(row) for row in rows]
