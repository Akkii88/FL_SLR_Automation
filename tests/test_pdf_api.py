"""
Tests: PDF & Notes API Endpoints
==================================
Tests for PDF management and paper notes REST API.
"""

import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.main import app
from app.db.engine import Base, get_db
from app.models.paper import Paper
from app.models.pdf_file import PdfFile, PaperNote

# Test database
TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def client():
    """Create a test client with fresh database and sample data."""
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db

    db = TestSessionLocal()

    papers = [
        Paper(
            openalex_id="W001",
            doi="10.0001/test.001",
            title="Paper With PDF",
            normalized_title="paper with pdf",
            pdf_url="https://example.org/paper.pdf",
            oa_status="gold",
            publication_year=2023,
        ),
        Paper(
            openalex_id="W002",
            doi="10.0001/test.002",
            title="Paper Without PDF",
            normalized_title="paper without pdf",
            pdf_url=None,
            oa_status="closed",
            publication_year=2023,
        ),
    ]
    db.add_all(papers)
    db.commit()
    db.close()

    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


class TestPdfDiscoveryAPI:
    """Test PDF discovery endpoints."""

    def test_discover_paper_with_pdf(self, client):
        response = client.post("/api/pdf/discover/1")
        assert response.status_code == 200
        data = response.json()
        assert data["availability"] == "oa_pdf"
        assert data["pdf_url"] == "https://example.org/paper.pdf"

    def test_discover_paper_without_pdf(self, client):
        response = client.post("/api/pdf/discover/2")
        assert response.status_code == 200
        data = response.json()
        assert data["availability"] == "none"

    def test_discover_not_found(self, client):
        response = client.post("/api/pdf/discover/9999")
        assert response.status_code == 404

    def test_discover_all(self, client):
        response = client.post("/api/pdf/discover")
        assert response.status_code == 200
        data = response.json()
        assert data["total_papers"] == 2

    def test_pdf_status(self, client):
        response = client.get("/api/pdf/status/1")
        assert response.status_code == 200
        data = response.json()
        assert data["has_oa_url"] is True

    def test_download_stats(self, client):
        response = client.get("/api/pdf/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_records" in data
        assert "downloaded" in data

    def test_pending_list(self, client):
        response = client.get("/api/pdf/pending")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 0


class TestPaperNotesAPI:
    """Test paper notes endpoints."""

    def test_create_note(self, client):
        response = client.post(
            "/api/papers/notes",
            json={
                "paper_id": 1,
                "content": "This paper compares FedAvg and FedProx.",
                "note_type": "general",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "created"

    def test_create_note_with_location(self, client):
        response = client.post(
            "/api/papers/notes",
            json={
                "paper_id": 1,
                "content": "Important result",
                "note_type": "result",
                "page": 7,
                "section": "Results",
                "table_ref": "Table 3",
            },
        )
        assert response.status_code == 200

    def test_create_note_paper_not_found(self, client):
        response = client.post(
            "/api/papers/notes",
            json={"paper_id": 9999, "content": "Test"},
        )
        assert response.status_code == 404

    def test_get_notes(self, client):
        # Create a note first
        client.post(
            "/api/papers/notes",
            json={"paper_id": 1, "content": "Note 1"},
        )

        response = client.get("/api/papers/1/notes")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

    def test_update_note(self, client):
        # Create a note
        create_resp = client.post(
            "/api/papers/notes",
            json={"paper_id": 1, "content": "Original"},
        )
        note_id = create_resp.json()["note_id"]

        # Update it
        response = client.put(
            f"/api/papers/notes/{note_id}",
            json={"content": "Updated content"},
        )
        assert response.status_code == 200

    def test_delete_note(self, client):
        # Create a note
        create_resp = client.post(
            "/api/papers/notes",
            json={"paper_id": 1, "content": "To delete"},
        )
        note_id = create_resp.json()["note_id"]

        # Delete it
        response = client.delete(f"/api/papers/notes/{note_id}")
        assert response.status_code == 200

        # Verify it's gone
        get_resp = client.get("/api/papers/1/notes")
        assert get_resp.json()["total"] == 0


class TestPaperDetailEnhanced:
    """Test enhanced paper detail endpoint."""

    def test_detail_includes_pdf_and_screening(self, client):
        # Create a screening decision
        client.post(
            "/api/screening/submit",
            json={
                "paper_id": 1,
                "decision": "include",
                "q1_fl_comparison": "YES",
                "q2_non_iid": "YES",
                "q3_superiority_claim": "YES",
                "q4_full_text_available": "YES",
            },
        )

        # Create a note
        client.post(
            "/api/papers/notes",
            json={"paper_id": 1, "content": "Test note"},
        )

        response = client.get("/api/papers/1")
        assert response.status_code == 200
        data = response.json()

        # Should include PDF files
        assert "pdf_files" in data

        # Should include screening history
        assert "screening_history" in data
        assert len(data["screening_history"]) == 1

        # Should include notes
        assert "notes" in data
        assert len(data["notes"]) == 1

    def test_detail_includes_provenance(self, client):
        response = client.get("/api/papers/1")
        assert response.status_code == 200
        data = response.json()
        assert "provenance" in data
