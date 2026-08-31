"""
PDF Download Service
=====================
Downloads PDFs from open-access URLs.
Validates PDFs using file signatures.
Prevents duplicate downloads.

IMPORTANT:
- Only downloads openly accessible/legal full text
- Does NOT bypass paywalls
- Does NOT attempt authentication bypass
- Does NOT scrape restricted content
"""

import os
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.pdf_file import PdfFile

logger = logging.getLogger(__name__)

# PDF file signature (magic bytes): %PDF-
PDF_MAGIC_BYTES = b"%PDF-"

# Download settings
DOWNLOAD_TIMEOUT = 60.0  # seconds
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB limit
DOWNLOAD_CHUNK_SIZE = 8192  # 8 KB chunks


def get_pdf_storage_path(paper_id: int, filename: str) -> Path:
    """
    Get the storage path for a PDF file.
    Organizes files by paper ID to avoid filename collisions.
    """
    base_dir = settings.project_root / "data" / "pdfs"
    # Use paper ID as subdirectory for organization
    paper_dir = base_dir / str(paper_id)
    paper_dir.mkdir(parents=True, exist_ok=True)
    return paper_dir / filename


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def validate_pdf(file_path: Path) -> bool:
    """
    Validate that a file is a real PDF by checking its magic bytes.
    Returns True if the file starts with %PDF-.
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(5)
            return header == PDF_MAGIC_BYTES
    except Exception:
        return False


def is_duplicate_download(db: Session, paper_id: int, url: str) -> Optional[PdfFile]:
    """
    Check if a PDF from this URL has already been downloaded for this paper.
    Prevents redundant downloads.
    """
    existing = db.query(PdfFile).filter(
        PdfFile.paper_id == paper_id,
        PdfFile.download_url == url,
        PdfFile.download_status == "downloaded",
    ).first()
    return existing


class PdfDownloadService:
    """
    Downloads and validates PDF files.
    """

    def __init__(self, db: Session):
        self.db = db

    def download_pdf(self, pdf_file_id: int) -> dict:
        """
        Download a PDF file by its PdfFile record ID.

        Args:
            pdf_file_id: The ID of the PdfFile record to download

        Returns:
            dict with download result
        """
        pdf_record = self.db.query(PdfFile).filter(PdfFile.id == pdf_file_id).first()
        if not pdf_record:
            raise ValueError(f"PdfFile record {pdf_file_id} not found")

        if not pdf_record.download_url:
            raise ValueError("No download URL available for this PDF record")

        return self._download(
            pdf_record.paper_id,
            pdf_record.download_url,
            pdf_record.source or "unknown",
            pdf_record,
        )

    def download_for_paper(self, paper_id: int, url: str, source: str = "manual") -> dict:
        """
        Download a PDF for a paper from a specific URL.

        Args:
            paper_id: The paper ID
            url: The URL to download from
            source: Source description

        Returns:
            dict with download result
        """
        # Check for duplicate
        existing = is_duplicate_download(self.db, paper_id, url)
        if existing:
            return {
                "status": "already_downloaded",
                "pdf_file_id": existing.id,
                "file_path": existing.file_path,
                "message": "This URL has already been downloaded for this paper.",
            }

        # Create a new PdfFile record
        pdf_record = PdfFile(
            paper_id=paper_id,
            download_url=url,
            source=source,
            download_status="pending",
        )
        self.db.add(pdf_record)
        self.db.commit()

        return self._download(paper_id, url, source, pdf_record)

    def _download(
        self,
        paper_id: int,
        url: str,
        source: str,
        pdf_record: PdfFile,
    ) -> dict:
        """
        Internal download method.
        """
        # Generate filename from URL
        from urllib.parse import urlparse
        parsed = urlparse(url)
        filename = os.path.basename(parsed.path) or f"paper_{paper_id}.pdf"
        if not filename.endswith(".pdf"):
            filename += ".pdf"

        # Get storage path
        file_path = get_pdf_storage_path(paper_id, filename)

        # Handle filename collisions
        counter = 1
        while file_path.exists():
            stem = filename[:-4]  # Remove .pdf
            file_path = file_path.parent / f"{stem}_{counter}.pdf"
            counter += 1

        pdf_record.download_status = "downloading"
        self.db.commit()

        try:
            # Download with streaming
            with httpx.stream(
                "GET",
                url,
                timeout=DOWNLOAD_TIMEOUT,
                follow_redirects=True,
                headers={
                    "User-Agent": "FL-SLR-Automation/1.0 (Academic Research Tool)",
                },
            ) as response:
                response.raise_for_status()

                # Check content length
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > MAX_FILE_SIZE:
                    raise ValueError(
                        f"File too large: {content_length} bytes "
                        f"(max: {MAX_FILE_SIZE})"
                    )

                # Download to file
                downloaded_size = 0
                with open(file_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=DOWNLOAD_CHUNK_SIZE):
                        downloaded_size += len(chunk)
                        if downloaded_size > MAX_FILE_SIZE:
                            raise ValueError("File exceeds maximum size limit")
                        f.write(chunk)

            # Validate PDF
            if not validate_pdf(file_path):
                # Not a valid PDF — remove and mark invalid
                file_path.unlink(missing_ok=True)
                pdf_record.download_status = "invalid"
                pdf_record.notes = "Downloaded file is not a valid PDF"
                self.db.commit()
                return {
                    "status": "invalid",
                    "pdf_file_id": pdf_record.id,
                    "message": "Downloaded file is not a valid PDF.",
                }

            # Compute hash
            file_hash = compute_file_hash(file_path)

            # Update record
            pdf_record.download_status = "downloaded"
            pdf_record.file_path = str(file_path)
            pdf_record.file_hash = file_hash
            pdf_record.file_size = downloaded_size
            pdf_record.download_date = datetime.now(timezone.utc)
            pdf_record.notes = f"Successfully downloaded from {source}"
            self.db.commit()

            logger.info(
                f"PDF downloaded for paper {paper_id}: {file_path.name} "
                f"({downloaded_size} bytes)"
            )

            return {
                "status": "downloaded",
                "pdf_file_id": pdf_record.id,
                "file_path": str(file_path),
                "file_size": downloaded_size,
                "file_hash": file_hash,
            }

        except httpx.HTTPStatusError as e:
            pdf_record.download_status = "failed"
            pdf_record.notes = f"HTTP error: {e.response.status_code}"
            self.db.commit()
            # Clean up partial download
            file_path.unlink(missing_ok=True)
            return {
                "status": "failed",
                "pdf_file_id": pdf_record.id,
                "error": f"HTTP {e.response.status_code}: {str(e)}",
            }

        except httpx.TimeoutException:
            pdf_record.download_status = "failed"
            pdf_record.notes = "Download timed out"
            self.db.commit()
            file_path.unlink(missing_ok=True)
            return {
                "status": "failed",
                "pdf_file_id": pdf_record.id,
                "error": "Download timed out",
            }

        except Exception as e:
            pdf_record.download_status = "failed"
            pdf_record.notes = f"Error: {str(e)}"
            self.db.commit()
            file_path.unlink(missing_ok=True)
            return {
                "status": "failed",
                "pdf_file_id": pdf_record.id,
                "error": str(e),
            }

    def get_download_stats(self) -> dict:
        """Get PDF download statistics."""
        from sqlalchemy import func

        total = self.db.query(func.count(PdfFile.id)).scalar()
        downloaded = self.db.query(func.count(PdfFile.id)).filter(
            PdfFile.download_status == "downloaded"
        ).scalar()
        pending = self.db.query(func.count(PdfFile.id)).filter(
            PdfFile.download_status == "pending"
        ).scalar()
        failed = self.db.query(func.count(PdfFile.id)).filter(
            PdfFile.download_status == "failed"
        ).scalar()
        invalid = self.db.query(func.count(PdfFile.id)).filter(
            PdfFile.download_status == "invalid"
        ).scalar()

        total_size = self.db.query(func.coalesce(func.sum(PdfFile.file_size), 0)).filter(
            PdfFile.download_status == "downloaded"
        ).scalar()

        return {
            "total_records": total,
            "downloaded": downloaded,
            "pending": pending,
            "failed": failed,
            "invalid": invalid,
            "total_size_bytes": total_size,
        }
