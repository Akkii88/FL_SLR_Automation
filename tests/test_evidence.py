"""
Tests: Ranking Stability Engine & Evidence Dashboard
======================================================
Tests for ranking analysis, evidence profiles, and dashboard endpoints.
"""

import json
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.engine import Base
from app.models.paper import Paper
from app.models.extraction import Claim, Experiment, Condition, EvidenceQuality
from app.services.ranking_engine import RankingStabilityEngine


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


def make_full_claim(db, paper_id):
    """Helper to create a claim with experiment and conditions."""
    claim = Claim(paper_id=paper_id, claim_scope="Global Model Accuracy")
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
            standard_deviation="0.3",
        ),
        Condition(
            experiment_id=exp.id,
            algorithm="FedAvg",
            metric_name="Accuracy",
            metric_value="89.2",
            ranking_position=2,
            is_winner=False,
            standard_deviation="0.4",
        ),
    ]
    db.add_all(conditions)
    db.commit()

    return claim, exp, conditions


class TestRankingAnalysis:
    """Test ranking stability analysis."""

    def test_consistent_winner(self, db):
        paper = make_paper(db)
        claim, exp, conditions = make_full_claim(db, paper.id)

        engine = RankingStabilityEngine(db)
        analysis = engine.analyze_claim_rankings(claim.id)

        assert analysis["winner_consistent_across_conditions"] is True
        assert analysis["consistent_winner"] == "FedX"
        assert len(analysis["algorithms_compared"]) == 2

    def test_no_experiments(self, db):
        paper = make_paper(db)
        claim = Claim(paper_id=paper.id)
        db.add(claim)
        db.commit()

        engine = RankingStabilityEngine(db)
        analysis = engine.analyze_claim_rankings(claim.id)

        assert analysis["total_conditions"] == 0
        assert analysis["winner_consistent_across_conditions"] is True
        assert analysis["consistent_winner"] is None

    def test_claim_not_found(self, db):
        engine = RankingStabilityEngine(db)

        with pytest.raises(ValueError, match="not found"):
            engine.analyze_claim_rankings(9999)


class TestEvidenceSummary:
    """Test evidence summary generation."""

    def test_evidence_summary_with_assessment(self, db):
        paper = make_paper(db)
        claim, _, _ = make_full_claim(db, paper.id)

        eq = EvidenceQuality(
            claim_id=claim.id,
            independent_runs=5,
            random_seed_reported="explicitly_reported",
            uncertainty_reporting="SD",
            sd_type="over independent runs",
            direct_statistical_test=True,
            statistical_unit="independent trial runs",
            matched_client_partition="YES",
            hyperparameter_tuning_fairness="matched/tuned_baselines",
            ranking_robustness="Observationally Stable",
        )
        db.add(eq)
        db.commit()

        engine = RankingStabilityEngine(db)
        summary = engine.get_evidence_summary(claim.id)

        assert summary["has_assessment"] is True
        assert summary["summary"]["repetition"] == "5 runs, seed reported"
        assert summary["summary"]["uncertainty"] == "SD (over independent runs)"
        assert "Yes" in summary["summary"]["direct_statistics"]
        assert summary["summary"]["ranking"] == "Observationally Stable"

    def test_evidence_summary_no_assessment(self, db):
        paper = make_paper(db)
        claim = Claim(paper_id=paper.id)
        db.add(claim)
        db.commit()

        engine = RankingStabilityEngine(db)
        summary = engine.get_evidence_summary(claim.id)

        assert summary["has_assessment"] is False

    def test_repetition_not_reported(self, db):
        paper = make_paper(db)
        claim = Claim(paper_id=paper.id)
        db.add(claim)
        db.commit()

        eq = EvidenceQuality(claim_id=claim.id)
        db.add(eq)
        db.commit()

        engine = RankingStabilityEngine(db)
        summary = engine.get_evidence_summary(claim.id)

        assert summary["summary"]["repetition"] == "Not reported"
        assert summary["summary"]["uncertainty"] == "None"
        assert summary["summary"]["direct_statistics"] == "No"
        assert summary["summary"]["ranking"] == "Not assessed"


class TestOverallEvidenceStats:
    """Test overall evidence statistics."""

    def test_empty_stats(self, db):
        engine = RankingStabilityEngine(db)
        stats = engine.get_overall_evidence_stats()

        assert stats["total_claims"] == 0
        assert stats["assessed_claims"] == 0
        assert stats["assessment_coverage_pct"] == 0

    def test_stats_with_data(self, db):
        paper = make_paper(db)
        claim1, _, _ = make_full_claim(db, paper.id)
        claim2 = Claim(paper_id=paper.id)
        db.add(claim2)
        db.commit()

        eq1 = EvidenceQuality(
            claim_id=claim1.id,
            independent_runs=5,
            direct_statistical_test=True,
            uncertainty_reporting="SD",
            ranking_robustness="Observationally Stable",
            matched_client_partition="YES",
            hyperparameter_tuning_fairness="matched/tuned_baselines",
        )
        eq2 = EvidenceQuality(
            claim_id=claim2.id,
            independent_runs=3,
            direct_statistical_test=False,
            mechanism_level_statistical_test=True,
            uncertainty_reporting="None",
            ranking_robustness="Not Assessable",
        )
        db.add_all([eq1, eq2])
        db.commit()

        engine = RankingStabilityEngine(db)
        stats = engine.get_overall_evidence_stats()

        assert stats["total_claims"] == 2
        assert stats["assessed_claims"] == 2
        assert stats["assessment_coverage_pct"] == 100.0
        assert stats["dimension_3_direct_statistics"]["direct_test"] == 1
        assert stats["dimension_3_direct_statistics"]["mechanism_only"] == 1
        assert stats["dimension_4_fairness"]["matched_partitions"] == 1
        assert stats["dimension_4_fairness"]["tuned_baselines"] == 1


class TestEvidenceProfileGeneration:
    """Test evidence profile structure."""

    def test_full_profile(self, db):
        paper = make_paper(db)
        claim = Claim(paper_id=paper.id)
        db.add(claim)
        db.commit()

        eq = EvidenceQuality(
            claim_id=claim.id,
            independent_runs=10,
            uncertainty_reporting="SD_CI",
            direct_statistical_test=True,
            matched_client_partition="YES",
            ranking_robustness="Explicitly Stable",
        )
        db.add(eq)
        db.commit()

        profile = eq.get_evidence_profile()

        assert profile["repetition"]["runs"] == 10
        assert profile["uncertainty"]["reporting"] == "SD_CI"
        assert profile["direct_statistics"]["test"] is True
        assert profile["fairness"]["matched_partition"] == "YES"
        assert profile["ranking"]["robustness"] == "Explicitly Stable"
