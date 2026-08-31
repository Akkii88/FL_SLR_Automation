"""
Tests: LLM Extraction Service
===============================
Tests for LLM-assisted extraction and screening.
Note: These tests mock the LLM client since we don't have API keys in tests.
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.engine import Base
from app.models.paper import Paper
from app.models.screening import ScreeningDecision, AuditLog
from app.services.llm_extraction import LLMExtractionService


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


def make_paper(db, title="Test Paper", abstract="Test abstract about federated learning."):
    """Helper to create a test paper."""
    paper = Paper(
        title=title,
        normalized_title=title.lower(),
        abstract=abstract,
        authors=json.dumps(["Test Author"]),
        publication_year=2023,
    )
    db.add(paper)
    db.commit()
    return paper


class TestLLMServiceConfiguration:
    """Test LLM service configuration."""

    def test_not_configured(self, db):
        service = LLMExtractionService(db)
        # Without env vars, should not be configured
        assert service.is_configured() is False

    def test_configured(self, db):
        with patch.object(service := LLMExtractionService(db), 'provider', 'openai'), \
             patch.object(service, 'api_key', 'test-key'), \
             patch.object(service, 'model', 'gpt-4'):
            assert service.is_configured() is True


class TestLLMExtractionMocked:
    """Test LLM extraction with mocked responses."""

    @patch("app.services.llm_extraction.settings")
    def test_suggest_extraction(self, mock_settings, db):
        paper = make_paper(
            db,
            abstract="This paper compares FedAvg and FedProx under non-IID data using Dirichlet partitioning.",
        )

        mock_settings.llm_provider = "openai"
        mock_settings.llm_api_key = "test-key"
        mock_settings.llm_model = "gpt-4"

        service = LLMExtractionService(db)

        # Mock the LLM call
        mock_response = {
            "content": json.dumps({
                "algorithms_compared": ["FedAvg", "FedProx"],
                "datasets": ["CIFAR-10"],
                "non_iid_type": "Label distribution skew",
                "partition_method": "Dirichlet",
                "confidence": 0.9,
                "evidence_snippets": {
                    "algorithms_compared": "compares FedAvg and FedProx",
                },
            }),
            "model": "gpt-4",
        }

        with patch.object(service, '_call_llm', return_value=mock_response):
            result = service.suggest_extraction(paper.id, "full")

        assert "algorithms_compared" in result
        assert result["algorithms_compared"] == ["FedAvg", "FedProx"]
        assert result["_metadata"]["model"] == "gpt-4"

    @patch("app.services.llm_extraction.settings")
    def test_suggest_screening(self, mock_settings, db):
        paper = make_paper(
            db,
            abstract="We compare FedAvg and FedProx under heterogeneous data and show our method outperforms baselines.",
        )

        mock_settings.llm_provider = "openai"
        mock_settings.llm_api_key = "test-key"
        mock_settings.llm_model = "gpt-4"

        service = LLMExtractionService(db)

        mock_response = {
            "content": json.dumps({
                "q1_fl_comparison": "YES",
                "q2_non_iid": "YES",
                "q3_superiority_claim": "YES",
                "q4_full_text_available": "UNCLEAR",
                "recommended_decision": "likely_include",
                "reasoning": "The abstract clearly compares two FL methods under non-IID data.",
                "confidence": 0.85,
                "evidence_snippets": {
                    "q1": "compare FedAvg and FedProx",
                    "q2": "heterogeneous data",
                    "q3": "outperforms baselines",
                },
            }),
            "model": "gpt-4",
        }

        with patch.object(service, '_call_llm', return_value=mock_response):
            result = service.suggest_screening(paper.id)

        assert result["q1_fl_comparison"] == "YES"
        assert result["recommended_decision"] == "likely_include"

    @patch("app.services.llm_extraction.settings")
    def test_llm_error_handling(self, mock_settings, db):
        paper = make_paper(db)

        mock_settings.llm_provider = "openai"
        mock_settings.llm_api_key = "test-key"
        mock_settings.llm_model = "gpt-4"

        service = LLMExtractionService(db)

        with patch.object(service, '_call_llm', side_effect=Exception("API error")):
            result = service.suggest_extraction(paper.id)

        assert "error" in result


class TestLLMSourceText:
    """Test source text building."""

    def test_build_source_text(self, db):
        paper = make_paper(
            db,
            title="Test FL Paper",
            abstract="This is about federated learning.",
        )

        service = LLMExtractionService(db)
        text = service._build_source_text(paper)

        assert "Test FL Paper" in text
        assert "This is about federated learning." in text
        assert "Test Author" in text

    def test_build_source_text_minimal(self, db):
        paper = Paper(title="Minimal")
        db.add(paper)
        db.commit()

        service = LLMExtractionService(db)
        text = service._build_source_text(paper)

        assert "Minimal" in text


class TestLLMAPIMocked:
    """Test LLM API endpoints with mocked service."""

    def test_status_endpoint(self):
        from fastapi.testclient import TestClient
        from app.api.main import app

        with TestClient(app) as c:
            response = c.get("/api/llm/status")
            assert response.status_code == 200
            data = response.json()
            assert "configured" in data

    def test_config_endpoint(self):
        from fastapi.testclient import TestClient
        from app.api.main import app

        with TestClient(app) as c:
            response = c.get("/api/llm/config")
            assert response.status_code == 200
            data = response.json()
            assert "supported_providers" in data
            assert "openai" in data["supported_providers"]

    def test_extract_not_configured(self):
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
            response = c.post(
                "/api/llm/extract",
                json={"paper_id": 1, "extraction_type": "full"},
            )
            assert response.status_code == 400
            assert "not configured" in response.json()["detail"].lower()

        session.close()
        transaction.rollback()
        connection.close()
        Base.metadata.drop_all(engine)
        app.dependency_overrides.clear()
