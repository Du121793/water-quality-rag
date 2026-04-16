from __future__ import annotations

from datetime import date
import re
from pathlib import Path

from fastapi import UploadFile

from SQL_Controller.paper_chunks import list_paper_chunks_by_source_id
from SQL_Controller.paper_embeddings import upsert_paper_embedding
from SQL_Controller.paper_sources import (
    delete_paper_chunks_by_source_id,
    find_duplicate_paper_source,
    get_paper_source_by_id,
    insert_paper_chunk,
    list_paper_sources,
    upsert_paper_source,
)
from methods.rag.citation_formatter import format_citations
from methods.rag.embeddings import embed_texts, embedding_is_configured, get_embedding_identity
from methods.rag.paper_ingest import (
    chunk_text,
    extract_pdf_text_from_bytes,
    infer_tags_from_text,
    normalize_doi,
    normalize_title,
    sha256_hex,
)

UPLOAD_DIR = Path("papers/uploads")


def _sanitize_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", filename or "paper.pdf")
    return cleaned.strip("._") or "paper.pdf"


def _derive_source_url(source_url: str | None, file_hash: str) -> str:
    if source_url and source_url.strip():
        return source_url.strip()
    return f"local://{file_hash}"


def _duplicate_response(duplicate: dict | None) -> dict:
    if duplicate is None:
        return {
            "is_duplicate": False,
            "matched_by": None,
            "paper_source": None,
        }
    return {
        "is_duplicate": True,
        "matched_by": duplicate.get("matched_by"),
        "paper_source": duplicate,
    }


