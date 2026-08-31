"""
OpenAlex API Connector
=======================
Handles all communication with the OpenAlex API:
- Pagination with cursor support
- Rate-limit handling (429 responses)
- Retry with exponential backoff
- Timeout handling
- Structured logging
"""

import time
import logging
from datetime import datetime, timezone
from typing import Optional, Generator, Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

OPENALEX_BASE_URL = "https://api.openalex.org"
DEFAULT_TIMEOUT = 30.0  # seconds
MAX_RETRIES = 5
RETRY_BACKOFF_BASE = 2.0  # exponential backoff base
RATE_LIMIT_WAIT = 1.0  # initial wait on 429


class OpenAlexError(Exception):
    """Custom exception for OpenAlex API errors."""
    pass


class OpenAlexRateLimitError(OpenAlexError):
    """Raised when rate limit is hit and retries exhausted."""
    pass


class OpenAlexConnector:
    """
    Connector for the OpenAlex API.
    Supports cursor-based pagination, retries, and rate-limit handling.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        email: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
    ):
        self.api_key = api_key or settings.openalex_api_key
        self.email = email or settings.openalex_email
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: Optional[httpx.Client] = None
        self.last_search_summary: Optional[dict] = None
        self._last_request_retries: int = 0
        self._current_cursor: Optional[str] = None

    def _get_client(self) -> httpx.Client:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            headers = {
                "User-Agent": "FL-SLR-Automation/1.0 (mailto:fslr@example.com)",
                "Accept": "application/json",
            }
            self._client = httpx.Client(
                base_url=OPENALEX_BASE_URL,
                headers=headers,
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._client

    def _get_params(self, extra: Optional[dict] = None) -> dict:
        """Build query parameters, adding API key and email if available."""
        params = {}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.email:
            params["mailto"] = self.email
        if extra:
            params.update(extra)
        return params

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """
        Make an HTTP request with retry and rate-limit handling.
        Returns the response. Tracks retry count in self._last_request_retries.
        """
        client = self._get_client()
        last_exception = None
        self._last_request_retries = 0

        for attempt in range(1, self.max_retries + 1):
            try:
                response = client.request(method, path, **kwargs)

                if response.status_code == 200:
                    return response

                if response.status_code == 429:
                    # Rate limited - wait and retry
                    self._last_request_retries += 1
                    wait_time = RATE_LIMIT_WAIT * (RETRY_BACKOFF_BASE ** (attempt - 1))
                    logger.warning(
                        f"Rate limited (429). Attempt {attempt}/{self.max_retries}. "
                        f"Waiting {wait_time:.1f}s..."
                    )
                    time.sleep(wait_time)
                    continue

                if response.status_code >= 500:
                    # Server error - retry
                    self._last_request_retries += 1
                    wait_time = RETRY_BACKOFF_BASE ** (attempt - 1)
                    logger.warning(
                        f"Server error ({response.status_code}). Attempt {attempt}/{self.max_retries}. "
                        f"Waiting {wait_time:.1f}s..."
                    )
                    time.sleep(wait_time)
                    continue

                # Client error (4xx except 429) - don't retry
                raise OpenAlexError(
                    f"OpenAlex API error: {response.status_code} - {response.text[:500]}"
                )

            except httpx.TimeoutException as e:
                last_exception = e
                self._last_request_retries += 1
                wait_time = RETRY_BACKOFF_BASE ** (attempt - 1)
                logger.warning(
                    f"Timeout. Attempt {attempt}/{self.max_retries}. "
                    f"Waiting {wait_time:.1f}s..."
                )
                time.sleep(wait_time)
                continue

            except httpx.NetworkError as e:
                last_exception = e
                self._last_request_retries += 1
                wait_time = RETRY_BACKOFF_BASE ** (attempt - 1)
                logger.warning(
                    f"Network error. Attempt {attempt}/{self.max_retries}. "
                    f"Waiting {wait_time:.1f}s..."
                )
                time.sleep(wait_time)
                continue

        raise OpenAlexError(
            f"Max retries ({self.max_retries}) exceeded. Last error: {last_exception}"
        )

    def search_works(
        self,
        query: str,
        per_page: int = 200,
        max_results: int = 500,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        start_cursor: Optional[str] = None,
    ) -> Generator[dict, None, dict]:
        """
        Search OpenAlex works with cursor-based pagination.

        Yields each work record as a dict.
        Returns a summary dict when complete.

        Args:
            query: Search query string
            per_page: Results per page (max 200)
            max_results: Maximum total results to retrieve
            year_from: Filter by publication year (inclusive)
            year_to: Filter by publication year (inclusive)
            start_cursor: Cursor to resume from (for resumable searches)

        Yields:
            dict: Individual work records

        Returns:
            dict: Summary with total_count, records_retrieved, pages, errors, duration
        """
        start_time = datetime.now(timezone.utc)
        cursor = start_cursor if start_cursor else "*"
        self._current_cursor = cursor
        records_retrieved = 0
        pages = 0
        errors = []
        total_count = 0
        total_retries = 0

        # Build filter
        filters = []
        if year_from and year_to:
            filters.append(f"publication_year:{year_from}-{year_to}")
        elif year_from:
            filters.append(f"publication_year:>={year_from}")
        elif year_to:
            filters.append(f"publication_year:<={year_to}")

        filter_str = ",".join(filters) if filters else None

        logger.info(f"Starting OpenAlex search: query='{query[:80]}...', max_results={max_results}")

        while cursor and records_retrieved < max_results:
            params = self._get_params({
                "search": query,
                "per-page": min(per_page, 200),
                "cursor": cursor,
            })
            if filter_str:
                params["filter"] = filter_str

            try:
                response = self._request("GET", "/works", params=params)
                total_retries += self._last_request_retries
                data = response.json()

                pages += 1
                results = data.get("results", [])
                meta = data.get("meta", {})
                total_count = meta.get("count", 0)

                if not results:
                    logger.info("No more results from OpenAlex.")
                    break

                for work in results:
                    if records_retrieved >= max_results:
                        break
                    yield work
                    records_retrieved += 1

                # Get next cursor
                cursor = meta.get("next_cursor")
                self._current_cursor = cursor

                logger.debug(
                    f"Page {pages}: retrieved {len(results)} records "
                    f"(total so far: {records_retrieved}/{max_results})"
                )

            except OpenAlexError as e:
                errors.append(str(e))
                logger.error(f"OpenAlex search error: {e}")
                break
            except Exception as e:
                errors.append(str(e))
                logger.error(f"Unexpected error during search: {e}")
                break

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        summary = {
            "total_count": total_count,
            "records_retrieved": records_retrieved,
            "pages": pages,
            "errors": errors,
            "retries": total_retries,
            "duration_seconds": duration,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        }

        # Store summary as instance attribute for access after iteration
        self.last_search_summary = summary

        logger.info(
            f"OpenAlex search complete: {records_retrieved} records in {duration:.1f}s "
            f"({pages} pages)"
        )

        return summary

    def get_work_by_id(self, openalex_id: str) -> Optional[dict]:
        """Fetch a single work by its OpenAlex ID."""
        try:
            # Normalize ID - extract the work ID from full URL if needed
            if openalex_id.startswith("http"):
                openalex_id = openalex_id.rstrip("/").split("/")[-1]

            params = self._get_params()
            response = self._request("GET", f"/works/{openalex_id}", params=params)
            return response.json()
        except OpenAlexError as e:
            logger.error(f"Failed to fetch work {openalex_id}: {e}")
            return None

    @property
    def current_cursor(self) -> Optional[str]:
        """The current cursor position in the search (for checkpointing)."""
        return self._current_cursor

    def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
