"""
Regression tests for evidence quality dashboard counting.
Ensures distinct claim counts are used, not row counts.
"""
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
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
    Base.metadata.drop_all(bind=engine)


def make_paper(db, paper_id=1):
    paper = Paper(
        id=paper_id,
        title=f"Test Paper {paper_id}",
        normalized_title=f"test paper {paper_id}",
    )
    db.add(paper)
    db.commit()
    return paper


def make_claim(db, claim_id=1, paper_id=1):
    claim = Claim(
        id=claim_id,
        paper_id=paper_id,
        claim_scope="Global Model Accuracy",
    )
    db.add(claim)
    db.commit()
    return claim


def make_eq(db, claim_id=1, eq_id=None, **kwargs):
    eq = EvidenceQuality(
        id=eq_id,
        claim_id=claim_id,
        **kwargs,
    )
    db.add(eq)
    db.commit()
    return eq


class TestEvidenceDashboardCounting:
    """Test that evidence dashboard counts distinct claims, not rows."""

    def test_one_claim_one_eq_100_percent(self, db):
        """One claim + one EQ = 100% coverage."""
        make_paper(db)
        make_claim(db)
        make_eq(db, claim_id=1)

        engine = RankingStabilityEngine(db)
        stats = engine.get_overall_evidence_stats()

        assert stats["total_claims"] == 1
        assert stats["assessed_claims"] == 1
        assert stats["assessment_coverage_pct"] == 100.0

    def test_duplicate_eq_rows_not_double_counted(self, db):
        """Duplicate EQ rows for same claim should count as 1 assessed."""
        make_paper(db)
        make_claim(db)

        # Create two EQ records for the same claim (simulating accidental duplicate)
        make_eq(db, claim_id=1, eq_id=1, independent_runs=5)
        make_eq(db, claim_id=1, eq_id=2, independent_runs=None)

        engine = RankingStabilityEngine(db)
        stats = engine.get_overall_evidence_stats()

        # Should count 1 distinct claim, not 2 rows
        assert stats["total_claims"] == 1
        assert stats["assessed_claims"] == 1
        assert stats["assessment_coverage_pct"] == 100.0

    def test_direct_stat_count_uses_distinct_claims(self, db):
        """Direct stat test count should use distinct claims."""
        make_paper(db)
        make_claim(db)

        # Two EQ rows, both with direct_stat=True
        make_eq(db, claim_id=1, eq_id=1, direct_statistical_test=True)
        make_eq(db, claim_id=1, eq_id=2, direct_statistical_test=True)

        engine = RankingStabilityEngine(db)
        stats = engine.get_overall_evidence_stats()

        # Should be 1 distinct claim, not 2
        assert stats["dimension_3_direct_statistics"]["direct_test"] == 1

    def test_ranking_robustness_count_uses_distinct_claims(self, db):
        """Ranking robustness count should use distinct claims."""
        make_paper(db)
        make_claim(db)

        # Two EQ rows, both with same ranking
        make_eq(db, claim_id=1, eq_id=1, ranking_robustness="Not Assessable")
        make_eq(db, claim_id=1, eq_id=2, ranking_robustness="Not Assessable")

        engine = RankingStabilityEngine(db)
        stats = engine.get_overall_evidence_stats()

        # Should be 1 distinct claim
        not_assessable = [
            d for d in stats["dimension_5_ranking"]["distribution"]
            if d["type"] == "Not Assessable"
        ]
        assert len(not_assessable) == 1
        assert not_assessable[0]["count"] == 1

    def test_multiple_claims_correct_count(self, db):
        """Multiple claims should be counted correctly."""
        make_paper(db, paper_id=1)
        make_paper(db, paper_id=2)
        make_paper(db, paper_id=3)

        make_claim(db, claim_id=1, paper_id=1)
        make_claim(db, claim_id=2, paper_id=2)
        make_claim(db, claim_id=3, paper_id=3)

        # Only 2 of 3 claims have EQ
        make_eq(db, claim_id=1)
        make_eq(db, claim_id=2)

        engine = RankingStabilityEngine(db)
        stats = engine.get_overall_evidence_stats()

        assert stats["total_claims"] == 3
        assert stats["assessed_claims"] == 2
        assert stats["assessment_coverage_pct"] == 66.7

    def test_no_claims_zero_coverage(self, db):
        """No claims should result in 0% coverage."""
        engine = RankingStabilityEngine(db)
        stats = engine.get_overall_evidence_stats()

        assert stats["total_claims"] == 0
        assert stats["assessed_claims"] == 0
        assert stats["assessment_coverage_pct"] == 0

    def test_uncertainty_distribution_uses_distinct(self, db):
        """Uncertainty distribution should count distinct claims."""
        make_paper(db)
        make_claim(db)

        # Two EQ rows with same uncertainty reporting
        make_eq(db, claim_id=1, eq_id=1, uncertainty_reporting="SD")
        make_eq(db, claim_id=1, eq_id=2, uncertainty_reporting="SD")

        engine = RankingStabilityEngine(db)
        stats = engine.get_overall_evidence_stats()

        sd_count = [
            d for d in stats["dimension_2_uncertainty"]["distribution"]
            if d["type"] == "SD"
        ]
        assert len(sd_count) == 1
        assert sd_count[0]["count"] == 1
