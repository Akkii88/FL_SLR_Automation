"""
Paper Parser Service
=====================
Transforms OpenAlex work records into our internal Paper model format.
Handles abstract reconstruction from inverted index format.
"""

import json
import re
import logging
from datetime import datetime
from typing import Optional

from app.models.paper import Paper

logger = logging.getLogger(__name__)


def reconstruct_abstract(inverted_index: Optional[dict]) -> Optional[str]:
    """
    Reconstruct an abstract string from OpenAlex's inverted index format.

    OpenAlex stores abstracts as a word-position mapping:
    {"the": [0, 15], "federated": [1], "learning": [2], ...}

    We reconstruct by placing each word at its positions and joining.
    """
    if not inverted_index or not isinstance(inverted_index, dict):
        return None

    try:
        # Build position -> word mapping
        word_positions = []
        for word, positions in inverted_index.items():
            if isinstance(positions, list):
                for pos in positions:
                    word_positions.append((pos, word))

        if not word_positions:
            return None

        # Sort by position and join
        word_positions.sort(key=lambda x: x[0])
        abstract = " ".join(word for _, word in word_positions)

        # Clean up extra whitespace
        abstract = re.sub(r"\s+", " ", abstract).strip()

        return abstract if abstract else None

    except Exception as e:
        logger.warning(f"Failed to reconstruct abstract: {e}")
        return None


def normalize_title(title: str) -> str:
    """
    Normalize a title for deduplication:
    - Lowercase
    - Remove punctuation
    - Collapse whitespace
    - Strip
    """
    if not title:
        return ""
    normalized = title.lower().strip()
    normalized = re.sub(r"[^\w\s]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def normalize_doi(doi: Optional[str]) -> Optional[str]:
    """
    Normalize a DOI:
    - Strip whitespace
    - Remove URL prefix (https://doi.org/)
    - Lowercase
    """
    if not doi:
        return None
    doi = doi.strip().lower()
    # Remove common URL prefixes
    for prefix in ["https://doi.org/", "http://doi.org/", "doi.org/"]:
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi if doi else None


def parse_openalex_work(work: dict) -> Optional[Paper]:
    """
    Parse a single OpenAlex work record into a Paper model.

    Args:
        work: dict from OpenAlex API response

    Returns:
        Paper instance (not yet committed to DB)
    """
    try:
        # --- Identifiers ---
        openalex_id = work.get("id", "")
        if openalex_id.startswith("http"):
            openalex_id = openalex_id.rstrip("/").split("/")[-1]

        doi = normalize_doi(work.get("doi"))

        # --- Title ---
        title = work.get("title", "") or work.get("display_name", "")
        if not title:
            logger.warning(f"Skipping work {openalex_id}: no title")
            return None

        normalized_title = normalize_title(title)

        # --- Abstract ---
        abstract = None
        inverted_index = work.get("abstract_inverted_index")
        if inverted_index:
            abstract = reconstruct_abstract(inverted_index)

        # --- Publication Date / Year ---
        pub_date = work.get("publication_date") or work.get("publication_year")
        pub_year = work.get("publication_year")

        # --- Authors ---
        authors_list = []
        authorship = work.get("authorships", [])
        for auth in authorship:
            author_info = auth.get("author", {})
            name = author_info.get("display_name", "")
            if name:
                authors_list.append(name)

        authors_json = json.dumps(authors_list) if authors_list else None

        # --- Institutions ---
        institutions_list = []
        for auth in authorship:
            for inst in auth.get("institutions", []):
                inst_name = inst.get("display_name", "")
                if inst_name and inst_name not in institutions_list:
                    institutions_list.append(inst_name)

        institutions_json = json.dumps(institutions_list) if institutions_list else None

        # --- Source / Venue ---
        source = None
        source_type = work.get("type") or work.get("type_crossref")
        host_venue = work.get("host_venue") or work.get("primary_location") or {}
        if isinstance(host_venue, dict):
            source = host_venue.get("display_name") or (host_venue.get("source", {}) or {}).get("display_name")

        # --- Language ---
        language = work.get("language")

        # --- Citation Count ---
        citation_count = work.get("cited_by_count")

        # --- Open Access ---
        oa_info = work.get("open_access", {})
        is_oa = oa_info.get("is_oa", False)
        oa_status = oa_info.get("oa_status")
        oa_url = oa_info.get("oa_url")

        # --- Best OA Location ---
        best_oa_location = None
        pdf_url = None
        locations = work.get("locations", []) or []
        for loc in locations:
            if isinstance(loc, dict):
                loc_oa_url = loc.get("landing_page_url")
                loc_pdf_url = loc.get("pdf_url")
                is_version_ok = loc.get("version") in ("publishedVersion", "acceptedVersion", None)

                if is_version_ok and loc_pdf_url:
                    if not pdf_url:
                        pdf_url = loc_pdf_url
                    if not best_oa_location:
                        best_oa_location = loc_oa_url or loc_pdf_url

                if not best_oa_location and loc_oa_url:
                    best_oa_location = loc_oa_url

        # --- Retraction ---
        is_retracted = work.get("is_retracted", False)

        return Paper(
            openalex_id=openalex_id,
            doi=doi,
            title=title,
            normalized_title=normalized_title,
            abstract=abstract,
            publication_date=pub_date if isinstance(pub_date, str) else None,
            publication_year=pub_year,
            authors=authors_json,
            institutions=institutions_json,
            source=source,
            source_type=source_type,
            language=language,
            citation_count=citation_count,
            is_open_access=is_oa,
            oa_status=oa_status,
            oa_url=oa_url,
            best_oa_location=best_oa_location,
            pdf_url=pdf_url,
            is_retracted=is_retracted,
        )

    except Exception as e:
        logger.error(f"Error parsing OpenAlex work: {e}", exc_info=True)
        return None
