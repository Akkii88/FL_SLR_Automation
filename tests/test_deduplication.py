"""
Tests: Deduplication Engine
=============================
Tests for multi-pass deduplication, manual overrides, and logging.
"""

import json
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.engine import Base
from app.models.paper import Paper
from app.models.deduplication import DeduplicationLog
from app.models.screening import AuditLog
from app.services.deduplication import (
    DeduplicationEngine,
    DeduplicationResult,
    _compute_title_similarity,
    _compute_author_overlap,
    _parse_authors,
    _is_likely_version_relationship,
)


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


def make_paper(
    db,
    title="Test Paper",
    doi=None,
    openalex_id=None,
    year=2023,
    authors=None,
    source_type="journal-article",
    source="Test Journal",
    commit=True,
):
    """Helper to create a test paper."""
    paper = Paper(
        title=title,
        normalized_title=title.lower(),
        doi=doi,
        openalex_id=openalex_id,
        publication_year=year,
        authors=json.dumps(authors) if authors else None,
        source_type=source_type,
        source=source,
        duplicate_status="unique",
    )
    db.add(paper)
    if commit:
        db.commit()
    return paper


class TestTitleSimilarity:
    """Test fuzzy title similarity computation."""

    def test_identical_titles(self):
        assert _compute_title_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        assert _compute_title_similarity("abc", "xyz") < 0.3

    def test_similar_titles(self):
        sim = _compute_title_similarity(
            "federated learning for image classification",
            "federated learning for image classification with non-iid data",
        )
        assert sim > 0.7

    def test_empty_titles(self):
        assert _compute_title_similarity("", "test") == 0.0
        assert _compute_title_similarity("test", "") == 0.0
        assert _compute_title_similarity("", "") == 0.0

    def test_case_insensitive(self):
        assert _compute_title_similarity("Hello World", "hello world") == 1.0


class TestAuthorOverlap:
    """Test author overlap computation."""

    def test_identical_authors(self):
        authors = ["Alice", "Bob", "Charlie"]
        assert _compute_author_overlap(authors, authors) == 1.0

    def test_partial_overlap(self):
        a = ["Alice", "Bob", "Charlie"]
        b = ["Alice", "Bob", "David"]
        overlap = _compute_author_overlap(a, b)
        assert 0.4 < overlap < 0.6

    def test_no_overlap(self):
        a = ["Alice", "Bob"]
        b = ["Charlie", "David"]
        assert _compute_author_overlap(a, b) == 0.0

    def test_empty_authors(self):
        assert _compute_author_overlap([], ["Alice"]) == 0.0
        assert _compute_author_overlap(["Alice"], []) == 0.0


class TestVersionRelationship:
    """Test version relationship detection."""

    def test_conference_vs_journal(self):
        p1 = Paper(source_type="conference-paper", source="ICML")
        p2 = Paper(source_type="journal-article", source="JMLR")
        assert _is_likely_version_relationship(p1, p2) is True

    def test_same_type(self):
        p1 = Paper(source_type="journal-article", source="Nature")
        p2 = Paper(source_type="journal-article", source="Science")
        assert _is_likely_version_relationship(p1, p2) is False

    def test_arxiv_preprint(self):
        p1 = Paper(source_type="preprint", source="arXiv")
        p2 = Paper(source_type="journal-article", source="Test Journal")
        assert _is_likely_version_relationship(p1, p2) is True


class TestDOIMatching:
    """Test DOI exact match deduplication."""

    def test_doi_match(self, db):
        p1 = make_paper(db, title="Paper A", doi="10.1234/test.001")
        p2 = make_paper(db, title="Paper A Second", doi="10.1234/test.001")

        engine = DeduplicationEngine(db)
        results = engine.run_deduplication()

        assert len(results) == 1
        assert results[0].match_type == "doi_exact"
        assert results[0].confidence == 1.0
        assert results[0].is_duplicate is True

    def test_doi_no_match(self, db):
        make_paper(db, title="Paper A", doi="10.1234/test.001")
        make_paper(db, title="Paper B", doi="10.1234/test.002")

        engine = DeduplicationEngine(db)
        results = engine.run_deduplication()

        # No DOI matches expected
        doi_results = [r for r in results if r.match_type == "doi_exact"]
        assert len(doi_results) == 0

    def test_doi_null_not_matched(self, db):
        make_paper(db, title="Paper A", doi=None)
        make_paper(db, title="Paper A", doi=None)

        engine = DeduplicationEngine(db)
        results = engine.run_deduplication()

        doi_results = [r for r in results if r.match_type == "doi_exact"]
        assert len(doi_results) == 0


