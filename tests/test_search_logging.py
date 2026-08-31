"""
Tests: Enhanced Search Run Logging
====================================
Tests for search run duration, retries, pages tracking.
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.engine import Base
from app.models.search_run import SearchRun


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


class TestSearchRunLogging:
    """Test enhanced search run fields."""

    def test_duration_seconds(self, db):
        run = SearchRun(
            source="OpenAlex",
            search_family="A",
            exact_query="test",
            search_date=datetime.now(timezone.utc),
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc),
            duration_seconds=12.5,
        )
        db.add(run)
        db.commit()

        assert run.duration_seconds == 12.5

    def test_retries_tracking(self, db):
        run = SearchRun(
            source="OpenAlex",
            search_family="A",
            exact_query="test",
            search_date=datetime.now(timezone.utc),
            start_time=datetime.now(timezone.utc),
            retries=3,
        )
        db.add(run)
        db.commit()

        assert run.retries == 3

    def test_pages_retrieved(self, db):
        run = SearchRun(
            source="OpenAlex",
            search_family="A",
            exact_query="test",
            search_date=datetime.now(timezone.utc),
            start_time=datetime.now(timezone.utc),
            pages_retrieved=5,
        )
        db.add(run)
        db.commit()

        assert run.pages_retrieved == 5

    def test_errors_json_serialization(self, db):
        errors = ["Timeout on page 2", "Rate limited on page 3"]
        run = SearchRun(
            source="OpenAlex",
            search_family="A",
            exact_query="test",
            search_date=datetime.now(timezone.utc),
            start_time=datetime.now(timezone.utc),
            errors=json.dumps(errors),
        )
        db.add(run)
        db.commit()

        loaded_errors = json.loads(run.errors)
        assert len(loaded_errors) == 2
        assert "Timeout" in loaded_errors[0]

    def test_null_duration(self, db):
        run = SearchRun(
            source="OpenAlex",
            search_family="A",
            exact_query="test",
            search_date=datetime.now(timezone.utc),
            start_time=datetime.now(timezone.utc),
        )
        db.add(run)
        db.commit()

        assert run.duration_seconds is None
        assert run.retries == 0
        assert run.pages_retrieved == 0


class TestOpenAlexRetryTracking:
    """Test that the connector tracks retries correctly."""

    def test_initial_retry_count(self):
        from app.services.openalex import OpenAlexConnector

        conn = OpenAlexConnector()
        assert conn._last_request_retries == 0
        conn.close()

    @patch("app.services.openalex.httpx.Client")
    def test_retry_count_incremented_on_429(self, mock_client_cls):
        from app.services.openalex import OpenAlexConnector

        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "results": [{"id": "W1", "title": "Paper 1"}],
            "meta": {"count": 1, "next_cursor": None},
        }

        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_client.request.side_effect = [rate_limit_response, success_response]
        mock_client_cls.return_value = mock_client

        conn = OpenAlexConnector()
        conn._client = mock_client

        with patch("app.services.openalex.time.sleep"):
            results = list(conn.search_works(query="test", max_results=10))

        # Should have retried once
        assert len(results) == 1
        assert conn.last_search_summary["retries"] == 1

        conn.close()
