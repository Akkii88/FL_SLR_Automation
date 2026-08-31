"""
Regression test: total_matching_count persistence.
Verifies that OpenAlex meta.count is persisted to the search_runs table.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.engine import Base
from app.core.review_config import ReviewConfig
from app.services.search_service import SearchService
from app.models.search_run import SearchRun


@pytest.fixture(scope="function")
def db():
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
    return ReviewConfig.default_config()


class TestTotalMatchingCountPersistence:
    """Test that OpenAlex meta.count is persisted."""

    def test_total_matching_count_saved(self, db, review_config):
        """Verify meta.count from OpenAlex is saved to total_matching_count."""
        service = SearchService(db, review_config)

        mock_works = [
            {
                "id": f"https://openalex.org/W{i:010d}",
                "title": f"Paper {i}",
                "publication_year": 2023,
                "doi": f"10.0000/test.{i:03d}",
                "abstract_inverted_index": {"test": [0]},
                "cited_by_count": i,
                "open_access": {"is_oa": True, "oa_status": "gold"},
                "authorships": [{"author": {"display_name": f"Author {i}"}, "institutions": []}],
                "type": "journal-article",
            }
            for i in range(1, 11)
        ]

        def mock_generator(*args, **kwargs):
            for w in mock_works:
                yield w

        with patch.object(service.connector, 'search_works', side_effect=mock_generator):
            service.connector.last_search_summary = {
                "total_count": 66215,
                "records_retrieved": 10,
                "pages": 1,
                "errors": [],
                "retries": 0,
                "duration_seconds": 2.0,
            }
            result = service.run_search_family("A", max_candidates=10)

        # Verify the SearchRun record has total_matching_count
        run = db.query(SearchRun).filter(SearchRun.id == result["search_run_id"]).first()
        assert run is not None
        assert run.total_matching_count == 66215

    def test_total_matching_count_null_when_unavailable(self, db, review_config):
        """Verify total_matching_count is NULL when OpenAlex doesn't provide it."""
        service = SearchService(db, review_config)

        def mock_generator(*args, **kwargs):
            return
            yield  # make it a generator

        with patch.object(service.connector, 'search_works', side_effect=mock_generator):
            service.connector.last_search_summary = {
                "total_count": None,  # Simulate missing count
                "records_retrieved": 0,
                "pages": 0,
                "errors": [],
                "retries": 0,
                "duration_seconds": 0.1,
            }
            result = service.run_search_family("A", max_candidates=10)

        run = db.query(SearchRun).filter(SearchRun.id == result["search_run_id"]).first()
        assert run is not None
        assert run.total_matching_count is None

    def test_total_matching_count_in_history_api(self, db, review_config):
        """Verify total_matching_count appears in search history API response."""
        service = SearchService(db, review_config)

        mock_works = [
            {
                "id": f"https://openalex.org/W{i:010d}",
                "title": f"Paper {i}",
                "publication_year": 2023,
                "doi": f"10.0000/test.{i:03d}",
                "abstract_inverted_index": {"test": [0]},
                "cited_by_count": i,
                "open_access": {"is_oa": True, "oa_status": "gold"},
                "authorships": [{"author": {"display_name": f"Author {i}"}, "institutions": []}],
                "type": "journal-article",
            }
            for i in range(1, 6)
        ]

        def mock_generator(*args, **kwargs):
            for w in mock_works:
                yield w

        with patch.object(service.connector, 'search_works', side_effect=mock_generator):
            service.connector.last_search_summary = {
                "total_count": 12345,
                "records_retrieved": 5,
                "pages": 1,
                "errors": [],
                "retries": 0,
                "duration_seconds": 1.0,
            }
            service.run_search_family("A", max_candidates=5)

        # Query via API
        history = db.query(SearchRun).filter(SearchRun.search_family == "A").all()
        assert len(history) == 1
        assert history[0].total_matching_count == 12345
