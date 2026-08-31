"""
Tests: Screening Service
==========================
Tests for screening decision logic, validation, auto-suggestion, and progress.
"""

import json
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.engine import Base
from app.models.paper import Paper
from app.models.screening import ScreeningDecision, AuditLog
from app.services.screening import ScreeningService


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


def make_paper(db, title="Test Paper", status="not_screened", duplicate_status="unique"):
    """Helper to create a test paper."""
    paper = Paper(
        title=title,
        normalized_title=title.lower(),
        screening_status=status,
        duplicate_status=duplicate_status,
    )
    db.add(paper)
    db.commit()
    return paper


class TestScreeningAutoSuggestion:
    """Test auto-suggestion logic based on Q1-Q4 answers."""

    def test_all_yes_suggests_include(self, db):
        service = ScreeningService(db)
        result = service._suggest_decision("YES", "YES", "YES", "YES")
        assert result == "include"

    def test_q1_no_suggests_exclude(self, db):
        service = ScreeningService(db)
        result = service._suggest_decision("NO", "YES", "YES", "YES")
        assert result == "exclude"

    def test_q2_no_suggests_exclude(self, db):
        service = ScreeningService(db)
        result = service._suggest_decision("YES", "NO", "YES", "YES")
        assert result == "exclude"

    def test_q3_no_suggests_exclude(self, db):
        service = ScreeningService(db)
        result = service._suggest_decision("YES", "YES", "NO", "YES")
        assert result == "exclude"

    def test_q4_no_suggests_awaiting(self, db):
        service = ScreeningService(db)
        result = service._suggest_decision("YES", "YES", "YES", "NO")
        assert result == "awaiting_full_text"

    def test_unclear_suggests_borderline(self, db):
        service = ScreeningService(db)
        result = service._suggest_decision("YES", "UNCLEAR", "YES", "YES")
        assert result == "borderline"

    def test_no_answer_no_suggestion(self, db):
        service = ScreeningService(db)
        result = service._suggest_decision("YES", None, "YES", "YES")
        assert result is None


class TestScreeningSubmission:
    """Test screening decision submission."""

    def test_submit_include(self, db):
        paper = make_paper(db)
        service = ScreeningService(db)

        result = service.submit_decision(
            paper_id=paper.id,
            q1="YES", q2="YES", q3="YES", q4="YES",
            decision="include",
        )

        assert result["status"] == "recorded"
        assert result["decision"] == "include"

        # Check paper was updated
        db.refresh(paper)
        assert paper.screening_status == "include"

    def test_submit_exclude_with_reason(self, db):
        paper = make_paper(db)
        service = ScreeningService(db)

        result = service.submit_decision(
            paper_id=paper.id,
            q1="NO", q2="YES", q3="YES", q4="YES",
            decision="exclude",
            exclusion_reason="no_fl_algorithm_comparison",
        )

        assert result["status"] == "recorded"
        db.refresh(paper)
        assert paper.screening_status == "exclude"
        assert "no_fl_algorithm_comparison" in paper.exclusion_reason

    def test_exclude_without_reason_raises(self, db):
        paper = make_paper(db)
        service = ScreeningService(db)

        with pytest.raises(ValueError, match="Exclusion reason is required"):
            service.submit_decision(
                paper_id=paper.id,
                decision="exclude",
            )

    def test_invalid_decision_raises(self, db):
        paper = make_paper(db)
        service = ScreeningService(db)

        with pytest.raises(ValueError, match="Invalid decision"):
            service.submit_decision(
                paper_id=paper.id,
                decision="invalid",
            )

    def test_invalid_answer_raises(self, db):
        paper = make_paper(db)
        service = ScreeningService(db)

        with pytest.raises(ValueError, match="Invalid Q1"):
            service.submit_decision(
                paper_id=paper.id,
                q1="MAYBE",
            )

    def test_invalid_exclusion_reason_raises(self, db):
        paper = make_paper(db)
        service = ScreeningService(db)

        with pytest.raises(ValueError, match="Invalid exclusion reason"):
            service.submit_decision(
                paper_id=paper.id,
                decision="exclude",
                exclusion_reason="not_a_real_reason",
            )

    def test_paper_not_found_raises(self, db):
        service = ScreeningService(db)

        with pytest.raises(ValueError, match="not found"):
            service.submit_decision(paper_id=9999, decision="include")

    def test_full_text_stage(self, db):
        paper = make_paper(db, status="include")
        service = ScreeningService(db)

        result = service.submit_decision(
            paper_id=paper.id,
            stage="full_text",
            q1="YES", q2="YES", q3="YES", q4="YES",
            decision="include",
        )

        assert result["stage"] == "full_text"

    def test_invalid_stage_raises(self, db):
        paper = make_paper(db)
        service = ScreeningService(db)

        with pytest.raises(ValueError, match="Invalid stage"):
            service.submit_decision(
                paper_id=paper.id,
                stage="invalid_stage",
            )


