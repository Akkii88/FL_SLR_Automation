"""
Google Gemini LLM Provider
============================
Implements the LLMProvider interface for Google Gemini API.
Uses the official google-genai SDK.
"""

import logging
import time
from typing import Optional

from app.core.config import settings
from app.services.llm_provider import LLMProvider, LLMResponse, LLMError

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """Google Gemini provider using google-genai SDK."""

    def __init__(self):
        self._client = None

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def is_configured(self) -> bool:
        return bool(settings.gemini_api_key and settings.gemini_model)

    def _get_client(self):
        if self._client is None:
            try:
                from google import genai
                self._client = genai.Client(api_key=settings.gemini_api_key)
            except ImportError:
                raise LLMError(
                    message="google-genai package not installed. Run: pip install google-genai",
                    is_permanent=True,
                    provider="gemini",
                )
        return self._client

    def get_retry_config(self) -> dict:
        return {
            "max_retries": settings.gemini_max_retries,
            "initial_backoff": settings.gemini_initial_backoff_seconds,
            "max_backoff": settings.gemini_max_backoff_seconds,
            "request_delay": settings.gemini_request_delay_seconds,
        }

    def call(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        """
        Call Gemini API. Raises LLMError on failure.
        """
        client = self._get_client()

        try:
            # Combine system and user prompts for Gemini
            combined_prompt = f"{system_prompt}\n\n{user_prompt}"

            # Use the correct google-genai SDK syntax for v2.x
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=[combined_prompt],
            )

            # Check for empty response (may be blocked by safety filters)
            if response.text is None or response.text.strip() == "":
                # Try to get more info about why
                finish_reason = None
                if hasattr(response, 'candidates') and response.candidates:
                    candidate = response.candidates[0]
                    finish_reason = getattr(candidate, 'finish_reason', None)
                    safety_ratings = getattr(candidate, 'safety_ratings', None)

                raise LLMError(
                    message=f"Gemini returned empty response. Finish reason: {finish_reason}",
                    provider="gemini",
                )

            content = response.text

            # Extract token usage if available
            token_usage = None
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                token_usage = {
                    "prompt_tokens": getattr(response.usage_metadata, 'prompt_token_count', None),
                    "completion_tokens": getattr(response.usage_metadata, 'candidates_token_count', None),
                    "total_tokens": getattr(response.usage_metadata, 'total_token_count', None),
                }

            return LLMResponse(
                content=content,
                model=settings.gemini_model,
                provider="gemini",
                token_usage=token_usage,
            )

        except LLMError:
            raise  # Re-raise our own errors
        except Exception as e:
            raise self._classify_error(e)

    def _classify_error(self, error: Exception) -> LLMError:
        """Classify an exception into an LLMError."""
        error_str = str(error).lower()
        status_code = getattr(error, "status_code", None) or getattr(error, "code", None)

        # Check for 404 first
        is_404 = (
            status_code == 404 or
            "404" in error_str or
            "not found" in error_str
        )

        # Check for rate limiting
        is_rate_limit = (
            status_code == 429 or
            (not is_404 and (
                "rate_limit" in error_str or
                "too many requests" in error_str or
                "resource exhausted" in error_str
            ))
        )

        # Check for daily quota exhaustion
        is_daily = (
            "per day" in error_str or
            "daily" in error_str or
            "quota exceeded" in error_str
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
            is_404=is_404,
            is_server_error=is_server_error,
            provider="gemini",
        )