class TestOpenAlexIDMatching:
    """Test OpenAlex ID exact match deduplication."""

    def test_id_match(self, db):
        p1 = make_paper(db, title="Paper A", openalex_id="W12345")
        p2 = make_paper(db, title="Paper A v2", openalex_id="W12345")

        engine = DeduplicationEngine(db)
        results = engine.run_deduplication()

        id_results = [r for r in results if r.match_type == "openalex_id_exact"]
        assert len(id_results) == 1
        assert id_results[0].confidence == 1.0


class TestTitleYearMatching:
    """Test normalized title + year exact match."""

    def test_title_year_match(self, db):
        p1 = make_paper(
            db, title="Federated Learning Survey", doi=None, openalex_id=None, year=2023,
        )
        p2 = make_paper(
            db, title="Federated Learning Survey", doi=None, openalex_id=None, year=2023,
        )

        engine = DeduplicationEngine(db)
        results = engine.run_deduplication()

        ty_results = [r for r in results if r.match_type == "title_year_exact"]
        assert len(ty_results) == 1
        assert ty_results[0].is_duplicate is True

    def test_different_years_not_matched(self, db):
        make_paper(db, title="Same Title", doi=None, openalex_id=None, year=2022)
        make_paper(db, title="Same Title", doi=None, openalex_id=None, year=2023)

        engine = DeduplicationEngine(db)
        results = engine.run_deduplication()

        ty_results = [r for r in results if r.match_type == "title_year_exact"]
        assert len(ty_results) == 0

    def test_version_relationship_not_auto_matched(self, db):
        make_paper(
            db, title="FedX: A New Method", doi=None, openalex_id=None, year=2023,
            source_type="conference-paper", source="ICML",
        )
        make_paper(
            db, title="FedX: A New Method", doi=None, openalex_id=None, year=2023,
            source_type="journal-article", source="JMLR",
        )

        engine = DeduplicationEngine(db)
        results = engine.run_deduplication()

        # Should be detected but rejected as version relationship
        ty_results = [
            r for r in results
            if r.match_type == "title_year_exact"
        ]
        assert len(ty_results) == 1
        assert ty_results[0].is_duplicate is False


class TestFuzzyTitleMatching:
    """Test fuzzy title similarity deduplication."""

    def test_fuzzy_match(self, db):
        make_paper(
            db, title="Federated Learning for Image Classification",
            doi=None, openalex_id=None, year=2023,
        )
        make_paper(
            db, title="Federated Learning for Image Classification with Non-IID",
            doi=None, openalex_id=None, year=2023,
        )

        engine = DeduplicationEngine(db)
        results = engine.run_deduplication()

        fuzzy_results = [r for r in results if r.match_type == "fuzzy_title"]
        assert len(fuzzy_results) == 1
        assert fuzzy_results[0].confidence >= 0.90

    def test_dissimilar_titles_not_matched(self, db):
        make_paper(
            db, title="Federated Learning Optimization",
            doi=None, openalex_id=None, year=2023,
        )
        make_paper(
            db, title="Deep Reinforcement Learning for Robotics",
            doi=None, openalex_id=None, year=2023,
        )

        engine = DeduplicationEngine(db)
        results = engine.run_deduplication()

        fuzzy_results = [r for r in results if r.match_type == "fuzzy_title"]
        assert len(fuzzy_results) == 0


class TestAuthorYearMatching:
    """Test author/year similarity deduplication."""

    def test_author_year_match(self, db):
        authors_a = ["Alice Smith", "Bob Jones", "Charlie Brown"]
        authors_b = ["Alice Smith", "Bob Jones", "Charlie Brown", "Diana Prince"]

        make_paper(
            db, title="FL Method A", doi=None, openalex_id=None, year=2023,
            authors=authors_a,
        )
        make_paper(
            db, title="FL Method A Extended", doi=None, openalex_id=None, year=2023,
            authors=authors_b,
        )

        engine = DeduplicationEngine(db)
        results = engine.run_deduplication()

        ay_results = [r for r in results if r.match_type == "author_year"]
        assert len(ay_results) == 1
        assert ay_results[0].confidence >= 0.80

    def test_different_years_not_matched(self, db):
        authors = ["Alice Smith", "Bob Jones"]
        make_paper(
            db, title="FL Method", doi=None, openalex_id=None, year=2022,
            authors=authors,
        )
        make_paper(
            db, title="FL Method", doi=None, openalex_id=None, year=2023,
            authors=authors,
        )

        engine = DeduplicationEngine(db)
        results = engine.run_deduplication()

        ay_results = [r for r in results if r.match_type == "author_year"]
        assert len(ay_results) == 0


