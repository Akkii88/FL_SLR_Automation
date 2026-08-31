"""
LLM Provider Manager
======================
Manages primary and fallback LLM providers for AI screening.
Handles provider selection, rate limiting, and fallback logic.
"""

import json
import logging
import time
import random
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.llm_provider import LLMProvider, LLMResponse, LLMError
from app.services.groq_provider import GroqProvider
from app.services.gemini_provider import GeminiProvider
from app.services.openrouter_provider import OpenRouterProvider

logger = logging.getLogger(__name__)


class ProviderStatus:
    """Tracks the current status of a provider."""

    def __init__(self, name: str):
        self.name = name
        self.is_available = True
        self.last_error = None
        self.last_success = None
        self.last_error_time = None
        self.requests_in_batch = 0
        self.retry_count = 0
        self.rate_limit_count = 0
        self.daily_quota_exhausted = False

    def record_success(self):
        self.is_available = True
        self.last_success = datetime.now(timezone.utc)
        self.requests_in_batch += 1

    def record_error(self, error: LLMError):
        self.last_error = error.message[:200]  # Truncate for storage
        self.last_error_time = datetime.now(timezone.utc)
        self.retry_count += 1

        if error.is_rate_limit:
            self.rate_limit_count += 1

        if error.is_daily_limit:
            self.daily_quota_exhausted = True
            self.is_available = False

        if error.is_permanent:
            self.is_available = False

    def reset_batch_counters(self):
        self.requests_in_batch = 0
        self.retry_count = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "is_available": self.is_available,
            "configured": False,  # Set by manager
            "status": self._get_status(),
            "last_error": self.last_error,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "requests_in_batch": self.requests_in_batch,
            "retry_count": self.retry_count,
            "rate_limit_count": self.rate_limit_count,
            "daily_quota_exhausted": self.daily_quota_exhausted,
        }

    def _get_status(self) -> str:
        if not self.is_available:
            if self.daily_quota_exhausted:
                return "daily_quota_exhausted"
            return "error"
        if self.rate_limit_count > 0:
            return "rate_limited"
        return "available"


# Global provider status tracking
_provider_status = {
    "groq": ProviderStatus("groq"),
    "gemini": ProviderStatus("gemini"),
    "openrouter": ProviderStatus("openrouter"),
}

# Quota event deduplication
_quota_events = {}  # {event_key: last_notification_time}
QUOTA_NOTIFICATION_COOLDOWN_SECONDS = 300  # 5 minutes


def get_provider_status() -> dict:
    """Get current status of all providers."""
    groq = GroqProvider()
    gemini = GeminiProvider()
    openrouter = OpenRouterProvider()

    result = {
        "groq": {**_provider_status["groq"].to_dict(), "configured": groq.is_configured},
        "gemini": {**_provider_status["gemini"].to_dict(), "configured": gemini.is_configured},
        "openrouter": {
            **_provider_status["openrouter"].to_dict(),
            "configured": openrouter.is_configured,
            "enabled": settings.openrouter_enabled,
            "disabled_reason": "Model unavailable (openai/gpt-oss-120b:free)" if not settings.openrouter_enabled else None,
        },
    }

    # Determine current provider and fallback status
    # OpenRouter is only used if explicitly enabled
    if _provider_status["groq"].is_available and groq.is_configured:
        result["current_provider"] = "groq"
        result["fallback_active"] = False
    elif _provider_status["gemini"].is_available and gemini.is_configured:
        result["current_provider"] = "gemini"
        result["fallback_active"] = True
    elif openrouter.is_configured and settings.openrouter_enabled:
        result["current_provider"] = "openrouter"
        result["fallback_active"] = True
    else:
        result["current_provider"] = "none"
        result["fallback_active"] = False

    # Show active fallback chain (excluding disabled providers)
    chain = ["groq", "gemini"]
    if settings.openrouter_enabled:
        chain.append("openrouter")
    result["fallback_chain"] = chain

    return result


def reset_provider_status():
    """Reset provider status (e.g., for a new batch)."""
    global _provider_status, _quota_events
    _provider_status = {
        "groq": ProviderStatus("groq"),
        "gemini": ProviderStatus("gemini"),
        "openrouter": ProviderStatus("openrouter"),
    }
    _quota_events = {}


