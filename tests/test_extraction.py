"""
Tests: Extraction System & Codebook
======================================
Tests for claim-level extraction, evidence quality, and codebook validation.
"""

import json
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.engine import Base
from app.models.paper import Paper
from app.models.extraction import Claim, Experiment, Condition, EvidenceQuality
from app.models.screening import AuditLog
from app.services.extraction import ExtractionService


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


def make_paper(db, title="Test Paper"):
    """Helper to create a test paper."""
    paper = Paper(
        title=title,
        normalized_title=title.lower(),
        screening_status="include",
    )
    db.add(paper)
    db.commit()
    return paper


class TestClaimCreation:
    """Test claim creation and validation."""

    def test_create_claim(self, db):
        paper = make_paper(db)
        service = ExtractionService(db)

        claim = service.create_claim(
            paper_id=paper.id,
            claim_text="FedX outperforms FedAvg on CIFAR-10",
            claim_scope="Global Model Accuracy",
            algorithms_compared=["FedX", "FedAvg"],
            winner_algorithm="FedX",
            datasets=["CIFAR-10"],
            non_iid_type="Label distribution skew",
            partition_method="Dirichlet",
            heterogeneity_param="alpha=0.1",
        )

        assert claim.id is not None
        assert claim.paper_id == paper.id
        assert claim.claim_scope == "Global Model Accuracy"

    def test_create_claim_invalid_scope(self, db):
        paper = make_paper(db)
        service = ExtractionService(db)

        with pytest.raises(ValueError, match="Invalid claim_scope"):
            service.create_claim(
                paper_id=paper.id,
                claim_scope="Invalid Scope",
            )

    def test_create_claim_invalid_non_iid(self, db):
        paper = make_paper(db)
        service = ExtractionService(db)

        with pytest.raises(ValueError, match="Invalid non_iid_type"):
            service.create_claim(
                paper_id=paper.id,
                non_iid_type="Invalid Type",
            )

    def test_create_claim_paper_not_found(self, db):
        service = ExtractionService(db)

        with pytest.raises(ValueError, match="not found"):
            service.create_claim(paper_id=9999)

    def test_get_claims_for_paper(self, db):
        paper = make_paper(db)
        service = ExtractionService(db)

        service.create_claim(paper_id=paper.id, claim_scope="Global Model Accuracy")
        service.create_claim(paper_id=paper.id, claim_scope="Convergence Speed")

        claims = service.get_claims_for_paper(paper.id)
        assert len(claims) == 2

    def test_claim_json_fields(self, db):
        paper = make_paper(db)
        service = ExtractionService(db)

        claim = service.create_claim(
            paper_id=paper.id,
            algorithms_compared=["FedX", "FedAvg", "SCAFFOLD"],
            datasets=["CIFAR-10", "CIFAR-100"],
        )

        algorithms = json.loads(claim.algorithms_compared)
        assert len(algorithms) == 3
        assert "FedX" in algorithms


class TestExperimentCreation:
    """Test experiment creation."""

    def test_create_experiment(self, db):
        paper = make_paper(db)
        service = ExtractionService(db)
        claim = service.create_claim(paper_id=paper.id)

        exp = service.create_experiment(
            claim_id=claim.id,
            experiment_name="CIFAR-10 Experiment",
            dataset="CIFAR-10",
            independent_runs=5,
            random_seed_reported="explicitly_reported",
        )

        assert exp.id is not None
        assert exp.dataset == "CIFAR-10"
        assert exp.independent_runs == 5

    def test_create_experiment_invalid_seed(self, db):
        paper = make_paper(db)
        service = ExtractionService(db)
        claim = service.create_claim(paper_id=paper.id)

        with pytest.raises(ValueError, match="Invalid random_seed_reported"):
            service.create_experiment(
                claim_id=claim.id,
                random_seed_reported="invalid",
            )


class TestConditionCreation:
    """Test condition creation."""

    def test_create_condition(self, db):
        paper = make_paper(db)
        service = ExtractionService(db)
        claim = service.create_claim(paper_id=paper.id)
        exp = service.create_experiment(claim_id=claim.id)

        cond = service.create_condition(
            experiment_id=exp.id,
            algorithm="FedX",
            metric_name="Accuracy",
            metric_value="92.5",
            ranking_position=1,
            is_winner=True,
            standard_deviation="0.3",
        )

        assert cond.id is not None
        assert cond.is_winner is True
        assert cond.metric_value == "92.5"


