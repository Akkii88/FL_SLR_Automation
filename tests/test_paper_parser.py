"""
Tests: Paper Parser Service
============================
Tests for OpenAlex work parsing, abstract reconstruction,
DOI normalization, and title normalization.
"""

import pytest
from app.services.paper_parser import (
    parse_openalex_work,
    reconstruct_abstract,
    normalize_doi,
    normalize_title,
)


class TestReconstructAbstract:
    """Test abstract reconstruction from inverted index."""

    def test_basic_reconstruction(self):
        inverted = {
            "federated": [0],
            "learning": [1],
            "is": [2],
            "great": [3],
        }
        result = reconstruct_abstract(inverted)
        assert result == "federated learning is great"

    def test_multiple_positions(self):
        inverted = {
            "the": [0, 5],
            "cat": [1],
            "sat": [2],
            "on": [3],
            "mat": [4],
        }
        result = reconstruct_abstract(inverted)
        assert result == "the cat sat on the mat"

    def test_none_input(self):
        assert reconstruct_abstract(None) is None

    def test_empty_dict(self):
        assert reconstruct_abstract({}) is None

    def test_non_dict_input(self):
        assert reconstruct_abstract("not a dict") is None

    def test_abstract_with_extra_whitespace(self):
        inverted = {
            "hello": [0],
            "world": [1],
        }
        result = reconstruct_abstract(inverted)
        assert result == "hello world"
        assert "  " not in result  # No double spaces


class TestNormalizeDoi:
    """Test DOI normalization."""

    def test_url_prefix_removal(self):
        assert normalize_doi("https://doi.org/10.1234/example") == "10.1234/example"

    def test_http_prefix_removal(self):
        assert normalize_doi("http://doi.org/10.1234/example") == "10.1234/example"

    def test_doi_org_prefix_removal(self):
        assert normalize_doi("doi.org/10.1234/example") == "10.1234/example"

    def test_lowercase(self):
        assert normalize_doi("10.1234/EXAMPLE") == "10.1234/example"

    def test_whitespace_stripping(self):
        assert normalize_doi("  10.1234/example  ") == "10.1234/example"

    def test_none_input(self):
        assert normalize_doi(None) is None

    def test_empty_string(self):
        assert normalize_doi("") is None


class TestNormalizeTitle:
    """Test title normalization for deduplication."""

    def test_lowercase(self):
        assert normalize_title("Hello World") == "hello world"

    def test_punctuation_removal(self):
        assert normalize_title("Hello, World!") == "hello world"

    def test_whitespace_collapsing(self):
        assert normalize_title("Hello   World") == "hello world"

    def test_strip(self):
        assert normalize_title("  Hello World  ") == "hello world"

    def test_none_input(self):
        assert normalize_title(None) == ""

    def test_empty_string(self):
        assert normalize_title("") == ""

    def test_special_characters(self):
        assert normalize_title("FedAvg: A Method (v2.0)") == "fedavg a method v20"


class TestParseOpenAlexWork:
    """Test full work record parsing."""

    def test_basic_parsing(self, sample_openalex_work):
        paper = parse_openalex_work(sample_openalex_work)
        assert paper is not None
        assert paper.title == "A Comparative Study of Federated Learning Algorithms"
        assert paper.publication_year == 2023
        assert paper.doi == "10.1234/example.2023.001"
        assert paper.is_open_access is True
        assert paper.citation_count == 42

    def test_openalex_id_extraction(self, sample_openalex_work):
        paper = parse_openalex_work(sample_openalex_work)
        assert paper.openalex_id == "W1234567890"

    def test_missing_title(self):
        work = {"id": "W123", "title": None, "display_name": None}
        paper = parse_openalex_work(work)
        assert paper is None

    def test_empty_title(self):
        work = {"id": "W123", "title": ""}
        paper = parse_openalex_work(work)
        assert paper is None

    def test_display_name_fallback(self):
        work = {"id": "W123", "title": None, "display_name": "Fallback Title"}
        paper = parse_openalex_work(work)
        assert paper is not None
        assert paper.title == "Fallback Title"

    def test_authors_serialization(self, sample_openalex_work):
        paper = parse_openalex_work(sample_openalex_work)
        import json
        authors = json.loads(paper.authors)
        assert len(authors) == 2
        assert "John Doe" in authors
        assert "Jane Smith" in authors

    def test_no_abstract(self):
        work = {
            "id": "W123",
            "title": "Test Paper",
            "abstract_inverted_index": None,
        }
        paper = parse_openalex_work(work)
        assert paper is not None
        assert paper.abstract is None

    def test_pdf_url_extraction(self, sample_openalex_work):
        paper = parse_openalex_work(sample_openalex_work)
        assert paper.pdf_url == "https://example.org/paper.pdf"

    def test_oa_status(self, sample_openalex_work):
        paper = parse_openalex_work(sample_openalex_work)
        assert paper.oa_status == "gold"

    def test_retraction_flag(self):
        work = {
            "id": "W123",
            "title": "Retracted Paper",
            "is_retracted": True,
        }
        paper = parse_openalex_work(work)
        assert paper.is_retracted is True

    def test_malformed_record_handling(self):
        """Parser should not crash on unexpected data."""
        work = {"id": "W123", "title": "Test", "authorships": "unexpected"}
        # Should not raise
        paper = parse_openalex_work(work)
        # May return None or a partial record, but must not crash