def get_quota_notifications(clear: bool = False) -> list:
    """Get pending quota notifications."""
    global _quota_events
    notifications = []
    now = time.time()

    for event_key, event_data in list(_quota_events.items()):
        if event_data.get("shown", False):
            continue
        if now - event_data["timestamp"] > QUOTA_NOTIFICATION_COOLDOWN_SECONDS:
            # Expired without being shown
            continue
        notifications.append(event_data)
        if clear:
            event_data["shown"] = True

    return notifications


class LLMProviderManager:
    """
    Manages LLM provider selection, fallback, and rate limiting.
    Fallback order: Groq → Gemini → OpenRouter
    """

    def __init__(self, db: Session):
        self.db = db
        self.groq = GroqProvider()
        self.gemini = GeminiProvider()
        self.openrouter = OpenRouterProvider()

    def call_with_fallback(
        self,
        system_prompt: str,
        user_prompt: str,
        paper_id: int,
    ) -> tuple[LLMResponse, dict]:
        """
        Call LLM with automatic fallback: Groq → Gemini → OpenRouter.

        Returns:
            tuple of (LLMResponse, metadata_dict)

        Raises:
            LLMError: If all providers fail
        """
        metadata = {
            "original_provider": None,
            "final_provider": None,
            "fallback_used": False,
            "retry_count": 0,
            "errors": [],
            "provider_attempts": [],
        }

        # Try primary provider (Groq) first
        if self.groq.is_configured and _provider_status["groq"].is_available:
            response, meta = self._try_provider(
                self.groq, system_prompt, user_prompt, paper_id
            )
            metadata["original_provider"] = "groq"
            metadata["retry_count"] = meta["retry_count"]
            metadata["errors"] = meta["errors"]
            metadata["provider_attempts"].append({"provider": "groq", "result": "success" if response else "failed"})

            if response is not None:
                metadata["final_provider"] = "groq"
                return response, metadata

            # Groq failed - check if we should fallback
            last_error = meta.get("last_error")
            if last_error and self._should_fallback(last_error):
                self._emit_quota_event("groq", last_error, paper_id)
            else:
                raise last_error

        # Fallback to Gemini
        if self.gemini.is_configured and _provider_status["gemini"].is_available:
            metadata["fallback_used"] = True
            response, meta = self._try_provider(
                self.gemini, system_prompt, user_prompt, paper_id
            )
            metadata["retry_count"] += meta["retry_count"]
            metadata["errors"].extend(meta["errors"])
            metadata["provider_attempts"].append({"provider": "gemini", "result": "success" if response else "failed"})

            if response is not None:
                metadata["final_provider"] = "gemini"
                return response, metadata

            # Gemini failed - check if we should fallback to OpenRouter
            last_error = meta.get("last_error")
            if last_error and self._should_fallback(last_error):
                self._emit_quota_event("gemini", last_error, paper_id)
            else:
                raise last_error

        # Fallback to OpenRouter (3rd) - ONLY if enabled
        if settings.openrouter_enabled and self.openrouter.is_configured and _provider_status["openrouter"].is_available:
            metadata["fallback_used"] = True
            response, meta = self._try_provider(
                self.openrouter, system_prompt, user_prompt, paper_id
            )
            metadata["retry_count"] += meta["retry_count"]
            metadata["errors"].extend(meta["errors"])
            metadata["provider_attempts"].append({"provider": "openrouter", "result": "success" if response else "failed"})

            if response is not None:
                metadata["final_provider"] = "openrouter"
                return response, metadata

            # All providers failed
            last_error = meta.get("last_error")
            self._emit_quota_event("openrouter", last_error, paper_id)
            raise last_error

        # No more providers available (OpenRouter disabled or all failed)
        raise LLMError(
            "All available providers failed (OpenRouter disabled or unavailable)",
            provider="manager",
        )

    def _try_provider(
        self,
        provider: LLMProvider,
        system_prompt: str,
        user_prompt: str,
        paper_id: int,
    ) -> tuple[Optional[LLMResponse], dict]:
        """
        Try a single provider with retries.
        Returns (response, meta) where response is None on failure.
        """
        config = provider.get_retry_config()
        max_retries = config["max_retries"]
        initial_backoff = config["initial_backoff"]
        max_backoff = config["max_backoff"]

        meta = {
            "retry_count": 0,
            "errors": [],
            "last_error": None,
        }

        for attempt in range(1, max_retries + 2):
            try:
                response = provider.call(system_prompt, user_prompt)
                _provider_status[provider.name].record_success()
                return response, meta

            except LLMError as e:
                _provider_status[provider.name].record_error(e)
                meta["retry_count"] += 1
                meta["last_error"] = e
                meta["errors"].append({
                    "provider": provider.name,
                    "attempt": attempt,
                    "error": e.message[:200],
                    "status_code": e.status_code,
                    "is_rate_limit": e.is_rate_limit,
                    "is_daily_limit": e.is_daily_limit,
                    "is_permanent": e.is_permanent,
                    "is_404": e.is_404,
                    "is_server_error": e.is_server_error,
                })

                # Don't retry permanent errors (auth, 404 model not found)
                if e.is_permanent:
                    logger.warning(
                        f"Paper {paper_id}: {provider.name} permanent error "
                        f"(status={e.status_code}): {e.message[:100]}"
                    )
                    break

                # Don't retry daily limits
                if e.is_daily_limit:
                    logger.warning(f"Paper {paper_id}: {provider.name} daily quota exhausted")
                    break

                # Don't retry 404 (model not found) - it's a configuration error
                if e.is_404:
                    logger.warning(
                        f"Paper {paper_id}: {provider.name} 404 model not found. "
                        f"Check model configuration: {getattr(settings, f'{provider.name}_model', 'unknown')}"
                    )
                    break

                # Retry server errors (5xx) with backoff
                if e.is_server_error:
                    logger.warning(f"Paper {paper_id}: {provider.name} server error (5xx)")

                # Check if we've exhausted retries
                if attempt > max_retries:
                    logger.warning(f"Paper {paper_id}: {provider.name} retries exhausted")
                    break

                # Calculate wait time
                if e.retry_after and e.retry_after > 0:
                    wait_seconds = e.retry_after
                    source = "Retry-After"
                else:
                    wait_seconds = min(initial_backoff * (2 ** (attempt - 1)), max_backoff)
                    source = "exponential backoff"

                # Add jitter
                jitter = wait_seconds * 0.25 * (2 * random.random() - 1)
                wait_seconds = max(0.1, wait_seconds + jitter)

                logger.info(
                    f"Paper {paper_id}: {provider.name} rate limited (attempt {attempt}/{max_retries + 1}). "
                    f"Waiting {wait_seconds:.2f}s ({source})"
                )
                time.sleep(wait_seconds)

            except Exception as e:
                # Unexpected error
                logger.error(f"Paper {paper_id}: {provider.name} unexpected error: {e}")
                meta["errors"].append({
                    "provider": provider.name,
                    "attempt": attempt,
                    "error": str(e)[:200],
                    "is_rate_limit": False,
                    "is_daily_limit": False,
                    "is_permanent": False,
                })
                break

        return None, meta

    def _should_fallback(self, error: LLMError) -> bool:
        """Determine if an error should trigger fallback to next provider."""
        # Fallback on rate limits and daily quota
        if error.is_rate_limit or error.is_daily_limit:
            return True
        # Fallback on server errors (5xx)
        if error.is_server_error:
            return True
        # Don't fallback on permanent errors (auth, 404 model not found)
        if error.is_permanent:
            return False
        # Don't fallback on 404 (model not found)
        if error.is_404:
            return False
        # Fallback on other errors
        return True

    def _emit_quota_event(self, provider_name: str, error: LLMError, paper_id: int):
        """Emit a quota event for frontend notification."""
        global _quota_events

        event_key = f"{provider_name}:{error.is_daily_limit}"
        now = time.time()

        # Check cooldown
        if event_key in _quota_events:
            last_time = _quota_events[event_key]["timestamp"]
            if now - last_time < QUOTA_NOTIFICATION_COOLDOWN_SECONDS:
                return  # Suppress duplicate

        event_data = {
            "timestamp": now,
            "shown": False,
            "provider": provider_name,
            "is_daily_limit": error.is_daily_limit,
            "paper_id": paper_id,
            "message": self._get_quota_message(provider_name, error),
        }

        _quota_events[event_key] = event_data
        logger.info(f"Quota event emitted: {event_key}")

    def _get_quota_message(self, provider_name: str, error: LLMError) -> str:
        """Get a human-readable quota event message."""
        if error.is_daily_limit:
            return f"{provider_name.upper()} daily quota exhausted. Switching to fallback provider."
        return f"{provider_name.upper()} rate limit reached. Retrying with backoff."
