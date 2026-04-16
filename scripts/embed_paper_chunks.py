from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from SQL_Controller.paper_embeddings import (  # noqa: E402
    count_paper_embeddings,
    list_chunks_without_embeddings,
    upsert_paper_embedding,
)
from methods.base.logger import error, info  # noqa: E402
from methods.infra.database import close_database_pools, initialize_database_pools  # noqa: E402
from methods.rag.embeddings import embed_texts, embedding_is_configured, get_embedding_identity  # noqa: E402


async def main() -> None:
    if not embedding_is_configured():
        raise RuntimeError("尚未完成 embedding provider 設定，請先檢查 .env")

    provider, model = get_embedding_identity()
    processed = 0
    batch_size = 8

    await initialize_database_pools()
    try:
        info("EmbeddingPipeline", f"開始寫入論文向量 provider={provider} model={model} batch_size={batch_size}")

        while True:
            rows = await list_chunks_without_embeddings(provider, model, limit=batch_size)
            if not rows:
                break

            embeddings = await embed_texts([row["chunk_text"] for row in rows])
            for row, embedding in zip(rows, embeddings, strict=True):
                await upsert_paper_embedding(
                    paper_chunk_id=int(row["id"]),
                    embedding_provider=provider,
                    embedding_model=model,
                    embedding=embedding,
                )
                processed += 1
                info(
                    "EmbeddingPipeline",
                    f"已寫入 chunk_id={row['id']} title={row['title']} chunk_index={row['chunk_index']}",
                )

        total = await count_paper_embeddings(provider, model)
        info("EmbeddingPipeline", f"完成，新增 {processed} 筆，目前總數 {total}")
    finally:
        await close_database_pools()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as err:
        error("EmbeddingPipeline", err)
        raise
