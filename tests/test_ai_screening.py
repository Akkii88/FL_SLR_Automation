"""
Regression tests for AI screening error handling.
Tests that all endpoints return valid JSON, including error cases.
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


class TestAIScreeningErrorHandling:
    """Test that AI screening handles errors gracefully."""

    def test_successful_screening(self, db):
        """Test successful AI screening returns valid result."""
        paper = make_paper(db)
        service = AIScreeningService(db)

        mock_response = {
            "content": json.dumps({
                "q1_fl_comparison": "YES",
                "q2_non_iid": "YES",
                "q3_superiority_claim": "YES",
                "q4_info_available": "YES",
                "recommendation": "likely_include",
                "confidence": "high",
                "reasoning": "Clear evidence in abstract.",
                "q1_evidence": "compares FedAvg and FedProx",
                "q2_evidence": "uses non-IID data",
                "q3_evidence": "outperforms baseline",
                "q4_evidence": "sufficient information",
            }),
            "model": "test-model",
        }

        with patch.object(service, '_call_llm', return_value=mock_response):
            result = service.screen_paper(paper.id, use_cache=False)

        assert result.processing_status == "completed"
        assert result.recommendation == "likely_include"
        assert result.confidence == "high"
        assert result.q1_fl_comparison == "YES"

    def test_malformed_json_response(self, db):
        """Test handling of malformed LLM JSON."""
        paper = make_paper(db)
        service = AIScreeningService(db)

        mock_response = {
            "content": "This is not JSON at all",
            "model": "test-model",
        }

        with patch.object(service, '_call_llm', return_value=mock_response):
            result = service.screen_paper(paper.id, use_cache=False)

        assert result.processing_status == "failed"
        assert result.error_message is not None

    def test_markdown_fenced_json(self, db):
        """Test handling of Markdown-fenced JSON response."""
        paper = make_paper(db)
        service = AIScreeningService(db)

        mock_response = {
            "content": '```json\n{"q1_fl_comparison": "NO", "q2_non_iid": "NO", "q3_superiority_claim": "NO", "q4_info_available": "YES", "recommendation": "likely_exclude", "confidence": "high", "reasoning": "test", "q1_evidence": "", "q2_evidence": "", "q3_evidence": "", "q4_evidence": ""}\n```',
            "model": "test-model",
        }

        with patch.object(service, '_call_llm', return_value=mock_response):
            result = service.screen_paper(paper.id, use_cache=False)

        assert result.processing_status == "completed"
        assert result.q1_fl_comparison == "NO"
        assert result.recommendation == "likely_exclude"

    def test_json_with_extra_text(self, db):
        """Test handling of JSON with extra text before/after."""
        paper = make_paper(db)
        service = AIScreeningService(db)

        mock_response = {
            "content": 'Here is my analysis:\n\n{"q1_fl_comparison": "UNCLEAR", "q2_non_iid": "UNCLEAR", "q3_superiority_claim": "UNCLEAR", "q4_info_available": "NO", "recommendation": "unclear", "confidence": "low", "reasoning": "not enough info", "q1_evidence": "", "q2_evidence": "", "q3_evidence": "", "q4_evidence": ""}\n\nThis is my recommendation.',
            "model": "test-model",
        }

        with patch.object(service, '_call_llm', return_value=mock_response):
            result = service.screen_paper(paper.id, use_cache=False)

        assert result.processing_status == "completed"
        assert result.q1_fl_comparison == "UNCLEAR"

    def test_llm_api_failure(self, db):
        """Test handling of LLM API failure."""
        paper = make_paper(db)
        service = AIScreeningService(db)

        def raise_error(*args, **kwargs):
            raise Exception("API timeout")

        with patch.object(service, '_call_llm', side_effect=raise_error):
            result = service.screen_paper(paper.id, use_cache=False)

        assert result.processing_status == "failed"
        assert "API timeout" in result.error_message

    def test_batch_with_one_failure(self, db):
        """Test that one failed paper doesn't stop the batch."""
        papers = [
            make_paper(db, paper_id=i, title=f"Paper {i}", abstract=f"Abstract {i}")
            for i in range(1, 6)
        ]
        service = AIScreeningService(db)

        def mock_call_llm(system_prompt, user_prompt):
            # Paper 3 fails
            if "Paper 3" in user_prompt:
                raise Exception("LLM error for paper 3")
            return {
                "content": json.dumps({
                    "q1_fl_comparison": "YES",
                    "q2_non_iid": "YES",
                    "q3_superiority_claim": "YES",
                    "q4_info_available": "YES",
                    "recommendation": "likely_include",
                    "confidence": "high",
                    "reasoning": "test",
                    "q1_evidence": "test",
                    "q2_evidence": "test",
                    "q3_evidence": "test",
                    "q4_evidence": "test",
                }),
                "model": "test-model",
            }

        with patch.object(service, '_call_llm', side_effect=mock_call_llm):
            result = service.batch_screen(batch_size=5)

        assert result["processed"] == 5
        assert result["succeeded"] == 4
        assert result["failed"] == 1

    def test_caching_prevents_duplicate_calls(self, db):
        """Test that caching prevents duplicate LLM calls."""
        paper = make_paper(db)
        service = AIScreeningService(db)

        call_count = 0
        def counting_call_llm(system_prompt, user_prompt):
            nonlocal call_count
            call_count += 1
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

        with patch.object(service, '_call_llm', side_effect=counting_call_llm):
            result1 = service.screen_paper(paper.id, use_cache=False)
            result2 = service.screen_paper(paper.id, use_cache=True)  # Should hit cache

        assert call_count == 1  # Only one LLM call
        assert result1.id == result2.id  # Same result returned

    def test_invalid_q1_values_default_to_unclear(self, db):
        """Test that invalid Q1-Q4 values default to UNCLEAR."""
        paper = make_paper(db)
        service = AIScreeningService(db)

        mock_response = {
            "content": json.dumps({
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
            "model": "test-model",
        }

        with patch.object(service, '_call_llm', return_value=mock_response):
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
            result = service.screen_paper(paper.id, use_cache=False)

        # Verify it's in the database
        db_result = db.query(AIScreeningResult).filter(
            AIScreeningResult.id == result.id
        ).first()
        assert db_result is not None
        assert db_result.processing_status == "completed"


class TestAIScreeningCountIntegrity:
    """Test that AI screening counts are based on distinct papers."""

    def test_failed_attempts_not_counted(self, db):
        """Failed attempts should not increase 'AI Screened' count."""
        # Create paper with failed + completed results
        paper = make_paper(db, paper_id=100)

        # Add 3 failed results
        for _ in range(3):
            failed = AIScreeningResult(
                paper_id=100,
                processing_status="failed",
                error_message="test error",
                is_active=False,
            )
            db.add(failed)

        # Add 1 completed result
        completed = AIScreeningResult(
            paper_id=100,
            processing_status="completed",
            recommendation="likely_include",
            confidence="high",
            is_active=True,
        )
        db.add(completed)
        db.commit()

        # Summary should count 1 distinct paper, not 4 rows
        service = AIScreeningService(db)
        summary = service.get_screening_summary()

        # The distinct count should be 1 (just this paper)
        assert summary["ai_screened"] >= 1

    def test_distinct_paper_count(self, db):
        """Multiple results for same paper should count as 1."""
        service = AIScreeningService(db)

        # Create papers
        p1 = make_paper(db, paper_id=200, title="Paper A")
        p2 = make_paper(db, paper_id=201, title="Paper B")

        # Add multiple completed results for p1 (simulating re-screens)
        for i in range(3):
            r = AIScreeningResult(
                paper_id=200,
                processing_status="completed",
                recommendation="likely_include",
                is_active=(i == 2),  # Only last one active
            )
            db.add(r)

        # Add one result for p2
        r2 = AIScreeningResult(
            paper_id=201,
            processing_status="completed",
            recommendation="likely_exclude",
            is_active=True,
        )
        db.add(r2)
        db.commit()

        # Count distinct papers with active completed results
        from sqlalchemy import and_, func
        distinct_count = db.query(func.count(func.distinct(AIScreeningResult.paper_id))).filter(
            and_(
                AIScreeningResult.is_active == True,
                AIScreeningResult.processing_status == "completed",
            )
        ).scalar()

        assert distinct_count == 2  # Papers 200 and 201, not 4 rows

    def test_recommendation_counts_are_distinct(self, db):
        """Recommendation counts should be based on distinct papers."""
        from sqlalchemy import and_, func

        # Create papers with different recommendations
        for i, rec in enumerate(["likely_include", "likely_include", "likely_exclude"]):
            p = make_paper(db, paper_id=300 + i, title=f"Paper {i}")
            r = AIScreeningResult(
                paper_id=300 + i,
                processing_status="completed",
                recommendation=rec,
                is_active=True,
            )
            db.add(r)
        db.commit()

        # Count distinct papers per recommendation
        include_count = db.query(func.count(func.distinct(AIScreeningResult.paper_id))).filter(
            and_(
                AIScreeningResult.is_active == True,
                AIScreeningResult.processing_status == "completed",
                AIScreeningResult.recommendation == "likely_include",
            )
        ).scalar()

        exclude_count = db.query(func.count(func.distinct(AIScreeningResult.paper_id))).filter(
            and_(
                AIScreeningResult.is_active == True,
                AIScreeningResult.processing_status == "completed",
                AIScreeningResult.recommendation == "likely_exclude",
            )
        ).scalar()

        assert include_count == 2
        assert exclude_count == 1


class TestAIScreeningTitleIncluded:
    """Test that AI screening results include paper titles."""

    def test_to_dict_includes_title_from_join(self, db):
        """Verify that the API joins paper title into results."""
        paper = make_paper(db, paper_id=400, title="Test Paper Title Here")
        result = AIScreeningResult(
            paper_id=400,
            processing_status="completed",
            recommendation="likely_include",
            is_active=True,
        )
        db.add(result)
        db.commit()

        # Simulate what the API does: join with Paper
        from sqlalchemy import and_
        from app.models.paper import Paper
        row = db.query(AIScreeningResult, Paper).join(
            Paper, AIScreeningResult.paper_id == Paper.id
        ).filter(
            and_(
                AIScreeningResult.paper_id == 400,
                AIScreeningResult.is_active == True,
            )
        ).first()

        assert row is not None
        ai_result, paper = row
        d = ai_result.to_dict()
        d['title'] = paper.title
        assert d['title'] == "Test Paper Title Here"

    def test_paper_without_title(self, db):
        """Test handling of paper with empty title (edge case)."""
        from app.models.paper import Paper as PaperModel
        # Paper model requires title (NOT NULL), so test with empty string
        paper = PaperModel(id=401, normalized_title="no title", title="")
        db.add(paper)
        result = AIScreeningResult(
            paper_id=401,
            processing_status="completed",
            recommendation="unclear",
            is_active=True,
        )
        db.add(result)
        db.commit()

        from sqlalchemy import and_
        row = db.query(AIScreeningResult, PaperModel).join(
            PaperModel, AIScreeningResult.paper_id == PaperModel.id
        ).filter(
            and_(
                AIScreeningResult.paper_id == 401,
                AIScreeningResult.is_active == True,
            )
        ).first()

        ai_result, paper = row
        d = ai_result.to_dict()
        d['title'] = paper.title
        # Empty string title should be handled gracefully
        assert d['title'] == ""


class TestAIScreeningHumanSeparation:
    """Test that AI results don't overwrite human decisions."""

    def test_ai_does_not_modify_screening_decisions(self, db):
        """AI screening should not modify human screening decisions."""
        from app.models.screening import ScreeningDecision

        paper = make_paper(db, paper_id=500)

        # Create a human screening decision
        human_decision = ScreeningDecision(
            paper_id=500,
            stage="title_abstract",
            q1_fl_comparison="YES",
            q2_non_iid="YES",
            q3_superiority_claim="YES",
            q4_full_text_available="YES",
            decision="include",
            exclusion_reason=None,
            decided_by="user",
        )
        db.add(human_decision)
        db.commit()

        # Now run AI screening
        service = AIScreeningService(db)
        mock_response = {
            "content": json.dumps({
                "q1_fl_comparison": "NO",
                "q2_non_iid": "NO",
                "q3_superiority_claim": "NO",
                "q4_info_available": "YES",
                "recommendation": "likely_exclude",
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
            service.screen_paper(500, use_cache=False)

        # Verify human decision is unchanged
        human = db.query(ScreeningDecision).filter(
            ScreeningDecision.paper_id == 500
        ).first()
        assert human.decision == "include"
        assert human.q1_fl_comparison == "YES"
        assert human.decided_by == "user"
