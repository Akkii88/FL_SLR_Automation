"""
Regression test: max_candidates pagination.
Verifies that the search retrieves up to the configured limit across multiple pages.
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
from app.services.openalex import OpenAlexConnector


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


def make_mock_work(work_id: int):
    """Create a mock OpenAlex work record."""
    return {
        "id": f"https://openalex.org/W{work_id:010d}",
        "title": f"Test Paper {work_id}",
        "publication_year": 2023,
        "doi": f"10.0000/test.{work_id:03d}",
        "abstract_inverted_index": {"test": [0]},
        "cited_by_count": work_id,
        "open_access": {"is_oa": True, "oa_status": "gold", "oa_url": None},
        "authorships": [{"author": {"display_name": f"Author {work_id}"}, "institutions": []}],
        "type": "journal-article",
    }


class TestMaxCandidatesPagination:
    """Test that max_candidates is respected across multiple pages."""

    def test_max_candidates_500_retrieves_500(self, db, review_config):
        """Test that max_candidates=500 retrieves exactly 500 records across multiple pages."""
        service = SearchService(db, review_config)

        # Create 500 mock works
        all_works = [make_mock_work(i) for i in range(1, 501)]

        # The search_works generator yields ALL pages in sequence
        # We mock it to yield all 500 at once (simulating what the real generator does)
        def mock_generator(*args, **kwargs):
            # Verify max_results was passed correctly
            assert kwargs.get("max_results") == 500, f"Expected max_results=500, got {kwargs.get('max_results')}"
            for work in all_works:
                yield work

        with patch.object(service.connector, 'search_works', side_effect=mock_generator):
            service.connector.last_search_summary = {
                "total_count": 66215,
                "records_retrieved": 500,
                "pages": 3,
                "errors": [],
                "retries": 0,
                "duration_seconds": 10.0,
            }

            result = service.run_search_family("A", max_candidates=500)

        assert result["records_seen"] == 500, f"Expected 500 records seen, got {result['records_seen']}"
        assert result["records_saved"] == 500, f"Expected 500 records saved, got {result['records_saved']}"
        assert result["errors"] == [], f"Unexpected errors: {result['errors']}"

    def test_max_candidates_respects_config_default(self, db, review_config):
        """Test that when max_candidates is None, config default is used."""
        service = SearchService(db, review_config)

        # Create 500 mock works (more than we should retrieve)
        all_works = [make_mock_work(i) for i in range(1, 501)]

        def mock_generator(*args, **kwargs):
            # Verify max_results was passed correctly
            assert kwargs.get("max_results") == 500, f"Expected max_results=500, got {kwargs.get('max_results')}"
            for work in all_works:
                yield work

        with patch.object(service.connector, 'search_works', side_effect=mock_generator):
            service.connector.last_search_summary = {
                "total_count": 66215,
                "records_retrieved": 500,
                "pages": 3,
                "errors": [],
                "retries": 0,
                "duration_seconds": 10.0,
            }

            # Pass None to use config default
            result = service.run_search_family("A", max_candidates=None)

        assert result["records_seen"] == 500

    def test_max_candidates_smaller_than_page_size(self, db, review_config):
        """Test max_candidates < per_page (e.g., 50)."""
        service = SearchService(db, review_config)

        all_works = [make_mock_work(i) for i in range(1, 51)]

        def mock_generator(*args, **kwargs):
            assert kwargs.get("max_results") == 50
            for work in all_works:
                yield work

        with patch.object(service.connector, 'search_works', side_effect=mock_generator):
            service.connector.last_search_summary = {
                "total_count": 1000,
                "records_retrieved": 50,
                "pages": 1,
                "errors": [],
                "retries": 0,
                "duration_seconds": 2.0,
            }

            result = service.run_search_family("A", max_candidates=50)

        assert result["records_seen"] == 50
        assert result["records_saved"] == 50

    def test_pagination_stops_at_max_results(self, db, review_config):
        """Test that pagination stops exactly at max_results even if more pages exist."""
        service = SearchService(db, review_config)

        # Simulate a generator that yields 1000 results (more than max_results)
        # The search service should stop at 500
        def mock_generator(*args, **kwargs):
            for i in range(1, 1001):
                yield make_mock_work(i)

        with patch.object(service.connector, 'search_works', side_effect=mock_generator):
            service.connector.last_search_summary = {
                "total_count": 100000,
                "records_retrieved": 500,
                "pages": 3,
                "errors": [],
                "retries": 0,
                "duration_seconds": 15.0,
            }

            result = service.run_search_family("A", max_candidates=500)

        # Should stop at exactly 500, not continue to 1000
        assert result["records_seen"] == 500
        assert result["records_saved"] == 500
