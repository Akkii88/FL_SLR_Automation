"""
Tests: Evidence Dashboard API Endpoints
=========================================
Tests for evidence dashboard REST API.
"""

import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.main import app
from app.db.engine import Base, get_db
from app.models.paper import Paper
from app.models.extraction import Claim, Experiment, Condition, EvidenceQuality

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
        normalized_title="fedx a new fl method",
        screening_status="include",
    )
    db.add(paper)
    db.flush()

    claim = Claim(paper_id=paper.id, claim_scope="Global Model Accuracy")
    db.add(claim)
    db.flush()

    exp = Experiment(claim_id=claim.id, dataset="CIFAR-10")
    db.add(exp)
    db.flush()

    conditions = [
        Condition(
            experiment_id=exp.id,
            algorithm="FedX",
            metric_name="Accuracy",
            metric_value="92.5",
            ranking_position=1,
            is_winner=True,
        ),
        Condition(
            experiment_id=exp.id,
            algorithm="FedAvg",
            metric_name="Accuracy",
            metric_value="89.2",
            ranking_position=2,
            is_winner=False,
        ),
    ]
    db.add_all(conditions)

    eq = EvidenceQuality(
        claim_id=claim.id,
        independent_runs=5,
        direct_statistical_test=True,
        uncertainty_reporting="SD",
        ranking_robustness="Observationally Stable",
        matched_client_partition="YES",
    )
    db.add(eq)
    db.commit()
    db.close()

    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


class TestEvidenceOverview:
    """Test evidence overview endpoint."""

    def test_overview(self, client):
        response = client.get("/api/evidence/overview")
        assert response.status_code == 200
        data = response.json()
        assert data["total_claims"] == 1
        assert data["assessed_claims"] == 1
        assert data["dimension_3_direct_statistics"]["direct_test"] == 1

    def test_overview_empty(self):
        # Create fresh client with no data
        Base.metadata.create_all(bind=engine)
        app.dependency_overrides[get_db] = override_get_db

        with TestClient(app) as c:
            response = c.get("/api/evidence/overview")
            assert response.status_code == 200
            data = response.json()
            assert data["total_claims"] == 0

        Base.metadata.drop_all(bind=engine)
        app.dependency_overrides.clear()


class TestClaimEvidence:
    """Test claim evidence endpoint."""

    def test_claim_evidence(self, client):
        response = client.get("/api/evidence/claim/1")
        assert response.status_code == 200
        data = response.json()
        assert data["evidence"]["has_assessment"] is True
        assert "rankings" in data

    def test_claim_evidence_not_found(self, client):
        response = client.get("/api/evidence/claim/9999")
        assert response.status_code == 404


class TestRankingAnalysis:
    """Test ranking analysis endpoint."""

    def test_ranking_analysis(self, client):
        response = client.get("/api/evidence/ranking-analysis/1")
        assert response.status_code == 200
        data = response.json()
        assert data["winner_consistent_across_conditions"] is True
        assert data["consistent_winner"] == "FedX"
        assert len(data["conditions"]) == 2

    def test_ranking_not_found(self, client):
        response = client.get("/api/evidence/ranking-analysis/9999")
        assert response.status_code == 404


class TestDimensionBreakdown:
    """Test dimension breakdown endpoint."""

    def test_repetition_dimension(self, client):
        response = client.get("/api/evidence/by-dimension/repetition")
        assert response.status_code == 200
        data = response.json()
        assert data["dimension"] == "repetition"

    def test_uncertainty_dimension(self, client):
        response = client.get("/api/evidence/by-dimension/uncertainty")
        assert response.status_code == 200

    def test_direct_stats_dimension(self, client):
        response = client.get("/api/evidence/by-dimension/direct_statistics")
        assert response.status_code == 200

    def test_fairness_dimension(self, client):
        response = client.get("/api/evidence/by-dimension/fairness")
        assert response.status_code == 200

    def test_ranking_dimension(self, client):
        response = client.get("/api/evidence/by-dimension/ranking")
        assert response.status_code == 200

    def test_invalid_dimension(self, client):
        response = client.get("/api/evidence/by-dimension/invalid")
        assert response.status_code == 400


class TestEnhancedDashboard:
    """Test enhanced dashboard with evidence stats."""

    def test_dashboard_includes_evidence(self, client):
        response = client.get("/api/dashboard/")
        assert response.status_code == 200
        data = response.json()
        assert "evidence" in data
        assert data["evidence"]["total_claims"] == 1
        assert data["evidence"]["assessed_claims"] == 1
        assert data["evidence"]["direct_statistical_tests"] == 1
