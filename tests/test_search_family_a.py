"""
Regression test: Search Family A returns >0 records.
Tests the full SearchService path with mocked OpenAlex response.
"""
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.engine import Base
from app.core.review_config import ReviewConfig
from app.services.search_service import SearchService


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


@pytest.fixture
def review_config():
    """Provide a sample review configuration."""
    return ReviewConfig.default_config()


class TestSearchFamilyA:
    """Test Search Family A returns results."""

    def test_search_family_a_returns_results(self, db, review_config):
        """Test that Search Family A returns >0 records from OpenAlex."""
        # Mock OpenAlex response
        mock_results = [
            {
                "id": "https://openalex.org/W2995022099",
                "title": "Advances and Open Problems in Federated Learning",
                "publication_year": 2020,
                "doi": "10.48550/arXiv.1912.04977",
                "abstract_inverted_index": {"federated": [0], "learning": [1]},
                "cited_by_count": 5000,
                "open_access": {"is_oa": True, "oa_status": "gold", "oa_url": "https://arxiv.org/abs/1912.04977"},
                "authorships": [{"author": {"display_name": "Peter Kairouz"}, "institutions": []}],
                "type": "journal-article",
            },
            {
                "id": "https://openalex.org/W3001234567",
                "title": "Federated Learning with Non-IID Data",
                "publication_year": 2021,
                "doi": "10.1234/test.001",
                "abstract_inverted_index": {"non-IID": [0], "data": [1]},
                "cited_by_count": 100,
                "open_access": {"is_oa": False, "oa_status": None, "oa_url": None},
                "authorships": [{"author": {"display_name": "Test Author"}, "institutions": []}],
                "type": "conference-paper",
            },
        ]

        mock_meta = {
            "count": 66215,
            "next_cursor": "abc123nextpage",
        }

        service = SearchService(db, review_config)

        # Mock the connector's search_works method
        with patch.object(service.connector, 'search_works') as mock_search:
            # Make the generator yield our mock results
            mock_search.return_value.__iter__ = lambda self: iter(mock_results)
            # Set the last_search_summary
            service.connector.last_search_summary = {
                "total_count": 66215,
                "records_retrieved": 2,
                "pages": 1,
                "errors": [],
                "retries": 0,
                "duration_seconds": 1.5,
            }

            result = service.run_search_family("A", max_candidates=5)

        # Verify results
        assert result["records_saved"] == 2, f"Expected 2 records saved, got {result['records_saved']}"
        assert result["errors"] == [], f"Unexpected errors: {result['errors']}"

        # Verify papers in database
        from app.models.paper import Paper
        papers = db.query(Paper).all()
        assert len(papers) == 2, f"Expected 2 papers in DB, got {len(papers)}"

        # Verify first paper
        assert papers[0].openalex_id == "W2995022099"
        assert papers[0].title == "Advances and Open Problems in Federated Learning"

    def test_search_family_a_handles_empty_results(self, db, review_config):
        """Test that Search Family A handles empty results gracefully."""
        service = SearchService(db, review_config)

        with patch.object(service.connector, 'search_works') as mock_search:
            mock_search.return_value.__iter__ = lambda self: iter([])
            service.connector.last_search_summary = {
                "total_count": 0,
                "records_retrieved": 0,
                "pages": 1,
                "errors": [],
                "retries": 0,
                "duration_seconds": 0.5,
            }

            result = service.run_search_family("A", max_candidates=5)

        assert result["records_saved"] == 0
        assert "No results" in result.get("message", "") or result["records_seen"] == 0

    def test_search_family_a_logs_errors(self, db, review_config):
        """Test that Search Family A logs errors properly."""
        service = SearchService(db, review_config)

        with patch.object(service.connector, 'search_works') as mock_search:
            mock_search.side_effect = Exception("Connection failed")

            result = service.run_search_family("A", max_candidates=5)

        assert len(result["errors"]) > 0
        assert "Connection failed" in result["errors"][0]
