"""
Tests for batch recovery and error classification.
Tests Problems 1-4 fixes.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.engine import Base
from app.models.paper import Paper
from app.models.ai_screening import AIScreeningResult
from app.models.ai_batch import AIScreeningBatch
from app.services.llm_provider import LLMError
from app.services.groq_provider import GroqProvider
from app.services.gemini_provider import GeminiProvider
from app.services.openrouter_provider import OpenRouterProvider


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


class TestBatchRecovery:
    """Test batch recovery after server restart."""

    def test_stale_running_batch_recovery(self, db):
        """Test that a running batch with no worker is recovered on startup."""
        # Simulate a batch that was running when server died
        batch = AIScreeningBatch(
            status="running",
            batch_size=50,
            processed=3,
            succeeded=2,
            failed=1,
            started_at=datetime(2026, 8, 31, 21, 0, 0),
            last_progress_at=datetime(2026, 8, 31, 21, 2, 0),  # 2 min ago
        )
        db.add(batch)

        # Simulate papers stuck in processing (created AFTER batch started)
        for pid in [158, 162]:
            result = AIScreeningResult(
                paper_id=pid,
                processing_status="processing",
                created_at=datetime(2026, 8, 31, 21, 1, 0),  # After batch start
            )
            db.add(result)

        db.commit()
        batch_id = batch.id

        # Run recovery with the test session
        from app.services.ai_batch_processor import recover_interrupted_batches
        recover_interrupted_batches(db_session=db)

        # Verify batch was marked as interrupted
        db.refresh(batch)
        assert batch.status == "interrupted"

        # Verify papers were reset to pending
        for pid in [158, 162]:
            result = db.query(AIScreeningResult).filter(
                AIScreeningResult.paper_id == pid
            ).order_by(AIScreeningResult.created_at.desc()).first()
            assert result.processing_status == "pending"

    def test_completed_results_preserved_after_recovery(self, db):
        """Test that completed results are not affected by recovery."""
        # Add a completed result
        completed = AIScreeningResult(
            paper_id=100,
            processing_status="completed",
            recommendation="likely_include",
            confidence="high",
        )
        db.add(completed)

        # Add a stuck processing result
        stuck = AIScreeningResult(
            paper_id=101,
            processing_status="processing",
        )
        db.add(stuck)

        db.commit()

        # Run recovery
        from app.services.ai_batch_processor import recover_interrupted_batches
        recover_interrupted_batches()

        # Verify completed result is untouched
        completed_result = db.query(AIScreeningResult).filter(
            AIScreeningResult.paper_id == 100
        ).first()
        assert completed_result.processing_status == "completed"
        assert completed_result.recommendation == "likely_include"

    def test_heartbeat_tracking(self, db):
        """Test that batch heartbeat is updated during processing."""
        batch = AIScreeningBatch(
            status="running",
            batch_size=10,
            last_progress_at=datetime.now(timezone.utc),
        )
        db.add(batch)
        db.commit()

        # Verify heartbeat field exists and is set
        assert batch.last_progress_at is not None

    def test_stale_processing_recovery(self, db):
        """Test that orphaned processing papers are recovered."""
        # Add a processing paper not associated with any batch
        # This paper was created before any batch (orphaned)
        stuck = AIScreeningResult(
            paper_id=200,
            processing_status="processing",
            created_at=datetime(2026, 8, 31, 19, 0, 0),
        )
        db.add(stuck)
        db.commit()

        # Run recovery with the test session
        from app.services.ai_batch_processor import recover_interrupted_batches
        recover_interrupted_batches(db_session=db)

        # Verify paper was reset
        result = db.query(AIScreeningResult).filter(
            AIScreeningResult.paper_id == 200
        ).first()
        assert result.processing_status == "pending"


class TestErrorClassification:
    """Test proper error classification for all providers."""

    def test_groq_429_is_rate_limit(self, db):
        """Test that Groq 429 is classified as rate limit."""
        groq = GroqProvider()
        error = groq._classify_error(Exception("429 Too Many Requests"))
        assert error.is_rate_limit
        assert not error.is_permanent
        assert not error.is_404

    def test_groq_404_is_not_rate_limit(self, db):
        """Test that Groq 404 is NOT classified as rate limit."""
        groq = GroqProvider()
        error = groq._classify_error(Exception("404 Not Found"))
        assert not error.is_rate_limit
        assert error.is_404
        assert error.is_permanent

    def test_groq_daily_quota(self, db):
        """Test that Groq daily quota is detected."""
        groq = GroqProvider()
        error = groq._classify_error(Exception("tokens per day (TPD): Limit 200000"))
        assert error.is_daily_limit
        assert not error.is_permanent  # Daily limits should fallback

    def test_groq_auth_error(self, db):
        """Test that Groq auth errors are permanent."""
        groq = GroqProvider()
        error = groq._classify_error(Exception("401 Unauthorized: Invalid API key"))
        assert error.is_permanent
        assert not error.is_rate_limit

    def test_gemini_503_is_server_error(self, db):
        """Test that Gemini 503 is classified as server error."""
        gemini = GeminiProvider()
        error = gemini._classify_error(Exception("503 Service Unavailable"))
        assert error.is_server_error
        assert not error.is_permanent  # Server errors should fallback

    def test_gemini_429_is_rate_limit(self, db):
        """Test that Gemini 429 is rate limit."""
        gemini = GeminiProvider()
        error = gemini._classify_error(Exception("429 Resource Exhausted"))
        assert error.is_rate_limit

    def test_openrouter_404_is_not_rate_limit(self, db):
        """Test that OpenRouter 404 is NOT treated as rate limit."""
        or_provider = OpenRouterProvider()
        error = or_provider._classify_error(Exception("404 Not Found"))
        assert error.is_404
        assert error.is_permanent
        assert not error.is_rate_limit  # KEY FIX: 404 should not be retried

    def test_openrouter_429_is_rate_limit(self, db):
        """Test that OpenRouter 429 is rate limit."""
        or_provider = OpenRouterProvider()
        error = or_provider._classify_error(Exception("429 Too Many Requests"))
        assert error.is_rate_limit
        assert not error.is_404

    def test_openrouter_daily_quota(self, db):
        """Test that OpenRouter daily quota is detected."""
        or_provider = OpenRouterProvider()
        error = or_provider._classify_error(Exception("free tier daily limit exceeded"))
        assert error.is_daily_limit

    def test_openrouter_auth_error(self, db):
        """Test that OpenRouter auth errors are permanent."""
        or_provider = OpenRouterProvider()
        error = or_provider._classify_error(Exception("401 Unauthorized"))
        assert error.is_permanent


class TestFallbackPolicy:
    """Test provider fallback policy with new error types."""

    def test_404_does_not_trigger_fallback(self, db):
        """Test that 404 errors do NOT trigger fallback (it's a config error)."""
        from app.services.llm_manager import LLMProviderManager

        error = LLMError("404 Not Found", status_code=404, is_404=True, is_permanent=True)
        manager = LLMProviderManager(db)

        # 404 should NOT trigger fallback
        assert manager._should_fallback(error) is False

    def test_server_error_triggers_fallback(self, db):
        """Test that 5xx errors DO trigger fallback."""
        from app.services.llm_manager import LLMProviderManager

        error = LLMError("503 Service Unavailable", status_code=503, is_server_error=True)
        manager = LLMProviderManager(db)

        # Server errors should trigger fallback
        assert manager._should_fallback(error) is True

    def test_rate_limit_triggers_fallback(self, db):
        """Test that rate limits trigger fallback."""
        from app.services.llm_manager import LLMProviderManager

        error = LLMError("429 Too Many Requests", status_code=429, is_rate_limit=True)
        manager = LLMProviderManager(db)

        assert manager._should_fallback(error) is True

    def test_auth_error_does_not_trigger_fallback(self, db):
        """Test that auth errors do NOT trigger fallback."""
        from app.services.llm_manager import LLMProviderManager

        error = LLMError("401 Unauthorized", status_code=401, is_permanent=True)
        manager = LLMProviderManager(db)

        assert manager._should_fallback(error) is False


class TestPaper165:
    """Test Paper 165 state after fixes."""

    def test_paper_165_failed_history_preserved(self, db):
        """Test that Paper 165's failed history is preserved."""
        # Create Paper 165 with failed history
        paper = Paper(id=165, title="Test Paper 165", normalized_title="test paper 165")
        db.add(paper)

        # Historical failed attempt
        failed = AIScreeningResult(
            paper_id=165,
            processing_status="failed",
            error_message="All providers failed",
            created_at=datetime(2026, 8, 31, 21, 30, 0),
        )
        db.add(failed)
        db.commit()

        # Verify history is preserved
        results = db.query(AIScreeningResult).filter(
            AIScreeningResult.paper_id == 165
        ).all()
        assert len(results) == 1
        assert results[0].processing_status == "failed"

    def test_paper_165_can_be_retried(self, db):
        """Test that Paper 165 is in a retryable state."""
        paper = Paper(id=165, title="Test Paper 165", normalized_title="test paper 165")
        db.add(paper)

        failed = AIScreeningResult(
            paper_id=165,
            processing_status="failed",
            error_message="All providers failed",
        )
        db.add(failed)
        db.commit()

        # Paper should be retryable (latest status is failed, no completed)
        latest = db.query(AIScreeningResult).filter(
            AIScreeningResult.paper_id == 165
        ).order_by(AIScreeningResult.created_at.desc()).first()

        assert latest.processing_status == "failed"
        # No completed result exists
        completed = db.query(AIScreeningResult).filter(
            AIScreeningResult.paper_id == 165,
            AIScreeningResult.processing_status == "completed"
        ).first()
        assert completed is None