class TestEvidenceQuality:
    """Test evidence quality creation and validation."""

    def test_create_evidence_quality(self, db):
        paper = make_paper(db)
        service = ExtractionService(db)
        claim = service.create_claim(paper_id=paper.id)

        eq = service.create_evidence_quality(
            claim_id=claim.id,
            independent_runs=5,
            random_seed_reported="explicitly_reported",
            uncertainty_reporting="SD",
            sd_type="over independent runs",
            ci_level="95%",
            direct_statistical_test=True,
            statistical_unit="independent trial runs",
            effect_size_reported=False,
            matched_client_partition="YES",
            hyperparameter_tuning_fairness="matched/tuned_baselines",
            ranking_robustness="Observationally Stable",
            evidence_basis=["mean + SD", "direct statistical comparison"],
            author_claim_vs_evidence="direct statistical test supports claim",
        )

        assert eq.id is not None
        assert eq.direct_statistical_test is True
        assert eq.ranking_robustness == "Observationally Stable"

    def test_create_eq_invalid_ranking(self, db):
        paper = make_paper(db)
        service = ExtractionService(db)
        claim = service.create_claim(paper_id=paper.id)

        with pytest.raises(ValueError, match="Invalid ranking_robustness"):
            service.create_evidence_quality(
                claim_id=claim.id,
                ranking_robustness="Invalid",
            )

    def test_create_eq_invalid_partition(self, db):
        paper = make_paper(db)
        service = ExtractionService(db)
        claim = service.create_claim(paper_id=paper.id)

        with pytest.raises(ValueError, match="Invalid matched_client_partition"):
            service.create_evidence_quality(
                claim_id=claim.id,
                matched_client_partition="maybe",
            )

    def test_evidence_profile(self, db):
        paper = make_paper(db)
        service = ExtractionService(db)
        claim = service.create_claim(paper_id=paper.id)

        eq = service.create_evidence_quality(
            claim_id=claim.id,
            independent_runs=5,
            uncertainty_reporting="SD",
            direct_statistical_test=True,
            matched_client_partition="YES",
            ranking_robustness="Observationally Stable",
        )

        profile = eq.get_evidence_profile()
        assert profile["repetition"]["runs"] == 5
        assert profile["uncertainty"]["reporting"] == "SD"
        assert profile["direct_statistics"]["test"] is True
        assert profile["fairness"]["matched_partition"] == "YES"
        assert profile["ranking"]["robustness"] == "Observationally Stable"


class TestExtractionStats:
    """Test extraction statistics."""

    def test_stats_empty(self, db):
        service = ExtractionService(db)
        stats = service.get_extraction_stats()

        assert stats["total_claims"] == 0
        assert stats["total_experiments"] == 0

    def test_stats_with_data(self, db):
        paper = make_paper(db)
        service = ExtractionService(db)

        claim1 = service.create_claim(paper_id=paper.id)
        claim2 = service.create_claim(paper_id=paper.id)
        service.create_experiment(claim_id=claim1.id)
        service.create_evidence_quality(claim_id=claim1.id, direct_statistical_test=True)

        stats = service.get_extraction_stats()
        assert stats["total_claims"] == 2
        assert stats["total_experiments"] == 1
        assert stats["total_evidence_quality"] == 1
        assert stats["direct_statistical_tests"] == 1
        assert stats["papers_with_claims"] == 1


class TestCodebookValues:
    """Test codebook value retrieval."""

    def test_get_codebook(self, db):
        service = ExtractionService(db)
        codebook = service.get_codebook_values()

        assert "claim_scopes" in codebook
        assert "Global Model Accuracy" in codebook["claim_scopes"]
        assert "non_iid_types" in codebook
        assert "Label distribution skew" in codebook["non_iid_types"]
        assert "ranking_robustness" in codebook
        assert "Observationally Stable" in codebook["ranking_robustness"]
