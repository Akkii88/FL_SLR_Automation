"""
Tests: API Endpoints
=====================
Tests for FastAPI endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.main import app
from app.db.engine import Base, get_db

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
    """Create a test client with fresh database."""
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


class TestHealthEndpoint:
    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_root(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "FL-SLR" in response.json()["app"]


class TestConfigEndpoints:
    def test_get_config(self, client):
        response = client.get("/api/config/")
        assert response.status_code == 200
        data = response.json()
        assert "title" in data
        assert "search_families" in data
        assert len(data["search_families"]) == 6

    def test_update_config(self, client):
        response = client.put(
            "/api/config/",
            json={"max_candidates_per_family": 1000},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "updated"


class TestPapersEndpoints:
    def test_list_papers_empty(self, client):
        response = client.get("/api/papers/")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["papers"] == []

    def test_get_paper_not_found(self, client):
        response = client.get("/api/papers/9999")
        assert response.status_code == 404


class TestDashboardEndpoints:
    def test_dashboard_empty(self, client):
        response = client.get("/api/dashboard/")
        assert response.status_code == 200
        data = response.json()
        assert data["total_records"] == 0
        assert data["screening"]["not_screened"] == 0


class TestSearchEndpoints:
    def test_search_history_empty(self, client):
        response = client.get("/api/search/history")
        assert response.status_code == 200
        assert response.json() == []
