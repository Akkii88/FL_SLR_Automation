"""
Tests for AI screening rate-limit retry logic.
"""
import json
import pytest
import time
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.engine import Base
from app.models.paper import Paper
from app.models.ai_screening import AIScreeningResult
from app.services.ai_screening import AIScreeningService, RateLimitError


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


class TestRateLimitRetry:
    """Test rate-limit retry handling."""

    def test_429_then_success(self, db):
        """Test that a 429 followed by successful retry produces a completed result."""
        paper = make_paper(db, paper_id=1)
        service = AIScreeningService(db)

        call_count = 0
        def mock_call_llm(system_prompt, user_prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RateLimitError("Rate limit exceeded", retry_after=0.1)
            return {
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

        with patch.object(service, '_call_llm', side_effect=mock_call_llm):
            with patch('time.sleep'):  # Skip actual sleep
                result = service.screen_paper(1, use_cache=False)

        assert result.processing_status == "completed"
        assert result.recommendation == "likely_include"
        assert call_count == 2  # First failed, second succeeded

    def test_429_exhausts_max_retries(self, db):
        """Test that repeated 429s eventually fail after max retries."""
        paper = make_paper(db, paper_id=1)
        service = AIScreeningService(db)

        def always_rate_limit(system_prompt, user_prompt):
            raise RateLimitError("Rate limit exceeded", retry_after=0.01)

        with patch.object(service, '_call_llm', side_effect=always_rate_limit):
            with patch('time.sleep'):  # Skip actual sleep
                result = service.screen_paper(1, use_cache=False)

        assert result.processing_status == "failed"
        assert "Rate limit" in result.error_message

    def test_retry_after_header_honored(self, db):
        """Test that Retry-After header value is used for wait time."""
        paper = make_paper(db, paper_id=1)
        service = AIScreeningService(db)

        sleep_times = []
        def mock_sleep(seconds):
            sleep_times.append(seconds)

        call_count = 0
        def mock_call_llm(system_prompt, user_prompt):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RateLimitError("Rate limited", retry_after=1.5)
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

        with patch.object(service, '_call_llm', side_effect=mock_call_llm):
            with patch('time.sleep', side_effect=mock_sleep):
                result = service.screen_paper(1, use_cache=False)

        assert result.processing_status == "completed"
        # Both waits should be approximately 1.5s (from Retry-After)
        assert len(sleep_times) == 2
        for t in sleep_times:
            assert 1.0 <= t <= 2.0  # 1.5s ± 25% jitter

    def test_exponential_backoff_without_retry_after(self, db):
        """Test exponential backoff when Retry-After is absent."""
        paper = make_paper(db, paper_id=1)
        service = AIScreeningService(db)

        sleep_times = []
        def mock_sleep(seconds):
            sleep_times.append(seconds)

        call_count = 0
        def mock_call_llm(system_prompt, user_prompt):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise RateLimitError("Rate limited", retry_after=None)
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

        with patch.object(service, '_call_llm', side_effect=mock_call_llm):
            with patch('time.sleep', side_effect=mock_sleep):
                result = service.screen_paper(1, use_cache=False)

        assert result.processing_status == "completed"
        assert len(sleep_times) == 3
        # Exponential: 2s, 4s, 8s (with ±25% jitter)
        assert sleep_times[0] >= 1.5  # 2s - 25%
        assert sleep_times[1] >= 3.0  # 4s - 25%
        assert sleep_times[2] >= 6.0  # 8s - 25%

    def test_permanent_400_error_not_retried(self, db):
        """Test that permanent errors (400) are NOT retried."""
        paper = make_paper(db, paper_id=1)
        service = AIScreeningService(db)

        call_count = 0
        def mock_call_llm(system_prompt, user_prompt):
            nonlocal call_count
            call_count += 1
            raise ValueError("Bad request: invalid parameter")

        with patch.object(service, '_call_llm', side_effect=mock_call_llm):
            result = service.screen_paper(1, use_cache=False)

        assert result.processing_status == "failed"
        assert call_count == 1  # No retries for non-rate-limit errors

    def test_permanent_401_error_not_retried(self, db):
        """Test that 401 (auth) errors are NOT retried."""
        paper = make_paper(db, paper_id=1)
        service = AIScreeningService(db)

        call_count = 0
        def mock_call_llm(system_prompt, user_prompt):
            nonlocal call_count
            call_count += 1
            raise Exception("401 Unauthorized: Invalid API key")

        with patch.object(service, '_call_llm', side_effect=mock_call_llm):
            result = service.screen_paper(1, use_cache=False)

        assert result.processing_status == "failed"
        assert call_count == 1  # No retries for auth errors

    def test_batch_one_failure_doesnt_stop_others(self, db):
        """Test that one failed paper doesn't terminate the batch."""
        papers = [make_paper(db, paper_id=i, title=f"Paper {i}") for i in range(1, 6)]
        service = AIScreeningService(db)

        call_count = 0
        def mock_call_llm(system_prompt, user_prompt):
            nonlocal call_count
            call_count += 1
            if "Paper 3" in user_prompt:
                raise RateLimitError("Rate limited", retry_after=0.01)
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

        with patch.object(service, '_call_llm', side_effect=mock_call_llm):
            with patch('time.sleep'):
                result = service.batch_screen(batch_size=5)

        assert result["processed"] == 5
        assert result["succeeded"] == 4
        assert result["failed"] == 1

    def test_successful_retry_creates_one_completed_result(self, db):
        """Test that a successful retry creates exactly one completed result."""
        paper = make_paper(db, paper_id=1)
        service = AIScreeningService(db)

        call_count = 0
        def mock_call_llm(system_prompt, user_prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RateLimitError("Rate limited", retry_after=0.01)
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

        with patch.object(service, '_call_llm', side_effect=mock_call_llm):
            with patch('time.sleep'):
                result = service.screen_paper(1, use_cache=False)

        # Should have exactly 1 completed result for this paper
        completed = db.query(AIScreeningResult).filter(
            AIScreeningResult.paper_id == 1,
            AIScreeningResult.processing_status == "completed"
        ).all()
        assert len(completed) == 1

    def test_failed_retry_remains_retryable(self, db):
        """Test that a paper with all retries failed remains in the queue."""
        paper = make_paper(db, paper_id=1)
        service = AIScreeningService(db)

        def always_fail(system_prompt, user_prompt):
            raise RateLimitError("Rate limited", retry_after=0.01)

        with patch.object(service, '_call_llm', side_effect=always_fail):
            with patch('time.sleep'):
                result = service.screen_paper(1, use_cache=False)

        assert result.processing_status == "failed"

        # Paper should still be in the queue (no completed result)
        completed = db.query(AIScreeningResult).filter(
            AIScreeningResult.paper_id == 1,
            AIScreeningResult.processing_status == "completed"
        ).first()
        assert completed is None

    def test_cached_papers_no_new_llm_call(self, db):
        """Test that cached completed papers don't trigger new LLM calls."""
        paper = make_paper(db, paper_id=1)

        # Pre-populate a completed result
        existing = AIScreeningResult(
            paper_id=1,
            processing_status="completed",
            recommendation="likely_include",
            confidence="high",
            is_active=True,
        )
        db.add(existing)
        db.commit()

        service = AIScreeningService(db)

        call_count = 0
        def counting_call(system_prompt, user_prompt):
            nonlocal call_count
            call_count += 1
            return {"content": "{}", "model": "test"}

        with patch.object(service, '_call_llm', side_effect=counting_call):
            result = service.screen_paper(1, use_cache=True)

        assert call_count == 0  # No LLM call made
        assert result.recommendation == "likely_include"

    def test_distinct_paper_counts_in_summary(self, db):
        """Test that summary counts distinct papers, not rows."""
        # Create papers with multiple results
        p1 = make_paper(db, paper_id=1, title="Paper 1")
        p2 = make_paper(db, paper_id=2, title="Paper 2")

        # Paper 1: 2 failed + 1 completed
        for _ in range(2):
            db.add(AIScreeningResult(
                paper_id=1, processing_status="failed", error_message="test",
                is_active=False
            ))
        db.add(AIScreeningResult(
            paper_id=1, processing_status="completed",
            recommendation="likely_include", is_active=True
        ))

        # Paper 2: 1 completed
        db.add(AIScreeningResult(
            paper_id=2, processing_status="completed",
            recommendation="likely_exclude", is_active=True
        ))
        db.commit()

        service = AIScreeningService(db)
        summary = service.get_screening_summary()

        # Should count 2 distinct papers, not 4 rows
        assert summary["ai_screened"] == 2
        assert summary["by_recommendation"]["likely_include"] == 1
        assert summary["by_recommendation"]["likely_exclude"] == 1
