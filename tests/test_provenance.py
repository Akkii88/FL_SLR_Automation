"""
Tests: Provenance Tracking
============================
Tests for source provenance and search family tracking.
"""

import json
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.engine import Base
from app.models.paper import Paper
from app.models.search_run import SearchRun, SearchRunPaper, SourceProvenance
from app.models.screening import AuditLog


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


class TestSourceProvenance:
    """Test source provenance model."""

    def test_create_provenance(self, db):
        paper = Paper(title="Test Paper", normalized_title="test paper")
        db.add(paper)
        db.flush()

        prov = SourceProvenance(
            paper_id=paper.id,
            source="OpenAlex",
            search_family="A",
            retrieval_timestamp=datetime.now(timezone.utc),
        )
        db.add(prov)
        db.commit()

        assert prov.id is not None
        assert prov.source == "OpenAlex"
        assert prov.search_family == "A"

    def test_multiple_provenance_for_paper(self, db):
        """A paper found by multiple searches should have multiple provenance records."""
        paper = Paper(title="Multi-Source Paper", normalized_title="multi-source paper")
        db.add(paper)
        db.flush()

        # Found by search family A
        prov1 = SourceProvenance(
            paper_id=paper.id,
            source="OpenAlex",
            search_family="A",
            retrieval_timestamp=datetime.now(timezone.utc),
        )
        db.add(prov1)

        # Also found by search family C
        prov2 = SourceProvenance(
            paper_id=paper.id,
            source="OpenAlex",
            search_family="C",
            retrieval_timestamp=datetime.now(timezone.utc),
        )
        db.add(prov2)

        # Also from Semantic Scholar (future)
        prov3 = SourceProvenance(
            paper_id=paper.id,
            source="Semantic Scholar",
            search_family=None,
            retrieval_timestamp=datetime.now(timezone.utc),
        )
        db.add(prov3)

        db.commit()

        # Verify all provenance records exist
        all_prov = db.query(SourceProvenance).filter(
            SourceProvenance.paper_id == paper.id
        ).all()
        assert len(all_prov) == 3

        families = [p.search_family for p in all_prov]
        assert "A" in families
        assert "C" in families

    def test_provenance_relationship(self, db):
        paper = Paper(title="Rel Test", normalized_title="rel test")
        db.add(paper)
        db.flush()

        prov = SourceProvenance(
            paper_id=paper.id,
            source="OpenAlex",
            search_family="B",
            retrieval_timestamp=datetime.now(timezone.utc),
        )
        db.add(prov)
        db.commit()

        # Access via relationship
        assert len(paper.provenance) == 1
        assert paper.provenance[0].source == "OpenAlex"


class TestSearchRunPaper:
    """Test search run to paper association."""

    def test_link_paper_to_search_run(self, db):
        paper = Paper(title="Link Test", normalized_title="link test")
        db.add(paper)
        db.flush()

        run = SearchRun(
            source="OpenAlex",
            search_family="A",
            exact_query="test query",
            search_date=datetime.now(timezone.utc),
            start_time=datetime.now(timezone.utc),
        )
        db.add(run)
        db.flush()

        link = SearchRunPaper(search_run_id=run.id, paper_id=paper.id)
        db.add(link)
        db.commit()

        assert link.id is not None

    def test_search_run_papers_relationship(self, db):
        paper1 = Paper(title="Paper 1", normalized_title="paper 1")
        paper2 = Paper(title="Paper 2", normalized_title="paper 2")
        db.add_all([paper1, paper2])
        db.flush()

        run = SearchRun(
            source="OpenAlex",
            search_family="A",
            exact_query="test",
            search_date=datetime.now(timezone.utc),
            start_time=datetime.now(timezone.utc),
        )
        db.add(run)
        db.flush()

        db.add_all([
            SearchRunPaper(search_run_id=run.id, paper_id=paper1.id),
            SearchRunPaper(search_run_id=run.id, paper_id=paper2.id),
        ])
        db.commit()

        assert len(run.papers) == 2
