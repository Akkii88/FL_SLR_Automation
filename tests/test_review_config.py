"""
Tests: Review Configuration
=============================
Tests for loading, saving, and validating review configuration.
"""

import json
import pytest
from pathlib import Path
from app.core.review_config import (
    ReviewConfig,
    SearchFamily,
    load_or_create_config,
    get_config_path,
)


class TestSearchFamily:
    """Test SearchFamily model."""

    def test_create_search_family(self):
        sf = SearchFamily(
            name="A",
            description="Test family",
            query="federated learning",
        )
        assert sf.name == "A"
        assert sf.enabled is True

    def test_serialization(self):
        sf = SearchFamily(name="B", description="Test", query="test query")
        data = sf.model_dump()
        assert data["name"] == "B"
        assert data["query"] == "test query"


class TestReviewConfig:
    """Test ReviewConfig model."""

    def test_default_config(self):
        config = ReviewConfig.default_config()
        assert "Best" in config.title
        assert len(config.search_families) == 6
        assert config.max_candidates_per_family == 500

    def test_search_family_names(self):
        config = ReviewConfig.default_config()
        names = [sf.name for sf in config.search_families]
        assert names == ["A", "B", "C", "D", "E", "F"]

    def test_save_and_load(self, tmp_path):
        config = ReviewConfig.default_config()
        config_path = tmp_path / "test_config.json"

        config.save(config_path)
        assert config_path.exists()

        loaded = ReviewConfig.load(config_path)
        assert loaded.title == config.title
        assert len(loaded.search_families) == len(config.search_families)

    def test_save_creates_directories(self, tmp_path):
        config = ReviewConfig.default_config()
        config_path = tmp_path / "subdir" / "config.json"

        config.save(config_path)
        assert config_path.exists()

    def test_default_dates(self):
        config = ReviewConfig.default_config()
        assert config.start_date.year == 2019
        assert config.end_date.year == 2026

    def test_custom_config(self):
        config = ReviewConfig(
            title="Custom Review",
            max_candidates_per_family=1000,
        )
        assert config.max_candidates_per_family == 1000
        assert len(config.search_families) == 0  # No defaults when custom

    def test_all_search_families_have_queries(self):
        config = ReviewConfig.default_config()
        for sf in config.search_families:
            assert len(sf.query) > 0, f"Search family {sf.name} has empty query"

    def test_no_statistical_terms_in_queries(self):
        """Verify search queries do NOT contain statistical terms."""
        config = ReviewConfig.default_config()
        forbidden_terms = ["p-value", "confidence interval", "random seed", "statistical significance"]
        for sf in config.search_families:
            query_lower = sf.query.lower()
            for term in forbidden_terms:
                assert term not in query_lower, (
                    f"Search family {sf.name} contains forbidden term '{term}'"
                )


class TestLoadOrCreateConfig:
    """Test config loading and creation."""

    def test_creates_default_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "app.core.review_config.get_config_path",
            lambda _: tmp_path / "review_config.json",
        )
        config = load_or_create_config(tmp_path)
        assert config is not None
        assert (tmp_path / "review_config.json").exists()

    def test_loads_existing(self, tmp_path, monkeypatch):
        # Create a config first
        config = ReviewConfig(title="Existing Config")
        config_path = tmp_path / "review_config.json"
        config.save(config_path)

        monkeypatch.setattr(
            "app.core.review_config.get_config_path",
            lambda _: config_path,
        )
        loaded = load_or_create_config(tmp_path)
        assert loaded.title == "Existing Config"
