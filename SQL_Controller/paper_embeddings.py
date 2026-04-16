from methods.base.serializer import row_to_jsonable, to_jsonable
from methods.infra.database import execute_ai, fetch_ai, fetchval_ai


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.12f}".rstrip("0").rstrip(".") for value in embedding) + "]"


async def list_chunks_without_embeddings(
    embedding_provider: str,
    embedding_model: str,
    limit: int = 50,
) -> list[dict]:
    rows = await fetch_ai(
        """
        SELECT
            pc.id,
            pc.paper_source_id,
            pc.chunk_index,
            pc.chunk_text,
            ps.title,
            ps.source_url
        FROM paper_chunks pc
        JOIN paper_sources ps ON ps.id = pc.paper_source_id
        LEFT JOIN paper_embeddings pe
            ON pe.paper_chunk_id = pc.id
           AND pe.embedding_provider = $1
           AND pe.embedding_model = $2
        WHERE pe.id IS NULL
        ORDER BY pc.id
        LIMIT $3
        """,
        embedding_provider,
        embedding_model,
        limit,
    )
    return [row_to_jsonable(row) for row in rows]


async def upsert_paper_embedding(
    paper_chunk_id: int,
    embedding_provider: str,
    embedding_model: str,
    embedding: list[float],
) -> None:
    dimensions = len(embedding)
    vector_literal = _vector_literal(embedding)
    await execute_ai(
        """
        INSERT INTO paper_embeddings (
            paper_chunk_id,
            embedding_provider,
            embedding_model,
            embedding_dimensions,
            embedding,
            updated_at
        )
        VALUES ($1, $2, $3, $4, $5::vector, NOW())
        ON CONFLICT (paper_chunk_id, embedding_provider, embedding_model)
        DO UPDATE
        SET
            embedding_dimensions = EXCLUDED.embedding_dimensions,
            embedding = EXCLUDED.embedding,
            updated_at = NOW()
        """,
        paper_chunk_id,
        embedding_provider,
        embedding_model,
        dimensions,
        vector_literal,
    )


async def count_paper_embeddings(embedding_provider: str, embedding_model: str) -> int:
    total = await fetchval_ai(
        """
        SELECT COUNT(*)
        FROM paper_embeddings
        WHERE embedding_provider = $1
          AND embedding_model = $2
        """,
        embedding_provider,
        embedding_model,
    )
    return int(total or 0)


async def delete_paper_embeddings_by_model(embedding_provider: str, embedding_model: str) -> None:
    await execute_ai(
        """
        DELETE FROM paper_embeddings
        WHERE embedding_provider = $1
          AND embedding_model = $2
        """,
        embedding_provider,
        embedding_model,
    )


async def delete_paper_embeddings_except_model(embedding_provider: str, embedding_model: str) -> None:
    await execute_ai(
        """
        DELETE FROM paper_embeddings
        WHERE NOT (
            embedding_provider = $1
            AND embedding_model = $2
        )
        """,
        embedding_provider,
        embedding_model,
    )


async def search_paper_chunks_by_embedding(
    embedding_provider: str,
    embedding_model: str,
    query_embedding: list[float],
    limit: int = 5,
) -> list[dict]:
    dimensions = len(query_embedding)
    vector_literal = _vector_literal(query_embedding)
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
            ps.published_at,
            ROUND((pe.embedding <=> $3::vector)::numeric, 6) AS distance
        FROM paper_embeddings pe
        JOIN paper_chunks pc ON pc.id = pe.paper_chunk_id
        JOIN paper_sources ps ON ps.id = pc.paper_source_id
        WHERE pe.embedding_provider = $1
          AND pe.embedding_model = $2
          AND pe.embedding_dimensions = $4
        ORDER BY pe.embedding <=> $3::vector
        LIMIT $5
        """,
        embedding_provider,
        embedding_model,
        vector_literal,
        dimensions,
        limit,
    )
    return [row_to_jsonable(row) for row in rows]


