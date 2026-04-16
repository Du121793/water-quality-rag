from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAPERS_ROOT = PROJECT_ROOT / "papers"
OPENALEX_MAILTO = "openai@example.com"
USER_AGENT = "Mozilla/5.0 (compatible; CodexPaperCollector/1.0; +https://openai.com)"

EXISTING_WATER_QUALITY_PAPERS = [
    {
        "filename": "01_dissolved-oxygen-prediction-gru-nbeats.pdf",
        "title": "A dissolved oxygen prediction model based on GRU-N-Beats",
        "source_url": "https://www.frontiersin.org/journals/marine-science/articles/10.3389/fmars.2024.1365047/pdf",
    },
    {
        "filename": "02_hybrid-intelligence-predicting-dissolved-oxygen-aquaculture.pdf",
        "title": "A hybrid intelligence model for predicting dissolved oxygen in aquaculture water",
        "source_url": "https://www.frontiersin.org/journals/marine-science/articles/10.3389/fmars.2023.1126556/pdf",
    },
    {
        "filename": "03_forecasting-ocean-hypoxia-salmonid-fish-farms.pdf",
        "title": "Forecasting ocean hypoxia in salmonid fish farms",
        "source_url": "https://www.frontiersin.org/journals/aquaculture/articles/10.3389/faquc.2024.1365123/pdf",
    },
    {
        "filename": "04_longitudinal-dissolved-oxygen-patterns-atlantic-salmon-aquaculture.pdf",
        "title": "Longitudinal dissolved oxygen patterns in Atlantic salmon aquaculture sites in British Columbia, Canada",
        "source_url": "https://www.frontiersin.org/journals/marine-science/articles/10.3389/fmars.2023.1289375/pdf",
    },
    {
        "filename": "05_water-physicochemical-factors-oxidative-stress-physiology-fish-review.pdf",
        "title": "Water physicochemical factors and oxidative stress physiology in fish, a review",
        "source_url": "https://www.frontiersin.org/journals/environmental-science/articles/10.3389/fenvs.2023.1240813/pdf",
    },
    {
        "filename": "06_testing-hypoxia-tolerance-hypoxic-performance-fishes.pdf",
        "title": "Testing the hypoxia tolerance and hypoxic performance of fishes: A two-tier screening approach",
        "source_url": "https://www.frontiersin.org/journals/marine-science/articles/10.3389/fmars.2022.939239/pdf",
    },
    {
        "filename": "07_hydrogen-injection-reduces-ammonia-nitrogen-aquaculture-water.pdf",
        "title": "Hydrogen injection reduces ammonia nitrogen and changes microbial community composition in aquaculture water",
        "source_url": "https://www.frontiersin.org/journals/marine-science/articles/10.3389/fmars.2023.1111067/pdf",
    },
    {
        "filename": "08_physicochemical-factors-drive-bacterial-communities-aquaculture-environment.pdf",
        "title": "Physicochemical Factors Drive Bacterial Communities in an Aquaculture Environment",
        "source_url": "https://www.frontiersin.org/journals/environmental-science/articles/10.3389/fenvs.2021.709541/pdf",
    },
]

