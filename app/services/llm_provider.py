"""
LLM Provider Abstraction
==========================
Defines the interface for LLM providers used in AI screening.
Each provider must implement the same interface so they are interchangeable.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""
    content: str
    model: str
    provider: str
    token_usage: Optional[dict] = None


@dataclass
class LLMError(Exception):
    """Standardized error from any LLM provider."""
    message: str
    status_code: Optional[int] = None
    retry_after: Optional[float] = None
    is_rate_limit: bool = False
    is_daily_limit: bool = False
    is_permanent: bool = False
    provider: str = ""


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'groq', 'gemini')."""
        pass

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Whether this provider has valid configuration."""
        pass

    @abstractmethod
    def call(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        """
        Call the LLM with the given prompts.
        Returns LLMResponse on success.
        Raises LLMError on failure.
        """
        pass

    @abstractmethod
    def get_retry_config(self) -> dict:
        """Return retry configuration for this provider."""
        pass
