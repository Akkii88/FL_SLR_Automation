"""
NotebookLM Batch Preparation Service
=====================================
Prepares clean PDF files for upload to NotebookLM.

Creates:
- data/exports/notebooklm_batch/
  - batch_001/
  - batch_002/
  - ...
- notebooklm_manifest.csv

Does NOT upload to NotebookLM — just prepares clean files.
"""

import os
import shutil
import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.config import settings
from app.models.paper import Paper
from app.models.pdf_file import PdfFile

logger = logging.getLogger(__name__)

# Batch size (NotebookLM has upload limits)
DEFAULT_BATCH_SIZE = 50


class NotebookLMPrepService:
    """
    Prepares PDF files for NotebookLM upload.
    """

    def __init__(self, db: Session):
        self.db = db
        self.batch_dir = settings.project_root / "data" / "exports" / "notebooklm_batch"

    def prepare_batches(
        self,
        screening_status: str = "include",
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> dict:
        """
        Prepare PDF batches for NotebookLM upload.
        
        Args:
            screening_status: Only include papers with this status
            batch_size: Max PDFs per batch
            
        Returns:
            dict with batch info and manifest path
        """
        # Get papers with downloaded PDFs
        papers = (
            self.db.query(Paper)
            .join(PdfFile, Paper.id == PdfFile.paper_id)
            .filter(
                Paper.screening_status == screening_status,
                PdfFile.download_status == "downloaded",
                PdfFile.file_path.isnot(None),
            )
            .distinct()
            .order_by(Paper.id)
            .all()
        )

        if not papers:
            return {
                "status": "no_pdfs",
                "message": f"No downloaded PDFs found for papers with status '{screening_status}'.",
            }

        # Clean up old batches
        if self.batch_dir.exists():
            shutil.rmtree(self.batch_dir)
        self.batch_dir.mkdir(parents=True, exist_ok=True)

        # Create batches
        batches = []
        manifest = []
        batch_num = 1
        current_batch = []

        for paper in papers:
            # Get the downloaded PDF for this paper
            pdf_file = (
                self.db.query(PdfFile)
                .filter(
                    PdfFile.paper_id == paper.id,
                    PdfFile.download_status == "downloaded",
                )
                .first()
            )

            if not pdf_file or not pdf_file.file_path:
                continue

            source_path = Path(pdf_file.file_path)
            if not source_path.exists():
                continue

            current_batch.append({
                "paper": paper,
                "pdf_file": pdf_file,
                "source_path": source_path,
            })

            # Start new batch if current is full
            if len(current_batch) >= batch_size:
                batches.append(self._create_batch(batch_num, current_batch))
                current_batch = []
                batch_num += 1

        # Last batch
        if current_batch:
            batches.append(self._create_batch(batch_num, current_batch))

        # Write manifest
        manifest_path = self._write_manifest(manifest)

        return {
            "status": "prepared",
            "total_papers": len(papers),
            "total_batches": len(batches),
            "batch_dir": str(self.batch_dir),
            "manifest_path": str(manifest_path),
            "batches": [
                {
                    "batch": f"batch_{i+1:03d}",
                    "paper_count": len(b["papers"]),
                    "path": str(b["path"]),
                }
                for i, b in enumerate(batches)
            ],
        }

    def _create_batch(self, batch_num: int, items: list) -> dict:
        """Create a single batch directory with clean PDFs."""
        batch_name = f"batch_{batch_num:03d}"
        batch_path = self.batch_dir / batch_name
        batch_path.mkdir(parents=True, exist_ok=True)

        batch_papers = []

        for item in items:
            paper = item["paper"]
            source_path = item["source_path"]

            # Create clean filename: {paper_id}_{sanitized_title}.pdf
            safe_title = self._sanitize_filename(paper.title[:60])
            dest_filename = f"paper_{paper.id}_{safe_title}.pdf"
            dest_path = batch_path / dest_filename

            # Copy file
            shutil.copy2(source_path, dest_path)

            batch_papers.append({
                "paper_id": paper.id,
                "title": paper.title,
                "year": paper.publication_year,
                "doi": paper.doi,
                "local_pdf": str(dest_path),
                "screening_status": paper.screening_status,
            })

        return {
            "name": batch_name,
            "path": batch_path,
            "papers": batch_papers,
        }

    def _write_manifest(self, batches: list) -> Path:
        """Write the notebooklm_manifest.csv file."""
        manifest_path = self.batch_dir / "notebooklm_manifest.csv"

        with open(manifest_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "batch", "paper_id", "title", "year", "doi",
                "local_pdf", "screening_status",
            ])

            for batch in batches:
                for paper in batch["papers"]:
                    writer.writerow([
                        batch["name"],
                        paper["paper_id"],
                        paper["title"],
                        paper["year"] or "",
                        paper["doi"] or "",
                        paper["local_pdf"],
                        paper["screening_status"],
                    ])

        return manifest_path

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string for use in a filename."""
        # Remove or replace problematic characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, "_")
        # Collapse spaces and underscores
        name = "_".join(name.split())
        return name.strip("_")


def generate_ris_citation(paper: Paper) -> str:
    """Generate a RIS format citation for a paper."""
    lines = []
    lines.append("TY  - JOUR")
    if paper.title:
        lines.append(f"TI  - {paper.title}")
    if paper.authors:
        import json
        try:
            authors = json.loads(paper.authors)
            for author in authors:
                lines.append(f"AU  - {author}")
        except:
            pass
    if paper.source:
        lines.append(f"JO  - {paper.source}")
    if paper.publication_year:
        lines.append(f"PY  - {paper.publication_year}")
    if paper.doi:
        lines.append(f"DO  - {paper.doi}")
    if paper.oa_url:
        lines.append(f"UR  - {paper.oa_url}")
    if paper.abstract:
        lines.append(f"AB  - {paper.abstract}")
    lines.append("ER  - ")
    return "\n".join(lines)


def generate_bibtex_citation(paper: Paper) -> str:
    """Generate a BibTeX format citation for a paper."""
    # Generate a citation key
    key_parts = []
    if paper.authors:
        import json
        try:
            authors = json.loads(paper.authors)
            if authors:
                first_author_last = authors[0].split()[-1] if authors[0] else "unknown"
                key_parts.append(first_author_last.lower())
        except:
            key_parts.append("unknown")
    else:
        key_parts.append("unknown")

    if paper.publication_year:
        key_parts.append(str(paper.publication_year))

    if paper.title:
        # First meaningful word of title
        words = paper.title.split()
        if words:
            key_parts.append(words[0].lower())

    citation_key = "_".join(key_parts)

    lines = []
    lines.append(f"@article{{{citation_key},")
    if paper.title:
        lines.append(f"  title = {{{paper.title}}},")
    if paper.authors:
        import json
        try:
            authors = json.loads(paper.authors)
            author_str = " and ".join(authors)
            lines.append(f"  author = {{{author_str}}},")
        except:
            pass
    if paper.source:
        lines.append(f"  journal = {{{paper.source}}},")
    if paper.publication_year:
        lines.append(f"  year = {{{paper.publication_year}}},")
    if paper.doi:
        lines.append(f"  doi = {{{paper.doi}}},")
    if paper.oa_url:
        lines.append(f"  url = {{{paper.oa_url}}},")
    lines.append("}")
    return "\n".join(lines)
