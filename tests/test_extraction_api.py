"""
Tests: Extraction API Endpoints
=================================
Tests for the extraction REST API.
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

    paper = Paper(
        openalex_id="W001",
        title="FedX: A New FL Method",
        normalizedtitle="fedx a new fl method",
        screening_status="include",
    )
    db.add(paper)
    db.commit()
    db.close()

    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


class TestCodebookAPI:
    """Test codebook endpoint."""

    def test_get_codebook(self, client):
        response = client.get("/api/extraction/codebook")
        assert response.status_code == 200
        data = response.json()
        assert "claim_scopes" in data
        assert "non_iid_types" in data
        assert "ranking_robustness" in data


class TestClaimAPI:
    """Test claim CRUD endpoints."""

    def test_create_claim(self, client):
        response = client.post(
            "/api/extraction/claims",
            json={
                "paper_id": 1,
                "claim_text": "FedX outperforms FedAvg",
                "claim_scope": "Global Model Accuracy",
                "algorithms_compared": ["FedX", "FedAvg"],
                "winner_algorithm": "FedX",
                "non_iid_type": "Label distribution skew",
                "partition_method": "Dirichlet",
                "heterogeneity_param": "alpha=0.1",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "created"

    def test_create_claim_invalid_scope(self, client):
        response = client.post(
            "/api/extraction/claims",
            json={
                "paper_id": 1,
                "claim_scope": "Invalid Scope",
            },
        )
        assert response.status_code == 400

    def test_list_claims(self, client):
        # Create a claim first
        client.post(
            "/api/extraction/claims",
            json={"paper_id": 1, "claim_scope": "Global Model Accuracy"},
        )

        response = client.get("/api/extraction/claims")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

    def test_get_claim_detail(self, client):
        # Create a claim
        create_resp = client.post(
            "/api/extraction/claims",
            json={"paper_id": 1, "claim_scope": "Global Model Accuracy"},
        )
        claim_id = create_resp.json()["claim_id"]

        response = client.get(f"/api/extraction/claims/{claim_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["claim"]["id"] == claim_id
        assert "experiments" in data
        assert "evidence_quality" in data


class TestExperimentAPI:
    """Test experiment endpoints."""

    def test_create_experiment(self, client):
        # Create a claim first
        claim_resp = client.post(
            "/api/extraction/claims",
            json={"paper_id": 1},
        )
        claim_id = claim_resp.json()["claim_id"]

        response = client.post(
            "/api/extraction/experiments",
            json={
                "claim_id": claim_id,
                "dataset": "CIFAR-10",
                "independent_runs": 5,
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "created"


class TestConditionAPI:
    """Test condition endpoints."""

    def test_create_condition(self, client):
        # Create claim and experiment
        claim_resp = client.post(
            "/api/extraction/claims",
            json={"paper_id": 1},
        )
        claim_id = claim_resp.json()["claim_id"]

        exp_resp = client.post(
            "/api/extraction/experiments",
            json={"claim_id": claim_id},
        )
        exp_id = exp_resp.json()["experiment_id"]

        response = client.post(
            "/api/extraction/conditions",
            json={
                "experiment_id": exp_id,
                "algorithm": "FedX",
                "metric_name": "Accuracy",
                "metric_value": "92.5",
                "is_winner": True,
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "created"


class TestEvidenceQualityAPI:
    """Test evidence quality endpoints."""

    def test_create_evidence_quality(self, client):
        # Create a claim first
        claim_resp = client.post(
            "/api/extraction/claims",
            json={"paper_id": 1},
        )
        claim_id = claim_resp.json()["claim_id"]

        response = client.post(
            "/api/extraction/evidence-quality",
            json={
                "claim_id": claim_id,
                "independent_runs": 5,
                "direct_statistical_test": True,
                "uncertainty_reporting": "SD",
                "ranking_robustness": "Observationally Stable",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "created"

    def test_create_eq_invalid_ranking(self, client):
        claim_resp = client.post(
            "/api/extraction/claims",
            json={"paper_id": 1},
        )
        claim_id = claim_resp.json()["claim_id"]

        response = client.post(
            "/api/extraction/evidence-quality",
            json={
                "claim_id": claim_id,
                "ranking_robustness": "Invalid",
            },
        )
        assert response.status_code == 400


class TestExtractionStats:
    """Test statistics endpoint."""

    def test_stats(self, client):
        response = client.get("/api/extraction/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_claims" in data
        assert "direct_statistical_tests" in data


class TestClaimsExport:
    """Test claims export endpoint."""

    def test_export_json(self, client):
        # Create a claim
        client.post(
            "/api/extraction/claims",
            json={"paper_id": 1, "claim_scope": "Global Model Accuracy"},
        )

        response = client.get("/api/export/claims?format=json")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1

    def test_export_csv(self, client):
        client.post(
            "/api/extraction/claims",
            json={"paper_id": 1},
        )

        response = client.get("/api/export/claims?format=csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
