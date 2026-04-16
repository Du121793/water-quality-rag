from __future__ import annotations

from SQL_Controller.paper_chunks import count_paper_chunks, list_paper_chunks_for_embedding_rebuild
from SQL_Controller.paper_embeddings import (
    delete_paper_embeddings_by_model,
    delete_paper_embeddings_except_model,
)
from SQL_Controller.rag_ingest_jobs import (
    complete_rag_ingest_job,
    fail_rag_ingest_job,
    mark_rag_ingest_job_running,
    update_rag_ingest_job_progress,
)
from methods.base.logger import error, info
from methods.rag.embeddings import embed_texts, get_embedding_identity
from methods.rag.paper_rag_service import embed_chunk_payloads


async def run_rag_embedding_job(job_id: str, chunk_payloads: list[dict]) -> None:
    embedded_chunks = 0

    try:
        await mark_rag_ingest_job_running(job_id)
        provider, model = get_embedding_identity()
        info("RAG背景任務", f"開始進行向量化 job_id={job_id} provider={provider} model={model}")

        batch_size = 8
        for offset in range(0, len(chunk_payloads), batch_size):
            batch = chunk_payloads[offset: offset + batch_size]
            embeddings = await embed_texts([item["chunk_text"] for item in batch])
            await embed_chunk_payloads(batch, precomputed_embeddings=embeddings)
            embedded_chunks += len(batch)
            await update_rag_ingest_job_progress(job_id, embedded_chunks)

        await complete_rag_ingest_job(job_id, embedded_chunks)
        info("RAG背景任務", f"向量化完成 job_id={job_id} embedded_chunks={embedded_chunks}")
    except Exception as err:
        error("RAG背景任務", err, extra={"job_id": job_id, "embedded_chunks": embedded_chunks})
        await fail_rag_ingest_job(job_id, str(err), embedded_chunks)


async def run_rag_embedding_rebuild_job(
    job_id: str,
    purge_current_model_embeddings: bool = True,
    purge_other_model_embeddings: bool = False,
) -> None:
    embedded_chunks = 0
    last_chunk_id = 0

    try:
        await mark_rag_ingest_job_running(job_id)
        provider, model = get_embedding_identity()
        info(
            "RAG重建任務",
            (
                "開始重建整庫向量 "
                f"job_id={job_id} provider={provider} model={model} "
                f"purge_current={purge_current_model_embeddings} purge_other={purge_other_model_embeddings}"
            ),
        )

        if purge_other_model_embeddings:
            await delete_paper_embeddings_except_model(provider, model)
        if purge_current_model_embeddings:
            await delete_paper_embeddings_by_model(provider, model)

        total_chunks = await count_paper_chunks()
        if total_chunks == 0:
            await complete_rag_ingest_job(job_id, 0)
            info("RAG重建任務", f"沒有可重建的 chunk，任務直接完成 job_id={job_id}")
            return

        batch_size = 8
        while True:
            batch = await list_paper_chunks_for_embedding_rebuild(after_chunk_id=last_chunk_id, limit=batch_size)
            if not batch:
                break

            embeddings = await embed_texts([item["chunk_text"] for item in batch])
            await embed_chunk_payloads(batch, precomputed_embeddings=embeddings)

            embedded_chunks += len(batch)
            last_chunk_id = int(batch[-1]["chunk_id"])
            await update_rag_ingest_job_progress(job_id, embedded_chunks)

        await complete_rag_ingest_job(job_id, embedded_chunks)
        info("RAG重建任務", f"整庫向量重建完成 job_id={job_id} embedded_chunks={embedded_chunks}")
    except Exception as err:
        error(
            "RAG重建任務",
            err,
            extra={"job_id": job_id, "embedded_chunks": embedded_chunks, "last_chunk_id": last_chunk_id},
        )
        await fail_rag_ingest_job(job_id, str(err), embedded_chunks)
