from __future__ import annotations

import json
import sys
from pathlib import Path

import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.collect_curated_aquaculture_papers import (  # noqa: E402
    CURATED_CATEGORIES,
    PAPERS_ROOT,
    resolve_openalex_record,
    slugify,
    write_category_index,
    write_root_index,
)


CATALOG_PATH = PAPERS_ROOT / "paper_catalog.json"
USER_AGENT = "Mozilla/5.0 (compatible; CodexPaperCollector/1.0; +https://openai.com)"

REPLACEMENTS = [
    {
        "category_slug": "drugs-and-disease-control",
        "replacement_for": "Use of veterinary medicines, feed additives and probiotics in four major internationally traded aquaculture species farmed in Asia",
        "title": "A mini-review on co-supplementation of probiotics and medicinal herbs: Application in aquaculture",
        "pdf_url": "https://www.frontiersin.org/articles/10.3389/fvets.2022.869564/pdf",
    },
    {
        "category_slug": "water-quality-improvement",
        "replacement_for": "Biofloc Technology (BFT): A Review for Aquaculture Application and Animal Food Industry",
        "title": "A Solution for Sustainable Utilization of Aquaculture Waste: A Comprehensive Review of Biofloc Technology and Aquamimicry",
        "pdf_url": "https://www.frontiersin.org/articles/10.3389/fnut.2021.791738/pdf",
    },
    {
        "category_slug": "water-quality-improvement",
        "replacement_for": "Biofloc technology application in aquaculture to support sustainable development goals",
        "title": "Biofloc Microbiome With Bioremediation and Health Benefits",
        "pdf_url": "https://www.frontiersin.org/articles/10.3389/fmicb.2021.741164/pdf",
    },
    {
        "category_slug": "water-quality-improvement",
        "replacement_for": "Probiotics, lactic acid bacteria and bacilli: interesting supplementation for aquaculture",
        "title": "Recent studies on probiotics as beneficial mediator in aquaculture: a review",
        "pdf_url": "https://basicandappliedzoology.springeropen.com/track/pdf/10.1186/s41936-020-00190-y",
    },
    {
        "category_slug": "water-quality-improvement",
        "replacement_for": "Aquaponics: A Sustainable Path to Food Sovereignty and Enhanced Water Use Efficiency",
        "title": "Aquaponics for Improved Food Security in Africa: A Review",
        "pdf_url": "https://www.frontiersin.org/articles/10.3389/fsufs.2021.705549/pdf",
    },
    {
        "category_slug": "water-quality-improvement",
        "replacement_for": "World Aquaculture: Environmental Impacts and Troubleshooting Alternatives",
        "title": "The complex microbiome in aquaponics: significance of the bacterial ecosystem",
        "pdf_url": "https://annalsmicrobiology.biomedcentral.com/track/pdf/10.1186/s13213-020-01613-5",
    },
    {
        "category_slug": "water-quality-improvement",
        "replacement_for": "Use of sugar kelp aquaculture in Long Island Sound and the Bronx River Estuary for nutrient extraction",
        "title": "Can Seaweed Farming Play a Role in Climate Change Mitigation and Adaptation?",
        "pdf_url": "https://www.frontiersin.org/articles/10.3389/fmars.2017.00100/pdf",
    },
    {
        "category_slug": "sensors-and-data-analysis",
        "replacement_for": "A Water Quality Prediction Method Based on the Deep LSTM Network Considering Correlation in Smart Mariculture",
        "title": "New perspectives on metagenomic analysis for pathogen monitoring in sustainable freshwater aquaculture production: a systematic review",
        "pdf_url": "https://public-pages-files-2025.frontiersin.org/journals/freshwater-science/articles/10.3389/ffwsc.2024.1459233/pdf",
    },
    {
        "category_slug": "fish-health-and-microbiota",
        "replacement_for": "Fish intestinal microbiome: diversity and symbiosis unravelled by metagenomics",
        "title": "Fish gut microbiome and its application in aquaculture and biological conservation",
        "pdf_url": "https://www.frontiersin.org/journals/microbiology/articles/10.3389/fmicb.2024.1521048/pdf",
    },
    {
        "category_slug": "fish-health-and-microbiota",
        "replacement_for": "Progress in fish gastrointestinal microbiota research",
        "title": "Gut Immune System and the Implications of Oral-Administered Immunoprophylaxis in Finfish Aquaculture",
        "pdf_url": "https://www.frontiersin.org/articles/10.3389/fimmu.2021.773193/pdf",
    },
    {
        "category_slug": "fish-health-and-microbiota",
        "replacement_for": "Immunological Control of Fish Diseases",
        "title": "Innate and adaptive immunity in teleost fish: a review",
        "pdf_url": "https://www.agriculturejournals.cz/publicFiles/50222.pdf",
    },
    {
        "category_slug": "fish-health-and-microbiota",
        "replacement_for": "Infectious Diseases Affect Marine Fisheries and Aquaculture Economics",
        "title": "Application of Outer Membrane Protein-Based Vaccines Against Major Bacterial Fish Pathogens in India",
        "pdf_url": "https://www.frontiersin.org/articles/10.3389/fimmu.2020.01362/pdf",
    },
]


def load_catalog() -> list[dict]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def save_catalog(rows: list[dict]) -> None:
    CATALOG_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def download_pdf(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    if not data.startswith(b"%PDF"):
        raise RuntimeError(f"下載內容不是 PDF: {url}")
    destination.write_bytes(data)


def next_index_for_category(category_dir: Path) -> int:
    used_numbers: set[int] = set()
    for path in category_dir.glob("*.*"):
        prefix = path.name.split("_", 1)[0]
        if prefix.isdigit():
            used_numbers.add(int(prefix))
    index = 1
    while index in used_numbers:
        index += 1
    return index


def category_definition_map() -> dict[str, dict]:
    return {item["slug"]: item for item in CURATED_CATEGORIES}


def rebuild_indexes(catalog_rows: list[dict]) -> None:
    category_map = category_definition_map()
    for slug, category in category_map.items():
        rows = [row for row in catalog_rows if row.get("category_slug") == slug]
        rows.sort(key=lambda item: item["filename"])
        write_category_index(category, rows)
    write_root_index(CURATED_CATEGORIES, total_count=len(catalog_rows))


def main() -> None:
    catalog_rows = load_catalog()
    existing_pairs = {
        (row.get("category_slug"), row.get("title"), row.get("replacement_for"))
        for row in catalog_rows
    }

    added = 0
    for item in REPLACEMENTS:
        identity = (item["category_slug"], item["title"], item["replacement_for"])
        if identity in existing_pairs:
            continue

        metadata = resolve_openalex_record(item["title"])
        category_dir = PAPERS_ROOT / item["category_slug"]
        file_index = next_index_for_category(category_dir)
        filename = f"{file_index:02d}_{slugify(metadata['title'])}.pdf"
        destination = category_dir / filename
        download_pdf(item["pdf_url"], destination)

        row = {
            **metadata,
            "category_slug": item["category_slug"],
            "filename": filename,
            "local_path": str(destination.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "source_url": item["pdf_url"],
            "access_status": "pdf",
            "replacement_for": item["replacement_for"],
        }
        catalog_rows.append(row)
        existing_pairs.add(identity)
        added += 1

    save_catalog(catalog_rows)
    rebuild_indexes(catalog_rows)
    print(f"Added {added} replacement papers.")


if __name__ == "__main__":
    main()
