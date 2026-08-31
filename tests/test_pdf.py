"""
Tests: PDF Discovery & Download Services
==========================================
Tests for PDF discovery, download, validation, and paper notes.
"""

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.engine import Base
from app.models.paper import Paper
from app.models.pdf_file import PdfFile, PaperNote
from app.services.pdf_discovery import PdfDiscoveryService, SOURCE_OA_PDF, SOURCE_LANDING_PAGE, SOURCE_NONE
from app.services.pdf_download import (
    PdfDownloadService,
    validate_pdf,
    compute_file_hash,
    is_duplicate_download,
    get_pdf_storage_path,
    PDF_MAGIC_BYTES,
)


@pytest.fixture(scope="function")
def db():
    """Create a fresh in-memory database."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()

    yield session

    session.close()
    transaction.rollback()
    connection.close()
    Base.metadata.drop_all(bind=engine)


def make_paper(
    db,
    title="Test Paper",
    pdf_url=None,
    oa_url=None,
    best_oa_location=None,
    oa_status=None,
    doi=None,
):
    """Helper to create a test paper."""
    paper = Paper(
        title=title,
        normalized_title=title.lower(),
        pdf_url=pdf_url,
        oa_url=oa_url,
        best_oa_location=best_oa_location,
        oa_status=oa_status,
        doi=doi,
    )
    db.add(paper)
    db.commit()
    return paper


class TestPdfDiscovery:
    """Test PDF discovery service."""

    def test_discover_with_pdf_url(self, db):
        paper = make_paper(
            db,
            pdf_url="https://example.org/paper.pdf",
            oa_status="gold",
        )

        service = PdfDiscoveryService(db)
        result = service.discover_for_paper(paper.id)

        assert result["availability"] == SOURCE_OA_PDF
        assert result["pdf_url"] == "https://example.org/paper.pdf"

    def test_discover_with_landing_page(self, db):
        paper = make_paper(
            db,
            best_oa_location="https://example.org/landing",
            oa_status="green",
        )

        service = PdfDiscoveryService(db)
        result = service.discover_for_paper(paper.id)

        assert result["availability"] == SOURCE_LANDING_PAGE

    def test_discover_no_full_text(self, db):
        paper = make_paper(db, doi="10.1234/test")

        service = PdfDiscoveryService(db)
        result = service.discover_for_paper(paper.id)

        assert result["availability"] == SOURCE_NONE
        assert "doi" in result.get("sources_checked", [])

    def test_discover_paper_not_found(self, db):
        service = PdfDiscoveryService(db)
        with pytest.raises(ValueError, match="not found"):
            service.discover_for_paper(9999)

    def test_discover_creates_pdf_record(self, db):
        paper = make_paper(db, pdf_url="https://example.org/paper.pdf")

        service = PdfDiscoveryService(db)
        result = service.discover_for_paper(paper.id)

        # A PdfFile record should have been created
        assert "pdf_file_id" in result

        pdf_record = db.query(PdfFile).filter(PdfFile.id == result["pdf_file_id"]).first()
        assert pdf_record is not None
        assert pdf_record.download_status == "pending"

    def test_discover_all(self, db):
        make_paper(db, title="P1", pdf_url="https://example.org/p1.pdf")
        make_paper(db, title="P2", best_oa_location="https://example.org/p2")
        make_paper(db, title="P3")

        service = PdfDiscoveryService(db)
        results = service.discover_all()

        assert results["total_papers"] == 3
        assert results["with_pdf_url"] == 1
        assert results["with_landing_page"] == 1
        assert results["no_full_text"] == 1

    def test_get_pdf_status(self, db):
        paper = make_paper(db, pdf_url="https://example.org/paper.pdf")

        # Create a PDF record
        pdf = PdfFile(
            paper_id=paper.id,
            download_url="https://example.org/paper.pdf",
            download_status="downloaded",
            file_path="/tmp/test.pdf",
        )
        db.add(pdf)
        db.commit()

        service = PdfDiscoveryService(db)
        status = service.get_pdf_status(paper.id)

        assert status["has_oa_url"] is True
        assert len(status["pdf_files"]) == 1
        assert status["pdf_files"][0]["download_status"] == "downloaded"


class TestPdfValidation:
    """Test PDF validation utilities."""

    def test_validate_pdf_valid(self, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(PDF_MAGIC_BYTES + b" rest of pdf content")
        assert validate_pdf(pdf_file) is True

    def test_validate_pdf_invalid(self, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"This is not a PDF")
        assert validate_pdf(pdf_file) is True is False

    def test_validate_pdf_nonexistent(self, tmp_path):
        assert validate_pdf(tmp_path / "nonexistent.pdf") is False

    def test_compute_file_hash(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")
        hash1 = compute_file_hash(test_file)
        hash2 = compute_file_hash(test_file)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex digest

    def test_is_duplicate_download(self, db):
        paper = make_paper(db)

        pdf = PdfFile(
            paper_id=paper.id,
            download_url="https://example.org/paper.pdf",
            download_status="downloaded",
        )
        db.add(pdf)
        db.commit()

        assert is_duplicate_download(db, paper.id, "https://example.org/paper.pdf") is not None
        assert is_duplicate_download(db, paper.id, "https://example.org/other.pdf") is None


class TestPaperNotes:
    """Test paper notes model and operations."""

    def test_create_note(self, db):
        paper = make_paper(db)

        note = PaperNote(
            paper_id=paper.id,
            content="This paper compares FedAvg and FedProx.",
            note_type="general",
        )
        db.add(note)
        db.commit()

        assert note.id is not None
        assert note.content == "This paper compares FedAvg and FedProx."

    def test_note_with_location(self, db):
        paper = make_paper(db)

        note = PaperNote(
            paper_id=paper.id,
            content="Important result in Table 3",
            note_type="result",
            page=7,
            section="Results",
            table_ref="Table 3",
        )
        db.add(note)
        db.commit()

        assert note.page == 7
        assert note.section == "Results"
        assert note.table_ref == "Table 3"

    def test_notes_relationship(self, db):
        paper = make_paper(db)

        note1 = PaperNote(paper_id=paper.id, content="Note 1")
        note2 = PaperNote(paper_id=paper.id, content="Note 2")
        db.add_all([note1, note2])
        db.commit()

        assert len(paper.notes) == 2

    def test_note_types(self, db):
        paper = make_paper(db)

        valid_types = ["general", "method", "result", "limitation", "decision", "evidence", "code", "other"]
        for note_type in valid_types:
            note = PaperNote(paper_id=paper.id, content=f"Note of type {note_type}", note_type=note_type)
            db.add(note)
        db.commit()

        assert len(paper.notes) == len(valid_types)


class TestPdfDownloadService:
    """Test PDF download service."""

    def test_duplicate_detection(self, db):
        paper = make_paper(db)

        # Create an existing downloaded record
        existing = PdfFile(
            paper_id=paper.id,
            download_url="https://example.org/paper.pdf",
            download_status="downloaded",
            file_path="/tmp/paper.pdf",
        )
        db.add(existing)
        db.commit()

        service = PdfDownloadService(db)
        result = service.download_for_paper(
            paper_id=paper.id,
            url="https://example.org/paper.pdf",
        )

        assert result["status"] == "already_downloaded"

    def test_missing_url_raises(self, db):
        paper = make_paper(db)

        # Create a PdfFile record without URL
        pdf_record = PdfFile(paper_id=paper.id, download_status="pending")
        db.add(pdf_record)
        db.commit()

        service = PdfDownloadService(db)
        with pytest.raises(ValueError, match="No download URL"):
            service.download_pdf(pdf_record.id)

    def test_download_stats(self, db):
        paper = make_paper(db)

        db.add_all([
            PdfFile(paper_id=paper.id, download_status="downloaded"),
            PdfFile(paper_id=paper.id, download_status="pending"),
            PdfFile(paper_id=paper.id, download_status="failed"),
        ])
        db.commit()

        service = PdfDownloadService(db)
        stats = service.get_download_stats()

        assert stats["downloaded"] == 1
        assert stats["pending"] == 1
        assert stats["failed"] == 1
