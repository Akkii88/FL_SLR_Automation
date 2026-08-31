"""
Regression tests for AI screening with provider abstraction.
Updated to mock the new LLMProviderManager interface.
"""
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.engine import Base
from app.models.paper import Paper
from app.models.ai_screening import AIScreeningResult
from app.services.ai_screening import AIScreeningService
from app.services.llm_provider import LLMResponse, LLMError


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


def make_paper(db, paper_id=1, title="Test Paper", abstract="Test abstract about FL."):
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


def make_llm_response(provider="groq"):
    return LLMResponse(
        content=json.dumps({
            "q1_fl_comparison": "YES",
            "q2_non_iid": "YES",
            "q3_superiority_claim": "YES",
            "q4_info_available": "YES",
            "recommendation": "likely_include",
            "confidence": "high",
            "reasoning": "test evidence",
            "q1_evidence": "compares FedAvg and FedProx",
            "q2_evidence": "uses non-IID data",
            "q3_evidence": "outperforms baseline",
            "q4_evidence": "sufficient information",
        }),
        model="test-model",
        provider=provider,
    )


def make_mock_manager(db, response=None, error=None, meta=None):
    """Create a mock LLMProviderManager."""
    manager = MagicMock()

    if error:
        def call(*args, **kwargs):
            raise error
    else:
        def call(*args, **kwargs):
            return response or make_llm_response(), meta or {
                "original_provider": "groq",
                "final_provider": "groq",
                "fallback_used": False,
                "retry_count": 0,
                "errors": [],
            }

    manager.call_with_fallback = call
    return manager


class TestAIScreeningWithProviders:
    """Test AI screening with the new provider abstraction."""

    def test_successful_screening(self, db):
        """Test successful AI screening returns valid result."""
        paper = make_paper(db)
        service = AIScreeningService(db)
        service.llm_manager = make_mock_manager(db)
        result = service.screen_paper(paper.id, use_cache=False)
        assert result.processing_status == "completed"
        assert result.recommendation == "likely_include"
        assert result.confidence == "high"

    def test_groq_succeeds_gemini_not_called(self, db):
        """Test that Gemini is not called when Groq succeeds."""
        paper = make_paper(db)
        service = AIScreeningService(db)
        service.llm_manager = make_mock_manager(db)
        result = service.screen_paper(paper.id, use_cache=False)
        assert result.provider == "groq"
        assert result.fallback_used is False

    def test_provider_provenance_stored(self, db):
        """Test that provider provenance is stored correctly."""
        paper = make_paper(db)
        service = AIScreeningService(db)
        service.llm_manager = make_mock_manager(db)
        result = service.screen_paper(paper.id, use_cache=False)
        assert result.original_provider == "groq"
        assert result.final_provider == "groq"
        assert result.fallback_used is False

    def test_malformed_json_response(self, db):
        """Test handling of malformed LLM JSON."""
        paper = make_paper(db)
        service = AIScreeningService(db)

        bad_response = LLMResponse(
            content="This is not JSON at all",
            model="test-model",
            provider="groq",
        )

        service.llm_manager = make_mock_manager(db, response=bad_response)
        result = service.screen_paper(paper.id, use_cache=False)
        assert result.processing_status == "failed"
        assert "invalid JSON" in result.error_message

    def test_markdown_fenced_json(self, db):
        """Test handling of Markdown-fenced JSON response."""
        paper = make_paper(db)
        service = AIScreeningService(db)

        fenced_response = LLMResponse(
            content='```json\n{"q1_fl_comparison": "NO", "q2_non_iid": "NO", "q3_superiority_claim": "NO", "q4_info_available": "YES", "recommendation": "likely_exclude", "confidence": "high", "reasoning": "test", "q1_evidence": "", "q2_evidence": "", "q3_evidence": "", "q4_evidence": ""}\n```',
            model="test-model",
            provider="groq",
        )

        service.llm_manager = make_mock_manager(db, response=fenced_response)
        result = service.screen_paper(paper.id, use_cache=False)
        assert result.processing_status == "completed"
        assert result.q1_fl_comparison == "NO"

    def test_json_with_extra_text(self, db):
        """Test handling of JSON with extra text before/after."""
        paper = make_paper(db)
        service = AIScreeningService(db)

        messy_response = LLMResponse(
            content='Here is my analysis:\n\n{"q1_fl_comparison": "UNCLEAR", "q2_non_iid": "UNCLEAR", "q3_superiority_claim": "UNCLEAR", "q4_info_available": "NO", "recommendation": "unclear", "confidence": "low", "reasoning": "not enough info", "q1_evidence": "", "q2_evidence": "", "q3_evidence": "", "q4_evidence": ""}\n\nThis is my recommendation.',
            model="test-model",
            provider="groq",
        )

        service.llm_manager = make_mock_manager(db, response=messy_response)
        result = service.screen_paper(paper.id, use_cache=False)
        assert result.processing_status == "completed"
        assert result.q1_fl_comparison == "UNCLEAR"

    def test_both_providers_fail(self, db):
        """Test that paper is marked failed when both providers fail."""
        paper = make_paper(db)
        service = AIScreeningService(db)
        error = LLMError("Both providers failed", provider="manager")
        service.llm_manager = make_mock_manager(db, error=error)
        result = service.screen_paper(paper.id, use_cache=False)
        assert result.processing_status == "failed"

    def test_invalid_q1_values_default_to_unclear(self, db):
        """Test that invalid Q1-Q4 values default to UNCLEAR."""
        paper = make_paper(db)
        service = AIScreeningService(db)

        invalid_response = LLMResponse(
            content=json.dumps({
                "q1_fl_comparison": "maybe",
                "q2_non_iid": "sometimes",
                "q3_superiority_claim": "",
                "q4_info_available": None,
                "recommendation": "invalid_recommendation",
                "confidence": "very_high",
                "reasoning": "test",
                "q1_evidence": "",
                "q2_evidence": "",
                "q3_evidence": "",
                "q4_evidence": "",
            }),
            model="test-model",
            provider="groq",
        )

        service.llm_manager = make_mock_manager(db, response=invalid_response)
        result = service.screen_paper(paper.id, use_cache=False)
        assert result.q1_fl_comparison == "UNCLEAR"
        assert result.q2_non_iid == "UNCLEAR"
        assert result.q3_superiority_claim == "UNCLEAR"
        assert result.q4_info_available == "UNCLEAR"
        assert result.recommendation == "unclear"
        assert result.confidence == "medium"

    def test_result_committed_before_response(self, db):
        """Test that result is committed to DB before returning."""
        paper = make_paper(db)
        service = AIScreeningService(db)
        service.llm_manager = make_mock_manager(db)
        result = service.screen_paper(paper.id, use_cache=False)

        # Verify it's in the database
        db_result = db.query(AIScreeningResult).filter(
            AIScreeningResult.id == result.id
        ).first()
        assert db_result is not None
        assert db_result.processing_status == "completed"

    def test_ai_does_not_modify_screening_decisions(self, db):
        """Test that AI screening doesn't modify human screening decisions."""
        from app.models.screening import ScreeningDecision

        paper = make_paper(db)

        # Create human decision
        human = ScreeningDecision(
            paper_id=paper.id, stage="title_abstract", decision="include",
            q1_fl_comparison="YES", decided_by="user"
        )
        db.add(human)
        db.commit()

        service = AIScreeningService(db)
        service.llm_manager = make_mock_manager(db)
        service.screen_paper(paper.id, use_cache=False)

        # Human decision unchanged
        human_result = db.query(ScreeningDecision).filter(
            ScreeningDecision.paper_id == paper.id
        ).first()
        assert human_result.decision == "include"
        assert human_result.decided_by == "user"


