"""
Tests: OpenAlex Connector (Mocked)
===================================
Tests the OpenAlex connector with mocked HTTP responses.
"""

import pytest
from unittest.mock import patch, MagicMock
import httpx

from app.services.openalex import (
    OpenAlexConnector,
    OpenAlexError,
)


class TestOpenAlexConnector:
    """Test OpenAlex connector with mocked responses."""

    def test_initialization(self):
        conn = OpenAlexConnector(api_key="test_key", email="test@example.com")
        assert conn.api_key == "test_key"
        assert conn.email == "test@example.com"
        conn.close()

    def test_default_initialization(self):
        conn = OpenAlexConnector()
        assert conn.api_key == ""
        assert conn.timeout == 30.0
        assert conn.max_retries == 5
        conn.close()

    @patch("app.services.openalex.httpx.Client")
    def test_successful_search(self, mock_client_cls):
        """Test successful API response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"id": "W1", "title": "Paper 1"},
                {"id": "W2", "title": "Paper 2"},
            ],
            "meta": {
                "count": 2,
                "next_cursor": None,
            },
        }

        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        conn = OpenAlexConnector()
        conn._client = mock_client

        results = list(conn.search_works(query="test", max_results=10))
        assert len(results) == 2
        assert results[0]["title"] == "Paper 1"

        conn.close()

    @patch("app.services.openalex.httpx.Client")
    def test_rate_limit_handling(self, mock_client_cls):
        """Test that 429 responses trigger retry."""
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

        # Patch time.sleep to avoid actual delays
        with patch("app.services.openalex.time.sleep"):
            results = list(conn.search_works(query="test", max_results=10))

        assert len(results) == 1

        conn.close()

    @patch("app.services.openalex.httpx.Client")
    def test_client_error_no_retry(self, mock_client_cls):
        """Test that 4xx errors (except 429) don't trigger retry."""
        error_response = MagicMock()
        error_response.status_code = 400
        error_response.text = "Bad Request"

        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_client.request.return_value = error_response
        mock_client_cls.return_value = mock_client

        conn = OpenAlexConnector()
        conn._client = mock_client

        with pytest.raises(OpenAlexError):
            list(conn.search_works(query="test", max_results=10))

        conn.close()

    @patch("app.services.openalex.httpx.Client")
    def test_pagination(self, mock_client_cls):
        """Test cursor-based pagination."""
        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = {
            "results": [{"id": "W1", "title": "Paper 1"}],
            "meta": {"count": 2, "next_cursor": "cursor_abc"},
        }

        page2 = MagicMock()
        page2.status_code = 200
        page2.json.return_value = {
            "results": [{"id": "W2", "title": "Paper 2"}],
            "meta": {"count": 2, "next_cursor": None},
        }

        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_client.request.side_effect = [page1, page2]
        mock_client_cls.return_value = mock_client

        conn = OpenAlexConnector()
        conn._client = mock_client

        results = list(conn.search_works(query="test", max_results=10))
        assert len(results) == 2

        conn.close()

    @patch("app.services.openalex.httpx.Client")
    def test_max_results_limit(self, mock_client_cls):
        """Test that max_results is respected."""
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "results": [{"id": f"W{i}", "title": f"Paper {i}"} for i in range(200)],
            "meta": {"count": 1000, "next_cursor": "next"},
        }

        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_client.request.return_value = response
        mock_client_cls.return_value = mock_client

        conn = OpenAlexConnector()
        conn._client = mock_client

        results = list(conn.search_works(query="test", max_results=50))
        assert len(results) == 50

        conn.close()
