"""
Tests: Screening API Endpoints
================================
Tests for the screening REST API.
"""

import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.main import app
from app.db.engine import Base, get_db
from app.models.paper import Paper

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
            title="Federated Learning Comparison Study",
            normalized_title="federated learning comparison study",
            abstract="This paper compares FedAvg and FedProx under non-IID data.",
            publication_year=2023,
            screening_status="not_screened",
            duplicate_status="unique",
        ),
        Paper(
            openalex_id="W002",
            title="Deep Learning for Images",
            normalized_title="deep learning for images",
            abstract="A study on CNN architectures.",
            publication_year=2023,
            screening_status="not_screened",
            duplicate_status="unique",
        ),
        Paper(
            openalex_id="W003",
            title="Already Screened Paper",
            normalized_title="already screened paper",
            publication_year=2022,
            screening_status="include",
            duplicate_status="unique",
        ),
    ]
    db.add_all(papers)
    db.commit()
    db.close()

    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


class TestScreeningQuestions:
    """Test the questions endpoint."""

    def test_get_questions(self, client):
        response = client.get("/api/screening/questions")
        assert response.status_code == 200
        data = response.json()
        assert len(data["questions"]) == 4
        assert "decisions" in data
        assert "exclusion_reasons" in data
        assert "include" in data["decisions"]
        assert "exclude" in data["decisions"]


class TestScreeningSubmit:
    """Test screening submission endpoint."""

    def test_submit_include(self, client):
        response = client.post(
            "/api/screening/submit",
            json={
                "paper_id": 1,
                "q1_fl_comparison": "YES",
                "q2_non_iid": "YES",
                "q3_superiority_claim": "YES",
                "q4_full_text_available": "YES",
                "decision": "include",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "recorded"
        assert data["decision"] == "include"

    def test_submit_exclude_with_reason(self, client):
        response = client.post(
            "/api/screening/submit",
            json={
                "paper_id": 2,
                "q1_fl_comparison": "NO",
                "q2_non_iid": "YES",
                "q3_superiority_claim": "YES",
                "q4_full_text_available": "YES",
                "decision": "exclude",
                "exclusion_reason": "no_fl_algorithm_comparison",
            },
        )
        assert response.status_code == 200

    def test_submit_exclude_without_reason(self, client):
        response = client.post(
            "/api/screening/submit",
            json={
                "paper_id": 2,
                "decision": "exclude",
            },
        )
        assert response.status_code == 400
        assert "Exclusion reason is required" in response.json()["detail"]

    def test_submit_invalid_decision(self, client):
        response = client.post(
            "/api/screening/submit",
            json={
                "paper_id": 1,
                "decision": "maybe",
            },
        )
        assert response.status_code == 400

    def test_submit_paper_not_found(self, client):
        response = client.post(
            "/api/screening/submit",
            json={
                "paper_id": 9999,
                "decision": "include",
            },
        )
        assert response.status_code == 400


class TestScreeningNext:
    """Test next paper endpoint."""

    def test_next_paper(self, client):
        response = client.get("/api/screening/next")
        assert response.status_code == 200
        data = response.json()
        assert data["paper"] is not None
        assert data["paper"]["screening_status"] == "not_screened"

    def test_next_with_stage(self, client):
        response = client.get("/api/screening/next?stage=full_text")
        assert response.status_code == 200


class TestScreeningHistory:
    """Test screening history endpoint."""

    def test_history_after_submission(self, client):
        # Submit a decision first
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

        response = client.get("/api/screening/history/1")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["history"][0]["decision"] == "include"


class TestScreeningProgress:
    """Test progress endpoint."""

    def test_progress(self, client):
        response = client.get("/api/screening/progress")
        assert response.status_code == 200
        data = response.json()
        assert data["total_candidates"] == 3
        assert data["not_screened"] == 2
        assert "screening_progress_pct" in data
        assert "exclusion_reasons" in data


class TestScreeningList:
    """Test screening queue list endpoint."""

    def test_list_not_screened(self, client):
        response = client.get("/api/screening/list?status=not_screened")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2

    def test_list_by_stage(self, client):
        response = client.get("/api/screening/list?stage=title_abstract")
        assert response.status_code == 200
        data = response.json()
        # Should show not_screened papers
        assert data["total"] == 2


class TestBulkSubmit:
    """Test bulk submission endpoint."""

    def test_bulk_submit(self, client):
        response = client.post(
            "/api/screening/bulk-submit",
            json={
                "decisions": [
                    {
                        "paper_id": 1,
                        "decision": "include",
                        "q1_fl_comparison": "YES",
                        "q2_non_iid": "YES",
                        "q3_superiority_claim": "YES",
                        "q4_full_text_available": "YES",
                    },
                    {
                        "paper_id": 2,
                        "decision": "exclude",
                        "exclusion_reason": "not_primary_empirical_study",
                    },
                ],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success_count"] == 2


class TestFullTextScreening:
    """Test full-text screening endpoint."""

    def test_get_full_text(self, client):
        response = client.get("/api/screening/full-text/3")
        assert response.status_code == 200
        data = response.json()
        assert data["paper"]["id"] == 3

    def test_full_text_not_found(self, client):
        response = client.get("/api/screening/full-text/9999")
        assert response.status_code == 404


class TestScreeningExport:
    """Test screening results export."""

    def test_export_json(self, client):
        # Submit a decision first
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

        response = client.get("/api/export/screening-results?format=json")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1

    def test_export_csv(self, client):
        client.post(
            "/api/screening/submit",
            json={
                "paper_id": 1,
                "decision": "include",
            },
        )

        response = client.get("/api/export/screening-results?format=csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
