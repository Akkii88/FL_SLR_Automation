"""
Tests: Phase 2 API Endpoints
=============================
Tests for provenance, export, and enhanced search/dashboard endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone

from app.api.main import app
from app.db.engine import Base, get_db
from app.models.paper import Paper
from app.models.search_run import SearchRun, SourceProvenance, SearchRunPaper
from app.models.screening import AuditLog

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

    # Add sample data
    db = TestSessionLocal()

    paper1 = Paper(
        openalex_id="W001",
        doi="10.0001/test.001",
        title="Test Paper One",
        normalized_title="test paper one",
        publication_year=2023,
        screening_status="not_screened",
        duplicate_status="unique",
    )
    paper2 = Paper(
        openalex_id="W002",
        doi="10.0001/test.002",
        title="Test Paper Two",
        normalized_title="test paper two",
        publication_year=2024,
        screening_status="include",
        duplicate_status="unique",
    )
    db.add_all([paper1, paper2])
    db.flush()

    # Add provenance
    prov1 = SourceProvenance(
        paper_id=paper1.id,
        source="OpenAlex",
        search_family="A",
        retrieval_timestamp=datetime.now(timezone.utc),
    )
    prov2 = SourceProvenance(
        paper_id=paper1.id,
        source="OpenAlex",
        search_family="C",
        retrieval_timestamp=datetime.now(timezone.utc),
    )
    prov3 = SourceProvenance(
        paper_id=paper2.id,
        source="OpenAlex",
        search_family="B",
        retrieval_timestamp=datetime.now(timezone.utc),
    )
    db.add_all([prov1, prov2, prov3])

    # Add search run
    run = SearchRun(
        source="OpenAlex",
        search_family="A",
        exact_query="test query",
        search_date=datetime.now(timezone.utc),
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        results_retrieved=10,
        records_saved=8,
        pages_retrieved=1,
        duration_seconds=5.5,
        retries=0,
    )
    db.add(run)

    # Add audit log
    audit = AuditLog(
        action="test_action",
        entity_type="paper",
        entity_id=paper1.id,
        description="Test audit entry",
        actor="system",
    )
    db.add(audit)
    db.commit()
    db.close()

    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


class TestProvenanceEndpoints:
    """Test provenance tracking endpoints."""

    def test_paper_provenance(self, client):
        response = client.get("/api/provenance/paper/1")
        assert response.status_code == 200
        data = response.json()
        assert data["paper_id"] == 1
        assert data["found_by_count"] == 2  # Found by families A and C

    def test_paper_provenance_not_found(self, client):
        response = client.get("/api/provenance/paper/9999")
        assert response.status_code == 404

    def test_family_papers(self, client):
        response = client.get("/api/provenance/family/A")
        assert response.status_code == 200
        data = response.json()
        assert data["family"] == "A"
        assert data["total"] == 1  # Only paper 1 was found by family A

    def test_provenance_summary(self, client):
        response = client.get("/api/provenance/summary")
        assert response.status_code == 200
        data = response.json()
        assert "by_family" in data
        assert data["total_provenance_records"] == 3


class TestExportEndpoints:
    """Test data export endpoints."""

    def test_export_search_log_json(self, client):
        response = client.get("/api/export/search-log?format=json")
        assert response.status_code == 200
        data = response.json()
        assert "search_log" in data
        assert data["count"] == 1

    def test_export_search_log_csv(self, client):
        response = client.get("/api/export/search-log?format=csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]

    def test_export_candidates_json(self, client):
        response = client.get("/api/export/candidates?format=json")
        assert response.status_code == 200
        data = response.json()
        assert "candidates" in data
        assert data["count"] == 2

    def test_export_candidates_csv(self, client):
        response = client.get("/api/export/candidates?format=csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]

    def test_export_audit_log(self, client):
        response = client.get("/api/export/audit-log?format=json")
        assert response.status_code == 200
        data = response.json()
        assert "audit_log" in data
        assert data["count"] == 1


class TestEnhancedDashboard:
    """Test enhanced dashboard with search family breakdown."""

    def test_dashboard_has_family_breakdown(self, client):
        response = client.get("/api/dashboard/")
        assert response.status_code == 200
        data = response.json()
        assert "by_family" in data
        assert "search_stats" in data
        assert "audit_entries" in data

    def test_dashboard_search_stats(self, client):
        response = client.get("/api/dashboard/")
        data = response.json()
        stats = data["search_stats"]
        assert stats["total_searches"] == 1
        assert stats["total_pages"] == 1


class TestEnhancedSearchHistory:
    """Test enhanced search history endpoint."""

    def test_history_includes_duration(self, client):
        response = client.get("/api/search/history")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["duration_seconds"] == 5.5
        assert data[0]["pages_retrieved"] == 1
        assert data[0]["year_filter"] is not None


class TestResumeEndpoint:
    """Test search resume endpoint."""

    def test_resume_without_checkpoint(self, client):
        response = client.post("/api/search/resume")
        assert response.status_code == 400
        assert "No checkpoint" in response.json()["detail"]