class TestManualOverride:
    """Test manual confirmation, rejection, and override."""

    def test_confirm_duplicate(self, db):
        p1 = make_paper(db, title="Paper A")
        p2 = make_paper(db, title="Paper A")

        engine = DeduplicationEngine(db)
        log = engine.confirm_duplicate(p1.id, p2.id, canonical_id=p1.id)

        assert log.match_status == "confirmed_duplicate"
        assert log.canonical_paper_id == p1.id

        # Check paper was updated
        p2_refreshed = db.query(Paper).filter(Paper.id == p2.id).first()
        assert p2_refreshed.duplicate_status == "confirmed_duplicate"
        assert p2_refreshed.duplicate_of == p1.id

    def test_reject_duplicate(self, db):
        p1 = make_paper(db, title="Paper A")
        p2 = make_paper(db, title="Paper A")

        # First mark as probable duplicate
        p2.duplicate_status = "probable_duplicate"
        p2.duplicate_of = p1.id
        db.commit()

        engine = DeduplicationEngine(db)
        log = engine.reject_duplicate(p1.id, p2.id, reason="Different methods")

        assert log.match_status == "rejected_not_duplicate"
        assert log.is_override is True

        p2_refreshed = db.query(Paper).filter(Paper.id == p2.id).first()
        assert p2_refreshed.duplicate_status == "unique"

    def test_manual_override(self, db):
        p1 = make_paper(db, title="Paper A")

        engine = DeduplicationEngine(db)
        log = engine.manual_override(
            paper_id=p1.id,
            new_status="manually_retained",
            reason="Conference version and journal extension are different studies",
        )

        assert log.match_status == "manually_overridden"
        assert log.is_override is True

        p1_refreshed = db.query(Paper).filter(Paper.id == p1.id).first()
        assert p1_refreshed.duplicate_status == "manually_retained"


class TestDeduplicationLogging:
    """Test that all deduplication decisions are logged."""

    def test_doi_match_logged(self, db):
        make_paper(db, title="Paper A", doi="10.1234/test.001")
        make_paper(db, title="Paper A v2", doi="10.1234/test.001")

        engine = DeduplicationEngine(db)
        engine.run_deduplication()

        logs = db.query(DeduplicationLog).all()
        assert len(logs) >= 1
        assert logs[0].match_type == "doi_exact"
        assert logs[0].match_confidence == 1.0

    def test_no_duplicate_records_deleted(self, db):
        """Verify that deduplication never deletes records."""
        p1 = make_paper(db, title="Paper A", doi="10.1234/test.001")
        p2 = make_paper(db, title="Paper A v2", doi="10.1234/test.001")

        engine = DeduplicationEngine(db)
        engine.run_deduplication()

        # Both papers should still exist
        count = db.query(Paper).count()
        assert count == 2

    def test_dedup_stats(self, db):
        make_paper(db, title="Unique Paper", doi="10.0001/unique")
        make_paper(db, title="Dup Paper A", doi="10.0001/dup")
        make_paper(db, title="Dup Paper B", doi="10.0001/dup")

        engine = DeduplicationEngine(db)
        engine.run_deduplication()

        stats = engine.get_deduplication_stats()
        assert stats["total_papers"] == 3
        assert stats["unique"] == 1
        assert stats["probable_duplicates"] == 1

    def test_duplicate_groups(self, db):
        p1 = make_paper(db, title="Canonical", doi="10.0001/dup")
        p2 = make_paper(db, title="Duplicate", doi="10.0001/dup")

        engine = DeduplicationEngine(db)
        engine.run_deduplication()

        groups = engine.get_duplicate_groups()
        assert len(groups) == 1
        assert groups[0]["duplicate_count"] == 1


class TestDryRun:
    """Test that dry_run mode does not modify papers."""

    def test_dry_run_no_modification(self, db):
        p1 = make_paper(db, title="Paper A", doi="10.1234/test.001")
        p2 = make_paper(db, title="Paper A v2", doi="10.1234/test.001")

        engine = DeduplicationEngine(db)
        results = engine.run_deduplication(dry_run=True)

        assert len(results) == 1

        # Papers should NOT be modified
        p1_refreshed = db.query(Paper).filter(Paper.id == p1.id).first()
        p2_refreshed = db.query(Paper).filter(Paper.id == p2.id).first()
        assert p1_refreshed.duplicate_status == "unique"
        assert p2_refreshed.duplicate_status == "unique"
