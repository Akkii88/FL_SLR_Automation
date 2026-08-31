"""
Regression test: retry failed paper endpoint.
Tests that POST /api/ai-screening/retry/{paper_id} works correctly.
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


class TestRetryEndpoint:
    """Test the retry endpoint for failed papers."""

    def test_retry_failed_paper_success(self, db):
        """Test retrying a failed paper succeeds."""
        paper = make_paper(db, paper_id=52, title="Paper 52")

        # Create a failed result
        failed_result = AIScreeningResult(
            paper_id=52,
            processing_status="failed",
            error_message="Rate limit exceeded",
            is_active=True,
        )
        db.add(failed_result)
        db.commit()

        service = AIScreeningService(db)

        mock_response = {
            "content": json.dumps({
                "q1_fl_comparison": "YES",
                "q2_non_iid": "YES",
                "q3_superiority_claim": "YES",
                "q4_info_available": "YES",
                "recommendation": "likely_include",
                "confidence": "high",
                "reasoning": "test",
                "q1_evidence": "",
                "q2_evidence": "",
                "q3_evidence": "",
                "q4_evidence": "",
            }),
            "model": "test-model",
        }

        with patch.object(service, '_call_llm', return_value=mock_response):
            result = service.screen_paper(52, use_cache=False)

        assert result.processing_status == "completed"
        assert result.recommendation == "likely_include"

    def test_retry_preserves_failed_history(self, db):
        """Test that retrying preserves previous failed attempts."""
        paper = make_paper(db, paper_id=52)

        # Create 2 failed results
        for _ in range(2):
            db.add(AIScreeningResult(
                paper_id=52,
                processing_status="failed",
                error_message="Rate limit",
                is_active=False,
            ))
        db.commit()

        service = AIScreeningService(db)
        mock_response = {
            "content": json.dumps({
                "q1_fl_comparison": "YES", "q2_non_iid": "YES",
                "q3_superiority_claim": "YES", "q4_info_available": "YES",
                "recommendation": "likely_include", "confidence": "high",
                "reasoning": "test", "q1_evidence": "", "q2_evidence": "",
                "q3_evidence": "", "q4_evidence": "",
            }),
            "model": "test-model",
        }

        with patch.object(service, '_call_llm', return_value=mock_response):
            service.screen_paper(52, use_cache=False)

        # Should have 3 total results: 2 failed + 1 completed
        all_results = db.query(AIScreeningResult).filter(
            AIScreeningResult.paper_id == 52
        ).all()
        assert len(all_results) == 3

        failed_count = sum(1 for r in all_results if r.processing_status == "failed")
        completed_count = sum(1 for r in all_results if r.processing_status == "completed")
        assert failed_count == 2
        assert completed_count == 1

    def test_retry_increases_distinct_count(self, db):
        """Test that successful retry increases distinct completed count."""
        from sqlalchemy import and_, func

        paper = make_paper(db, paper_id=52)

        # Create failed result
        db.add(AIScreeningResult(
            paper_id=52, processing_status="failed",
            error_message="Rate limit", is_active=True
        ))
        db.commit()

        service = AIScreeningService(db)
        mock_response = {
            "content": json.dumps({
                "q1_fl_comparison": "YES", "q2_non_iid": "YES",
                "q3_superiority_claim": "YES", "q4_info_available": "YES",
                "recommendation": "likely_include", "confidence": "high",
                "reasoning": "test", "q1_evidence": "", "q2_evidence": "",
                "q3_evidence": "", "q4_evidence": "",
            }),
            "model": "test-model",
        }

        with patch.object(service, '_call_llm', return_value=mock_response):
            service.screen_paper(52, use_cache=False)

        # Distinct completed count should be 1
        distinct_completed = db.query(func.count(func.distinct(AIScreeningResult.paper_id))).filter(
            AIScreeningResult.processing_status == "completed"
        ).scalar()
        assert distinct_completed == 1

    def test_retry_fails_again_remains_retryable(self, db):
        """Test that a failed retry keeps the paper retryable."""
        paper = make_paper(db, paper_id=52)

        db.add(AIScreeningResult(
            paper_id=52, processing_status="failed",
            error_message="Rate limit", is_active=True
        ))
        db.commit()

        service = AIScreeningService(db)

        def always_fail(system_prompt, user_prompt):
            raise Exception("API timeout")

        with patch.object(service, '_call_llm', side_effect=always_fail):
            result = service.screen_paper(52, use_cache=False)

        assert result.processing_status == "failed"
        assert "API timeout" in result.error_message

    def test_retry_does_not_modify_human_decisions(self, db):
        """Test that retry doesn't modify human screening decisions."""
        from app.models.screening import ScreeningDecision

        paper = make_paper(db, paper_id=52)

        # Create human decision
        human = ScreeningDecision(
            paper_id=52, stage="title_abstract", decision="include",
            q1_fl_comparison="YES", decided_by="user"
        )
        db.add(human)

        # Create failed AI result
        db.add(AIScreeningResult(
            paper_id=52, processing_status="failed",
            error_message="Rate limit", is_active=True
        ))
        db.commit()

        service = AIScreeningService(db)
        mock_response = {
            "content": json.dumps({
                "q1_fl_comparison": "NO", "q2_non_iid": "NO",
                "q3_superiority_claim": "NO", "q4_info_available": "YES",
                "recommendation": "likely_exclude", "confidence": "high",
                "reasoning": "test", "q1_evidence": "", "q2_evidence": "",
                "q3_evidence": "", "q4_evidence": "",
            }),
            "model": "test-model",
        }

        with patch.object(service, '_call_llm', return_value=mock_response):
            service.screen_paper(52, use_cache=False)

        # Human decision unchanged
        human_result = db.query(ScreeningDecision).filter(
            ScreeningDecision.paper_id == 52
        ).first()
        assert human_result.decision == "include"
        assert human_result.decided_by == "user"

    def test_retry_single_paper_not_batch(self, db):
        """Test that retrying paper 52 processes ONLY paper 52."""
        papers = [make_paper(db, paper_id=i, title=f"Paper {i}") for i in range(50, 56)]

        # Create failed result for paper 52
        db.add(AIScreeningResult(
            paper_id=52, processing_status="failed",
            error_message="Rate limit", is_active=True
        ))
        db.commit()

        service = AIScreeningService(db)

        llm_calls = []
        def tracking_llm(system_prompt, user_prompt):
            # Track which papers were sent to LLM
            for i in range(50, 56):
                if f"Paper {i}" in user_prompt:
                    llm_calls.append(i)
            return {
                "content": json.dumps({
                    "q1_fl_comparison": "YES", "q2_non_iid": "YES",
                    "q3_superiority_claim": "YES", "q4_info_available": "YES",
                    "recommendation": "likely_include", "confidence": "high",
                    "reasoning": "test", "q1_evidence": "", "q2_evidence": "",
                    "q3_evidence": "", "q4_evidence": "",
                }),
                "model": "test-model",
            }

        with patch.object(service, '_call_llm', side_effect=tracking_llm):
            result = service.screen_paper(52, use_cache=False)

        # Only paper 52 should have been sent to LLM
        assert llm_calls == [52]
        assert result.paper_id == 52
