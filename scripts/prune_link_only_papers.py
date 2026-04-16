from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.collect_curated_aquaculture_papers import (  # noqa: E402
    CURATED_CATEGORIES,
    PAPERS_ROOT,
    write_category_index,
    write_root_index,
)


CATALOG_PATH = PAPERS_ROOT / "paper_catalog.json"
SKIPPED_PATH = PAPERS_ROOT / "skipped_papers.json"
RECOVERY_LOG_PATH = PAPERS_ROOT / "recovery_log.json"


def load_catalog() -> list[dict]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def save_catalog(rows: list[dict]) -> None:
    CATALOG_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def rebuild_indexes(catalog_rows: list[dict]) -> None:
    category_map = {item["slug"]: item for item in CURATED_CATEGORIES}
    for slug, category in category_map.items():
        rows = [row for row in catalog_rows if row.get("category_slug") == slug]
        rows.sort(key=lambda item: item["filename"])
        write_category_index(category, rows)
    write_root_index(CURATED_CATEGORIES, total_count=len(catalog_rows))


def main() -> None:
    catalog_rows = load_catalog()
    removed_rows = [row for row in catalog_rows if row.get("access_status") == "link-only"]
    kept_rows = [row for row in catalog_rows if row.get("access_status") != "link-only"]

    for row in removed_rows:
        local_path = row.get("local_path")
        if not local_path:
            continue
        file_path = PROJECT_ROOT / local_path
        if file_path.exists() and file_path.suffix.lower() == ".url":
            file_path.unlink()

    save_catalog(kept_rows)
    rebuild_indexes(kept_rows)

    if SKIPPED_PATH.exists():
        SKIPPED_PATH.unlink()
    if RECOVERY_LOG_PATH.exists():
        RECOVERY_LOG_PATH.unlink()

    print(f"Removed {len(removed_rows)} link-only entries. Remaining papers: {len(kept_rows)}")


if __name__ == "__main__":
    main()