CURATED_CATEGORIES = [
    {
        "slug": "water-quality",
        "name": "Water Quality",
        "description": "水質、水質監測、溶氧、氨氮與污染風險。",
        "entries": [
            {"title": "Water Contamination by Heavy Metals and their Toxic Effect on Aquaculture and Human Health through Food Chain"},
            {"title": "Water quality monitoring in recirculating aquaculture systems"},
        ],
    },
    {
        "slug": "drugs-and-disease-control",
        "name": "Drugs and Disease Control",
        "description": "養殖魚塭魚類用藥、抗生素、抗藥性、殘留與疾病防治。",
        "entries": [
            {"title": "The Rising Tide of Antimicrobial Resistance in Aquaculture: Sources, Sinks and Solutions"},
            {"title": "Global trends in antimicrobial use in aquaculture"},
            {"title": "Aquaculture at the crossroads of global warming and antimicrobial resistance"},
            {"title": "Food safety impacts of antimicrobial use and their residues in aquaculture"},
            {"title": "Use of veterinary medicines, feed additives and probiotics in four major internationally traded aquaculture species farmed in Asia"},
            {"title": "Current Status of the Use of Antibiotics and the Antimicrobial Resistance in the Chilean Salmon Farms"},
            {"title": "Review of alternatives to antibiotic use in aquaculture"},
            {"title": "Maintenance of Fish Health in Aquaculture: Review of Epidemiological Approaches for Prevention and Control of Infectious Disease of Fish"},
            {"title": "Probiotics as Means of Diseases Control in Aquaculture, a Review of Current Knowledge and Future Perspectives"},
            {"title": "Emerging viral diseases of fish and shrimp"},
            {"title": "A Review of Antibiotics, Antibiotic Resistant Bacteria, and Resistance Genes in Aquaculture: Occurrence, Contamination, and Transmission"},
            {"title": "Antibiotic-Resistant Bacteria in Aquaculture and Climate Change: A Challenge for Health in the Mediterranean Area"},
        ],
    },
    {
        "slug": "water-quality-improvement",
        "name": "Water Quality Improvement",
        "description": "魚塭水質改善、養殖廢水治理、biofloc、益生菌與循環系統。",
        "entries": [
            {"title": "Biofloc Technology (BFT): A Review for Aquaculture Application and Animal Food Industry"},
            {"title": "Biofloc technology: an emerging avenue in aquatic animal healthcare and nutrition"},
            {"title": "Biofloc technology application in aquaculture to support sustainable development goals"},
            {"title": "Challenges of Sustainable and Commercial Aquaponics"},
            {"title": "Probiotics, lactic acid bacteria and bacilli: interesting supplementation for aquaculture"},
            {"title": "Fish Waste: From Problem to Valuable Resource"},
            {"title": "Aquaculture from inland fish cultivation to wastewater treatment: a review"},
            {"title": "Aquaponics: A Sustainable Path to Food Sovereignty and Enhanced Water Use Efficiency"},
            {"title": "Use of sugar kelp aquaculture in Long Island Sound and the Bronx River Estuary for nutrient extraction"},
            {"title": "World Aquaculture: Environmental Impacts and Troubleshooting Alternatives"},
        ],
    },
    {
        "slug": "sensors-and-data-analysis",
        "name": "Sensors and Data Analysis",
        "description": "魚塭感測器、IoT、數據分析、遙測與水質預測。",
        "entries": [
            {"title": "Precision Aquaculture"},
            {"title": "Water Quality Prediction for Smart Aquaculture Using Hybrid Deep Learning Models"},
            {"title": "A Water Quality Prediction Method Based on the Deep LSTM Network Considering Correlation in Smart Mariculture"},
            {"title": "Design and Deployment of Low-Cost Sensors for Monitoring the Water Quality and Fish Behavior in Aquaculture Tanks during the Feeding Process"},
            {"title": "Nonintrusive methods for biomass estimation in aquaculture with emphasis on fish: a review"},
            {"title": "Equipment and Intelligent Control System in Aquaponics: A Review"},
            {"title": "A Decision Support System for Urban Agriculture Using Digital Twin: A Case Study With Aquaponics"},
            {"title": "Nation-Scale Mapping of Coastal Aquaculture Ponds with Sentinel-1 SAR Data Using Google Earth Engine"},
            {"title": "Mapping Coastal Aquaculture Ponds of China Using Sentinel SAR Images in 2020 and Google Earth Engine"},
            {"title": "Review of cage and containment tank designs for offshore fish farming"},
        ],
    },
    {
        "slug": "fish-health-and-microbiota",
        "name": "Fish Health and Microbiota",
        "description": "魚類健康、免疫、腸道菌相、疾病風險與養殖支持型綜述。",
        "entries": [
            {"title": "Achieving sustainable aquaculture: Historical and current perspectives and future needs and challenges"},
            {"title": "Infectious Diseases Affect Marine Fisheries and Aquaculture Economics"},
            {"title": "Teleost microbiomes: the state of the art in their characterization, manipulation and importance in aquaculture and fisheries"},
            {"title": "The Gut Microbiota of Marine Fish"},
            {"title": "Progress in fish gastrointestinal microbiota research"},
            {"title": "Immunological Control of Fish Diseases"},
            {"title": "Fish intestinal microbiome: diversity and symbiosis unravelled by metagenomics"},
            {"title": "The role of the gut microbiome in sustainable teleost aquaculture"},
        ],
    },
]


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = normalized.replace("—", "-").replace("–", "-")
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", "", normalized)
    return normalized


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    normalized = normalized.strip("-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized[:90] or "paper"


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def resolve_openalex_record(title: str) -> dict:
    params = {
        "search": title,
        "filter": "is_oa:true,has_fulltext:true,type:article|review",
        "per-page": "8",
        "mailto": OPENALEX_MAILTO,
    }
    url = f"https://api.openalex.org/works?{urllib.parse.urlencode(params)}"
    payload = fetch_json(url)
    candidates = payload.get("results", [])
    if not candidates:
        raise RuntimeError(f"OpenAlex 查不到論文: {title}")

    target = normalize_text(title)
    best: dict | None = None
    best_score = float("-inf")

    for item in candidates:
        found_title = item.get("display_name", "")
        found_normalized = normalize_text(found_title)
        score = 0.0
        if found_normalized == target:
            score += 100
        if target in found_normalized or found_normalized in target:
            score += 20
        if (item.get("primary_location") or {}).get("pdf_url"):
            score += 10
        score += min(float(item.get("cited_by_count", 0)), 1000.0) / 1000.0
        if score > best_score:
            best = item
            best_score = score

    if not best:
        raise RuntimeError(f"OpenAlex 無法精準匹配論文: {title}")

    download_candidates: list[str] = []
    for location in best.get("locations", []):
        pdf_url = location.get("pdf_url")
        landing_url = location.get("landing_page_url")
        if pdf_url and pdf_url not in download_candidates:
            download_candidates.append(pdf_url)
        if landing_url and landing_url not in download_candidates:
            download_candidates.append(landing_url)

    return {
        "title": best.get("display_name") or title,
        "publication_year": best.get("publication_year"),
        "cited_by_count": best.get("cited_by_count", 0),
        "type": best.get("type"),
        "doi": best.get("doi"),
        "openalex_id": best.get("id"),
        "source_url": (best.get("primary_location") or {}).get("pdf_url") or "",
        "landing_page_url": (best.get("primary_location") or {}).get("landing_page_url"),
        "journal": ((best.get("primary_location") or {}).get("source") or {}).get("display_name"),
        "download_candidates": download_candidates,
        "institutions": sorted(
            {
                institution.get("display_name")
                for authorship in best.get("authorships", [])
                for institution in authorship.get("institutions", [])
                if institution.get("display_name")
            }
        )[:5],
    }


def download_pdf(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()

    if not data.startswith(b"%PDF"):
        raise RuntimeError(f"下載內容不是 PDF: {url}")

    destination.write_bytes(data)


def extract_pdf_links_from_html(base_url: str, html_text: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r'href=["\']([^"\']+)["\']', html_text, flags=re.IGNORECASE):
        href = unescape(match.group(1).strip())
        if not href:
            continue
        if ".pdf" not in href.lower() and "/pdf/" not in href.lower() and "fulltext" not in href.lower():
            continue
        resolved = urllib.parse.urljoin(base_url, href)
        if resolved not in candidates:
            candidates.append(resolved)
    return candidates


def fetch_html(url: str) -> tuple[str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        content_type = response.headers.get("Content-Type", "")
        data = response.read()
        if "html" not in content_type.lower() and not data.lstrip().startswith(b"<!DOCTYPE") and not data.lstrip().startswith(b"<html"):
            raise RuntimeError(f"不是 HTML 頁面: {url}")
        text = data.decode("utf-8", "ignore")
        return response.geturl(), text


def download_pdf_from_candidates(urls: list[str], destination: Path) -> str:
    errors: list[str] = []
    for url in urls:
        if not url:
            continue
        try:
            download_pdf(url, destination)
            return url
        except Exception as err:  # noqa: BLE001
            errors.append(f"{url} -> {err}")
            try:
                resolved_url, html_text = fetch_html(url)
                for nested_url in extract_pdf_links_from_html(resolved_url, html_text):
                    try:
                        download_pdf(nested_url, destination)
                        return nested_url
                    except Exception as nested_err:  # noqa: BLE001
                        errors.append(f"{nested_url} -> {nested_err}")
            except Exception as html_err:  # noqa: BLE001
                errors.append(f"{url} [html] -> {html_err}")

    joined = "\n".join(errors)
    raise RuntimeError(f"所有下載來源都失敗:\n{joined}")


def write_url_shortcut(destination: Path, url: str) -> None:
    content = f"[InternetShortcut]\nURL={url}\n"
    destination.write_text(content, encoding="utf-8")


def choose_link_target(metadata: dict) -> str:
    for key in ("landing_page_url", "doi", "source_url"):
        value = metadata.get(key)
        if value:
            return str(value)
    for value in metadata.get("download_candidates", []):
        if value:
            return str(value)
    raise RuntimeError(f"找不到可建立捷徑的網址: {metadata.get('title')}")


def write_category_index(category: dict, rows: list[dict]) -> None:
    pdf_count = sum(1 for row in rows if row.get("access_status") == "pdf")
    link_count = sum(1 for row in rows if row.get("access_status") == "link-only")
    summary = f"共 {len(rows)} 篇，其中 PDF {pdf_count} 篇。"
    if link_count:
        summary = f"共 {len(rows)} 篇，其中 PDF {pdf_count} 篇、link-only {link_count} 篇。"
    lines = [
        f"# {category['name']}",
        "",
        category["description"],
        "",
        summary,
        "",
        "## Papers",
        "",
    ]

    for index, row in enumerate(rows, start=1):
        lines.append(f"{index}. `{row['filename']}`")
        lines.append(f"   Title: {row['title']}")
        lines.append(f"   Source: {row['source_url']}")
        if row.get("landing_page_url"):
            lines.append(f"   Landing: {row['landing_page_url']}")
        if row.get("access_status"):
            lines.append(f"   Status: {row['access_status']}")
        if row.get("replacement_for"):
            lines.append(f"   Replacement For: {row['replacement_for']}")
        if row.get("doi"):
            lines.append(f"   DOI: {row['doi']}")
        if row.get("journal"):
            lines.append(f"   Journal: {row['journal']}")
        if row.get("publication_year"):
            lines.append(f"   Year: {row['publication_year']}")
        if row.get("cited_by_count") is not None:
            lines.append(f"   Citations (OpenAlex): {row['cited_by_count']}")
        if row.get("institutions"):
            lines.append(f"   Institutions: {', '.join(row['institutions'])}")
        lines.append("")

    index_path = PAPERS_ROOT / category["slug"] / "INDEX.md"
    index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_root_index(categories: list[dict], total_count: int) -> None:
    total_pdf = 0
    total_links = 0
    lines = [
        "# Aquaculture Paper Collection",
        "",
        "這份論文集以可公開取得的 peer-reviewed 論文為主，優先保留高引用數、綜述型(review)與常見學術出版平台的開放內容。",
        "",
        f"目前共整理 {total_count} 篇可直接使用的論文。",
        "",
    ]

    for category in categories:
        category_dir = PAPERS_ROOT / category["slug"]
        pdf_count = len(sorted(category_dir.glob("*.pdf")))
        link_count = len(sorted(category_dir.glob("*.url")))
        total_pdf += pdf_count
        total_links += link_count
        if link_count:
            lines.append(f"- `{category['slug']}`: 總計 {pdf_count + link_count} 篇，PDF {pdf_count} 篇，link-only {link_count} 篇")
        else:
            lines.append(f"- `{category['slug']}`: {pdf_count} 篇 PDF")
        lines.append(f"  說明: {category['description']}")

    lines.extend(
        [
            "",
            f"總計 PDF {total_pdf} 篇。",
            "",
            "建議後續用途：",
            "",
            "- 先從 `water-quality`、`drugs-and-disease-control`、`water-quality-improvement`、`sensors-and-data-analysis` 四類建立 RAG 主知識庫。",
            "- `fish-health-and-microbiota` 可作為魚病、免疫、微生態與管理建議的支援背景文獻。",
        ]
    )

    (PAPERS_ROOT / "INDEX.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_catalog(metadata: list[dict]) -> None:
    catalog_path = PAPERS_ROOT / "paper_catalog.json"
    catalog_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    PAPERS_ROOT.mkdir(parents=True, exist_ok=True)

    catalog_rows: list[dict] = []
    skipped: list[dict] = []

    water_quality_dir = PAPERS_ROOT / "water-quality"
    water_quality_dir.mkdir(exist_ok=True)

    existing_rows: list[dict] = []
    for item in EXISTING_WATER_QUALITY_PAPERS:
        file_path = water_quality_dir / item["filename"]
        if not file_path.exists():
            raise RuntimeError(f"既有論文不存在: {file_path}")
        row = {
            "category_slug": "water-quality",
            "filename": item["filename"],
            "title": item["title"],
            "source_url": item["source_url"],
            "local_path": str(file_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "access_status": "pdf",
        }
        existing_rows.append(row)
        catalog_rows.append(row)

    water_quality_downloads = []
    for index, entry in enumerate(CURATED_CATEGORIES[0]["entries"], start=len(existing_rows) + 1):
        try:
            metadata = resolve_openalex_record(entry["title"])
            pdf_filename = f"{index:02d}_{slugify(metadata['title'])}.pdf"
            pdf_destination = PAPERS_ROOT / "water-quality" / pdf_filename
            try:
                if not pdf_destination.exists():
                    downloaded_from = download_pdf_from_candidates(
                        metadata.get("download_candidates", []),
                        pdf_destination,
                    )
                    metadata["source_url"] = downloaded_from
                    time.sleep(0.5)
                elif not metadata.get("source_url") and metadata.get("download_candidates"):
                    metadata["source_url"] = metadata["download_candidates"][0]
                metadata.update(
                    {
                        "category_slug": "water-quality",
                        "filename": pdf_filename,
                        "local_path": str(pdf_destination.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                        "access_status": "pdf",
                    }
                )
            except Exception as err:  # noqa: BLE001
                shortcut_url = choose_link_target(metadata)
                shortcut_filename = f"{index:02d}_{slugify(metadata['title'])}.url"
                shortcut_destination = PAPERS_ROOT / "water-quality" / shortcut_filename
                write_url_shortcut(shortcut_destination, shortcut_url)
                metadata.update(
                    {
                        "category_slug": "water-quality",
                        "filename": shortcut_filename,
                        "local_path": str(shortcut_destination.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                        "access_status": "link-only",
                        "source_url": shortcut_url,
                    }
                )
                skipped.append(
                    {
                        "category_slug": "water-quality",
                        "title": entry["title"],
                        "error": str(err),
                    }
                )
            water_quality_downloads.append(metadata)
            catalog_rows.append(metadata)
        except Exception as err:  # noqa: BLE001
            skipped.append({"category_slug": "water-quality", "title": entry["title"], "error": str(err)})

    write_category_index(CURATED_CATEGORIES[0], existing_rows + water_quality_downloads)

    for category in CURATED_CATEGORIES[1:]:
        category_dir = PAPERS_ROOT / category["slug"]
        category_dir.mkdir(exist_ok=True)

        rows: list[dict] = []
        for index, entry in enumerate(category["entries"], start=1):
            try:
                metadata = resolve_openalex_record(entry["title"])
                pdf_filename = f"{index:02d}_{slugify(metadata['title'])}.pdf"
                pdf_destination = category_dir / pdf_filename
                try:
                    if not pdf_destination.exists():
                        downloaded_from = download_pdf_from_candidates(
                            metadata.get("download_candidates", []),
                            pdf_destination,
                        )
                        metadata["source_url"] = downloaded_from
                        time.sleep(0.5)
                    elif not metadata.get("source_url") and metadata.get("download_candidates"):
                        metadata["source_url"] = metadata["download_candidates"][0]
                    metadata.update(
                        {
                            "category_slug": category["slug"],
                            "filename": pdf_filename,
                            "local_path": str(pdf_destination.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                            "access_status": "pdf",
                        }
                    )
                except Exception as err:  # noqa: BLE001
                    shortcut_url = choose_link_target(metadata)
                    shortcut_filename = f"{index:02d}_{slugify(metadata['title'])}.url"
                    shortcut_destination = category_dir / shortcut_filename
                    write_url_shortcut(shortcut_destination, shortcut_url)
                    metadata.update(
                        {
                            "category_slug": category["slug"],
                            "filename": shortcut_filename,
                            "local_path": str(shortcut_destination.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                            "access_status": "link-only",
                            "source_url": shortcut_url,
                        }
                    )
                    skipped.append(
                        {
                            "category_slug": category["slug"],
                            "title": entry["title"],
                            "error": str(err),
                        }
                    )
                rows.append(metadata)
                catalog_rows.append(metadata)
            except Exception as err:  # noqa: BLE001
                skipped.append({"category_slug": category["slug"], "title": entry["title"], "error": str(err)})

        write_category_index(category, rows)

    write_root_index(CURATED_CATEGORIES, total_count=len(catalog_rows))
    write_catalog(catalog_rows)
    if skipped:
        skipped_path = PAPERS_ROOT / "skipped_papers.json"
        skipped_path.write_text(
            json.dumps(skipped, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"Collected {len(catalog_rows)} papers into {PAPERS_ROOT}")


if __name__ == "__main__":
    main()
