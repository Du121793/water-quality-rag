import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from methods.base.logger import error, info
from methods.infra.database import close_database_pools, initialize_database_pools
from methods.rag.paper_ingest import parse_paper_index
from methods.rag.paper_rag_service import ingest_local_pdf_path

PAPERS_DIR = Path("papers/water-quality")
INDEX_PATH = PAPERS_DIR / "INDEX.md"


async def ingest() -> None:
    metadata_map = parse_paper_index(INDEX_PATH)
    pdf_files = sorted(PAPERS_DIR.glob("*.pdf"))

    if not pdf_files:
        raise RuntimeError("找不到可匯入的 PDF 檔案")

    await initialize_database_pools()
    try:
        for pdf_file in pdf_files:
            metadata = metadata_map.get(pdf_file.name)
            if not metadata:
                info("論文匯入", f"INDEX.md 未定義該檔案，略過 {pdf_file.name}")
                continue

            info("論文匯入", f"開始匯入 {pdf_file.name}")
            result = await ingest_local_pdf_path(
                title=metadata["title"],
                pdf_path=str(pdf_file),
                source_url=metadata["source_url"],
                doi=metadata.get("doi"),
                journal_name=metadata.get("journal_name"),
                published_at=metadata.get("published_at"),
                duplicate_policy="replace_existing",
            )

            info(
                "論文匯入",
                (
                    f"完成 {pdf_file.name} "
                    f"chunk_count={result['chunk_count']} "
                    f"embedded_chunk_count={result['embedded_chunk_count']} "
                    f"matched_by={result['duplicate']['matched_by']}"
                ),
            )
    finally:
        await close_database_pools()


if __name__ == "__main__":
    try:
        asyncio.run(ingest())
    except Exception as err:
        error("論文匯入", err)
        raise
