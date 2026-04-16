from methods.base.serializer import to_jsonable
from methods.infra.database import execute_ai, fetchrow_ai, fetchval_ai


async def create_rag_ingest_job(
    *,
    job_id: str,
    paper_source_id: int | None,
    requested_by: int | None,
    embedding_provider: str | None,
    embedding_model: str | None,
    chunk_total: int,
) -> int:
    return int(
        await fetchval_ai(
            """
            INSERT INTO rag_ingest_jobs (
                job_id,
                paper_source_id,
                requested_by,
                status,
                embedding_provider,
                embedding_model,
                chunk_total,
                embedded_chunks,
                updated_at
            )
            VALUES ($1, $2, $3, 'queued', $4, $5, $6, 0, NOW())
            RETURNING id
            """,
            job_id,
            paper_source_id,
            requested_by,
            embedding_provider,
            embedding_model,
            chunk_total,
        )
    )


async def mark_rag_ingest_job_running(job_id: str) -> None:
    await execute_ai(
        """
        UPDATE rag_ingest_jobs
        SET status = 'running', updated_at = NOW()
        WHERE job_id = $1
        """,
        job_id,
    )


async def update_rag_ingest_job_progress(job_id: str, embedded_chunks: int) -> None:
    await execute_ai(
        """
        UPDATE rag_ingest_jobs
        SET embedded_chunks = $2, updated_at = NOW()
        WHERE job_id = $1
        """,
        job_id,
        embedded_chunks,
    )


async def complete_rag_ingest_job(job_id: str, embedded_chunks: int) -> None:
    await execute_ai(
        """
        UPDATE rag_ingest_jobs
        SET
            status = 'completed',
            embedded_chunks = $2,
            completed_at = NOW(),
            updated_at = NOW()
        WHERE job_id = $1
        """,
        job_id,
        embedded_chunks,
    )


async def fail_rag_ingest_job(job_id: str, error_message: str, embedded_chunks: int) -> None:
    await execute_ai(
        """
        UPDATE rag_ingest_jobs
        SET
            status = 'failed',
            error_message = $2,
            embedded_chunks = $3,
            completed_at = NOW(),
            updated_at = NOW()
        WHERE job_id = $1
        """,
        job_id,
        error_message,
        embedded_chunks,
    )


async def get_rag_ingest_job(job_id: str) -> dict | None:
    row = await fetchrow_ai(
        """
        SELECT
            id,
            job_id,
            paper_source_id,
            requested_by,
            status,
            embedding_provider,
            embedding_model,
            chunk_total,
            embedded_chunks,
            error_message,
            created_at,
            updated_at,
            completed_at
        FROM rag_ingest_jobs
        WHERE job_id = $1
        """,
        job_id,
    )
    return to_jsonable(dict(row)) if row else None
