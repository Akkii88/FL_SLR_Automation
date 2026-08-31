"""
Groq LLM Provider
===================
Implements the LLMProvider interface for Groq (OpenAI-compatible API).
"""

import logging
import time
import random
from typing import Optional

from app.core.config import settings
from app.services.llm_provider import LLMProvider, LLMResponse, LLMError

logger = logging.getLogger(__name__)


class GroqProvider(LLMProvider):
    """Groq provider using OpenAI-compatible API."""

    def __init__(self):
        self._client = None

    @property
    def name(self) -> str:
        return "groq"

    @property
    def is_configured(self) -> bool:
        return bool(settings.llm_api_key and settings.llm_model)

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=settings.llm_api_key,
                base_url="https://api.groq.com/openai/v1",
            )
        return self._client

    def get_retry_config(self) -> dict:
        return {
            "max_retries": settings.groq_max_retries,
            "initial_backoff": settings.groq_initial_backoff_seconds,
            "max_backoff": settings.groq_max_backoff_seconds,
            "request_delay": settings.groq_request_delay_seconds,
        }

    def call(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        """
        Call Groq API. Raises LLMError on failure.
        """
        client = self._get_client()

        try:
            response = client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content

            # Extract token usage if available
            token_usage = None
            if hasattr(response, 'usage') and response.usage:
                token_usage = {
                    "prompt_tokens": getattr(response.usage, 'prompt_tokens', None),
                    "completion_tokens": getattr(response.usage, 'completion_tokens', None),
                    "total_tokens": getattr(response.usage, 'total_tokens', None),
                }

            return LLMResponse(
                content=content,
                model=settings.llm_model,
                provider="groq",
                token_usage=token_usage,
            )

        except Exception as e:
            raise self._classify_error(e)

    def _classify_error(self, error: Exception) -> LLMError:
        """Classify an exception into an LLMError."""
        error_str = str(error).lower()
        status_code = getattr(error, "status_code", None) or getattr(error, "code", None)

        # Check for 404 first (model/endpoint not found)
        is_404 = (
            status_code == 404 or
            "404" in error_str or
            "not found" in error_str
        )

        # Check for rate limiting (429 only)
        is_rate_limit = (
            status_code == 429 or
            (not is_404 and (
                "rate_limit" in error_str or
                "too many requests" in error_str
            ))
        )

        # Check for daily quota exhaustion
        is_daily = (
            "per day" in error_str or
            "daily" in error_str or
            "tpd" in error_str or
            "tokens per day" in error_str
        )

        # Check for authentication/authorization errors
        is_auth = (
            status_code in (401, 403) or
            "unauthorized" in error_str or
            "forbidden" in error_str or
            "invalid api key" in error_str or
            "authentication" in error_str
        )

        # Check for server errors (5xx)
        is_server_error = (
            (status_code is not None and 500 <= status_code < 600) or
            "service unavailable" in error_str or
            "internal server error" in error_str
        )

        # Permanent errors: auth, 404
        is_permanent = is_auth or is_404

        # Extract retry-after (only for rate limits)
        retry_after = None
        if is_rate_limit:
            retry_after = getattr(error, "retry_after", None)
            if retry_after is None:
                headers = getattr(error, "headers", {}) or {}
                retry_after = headers.get("retry-after") or headers.get("Retry-After")
                if retry_after:
                    try:
                        retry_after = float(retry_after)
                    except (ValueError, TypeError):
                        retry_after = None

        return LLMError(
            message=str(error),
            status_code=status_code,
            retry_after=retry_after,
            is_rate_limit=is_rate_limit,
            is_daily_limit=is_daily,
            is_permanent=is_permanent,
            is_404=is_404,
            is_server_error=is_server_error,
            provider="groq",
        )

        # Check for daily quota exhaustion
        is_daily = (
            "per day" in error_str or
            "daily" in error_str or
            "tpd" in error_str or
            "tokens per day" in error_str
        )

        # Check for permanent errors (auth, config)
        is_permanent = (
            status_code in (401, 403) or
            "unauthorized" in error_str or
            "forbidden" in error_str or
            "invalid api key" in error_str or
            "authentication" in error_str
        )

        # Extract retry-after
        retry_after = None
        if is_rate_limit:
            retry_after = getattr(error, "retry_after", None)
            if retry_after is None:
                headers = getattr(error, "headers", {}) or {}
                retry_after = headers.get("retry-after") or headers.get("Retry-After")
                if retry_after:
                    try:
                        retry_after = float(retry_after)
                    except (ValueError, TypeError):
                        retry_after = None

        return LLMError(
            message=str(error),
            status_code=status_code,
            retry_after=retry_after,
            is_rate_limit=is_rate_limit,
            is_daily_limit=is_daily,
            is_permanent=is_permanent,
            provider="groq",
        )
