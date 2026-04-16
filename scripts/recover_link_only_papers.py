from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Response, sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.collect_curated_aquaculture_papers import (
    CURATED_CATEGORIES,
    PAPERS_ROOT,
    resolve_openalex_record,
    write_category_index,
    write_root_index,
)


CATALOG_PATH = PAPERS_ROOT / "paper_catalog.json"
SKIPPED_PATH = PAPERS_ROOT / "skipped_papers.json"
RECOVERY_LOG_PATH = PAPERS_ROOT / "recovery_log.json"
REQUEST_TIMEOUT_MS = 45000
PAGE_TIMEOUT_MS = 45000
PREFERRED_HOST_MARKERS = [
    "pmc.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov/pmc",
    "hdl.handle.net",
    "uu.diva-portal.org",
    "api.nva.unit.no",
    "nva.sikt.no",
]


def load_catalog() -> list[dict]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def save_catalog(rows: list[dict]) -> None:
    CATALOG_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def response_is_pdf(response: Response) -> bool:
    content_type = (response.headers.get("content-type") or "").lower()
    if "application/pdf" in content_type:
        return True
    try:
        return response.body().startswith(b"%PDF")
    except Exception:  # noqa: BLE001
        return False


def save_pdf_response(response: Response, target_path: Path) -> bool:
    body = response.body()
    if not body.startswith(b"%PDF"):
        return False
    target_path.write_bytes(body)
    return True


def try_request_pdf(context: BrowserContext, url: str, target_path: Path) -> str | None:
    if not url:
        return None
    response = context.request.get(url, timeout=REQUEST_TIMEOUT_MS)
    if not response.ok:
        return None
    if not response_is_pdf(response):
        return None
    if save_pdf_response(response, target_path):
        return url
    return None


def try_pmc_page(page: Page, target_path: Path) -> str | None:
    current_url = page.url
    if "pmc.ncbi.nlm.nih.gov/articles/" not in current_url and not page.title().endswith(" - PMC"):
        return None

    pdf_links = page.eval_on_selector_all(
        "a",
        """
        els => els
          .map(a => a.href || '')
          .filter(href => href.includes('/pdf/'))
        """,
    )
    if not pdf_links:
        return None

    pdf_url = pdf_links[0]
    page.goto(pdf_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    page.wait_for_timeout(3000)
    page.goto(current_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)

    downloaded = try_request_pdf(page.context, pdf_url, target_path)
    return downloaded


def try_nva_page(page: Page, target_path: Path) -> str | None:
    html = page.content()
    publication_match = re.search(
        r'"id"\s*:\s*"(https://api\.nva\.unit\.no/publication/[^"]+)"',
        html,
    )
    artifact_match = re.search(
        r'"associatedArtifacts"\s*:\s*\[\s*\{\s*"identifier"\s*:\s*"([^"]+)"',
        html,
        flags=re.DOTALL,
    )
    if not publication_match or not artifact_match:
        return None

    publication_url = publication_match.group(1)
    artifact_id = artifact_match.group(1)
    filelink_url = f"{publication_url}/filelink/{artifact_id}"

    response = page.context.request.get(filelink_url, timeout=REQUEST_TIMEOUT_MS)
    if not response.ok:
        return None

    payload = response.json()
    presigned_url = payload.get("id") or payload.get("alias")
    if not presigned_url:
        return None

    downloaded = try_request_pdf(page.context, presigned_url, target_path)
    return downloaded or payload.get("alias") or presigned_url


def try_generic_page(page: Page, target_path: Path) -> str | None:
    pdf_links = page.eval_on_selector_all(
        "a",
        """
        els => els
          .map(a => ({ href: a.href || '', text: (a.textContent || '').trim() }))
          .filter(x => /\\.pdf($|\\?)/i.test(x.href) || /\\/pdf\\//i.test(x.href) || /pdf|full\\s*text|download/i.test(x.text))
          .map(x => x.href)
        """,
    )

    seen: set[str] = set()
    for link in pdf_links:
        if not link or link in seen:
            continue
        seen.add(link)
        downloaded = try_request_pdf(page.context, link, target_path)
        if downloaded:
            return downloaded
    return None


def recover_entry(context: BrowserContext, row: dict) -> tuple[bool, str]:
    target_dir = PROJECT_ROOT / Path(row["local_path"]).parent
    pdf_path = target_dir / (Path(row["filename"]).stem + ".pdf")

    metadata = resolve_openalex_record(row["title"])
    candidate_urls: list[str] = []
    for url in [row.get("source_url"), row.get("landing_page_url"), row.get("doi"), *metadata.get("download_candidates", [])]:
        if url and url not in candidate_urls:
            candidate_urls.append(str(url))

    candidate_urls.sort(
        key=lambda url: (
            0
            if any(marker in url for marker in PREFERRED_HOST_MARKERS)
            else 1,
            len(url),
        )
    )

    for url in candidate_urls:
        downloaded = try_request_pdf(context, url, pdf_path)
        if downloaded:
            row["source_url"] = downloaded
            break

        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            page.wait_for_timeout(1500)
            downloaded = try_pmc_page(page, pdf_path)
            if not downloaded:
                downloaded = try_nva_page(page, pdf_path)
            if not downloaded:
                downloaded = try_generic_page(page, pdf_path)
            if downloaded:
                row["source_url"] = downloaded
                break
        except Exception:  # noqa: BLE001
            pass
        finally:
            page.close()
    else:
        return False, "no_recoverable_pdf_found"

    old_path = PROJECT_ROOT / row["local_path"]
    if old_path.exists() and old_path.suffix.lower() == ".url":
        old_path.unlink()

    row["filename"] = pdf_path.name
    row["local_path"] = str(pdf_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    row["access_status"] = "pdf"
    return True, row["source_url"]


def rebuild_indexes(catalog_rows: list[dict]) -> None:
    for category in CURATED_CATEGORIES:
        rows = [row for row in catalog_rows if row.get("category_slug") == category["slug"]]
        rows.sort(key=lambda item: item["filename"])
        write_category_index(category, rows)

    write_root_index(CURATED_CATEGORIES, total_count=len(catalog_rows))


def main() -> None:
    catalog_rows = load_catalog()
    skipped_rows = json.loads(SKIPPED_PATH.read_text(encoding="utf-8")) if SKIPPED_PATH.exists() else []

    recovery_log: list[dict] = []
    failures_by_title = {item["title"]: item for item in skipped_rows if item.get("title")}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()

        for row in catalog_rows:
            if row.get("access_status") != "link-only":
                continue

            success, detail = recover_entry(context, row)
            recovery_log.append(
                {
                    "title": row["title"],
                    "category_slug": row["category_slug"],
                    "success": success,
                    "detail": detail,
                }
            )
            if success and row["title"] in failures_by_title:
                failures_by_title.pop(row["title"], None)
            save_catalog(catalog_rows)
            RECOVERY_LOG_PATH.write_text(
                json.dumps(recovery_log, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        browser.close()

    remaining_failures = list(failures_by_title.values())
    save_catalog(catalog_rows)
    rebuild_indexes(catalog_rows)
    RECOVERY_LOG_PATH.write_text(
        json.dumps(recovery_log, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    SKIPPED_PATH.write_text(
        json.dumps(remaining_failures, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    recovered_count = sum(1 for item in recovery_log if item["success"])
    print(f"Recovered {recovered_count} link-only papers.")


if __name__ == "__main__":
    main()
