from __future__ import annotations

import hashlib
import json

from SQL_Controller.paper_chunks import (
    list_neighbor_chunks_by_source,
    search_paper_chunks_by_keywords,
)
from SQL_Controller.paper_embeddings import search_paper_chunks_by_embedding
from methods.base.logger import warn
from methods.config.settings import settings
from methods.infra.redis_client import redis_client
from methods.rag.embeddings import embed_text, embedding_is_configured, get_embedding_identity


def _cache_key(query: str, limit: int) -> str:
    query_hash = hashlib.sha1(query.encode("utf-8")).hexdigest()[:16]
    return f"{settings.redis_key_prefix}:rag:{query_hash}:{limit}"


def _deduplicate_by_chunk_id(rows: list[dict]) -> list[dict]:
    deduplicated: list[dict] = []
    seen_ids: set[int] = set()

    for row in rows:
        row_id = int(row["id"])
        if row_id in seen_ids:
            continue
        deduplicated.append(row)
        seen_ids.add(row_id)

    return deduplicated


def _group_rows_by_paper(rows: list[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        paper_source_id = int(row["paper_source_id"])
        grouped.setdefault(paper_source_id, []).append(row)
    return grouped


def _pick_seed_rows(rows: list[dict], limit: int) -> list[dict]:
    picked: list[dict] = []
    paper_counts: dict[int, int] = {}

    for row in rows:
        paper_source_id = int(row["paper_source_id"])
        if len(paper_counts) >= settings.rag_max_context_papers and paper_source_id not in paper_counts:
            continue

        current_count = paper_counts.get(paper_source_id, 0)
        if current_count >= settings.rag_max_chunks_per_paper:
            continue

        picked.append(row)
        paper_counts[paper_source_id] = current_count + 1

        if len(picked) >= limit:
            break

    return picked


def _merge_neighbor_rows(seed_rows: list[dict], neighbor_rows: list[dict], limit: int) -> list[dict]:
    ordered: list[dict] = []
    seen_ids: set[int] = set()

    for row in seed_rows + neighbor_rows:
        row_id = int(row["id"])
        if row_id in seen_ids:
            continue
        seen_ids.add(row_id)
        ordered.append(row)
        if len(ordered) >= limit:
            break

    return ordered


def _is_evidence_sufficient(rows: list[dict]) -> tuple[bool, dict]:
    distinct_papers = len({int(row["paper_source_id"]) for row in rows})
    total_chunks = len(rows)
    total_characters = sum(len(row.get("chunk_text", "")) for row in rows)

    sufficient = (
        distinct_papers >= settings.rag_min_distinct_papers
        and total_chunks >= settings.rag_min_total_chunks
        and total_characters >= settings.rag_min_total_characters
    )

    return sufficient, {
        "distinct_papers": distinct_papers,
        "total_chunks": total_chunks,
        "total_characters": total_characters,
    }


async def _search_candidates(query: str, candidate_limit: int) -> list[dict]:
    results: list[dict] = []

    if embedding_is_configured():
        try:
            provider, model = get_embedding_identity()
            query_embedding = await embed_text(query)
            results = await search_paper_chunks_by_embedding(
                embedding_provider=provider,
                embedding_model=model,
                query_embedding=query_embedding,
                limit=candidate_limit,
            )
        except Exception as err:
            warn("RAG檢索", f"向量檢索失敗，改用關鍵字檢索: {err}")

    keyword_rows = await search_paper_chunks_by_keywords(query, limit=candidate_limit)
    return _deduplicate_by_chunk_id(results + keyword_rows)


async def _expand_with_neighbors(seed_rows: list[dict], limit: int) -> list[dict]:
    grouped = _group_rows_by_paper(seed_rows)
    neighbor_rows: list[dict] = []

    for paper_source_id, rows in grouped.items():
        chunk_indexes = [int(row["chunk_index"]) for row in rows]
        neighbor_rows.extend(
            await list_neighbor_chunks_by_source(
                paper_source_id=paper_source_id,
                chunk_indexes=chunk_indexes,
                neighbor_window=settings.rag_neighbor_window,
            )
        )

    return _merge_neighbor_rows(seed_rows, neighbor_rows, limit)


async def search_related_paper_context(query: str, limit: int = 8) -> dict:
    if redis_client is not None:
        cached = await redis_client.get(_cache_key(query, limit))
        if cached:
            return json.loads(cached)

    candidate_limit = max(limit, settings.rag_initial_candidate_limit)
    last_metrics = {
        "distinct_papers": 0,
        "total_chunks": 0,
        "total_characters": 0,
    }
    final_rows: list[dict] = []
    retrieval_rounds = 0

    for round_index in range(settings.rag_max_expand_rounds + 1):
        retrieval_rounds = round_index + 1
        candidates = await _search_candidates(query, candidate_limit)
        seed_limit = settings.rag_max_context_papers * settings.rag_max_chunks_per_paper
        seed_rows = _pick_seed_rows(candidates, seed_limit)
        final_rows = await _expand_with_neighbors(seed_rows, limit)

        sufficient, metrics = _is_evidence_sufficient(final_rows)
        last_metrics = metrics
        if sufficient:
            break

        candidate_limit += settings.rag_candidate_growth_step

    result = {
        "references": final_rows,
        "retrieval": {
            "rounds": retrieval_rounds,
            "candidate_limit": candidate_limit,
            "evidence_sufficient": (
                last_metrics["distinct_papers"] >= settings.rag_min_distinct_papers
                and last_metrics["total_chunks"] >= settings.rag_min_total_chunks
                and last_metrics["total_characters"] >= settings.rag_min_total_characters
            ),
            "metrics": last_metrics,
            "max_expand_rounds": settings.rag_max_expand_rounds,
            "max_context_papers": settings.rag_max_context_papers,
            "max_chunks_per_paper": settings.rag_max_chunks_per_paper,
            "neighbor_window": settings.rag_neighbor_window,
        },
    }

    if redis_client is not None:
        await redis_client.set(
            _cache_key(query, limit),
            json.dumps(result, ensure_ascii=False),
            ex=settings.cache_ttl_rag_result,
        )

    return result


async def search_related_paper_chunks(query: str, limit: int = 8) -> list[dict]:
    context = await search_related_paper_context(query, limit=limit)
    return context["references"]
