"""
Tests: PRISMA, Excel Export, NotebookLM
=========================================
Tests for PRISMA flow, Excel export, and citation formats.
"""

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.engine import Base
from app.models.paper import Paper
from app.models.search_run import SearchRun, SourceProvenance
from app.models.screening import ScreeningDecision, AuditLog
from app.services.prisma import PrismaService
from app.services.notebooklm import generate_ris_citation, generate_bibtex_citation


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


class TestPrismaService:
    """Test PRISMA flow generation."""

    def test_empty_flow(self, db):
        service = PrismaService(db)
        flow = service.get_prisma_flow()

        assert flow["identification"]["total_records_retrieved"] == 0
        assert flow["screening"]["unique_records"] == 0
        assert flow["included"]["final_included"] == 0

    def test_flow_with_data(self, db):
        # Create papers in different states
        make_paper(db, title="P1", status="include")
        make_paper(db, title="P2", status="exclude")
        make_paper(db, title="P3", status="not_screened")
        make_paper(db, title="Dup", status="unique", duplicate_status="confirmed_duplicate")

        service = PrismaService(db)
        flow = service.get_prisma_flow()

        assert flow["identification"]["total_records_retrieved"] == 4
        assert flow["screening"]["duplicates_removed"] == 1
        assert flow["screening"]["unique_records"] == 3
        assert flow["included"]["final_included"] == 1

    def test_prisma_counts(self, db):
        make_paper(db, title="P1", status="include")
        make_paper(db, title="P2", status="exclude")

        service = PrismaService(db)
        counts = service.get_prisma_counts()

        assert counts["identification"] == 2
        assert counts["included"] == 1


class TestCitationFormats:
    """Test RIS and BibTeX generation."""

    def test_ris_citation(self, db):
        paper = Paper(
            title="Test Paper on Federated Learning",
            authors=json.dumps(["John Doe", "Jane Smith"]),
            publication_year=2023,
            source="ICML",
            doi="10.1234/test.001",
            oa_url="https://example.org/paper.pdf",
            abstract="This is a test abstract.",
        )
        db.add(paper)
        db.commit()

        ris = generate_ris_citation(paper)

        assert "TY  - JOUR" in ris
        assert "TI  - Test Paper on Federated Learning" in ris
        assert "AU  - John Doe" in ris
        assert "AU  - Jane Smith" in ris
        assert "PY  - 2023" in ris
        assert "DO  - 10.1234/test.001" in ris
        assert "ER  - " in ris

    def test_bibtex_citation(self, db):
        paper = Paper(
            title="Test Paper on Federated Learning",
            authors=json.dumps(["John Doe", "Jane Smith"]),
            publication_year=2023,
            source="ICML",
            doi="10.1234/test.001",
        )
        db.add(paper)
        db.commit()

        bibtex = generate_bibtex_citation(paper)

        assert "@article{" in bibtex
        assert "title = {Test Paper on Federated Learning}" in bibtex
        assert "author = {John Doe and Jane Smith}" in bibtex
        assert "year = {2023}" in bibtex
        assert "doi = {10.1234/test.001}" in bibtex

    def test_bibtex_minimal_paper(self, db):
        paper = Paper(title="Minimal Paper")
        db.add(paper)
        db.commit()

        bibtex = generate_bibtex_citation(paper)
        assert "@article{" in bibtex
        assert "title = {Minimal Paper}" in bibtex


class TestPrismaAPI:
    """Test PRISMA API endpoints."""

    def test_prisma_flow_endpoint(self):
        from fastapi.testclient import TestClient
        from app.api.main import app

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        connection = engine.connect()
        transaction = connection.begin()
        session = sessionmaker(bind=connection)()

        def override_get_db():
            yield session

        app.dependency_overrides[get_db] = override_get_db

        with TestClient(app) as c:
            response = c.get("/api/prisma/flow")
            assert response.status_code == 200
            data = response.json()
            assert "identification" in data
            assert "screening" in data
            assert "included" in data

        session.close()
        transaction.rollback()
        connection.close()
        Base.metadata.drop_all(engine)
        app.dependency_overrides.clear()

    def test_prisma_counts_endpoint(self):
        from fastapi.testclient import TestClient
        from app.api.main import app

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        connection = engine.connect()
        transaction = connection.begin()
        session = sessionmaker(bind=connection)()

        def override_get_db():
            yield session

        app.dependency_overrides[get_db] = override_get_db

        with TestClient(app) as c:
            response = c.get("/api/prisma/counts")
            assert response.status_code == 200
            data = response.json()
            assert "identification" in data
            assert "included" in data

        session.close()
        transaction.rollback()
        connection.close()
        Base.metadata.drop_all(engine)
        app.dependency_overrides.clear()