class TestScreeningHistory:
    """Test screening history tracking."""

    def test_history_tracks_multiple_decisions(self, db):
        paper = make_paper(db)
        service = ScreeningService(db)

        # First decision: borderline
        service.submit_decision(
            paper_id=paper.id,
            q1="UNCLEAR", q2="YES", q3="YES", q4="YES",
            decision="borderline",
        )

        # Second decision: include
        service.submit_decision(
            paper_id=paper.id,
            q1="YES", q2="YES", q3="YES", q4="YES",
            decision="include",
        )

        history = service.get_screening_history(paper.id)
        assert len(history) == 2
        assert history[0]["decision"] == "borderline"
        assert history[1]["decision"] == "include"

    def test_history_empty_for_new_paper(self, db):
        paper = make_paper(db)
        service = ScreeningService(db)

        history = service.get_screening_history(paper.id)
        assert len(history) == 0


class TestScreeningProgress:
    """Test screening progress statistics."""

    def test_progress_counts(self, db):
        # Create papers in different states
        make_paper(db, title="P1", status="not_screened")
        make_paper(db, title="P2", status="not_screened")
        make_paper(db, title="P3", status="include")
        make_paper(db, title="P4", status="exclude")
        make_paper(db, title="P5", status="borderline")

        service = ScreeningService(db)
        progress = service.get_screening_progress()

        assert progress["total_candidates"] == 5
        assert progress["not_screened"] == 2
        assert progress["included"] == 1
        assert progress["excluded"] == 1
        assert progress["borderline"] == 1
        assert progress["screening_progress_pct"] == 60.0

    def test_progress_excludes_duplicates(self, db):
        make_paper(db, title="P1", status="not_screened")
        make_paper(db, title="P2", status="not_screened", duplicate_status="confirmed_duplicate")

        service = ScreeningService(db)
        progress = service.get_screening_progress()

        # Duplicate should be excluded from total
        assert progress["total_candidates"] == 1

    def test_exclusion_reasons_breakdown(self, db):
        p1 = make_paper(db, title="P1", status="exclude")
        p1.exclusion_reason = "no_fl_algorithm_comparison"
        p2 = make_paper(db, title="P2", status="exclude")
        p2.exclusion_reason = "iid_only"
        p3 = make_paper(db, title="P3", status="exclude")
        p3.exclusion_reason = "no_fl_algorithm_comparison"
        db.commit()

        service = ScreeningService(db)
        progress = service.get_screening_progress()

        reasons = {r["reason"]: r["count"] for r in progress["exclusion_reasons"]}
        assert reasons.get("no_fl_algorithm_comparison") == 2
        assert reasons.get("iid_only") == 1


class TestNextPaperToScreening:
    """Test getting the next paper to screen."""

    def test_next_returns_not_screened(self, db):
        p1 = make_paper(db, title="First", status="not_screened")
        make_paper(db, title="Second", status="include")

        service = ScreeningService(db)
        next_paper = service.get_next_paper_to_screen()

        assert next_paper is not None
        assert next_paper.id == p1.id

    def test_next_skips_duplicates(self, db):
        make_paper(db, title="Dup", status="not_screened", duplicate_status="confirmed_duplicate")
        p2 = make_paper(db, title="Unique", status="not_screened")

        service = ScreeningService(db)
        next_paper = service.get_next_paper_to_screen()

        assert next_paper is not None
        assert next_paper.id == p2.id

    def test_next_returns_none_when_done(self, db):
        make_paper(db, title="Done", status="include")

        service = ScreeningService(db)
        next_paper = service.get_next_paper_to_screen()

        assert next_paper is None


class TestBulkSubmit:
    """Test bulk screening submission."""

    def test_bulk_submit_success(self, db):
        p1 = make_paper(db, title="P1")
        p2 = make_paper(db, title="P2")
        p3 = make_paper(db, title="P3")

        service = ScreeningService(db)
        result = service.bulk_submit([
            {"paper_id": p1.id, "decision": "include", "q1": "YES", "q2": "YES", "q3": "YES", "q4": "YES"},
            {"paper_id": p2.id, "decision": "exclude", "exclusion_reason": "iid_only"},
            {"paper_id": p3.id, "decision": "borderline"},
        ])

        assert result["success_count"] == 3
        assert result["error_count"] == 0

    def test_bulk_submit_with_errors(self, db):
        p1 = make_paper(db, title="P1")

        service = ScreeningService(db)
        result = service.bulk_submit([
            {"paper_id": p1.id, "decision": "include"},
            {"paper_id": 9999, "decision": "include"},  # Non-existent
        ])

        assert result["success_count"] == 1
        assert result["error_count"] == 1