def _normalize_published_at(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _build_ingest_summary(
    *,
    duplicate: dict | None,
    paper_source: dict | None,
    paper_chunks: list[dict],
    inserted_chunks: list[dict],
    citations: list[dict],
    embedded_chunk_count: int,
    embedding_job_id: str | None = None,
    embedding_status: str = "completed",
) -> dict:
    provider, model = get_embedding_identity() if embedding_is_configured() else (None, None)
    return {
        "created": duplicate is None,
        "duplicate": _duplicate_response(duplicate),
        "paper_source": paper_source,
        "citations": citations,
        "chunk_count": len(paper_chunks),
        "embedded_chunk_count": embedded_chunk_count,
        "embedding_job_id": embedding_job_id,
        "embedding_status": embedding_status,
        "embedding_provider": provider,
        "embedding_model": model,
        "inserted_chunks": inserted_chunks,
    }


async def check_duplicate_by_pdf(
    *,
    title: str,
    source_url: str | None,
    doi: str | None,
    pdf_bytes: bytes,
) -> dict:
    extracted_text = extract_pdf_text_from_bytes(pdf_bytes)
    if not extracted_text:
        raise ValueError("PDF 解析失敗，無法從檔案中擷取可用文字內容。")

    duplicate = await find_duplicate_paper_source(
        source_url=source_url.strip() if source_url else None,
        doi=normalize_doi(doi),
        file_hash=sha256_hex(pdf_bytes),
        content_hash=sha256_hex(extracted_text),
        title_normalized=normalize_title(title),
    )
    return _duplicate_response(duplicate)


async def embed_chunk_payloads(
    chunk_payloads: list[dict],
    precomputed_embeddings: list[list[float]] | None = None,
) -> int:
    if not chunk_payloads or not embedding_is_configured():
        return 0

    provider, model = get_embedding_identity()
    embeddings = precomputed_embeddings or await embed_texts([item["chunk_text"] for item in chunk_payloads])

    for chunk_payload, embedding in zip(chunk_payloads, embeddings, strict=True):
        await upsert_paper_embedding(
            paper_chunk_id=int(chunk_payload["chunk_id"]),
            embedding_provider=provider,
            embedding_model=model,
            embedding=embedding,
        )

    return len(chunk_payloads)


async def ingest_pdf_bytes(
    *,
    title: str,
    pdf_bytes: bytes,
    original_filename: str,
    source_url: str | None = None,
    doi: str | None = None,
    authors: str | None = None,
    journal_name: str | None = None,
    published_at: str | None = None,
    duplicate_policy: str = "reject",
    run_embedding: bool = True,
) -> dict:
    normalized_title = normalize_title(title)
    normalized_doi = normalize_doi(doi)
    normalized_published_at = _normalize_published_at(published_at)
    file_hash = sha256_hex(pdf_bytes)
    extracted_text = extract_pdf_text_from_bytes(pdf_bytes)
    if not extracted_text:
        raise ValueError("PDF 解析失敗，無法從檔案中擷取可用文字內容。")

    content_hash = sha256_hex(extracted_text)
    resolved_source_url = _derive_source_url(source_url, file_hash)

    duplicate = await find_duplicate_paper_source(
        source_url=resolved_source_url,
        doi=normalized_doi,
        file_hash=file_hash,
        content_hash=content_hash,
        title_normalized=normalized_title,
    )

    if duplicate and duplicate_policy == "reject":
        provider, model = get_embedding_identity() if embedding_is_configured() else (None, None)
        return {
            "created": False,
            "duplicate": _duplicate_response(duplicate),
            "paper_source": duplicate,
            "citations": [],
            "chunk_count": 0,
            "embedded_chunk_count": 0,
            "embedding_job_id": None,
            "embedding_status": "skipped",
            "embedding_provider": provider,
            "embedding_model": model,
            "inserted_chunks": [],
        }

    if duplicate_policy not in {"reject", "replace_existing"}:
        raise ValueError("duplicate_policy 只接受 reject 或 replace_existing。")

    safe_filename = _sanitize_filename(original_filename)
    stored_filename = f"{file_hash[:16]}_{safe_filename}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_path = UPLOAD_DIR / stored_filename
    stored_path.write_bytes(pdf_bytes)

    species_tags, topic_tags = infer_tags_from_text(extracted_text, title)
    target_source_id = int(duplicate["id"]) if duplicate and duplicate_policy == "replace_existing" else None

    paper_source_id = await upsert_paper_source(
        title=title,
        title_normalized=normalized_title,
        source_url=resolved_source_url,
        local_file_path=stored_path.as_posix(),
        authors=authors,
        journal_name=journal_name,
        doi=normalized_doi,
        file_hash=file_hash,
        content_hash=content_hash,
        published_at=normalized_published_at,
        species_tags=species_tags,
        topic_tags=topic_tags,
        existing_paper_source_id=target_source_id,
    )

    await delete_paper_chunks_by_source_id(paper_source_id)

    inserted_chunks: list[dict] = []
    for chunk_index, chunk in enumerate(chunk_text(extracted_text), start=1):
        chunk_id = await insert_paper_chunk(
            paper_source_id=paper_source_id,
            chunk_index=chunk_index,
            chunk_text=chunk,
            metadata={
                "filename": stored_filename,
                "chunk_size": len(chunk),
                "species_tags": species_tags,
                "topic_tags": topic_tags,
                "doi": normalized_doi,
            },
        )
        inserted_chunks.append({"chunk_id": chunk_id, "chunk_text": chunk})

    embedded_chunk_count = 0
    if run_embedding:
        embedded_chunk_count = await embed_chunk_payloads(inserted_chunks)

    paper_source = await get_paper_source_by_id(paper_source_id)
    paper_chunks = await list_paper_chunks_by_source_id(paper_source_id)
    citations = format_citations(
        [
            {
                "id": row["id"],
                "paper_source_id": row["paper_source_id"],
                "chunk_index": row["chunk_index"],
                "chunk_text": row["chunk_text"],
                "title": paper_source["title"] if paper_source else title,
                "source_url": paper_source["source_url"] if paper_source else resolved_source_url,
                "doi": paper_source.get("doi") if paper_source else normalized_doi,
                "published_at": paper_source.get("published_at") if paper_source else normalized_published_at,
            }
            for row in paper_chunks[:5]
        ]
    )

    return _build_ingest_summary(
        duplicate=duplicate,
        paper_source=paper_source,
        paper_chunks=paper_chunks,
        inserted_chunks=inserted_chunks,
        citations=citations,
        embedded_chunk_count=embedded_chunk_count,
        embedding_status="completed" if run_embedding else "queued",
    )


async def ingest_pdf_file(
    *,
    title: str,
    upload_file: UploadFile,
    source_url: str | None = None,
    doi: str | None = None,
    authors: str | None = None,
    journal_name: str | None = None,
    published_at: str | None = None,
    duplicate_policy: str = "reject",
    run_embedding: bool = True,
) -> dict:
    pdf_bytes = await upload_file.read()
    return await ingest_pdf_bytes(
        title=title,
        pdf_bytes=pdf_bytes,
        original_filename=upload_file.filename or "paper.pdf",
        source_url=source_url,
        doi=doi,
        authors=authors,
        journal_name=journal_name,
        published_at=published_at,
        duplicate_policy=duplicate_policy,
        run_embedding=run_embedding,
    )


async def list_papers_for_api() -> list[dict]:
    return await list_paper_sources()


async def ingest_local_pdf_path(
    *,
    title: str,
    pdf_path: str,
    source_url: str | None = None,
    doi: str | None = None,
    authors: str | None = None,
    journal_name: str | None = None,
    published_at: str | None = None,
    duplicate_policy: str = "reject",
    run_embedding: bool = True,
) -> dict:
    file_path = Path(pdf_path)
    pdf_bytes = file_path.read_bytes()
    return await ingest_pdf_bytes(
        title=title,
        pdf_bytes=pdf_bytes,
        original_filename=file_path.name,
        source_url=source_url,
        doi=doi,
        authors=authors,
        journal_name=journal_name,
        published_at=published_at,
        duplicate_policy=duplicate_policy,
        run_embedding=run_embedding,
    )
