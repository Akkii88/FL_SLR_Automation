"""
PDF Discovery Service
======================
Identifies open-access full-text sources for papers.
Does NOT bypass paywalls or attempt authentication.

For each paper, determines:
A. OpenAlex cached full text available
B. Open-access PDF URL available
C. Landing-page only (no direct PDF)
D. No accessible full text found
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.paper import Paper
from app.models.pdf_file import PdfFile

logger = logging.getLogger(__name__)

# Source type constants
SOURCE_OPENALEX_CACHED = "openalex_cached"
SOURCE_OA_PDF = "oa_pdf"
SOURCE_LANDING_PAGE = "landing_page"
SOURCE_NONE = "none"


class PdfDiscoveryService:
    """
    Discovers open-access PDF URLs for papers.
    Only uses legally accessible sources.
    """

    def __init__(self, db: Session):
        self.db = db

    def discover_for_paper(self, paper_id: int) -> dict:
        """
        Discover PDF availability for a single paper.

        Returns:
            dict with availability info and any created PdfFile records
        """
        paper = self.db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper:
            raise ValueError(f"Paper {paper_id} not found")

        result = {
            "paper_id": paper_id,
            "availability": SOURCE_NONE,
            "pdf_url": None,
            "oa_status": paper.oa_status,
            "sources_checked": [],
        }

        # Check 1: Does the paper have a direct PDF URL from OpenAlex?
        if paper.pdf_url:
            result["sources_checked"].append("openalex_pdf_url")
            result["pdf_url"] = paper.pdf_url
            result["availability"] = SOURCE_OA_PDF

            # Check if we already have this URL recorded
            existing = self.db.query(PdfFile).filter(
                PdfFile.paper_id == paper_id,
                PdfFile.download_url == paper.pdf_url,
            ).first()

            if not existing:
                pdf_record = PdfFile(
                    paper_id=paper_id,
                    download_url=paper.pdf_url,
                    source=SOURCE_OA_PDF,
                    download_status="pending",
                    notes=f"OA URL from OpenAlex. OA status: {paper.oa_status}",
                )
                self.db.add(pdf_record)
                self.db.commit()
                result["pdf_file_id"] = pdf_record.id
            else:
                result["pdf_file_id"] = existing.id
                result["download_status"] = existing.download_status

            return result

        # Check 2: Does the paper have a best OA location?
        if paper.best_oa_location:
            result["sources_checked"].append("best_oa_location")
            # This might be a landing page or PDF
            url = paper.best_oa_location
            result["pdf_url"] = url
            result["availability"] = SOURCE_LANDING_PAGE

            existing = self.db.query(PdfFile).filter(
                PdfFile.paper_id == paper_id,
                PdfFile.download_url == url,
            ).first()

            if not existing:
                pdf_record = PdfFile(
                    paper_id=paper_id,
                    download_url=url,
                    source=SOURCE_LANDING_PAGE,
                    download_status="pending",
                    notes=f"Best OA location from OpenAlex. May be landing page.",
                )
                self.db.add(pdf_record)
                self.db.commit()
                result["pdf_file_id"] = pdf_record.id
            else:
                result["pdf_file_id"] = existing.id
                result["download_status"] = existing.download_status

            return result

        # Check 3: Does the paper have an OA URL?
        if paper.oa_url:
            result["sources_checked"].append("oa_url")
            result["pdf_url"] = paper.oa_url
            result["availability"] = SOURCE_LANDING_PAGE

            existing = self.db.query(PdfFile).filter(
                PdfFile.paper_id == paper_id,
                PdfFile.download_url == paper.oa_url,
            ).first()

            if not existing:
                pdf_record = PdfFile(
                    paper_id=paper_id,
                    download_url=paper.oa_url,
                    source=SOURCE_LANDING_PAGE,
                    download_status="pending",
                    notes="OA landing page URL.",
                )
                self.db.add(pdf_record)
                self.db.commit()
                result["pdf_file_id"] = pdf_record.id
            else:
                result["pdf_file_id"] = existing.id
                result["download_status"] = existing.download_status

            return result

        # Check 4: DOI-based lookup (Unpaywall-style, but we don't have API key)
        # We just note that DOI exists for manual lookup
        if paper.doi:
            result["sources_checked"].append("doi_lookup")
            result["doi"] = paper.doi
            result["availability"] = SOURCE_NONE
            result["note"] = (
                "No automated OA URL found. Use DOI to check manually: "
                f"https://doi.org/{paper.doi}"
            )
            return result

        # No sources found
        result["sources_checked"].append("all")
        result["availability"] = SOURCE_NONE
        result["note"] = "No OA URL, DOI, or landing page found."
        return result

    def discover_all(self, status_filter: Optional[str] = None) -> dict:
        """
        Run PDF discovery for all papers (or filtered subset).

        Args:
            status_filter: Optional screening status to filter by
                          (e.g., 'include' to only discover for included papers)

        Returns:
            dict with summary statistics
        """
        query = self.db.query(Paper)

        if status_filter:
            query = query.filter(Paper.screening_status == status_filter)

        papers = query.all()

        results = {
            "total_papers": len(papers),
            "with_pdf_url": 0,
            "with_landing_page": 0,
            "no_full_text": 0,
            "already_downloaded": 0,
            "details": [],
        }

        for paper in papers:
            # Check if already downloaded
            existing_downloaded = self.db.query(PdfFile).filter(
                PdfFile.paper_id == paper.id,
                PdfFile.download_status == "downloaded",
            ).first()

            if existing_downloaded:
                results["already_downloaded"] += 1
                continue

            result = self.discover_for_paper(paper.id)

            if result["availability"] == SOURCE_OA_PDF:
                results["with_pdf_url"] += 1
            elif result["availability"] == SOURCE_LANDING_PAGE:
                results["with_landing_page"] += 1
            else:
                results["no_full_text"] += 1

            results["details"].append(result)

        return results

    def get_pdf_status(self, paper_id: int) -> dict:
        """Get the PDF download status for a paper."""
        paper = self.db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper:
            raise ValueError(f"Paper {paper_id} not found")

        pdf_files = self.db.query(PdfFile).filter(
            PdfFile.paper_id == paper_id
        ).order_by(PdfFile.created_at).all()

        return {
            "paper_id": paper_id,
            "has_oa_url": bool(paper.pdf_url or paper.oa_url or paper.best_oa_location),
            "oa_status": paper.oa_status,
            "pdf_url": paper.pdf_url,
            "oa_url": paper.oa_url,
            "best_oa_location": paper.best_oa_location,
            "pdf_files": [
                {
                    "id": pf.id,
                    "download_url": pf.download_url,
                    "source": pf.source,
                    "file_path": pf.file_path,
                    "file_size": pf.file_size,
                    "download_status": pf.download_status,
                    "download_date": pf.download_date.isoformat() if pf.download_date else None,
                    "notes": pf.notes,
                }
                for pf in pdf_files
            ],
        }
