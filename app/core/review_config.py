"""
FL-SLR Review Configuration
============================
Manages the systematic review configuration stored in a versioned JSON file.
This includes: title, dates, search sources, search families, and methodology settings.
"""

import json
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


class SearchFamily(BaseModel):
    """A search family defines a group of related search queries."""
    name: str
    description: str
    query: str
    enabled: bool = True


class ReviewConfig(BaseModel):
    """The full systematic review configuration."""

    # --- Identity ---
    title: str = "Is \"Best\" Really Best? A Systematic Review of Evidence Quality Behind Federated Learning Algorithm Superiority Claims under Non-IID Data"
    version: str = "1.0.0"
    config_schema_version: str = "1.0"

    # --- Date Range ---
    start_date: date = date(2019, 1, 1)
    end_date: date = date(2026, 8, 30)

    # --- Primary Source ---
    primary_source: str = "OpenAlex"

    # --- Search Families ---
    search_families: list[SearchFamily] = Field(default_factory=list)

    # --- Retrieval Limits ---
    max_candidates_per_family: int = 500

    # --- Metadata ---
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def save(self, path: Path) -> None:
        """Save configuration to a JSON file."""
        self.updated_at = datetime.now(timezone.utc)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=2, default=str)

    @classmethod
    def load(cls, path: Path) -> "ReviewConfig":
        """Load configuration from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Pydantic v2 handles ISO date/datetime string parsing automatically
        # when the target field types are date/datetime.
        return cls.model_validate(data)

    @classmethod
    def default_config(cls) -> "ReviewConfig":
        """Create the default review configuration with predefined search families."""
        return cls(
            search_families=[
                SearchFamily(
                    name="A",
                    description="Core Federated Learning + Non-IID + Comparison",
                    query='(federated learning) AND (non-IID OR heterogeneous) AND (comparison OR comparative OR benchmark OR evaluation)',
                ),
                SearchFamily(
                    name="B",
                    description="Federated Learning algorithm names + heterogeneity",
                    query='(FedAvg OR FedProx OR SCAFFOLD OR FedNova OR FedOpt OR Moon OR FedBN) AND (non-IID OR heterogeneous OR skewed)',
                ),
                SearchFamily(
                    name="C",
                    description="Non-IID construction methods + Federated Learning",
                    query='(Dirichlet OR pathological OR shard-based OR label skew OR quantity skew) AND (federated learning)',
                ),
                SearchFamily(
                    name="D",
                    description="Benchmark/comparative FL terminology",
                    query='(federated learning) AND (benchmark OR state-of-the-art OR outperforms OR superior) AND (non-IID OR heterogeneous)',
                ),
                SearchFamily(
                    name="E",
                    description="Personalized Federated Learning + heterogeneity",
                    query='(personalized federated learning OR FedPer OR pFL) AND (non-IID OR heterogeneous)',
                ),
                SearchFamily(
                    name="F",
                    description="Robust/asynchronous/optimization FL + heterogeneity",
                    query='(robust federated learning OR asynchronous federated learning OR federated optimization) AND (non-IID OR heterogeneous)',
                ),
            ]
        )


def get_config_path(project_root: Path) -> Path:
    """Return the path to the review configuration file."""
    return project_root / "data" / "review_config.json"


def load_or_create_config(project_root: Path) -> ReviewConfig:
    """Load existing config or create default if not found."""
    config_path = get_config_path(project_root)
    if config_path.exists():
        return ReviewConfig.load(config_path)
    config = ReviewConfig.default_config()
    config.save(config_path)
    return config