class TestGeminiFallback:
    """Test Gemini fallback behavior."""

    def test_gemini_fallback_on_groq_failure(self, db):
        """Test that Gemini is used when Groq fails."""
        paper = make_paper(db)
        service = AIScreeningService(db)

        gemini_response = LLMResponse(
            content=json.dumps({
                "q1_fl_comparison": "YES", "q2_non_iid": "YES",
                "q3_superiority_claim": "YES", "q4_info_available": "YES",
                "recommendation": "likely_include", "confidence": "high",
                "reasoning": "gemini analysis",
                "q1_evidence": "", "q2_evidence": "",
                "q3_evidence": "", "q4_evidence": "",
            }),
            model="gemini-3.6-flash",
            provider="gemini",
        )

        meta = {
            "original_provider": "groq",
            "final_provider": "gemini",
            "fallback_used": True,
            "retry_count": 5,
            "errors": [{"provider": "groq", "error": "rate limit"}],
        }

        service.llm_manager = make_mock_manager(db, response=gemini_response, meta=meta)
        result = service.screen_paper(paper.id, use_cache=False)

        assert result.processing_status == "completed"
        assert result.fallback_used is True
        assert result.original_provider == "groq"
        assert result.final_provider == "gemini"
        assert result.provider == "gemini"

    def test_daily_limit_triggers_fallback(self, db):
        """Test that daily limit on Groq triggers immediate Gemini fallback."""
        paper = make_paper(db)
        service = AIScreeningService(db)

        gemini_response = LLMResponse(
            content=json.dumps({
                "q1_fl_comparison": "NO", "q2_non_iid": "NO",
                "q3_superiority_claim": "NO", "q4_info_available": "YES",
                "recommendation": "likely_exclude", "confidence": "high",
                "reasoning": "not FL comparison",
                "q1_evidence": "", "q2_evidence": "",
                "q3_evidence": "", "q4_evidence": "",
            }),
            model="gemini-3.6-flash",
            provider="gemini",
        )

        meta = {
            "original_provider": "groq",
            "final_provider": "gemini",
            "fallback_used": True,
            "retry_count": 0,
            "errors": [{"provider": "groq", "error": "daily quota exhausted"}],
        }

        service.llm_manager = make_mock_manager(db, response=gemini_response, meta=meta)
        result = service.screen_paper(paper.id, use_cache=False)

        assert result.processing_status == "completed"
        assert result.fallback_used is True
        assert result.final_provider == "gemini"
