"""
Tests: Deduplication API Endpoints
====================================
Tests for the deduplication REST API.
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

    # Add sample papers with duplicates
    db = TestSessionLocal()

    papers = [
        Paper(
            openalex_id="W001",
            doi="10.0001/test.001",
            title="Federated Learning Survey",
            normalized_title="federated learning survey",
            publication_year=2023,
            duplicate_status="unique",
            source_type="journal-article",
        ),
        Paper(
            openalex_id="W002",
            doi="10.0001/test.001",  # Same DOI as W001
            title="Federated Learning Survey v2",
            normalized_title="federated learning survey v2",
            publication_year=2023,
            duplicate_status="unique",
            source_type="journal-article",
        ),
        Paper(
            openalex_id="W003",
            doi="10.0001/test.002",
            title="Unique Paper",
            normalized_title="unique paper",
            publication_year=2024,
            duplicate_status="unique",
            source_type="conference-paper",
        ),
    ]
    db.add_all(papers)
    db.commit()
    db.close()

    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


class TestDeduplicationRun:
    """Test deduplication run endpoint."""

    def test_run_deduplication(self, client):
        response = client.post(
            "/api/deduplication/run",
            json={"dry_run": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "complete"
        assert data["total_matches"] >= 1

    def test_run_dry_run(self, client):
        response = client.post(
            "/api/deduplication/run",
            json={"dry_run": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["dry_run"] is True
        # Papers should not be modified
        stats = client.get("/api/deduplication/stats").json()
        assert stats["unique"] == 3  # All still unique

    def test_get_stats(self, client):
        response = client.get("/api/deduplication/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_papers"] == 3
        assert "unique" in data
        assert "by_match_type" in data


class TestDeduplicationGroups:
    """Test duplicate groups endpoint."""

    def test_groups_after_run(self, client):
        # First run deduplication
        client.post("/api/deduplication/run", json={"dry_run": False})

        response = client.get("/api/deduplication/groups")
        assert response.status_code == 200
        data = response.json()
        assert data["total_groups"] >= 1

    def test_groups_empty(self, client):
        response = client.get("/api/deduplication/groups")
        assert response.status_code == 200
        data = response.json()
        assert data["total_groups"] == 0


class TestDeduplicationReview:
    """Test review endpoint."""

    def test_review_probable_duplicates(self, client):
        # Run deduplication first
        client.post("/api/deduplication/run", json={"dry_run": False})

        response = client.get("/api/deduplication/review?status=probable_duplicate")
        assert response.status_code == 200
        data = response.json()
        assert data["status_filter"] == "probable_duplicate"
        assert data["total"] >= 1


class TestDeduplicationConfirm:
    """Test manual confirmation endpoint."""

    def test_confirm_duplicate(self, client):
        response = client.post(
            "/api/deduplication/confirm",
            json={
                "paper_id_a": 1,
                "paper_id_b": 2,
                "canonical_id": 1,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "confirmed"
        assert data["canonical_paper_id"] == 1

    def test_confirm_not_found(self, client):
        response = client.post(
            "/api/deduplication/confirm",
            json={
                "paper_id_a": 9999,
                "paper_id_b": 8888,
                "canonical_id": 9999,
            },
        )
        assert response.status_code == 404


class TestDeduplicationReject:
    """Test rejection endpoint."""

    def test_reject_duplicate(self, client):
        # First run deduplication to create a probable duplicate
        client.post("/api/deduplication/run", json={"dry_run": False})

        response = client.post(
            "/api/deduplication/reject",
            json={
                "paper_id_a": 1,
                "paper_id_b": 2,
                "reason": "Different studies",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"


class TestDeduplicationOverride:
    """Test override endpoint."""

    def test_override_status(self, client):
        response = client.post(
            "/api/deduplication/override",
            json={
                "paper_id": 1,
                "new_status": "manually_retained",
                "reason": "Conference and journal versions are different studies",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "overridden"
        assert data["new_status"] == "manually_retained"

    def test_override_invalid_status(self, client):
        response = client.post(
            "/api/deduplication/override",
            json={
                "paper_id": 1,
                "new_status": "invalid_status",
                "reason": "test",
            },
        )
        assert response.status_code == 400


class TestDeduplicationLog:
    """Test deduplication log endpoint."""

    def test_get_log(self, client):
        # Run deduplication to generate logs
        client.post("/api/deduplication/run", json={"dry_run": False})

        response = client.get("/api/deduplication/log")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["logs"]) >= 1

    def test_filter_by_type(self, client):
        client.post("/api/deduplication/run", json={"dry_run": False})

        response = client.get("/api/deduplication/log?match_type=doi_exact")
        assert response.status_code == 200
        data = response.json()
        # All returned logs should be doi_exact
        for log in data["logs"]:
            assert log["match_type"] == "doi_exact"
