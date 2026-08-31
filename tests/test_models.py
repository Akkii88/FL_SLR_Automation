"""
Tests: Database Models
========================
Tests for ORM models and database operations.
"""

import json
import pytest
from datetime import datetime
from app.models.paper import Paper
from app.models.search_run import SearchRun, SearchRunPaper, SourceProvenance
from app.models.screening import ScreeningDecision, AuditLog
from app.models.pdf_file import PdfFile


class TestPaperModel:
    """Test Paper model creation and storage."""

    def test_create_paper(self, db):
        paper = Paper(
            openalex_id="W123",
            doi="10.1234/test",
            title="Test Paper",
            normalized_title="test paper",
            publication_year=2023,
        )
        db.add(paper)
        db.commit()

        assert paper.id is not None
        assert paper.screening_status == "not_screened"
        assert paper.duplicate_status == "unique"

    def test_paper_timestamps(self, db):
        paper = Paper(title="Timestamp Test", normalized_title="timestamp test")
        db.add(paper)
        db.commit()

        assert paper.created_at is not None
        assert paper.updated_at is not None

    def test_paper_json_fields(self, db):
        paper = Paper(
            title="JSON Test",
            authors=json.dumps(["Author A", "Author B"]),
            institutions=json.dumps(["Inst A"]),
        )
        db.add(paper)
        db.commit()

        authors = json.loads(paper.authors)
        assert len(authors) == 2

    def test_paper_default_flags(self, db):
        paper = Paper(title="Flag Test")
        db.add(paper)
        db.commit()

        assert paper.is_open_access is False
        assert paper.is_retracted is False
        assert paper.canonical_record_id is None


class TestSearchRunModel:
    """Test SearchRun model."""

    def test_create_search_run(self, db):
        run = SearchRun(
            source="OpenAlex",
            search_family="A",
            exact_query="federated learning",
            search_date=datetime.utcnow(),
            start_time=datetime.utcnow(),
        )
        db.add(run)
        db.commit()

        assert run.id is not None
        assert run.results_retrieved == 0

    def test_search_run_paper_link(self, db):
        paper = Paper(title="Link Test")
        db.add(paper)
        db.flush()

        run = SearchRun(
            source="OpenAlex",
            search_family="A",
            exact_query="test",
            search_date=datetime.utcnow(),
            start_time=datetime.utcnow(),
        )
        db.add(run)
        db.flush()

        link = SearchRunPaper(search_run_id=run.id, paper_id=paper.id)
        db.add(link)
        db.commit()

        assert link.id is not None


class TestAuditLog:
    """Test audit logging."""

    def test_create_audit_log(self, db):
        log = AuditLog(
            action="test_action",
            entity_type="paper",
            entity_id=1,
            description="Test audit entry",
            actor="test",
        )
        db.add(log)
        db.commit()

        assert log.id is not None
        assert log.timestamp is not None

    def test_audit_log_with_values(self, db):
        log = AuditLog(
            action="status_change",
            entity_type="paper",
            entity_id=1,
            description="Status changed",
            old_value="not_screened",
            new_value="include",
            actor="user",
        )
        db.add(log)
        db.commit()

        assert log.old_value == "not_screened"
        assert log.new_value == "include"


class TestScreeningDecision:
    """Test screening decision model."""

    def test_create_decision(self, db):
        paper = Paper(title="Screening Test")
        db.add(paper)
        db.flush()

        decision = ScreeningDecision(
            paper_id=paper.id,
            stage="title_abstract",
            q1_fl_comparison="YES",
            q2_non_iid="YES",
            q3_superiority_claim="YES",
            q4_full_text_available="YES",
            decision="include",
        )
        db.add(decision)
        db.commit()

        assert decision.id is not None
        assert decision.q1_fl_comparison == "YES"
