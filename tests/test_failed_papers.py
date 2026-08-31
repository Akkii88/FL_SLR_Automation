"""
Regression tests for failed-papers endpoint.
Tests that failed papers are correctly identified and returned.
"""
import json
import pytest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.engine import Base
from app.models.paper import Paper
from app.models.ai_screening import AIScreeningResult
from app.services.ai_screening import AIScreeningService


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


def make_paper(db, paper_id=1, title="Test Paper", abstract="Test abstract."):
    paper = Paper(
        id=paper_id,
        title=title,
        normalized_title=title.lower(),
        abstract=abstract,
        publication_year=2023,
        source_type="journal-article",
    )
    db.add(paper)
    db.commit()
    return paper


class TestFailedPapersEndpoint:
    """Test the failed-papers retrieval logic."""

    def test_failed_paper_appears_in_failed_list(self, db):
        """A paper with failed status should appear in failed-papers."""
        paper = make_paper(db, paper_id=52, title="Paper 52")

        failed_result = AIScreeningResult(
            paper_id=52,
            processing_status="failed",
            error_message="Rate limit exceeded",
            is_active=True,
        )
        db.add(failed_result)
        db.commit()

        # Query like the endpoint does
        from sqlalchemy import and_, func
        latest = db.query(
            AIScreeningResult.paper_id,
            func.max(AIScreeningResult.created_at).label('max_created')
        ).group_by(AIScreeningResult.paper_id).subquery()

        rows = db.query(AIScreeningResult, Paper).join(
            Paper, AIScreeningResult.paper_id == Paper.id
        ).join(
            latest,
            and_(
                AIScreeningResult.paper_id == latest.c.paper_id,
                AIScreeningResult.created_at == latest.c.max_created,
            )
        ).filter(
            AIScreeningResult.processing_status == 'failed'
        ).all()

        assert len(rows) == 1
        assert rows[0][1].id == 52

    def test_completed_paper_not_in_failed_list(self, db):
        """A paper with completed status should NOT appear in failed-papers."""
        paper = make_paper(db, paper_id=1, title="Completed Paper")

        completed_result = AIScreeningResult(
            paper_id=1,
            processing_status="completed",
            recommendation="likely_include",
            is_active=True,
        )
        db.add(completed_result)
        db.commit()

        from sqlalchemy import and_, func
        latest = db.query(
            AIScreeningResult.paper_id,
            func.max(AIScreeningResult.created_at).label('max_created')
        ).group_by(AIScreeningResult.paper_id).subquery()

        rows = db.query(AIScreeningResult, Paper).join(
            Paper, AIScreeningResult.paper_id == Paper.id
        ).join(
            latest,
            and_(
                AIScreeningResult.paper_id == latest.c.paper_id,
                AIScreeningResult.created_at == latest.c.max_created,
            )
        ).filter(
            AIScreeningResult.processing_status == 'failed'
        ).all()

        assert len(rows) == 0

    def test_failed_paper_with_multiple_attempts_appears_once(self, db):
        """A paper with multiple failed attempts should appear exactly once."""
        paper = make_paper(db, paper_id=52, title="Paper 52")

        # Add 3 failed attempts
        for i in range(3):
            db.add(AIScreeningResult(
                paper_id=52,
                processing_status="failed",
                error_message=f"Attempt {i+1} failed",
                is_active=(i == 2),  # Only last one active
            ))
        db.commit()

        from sqlalchemy import and_, func
        latest = db.query(
            AIScreeningResult.paper_id,
            func.max(AIScreeningResult.created_at).label('max_created')
        ).group_by(AIScreeningResult.paper_id).subquery()

        rows = db.query(AIScreeningResult, Paper).join(
            Paper, AIScreeningResult.paper_id == Paper.id
        ).join(
            latest,
            and_(
                AIScreeningResult.paper_id == latest.c.paper_id,
                AIScreeningResult.created_at == latest.c.max_created,
            )
        ).filter(
            AIScreeningResult.processing_status == 'failed'
        ).all()

        assert len(rows) == 1  # Paper 52 appears once, not 3 times

    def test_failed_then_completed_not_in_failed_list(self, db):
        """A paper that failed then succeeded should NOT appear in failed-papers."""
        paper = make_paper(db, paper_id=1, title="Paper 1")

        # First failed
        db.add(AIScreeningResult(
            paper_id=1,
            processing_status="failed",
            error_message="Rate limit",
            is_active=False,
        ))
        # Then completed
        db.add(AIScreeningResult(
            paper_id=1,
            processing_status="completed",
            recommendation="likely_include",
            is_active=True,
        ))
        db.commit()

        from sqlalchemy import and_, func
        latest = db.query(
            AIScreeningResult.paper_id,
            func.max(AIScreeningResult.created_at).label('max_created')
        ).group_by(AIScreeningResult.paper_id).subquery()

        rows = db.query(AIScreeningResult, Paper).join(
            Paper, AIScreeningResult.paper_id == Paper.id
        ).join(
            latest,
            and_(
                AIScreeningResult.paper_id == latest.c.paper_id,
                AIScreeningResult.created_at == latest.c.max_created,
            )
        ).filter(
            AIScreeningResult.processing_status == 'failed'
        ).all()

        assert len(rows) == 0  # Latest is completed, not failed

    def test_failed_papers_use_distinct_paper_ids(self, db):
        """Each failed paper should appear exactly once."""
        for pid in [1, 2, 3]:
            make_paper(db, paper_id=pid, title=f"Paper {pid}")
            db.add(AIScreeningResult(
                paper_id=pid,
                processing_status="failed",
                error_message="Rate limit",
                is_active=True,
            ))
        db.commit()

        from sqlalchemy import and_, func
        latest = db.query(
            AIScreeningResult.paper_id,
            func.max(AIScreeningResult.created_at).label('max_created')
        ).group_by(AIScreeningResult.paper_id).subquery()

        rows = db.query(AIScreeningResult, Paper).join(
            Paper, AIScreeningResult.paper_id == Paper.id
        ).join(
            latest,
            and_(
                AIScreeningResult.paper_id == latest.c.paper_id,
                AIScreeningResult.created_at == latest.c.max_created,
            )
        ).filter(
            AIScreeningResult.processing_status == 'failed'
        ).all()

        assert len(rows) == 3
        paper_ids = [r[1].id for r in rows]
        assert len(set(paper_ids)) == 3  # All distinct

    def test_paper_52_is_retryable(self, db):
        """Paper 52 with failed status should be retryable."""
        paper = make_paper(db, paper_id=52, title="Paper 52")

        db.add(AIScreeningResult(
            paper_id=52,
            processing_status="failed",
            error_message="Error code: 429 - Rate limit",
            is_active=True,
        ))
        db.commit()

        # Check no completed result exists
        from sqlalchemy import and_
        completed = db.query(AIScreeningResult).filter(
            and_(
                AIScreeningResult.paper_id == 52,
                AIScreeningResult.is_active == True,
                AIScreeningResult.processing_status == "completed",
            )
        ).first()
        assert completed is None

        # Check latest is failed
        latest = db.query(AIScreeningResult).filter(
            AIScreeningResult.paper_id == 52
        ).order_by(AIScreeningResult.created_at.desc()).first()
        assert latest.processing_status == "failed"
