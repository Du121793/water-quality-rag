from __future__ import annotations


def _clean_excerpt(text: str, max_length: int = 220) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."


def _citation_identity(row: dict) -> tuple:
    paper_source_id = row.get("paper_source_id")
    if paper_source_id is not None:
        return ("paper_source_id", paper_source_id)

    return (
        "fallback",
        row.get("title"),
        row.get("doi"),
        row.get("source_url"),
    )


def format_citations(rows: list[dict], limit: int = 5) -> list[dict]:
    citations: list[dict] = []
    seen: set[tuple] = set()

    for row in rows:
        identity = _citation_identity(row)
        if identity in seen:
            continue
        seen.add(identity)

        published_at = row.get("published_at")
        published_year = None
        if published_at:
            published_year = str(published_at)[:4]

        title = row.get("title") or "未命名論文"
        chunk_index = row.get("chunk_index")
        reference_no = len(citations) + 1

        label = f"[{reference_no}] {title}"
        if published_year:
            label = f"{label} ({published_year})"

        citations.append(
            {
                "reference_no": reference_no,
                "paper_source_id": row.get("paper_source_id"),
                "chunk_id": row.get("id"),
                "chunk_index": chunk_index,
                "title": title,
                "doi": row.get("doi"),
                "source_url": row.get("source_url"),
                "published_at": published_at,
                "distance": row.get("distance"),
                "excerpt": _clean_excerpt(row.get("chunk_text", "")),
                "label": label,
            }
        )

        if len(citations) >= limit:
            break

    return citations
