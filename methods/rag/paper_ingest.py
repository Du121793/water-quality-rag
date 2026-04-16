from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

from pypdf import PdfReader


def parse_paper_index(index_path: str | Path) -> dict[str, dict]:
    """解析 papers 目錄下的 INDEX.md，取出論文基本 metadata。"""

    content = Path(index_path).read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=\d+\.\s+`)", content)
    metadata_map: dict[str, dict] = {}

    for block in blocks:
        filename_match = re.search(r"`(?P<filename>[^`]+)`", block)
        title_match = re.search(r"Title:\s*(?P<title>.+)", block)
        source_match = re.search(r"Source:\s*(?P<source>\S+)", block)
        doi_match = re.search(r"DOI:\s*(?P<doi>\S+)", block)
        journal_match = re.search(r"Journal:\s*(?P<journal>.+)", block)
        year_match = re.search(r"Year:\s*(?P<year>\d{4})", block)

        if not (filename_match and title_match and source_match):
            continue

        published_at = None
        if year_match:
            published_at = f"{year_match.group('year')}-01-01"

        metadata_map[filename_match.group("filename").strip()] = {
            "title": " ".join(title_match.group("title").split()),
            "source_url": source_match.group("source").strip(),
            "doi": doi_match.group("doi").strip() if doi_match else None,
            "journal_name": " ".join(journal_match.group("journal").split()) if journal_match else None,
            "published_at": published_at,
        }

    return metadata_map


def extract_pdf_text(pdf_path: str | Path) -> str:
    """從 PDF 擷取純文字，作為 chunk 與 embedding 的基礎內容。"""

    reader = PdfReader(str(pdf_path))
    return _extract_reader_text(reader)


def extract_pdf_text_from_bytes(pdf_bytes: bytes) -> str:
    """從 PDF 位元組擷取純文字，供 API 上傳流程使用。"""

    reader = PdfReader(io.BytesIO(pdf_bytes))
    return _extract_reader_text(reader)


def _extract_reader_text(reader: PdfReader) -> str:
    """從 PdfReader 統一擷取純文字。"""

    pages: list[str] = []

    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            pages.append(text)

    joined = "\n".join(pages)
    joined = joined.replace("\x00", " ")
    joined = re.sub(r"[ \t]+", " ", joined)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip()


def normalize_title(title: str) -> str:
    """將標題標準化，供重複檢查使用。"""

    normalized = (title or "").strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff ]+", "", normalized)
    return normalized.strip()


def normalize_doi(doi: str | None) -> str | None:
    """將 DOI 標準化為小寫且移除常見前綴。"""

    if doi is None:
        return None
    normalized = doi.strip().lower()
    if not normalized:
        return None
    normalized = normalized.removeprefix("https://doi.org/")
    normalized = normalized.removeprefix("http://doi.org/")
    normalized = normalized.removeprefix("doi:")
    return normalized.strip() or None


def sha256_hex(data: bytes | str) -> str:
    """計算 SHA-256 十六進位雜湊。"""

    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def infer_tags_from_text(text: str, title: str) -> tuple[list[str], list[str]]:
    """從標題與前段內容推測魚種與水質主題標籤。"""

    normalized = f"{title}\n{text[:4000]}".lower()

    topic_tags: list[str] = []
    species_tags: list[str] = []

    topic_rules = {
        "dissolved_oxygen": ["dissolved oxygen", "oxygen", "hypoxia", "do "],
        "ph": [" ph", "water ph", "acid", "alkaline"],
        "temperature": ["temperature", "thermal"],
        "ammonia": ["ammonia", "nitrogen"],
        "microbiology": ["bacterial", "microbial", "microbiome"],
        "water_quality": ["water quality", "aquaculture water"],
    }
    species_rules = {
        "salmon": ["salmon", "salmonid"],
        "fish": ["fish", "fishes"],
    }

    for tag, keywords in topic_rules.items():
        if any(keyword in normalized for keyword in keywords):
            topic_tags.append(tag)

    for tag, keywords in species_rules.items():
        if any(keyword in normalized for keyword in keywords):
            species_tags.append(tag)

    return sorted(set(species_tags)), sorted(set(topic_tags))


def chunk_text(text: str, max_chars: int = 1800, overlap_chars: int = 250) -> list[str]:
    """依段落切分文字，產出適合 RAG 與 embedding 的 chunk。"""

    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(paragraph) <= max_chars:
            current = paragraph
            continue

        start = 0
        while start < len(paragraph):
            end = min(start + max_chars, len(paragraph))
            chunks.append(paragraph[start:end].strip())
            if end >= len(paragraph):
                break
            start = max(end - overlap_chars, start + 1)
        current = ""

    if current:
        chunks.append(current)

    return [chunk for chunk in chunks if chunk]
