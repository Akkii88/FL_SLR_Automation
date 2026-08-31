"""
Tests: Checkpoint Service
===========================
Tests for search checkpoint/resume functionality.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from app.services.checkpoint import (
    save_checkpoint,
    load_checkpoint,
    clear_checkpoint,
    has_checkpoint,
    get_checkpoint_path,
)


class TestCheckpoint:
    """Test checkpoint save/load/clear."""

    def test_save_and_load(self, tmp_path):
        with patch("app.services.checkpoint.get_checkpoint_path", return_value=tmp_path / "checkpoint.json"):
            save_checkpoint(
                search_run_id=1,
                cursor="abc123",
                records_retrieved=50,
                pages_retrieved=3,
                family_name="A",
                query="federated learning",
            )

            assert has_checkpoint()

            loaded = load_checkpoint()
            assert loaded is not None
            assert loaded["search_run_id"] == 1
            assert loaded["cursor"] == "abc123"
            assert loaded["records_retrieved"] == 50
            assert loaded["family_name"] == "A"
            assert loaded["query"] == "federated learning"

    def test_load_no_checkpoint(self, tmp_path):
        with patch("app.services.checkpoint.get_checkpoint_path", return_value=tmp_path / "nonexistent.json"):
            assert not has_checkpoint()
            assert load_checkpoint() is None

    def test_clear_checkpoint(self, tmp_path):
        with patch("app.services.checkpoint.get_checkpoint_path", return_value=tmp_path / "checkpoint.json"):
            save_checkpoint(1, "cursor", 10, 1, "A", "query")
            assert has_checkpoint()

            clear_checkpoint()
            assert not has_checkpoint()

    def test_checkpoint_creates_directory(self, tmp_path):
        nested = tmp_path / "deep" / "subdir" / "checkpoint.json"
        with patch("app.services.checkpoint.get_checkpoint_path", return_value=nested):
            save_checkpoint(1, "cursor", 10, 1, "A", "query")
            assert nested.exists()

    def test_checkpoint_includes_timestamp(self, tmp_path):
        with patch("app.services.checkpoint.get_checkpoint_path", return_value=tmp_path / "checkpoint.json"):
            save_checkpoint(1, "cursor", 10, 1, "A", "query")
            loaded = load_checkpoint()
            assert "saved_at" in loaded
            assert "software_version" in loaded
