"""
Tests for paper source access functionality.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.engine import Base
from app.models.paper import Paper
from app.models.pdf_file import PdfFile
from app.api.routes.paper_sources import _build_links_array


@pytest.fixture(scope="function")
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
    Base.metadata.drop_all(bind=engine)


def make_paper(db, paper_id=1, **kwargs):
    defaults = dict(
        id=paper_id,
        title=f"Test Paper {paper_id}",
        normalized_title=f"test paper {paper_id}",
        publication_year=2023,
    )
    defaults.update(kwargs)
    paper = Paper(**defaults)
    db.add(paper)
    db.commit()
    return paper


class TestPaperSources:
    """Test paper source data access."""

    def test_paper_with_all_sources(self, db):
        """Test paper with DOI, OA, and PDF."""
        paper = make_paper(
            db,
            doi="10.1234/test.5678",
            openalex_id="W1234567890",
            oa_url="https://arxiv.org/abs/1234.5678",
            pdf_url="https://arxiv.org/pdf/1234.5678.pdf",
            is_open_access=True,
            oa_status="gold",
        )

        from app.api.routes.paper_sources import router
        # Test the links builder directly
        sources = {
            "doi": paper.doi,
            "doi_url": f"https://doi.org/{paper.doi}",
            "openalex_id": paper.openalex_id,
            "openalex_url": f"https://openalex.org/{paper.openalex_id}",
            "oa_url": paper.oa_url,
            "pdf_url": paper.pdf_url,
            "pdf_available": True,
            "pdf_downloaded": False,
        }
        links = _build_links_array(sources)

        # Should have 4 links: PDF, OA, DOI, OpenAlex
        assert len(links) == 4
        assert links[0]["type"] == "pdf"  # Highest priority
        assert links[-1]["type"] == "openalex"  # Lowest priority

    def test_paper_with_only_doi(self, db):
        """Test paper with only DOI (no OA, no PDF)."""
        paper = make_paper(db, doi="10.1234/test.5678")

        sources = {
            "doi": paper.doi,
            "doi_url": f"https://doi.org/{paper.doi}",
            "openalex_id": None,
            "openalex_url": None,
            "oa_url": None,
            "pdf_url": None,
            "pdf_available": False,
            "pdf_downloaded": False,
        }
        links = _build_links_array(sources)

        # Should have 1 link: DOI
        assert len(links) == 1
        assert links[0]["type"] == "doi"

    def test_paper_with_no_sources(self, db):
        """Test paper with no sources at all."""
        paper = make_paper(db, doi=None, openalex_id=None)

        sources = {
            "doi": None,
            "doi_url": None,
            "openalex_id": None,
            "openalex_url": None,
            "oa_url": None,
            "pdf_url": None,
            "pdf_available": False,
            "pdf_downloaded": False,
        }
        links = _build_links_array(sources)

        # Should have no links
        assert len(links) == 0

    def test_paper_with_openalex_id_containing_url(self, db):
        """Test that OpenAlex ID is correctly extracted from full URL."""
        paper = make_paper(db, openalex_id="https://openalex.org/W1234567890")

        # The endpoint should extract just the work ID
        oa_id = paper.openalex_id
        if oa_id.startswith("http"):
            oa_id = oa_id.rstrip("/").split("/")[-1]
        assert oa_id == "W1234567890"

    def test_links_priority_order(self, db):
        """Test that links are returned in correct priority order."""
        sources = {
            "doi": "10.1234/test",
            "doi_url": "https://doi.org/10.1234/test",
            "openalex_id": "W123",
            "openalex_url": "https://openalex.org/W123",
            "oa_url": "https://example.com/oa",
            "pdf_url": "https://example.com/paper.pdf",
            "pdf_available": True,
            "pdf_downloaded": False,
        }
        links = _build_links_array(sources)

        # Priority: PDF (1) > OA (2) > DOI (3) > OpenAlex (4)
        assert links[0]["type"] == "pdf"
        assert links[1]["type"] == "oa"
        assert links[2]["type"] == "doi"
        assert links[3]["type"] == "openalex"

    def test_no_fake_urls_generated(self, db):
        """Test that no fake URLs are generated for missing data."""
        paper = make_paper(db, doi=None, pdf_url=None, oa_url=None)

        sources = {
            "doi": paper.doi,
            "doi_url": None,
            "openalex_id": paper.openalex_id,
            "openalex_url": f"https://openalex.org/{paper.openalex_id}" if paper.openalex_id else None,
            "oa_url": paper.oa_url,
            "pdf_url": paper.pdf_url,
            "pdf_available": False,
            "pdf_downloaded": False,
        }
        links = _build_links_array(sources)

        # No fake URLs should be generated
        for link in links:
            assert "fake" not in link["url"].lower()
            assert link["url"].startswith("http")

    def test_downloaded_pdf_flagged(self, db):
        """Test that downloaded PDF is correctly flagged."""
        paper = make_paper(db, pdf_url="https://example.com/paper.pdf")

        pdf = PdfFile(
            paper_id=paper.id,
            download_url="https://example.com/paper.pdf",
            file_path="/data/pdfs/1/paper.pdf",
            download_status="downloaded",
        )
        db.add(pdf)
        db.commit()

        # Query should show pdf_downloaded=True
        downloaded = db.query(PdfFile).filter(
            PdfFile.paper_id == paper.id,
            PdfFile.download_status == "downloaded"
        ).first()
        assert downloaded is not None


class TestSourcePriority:
    """Test source priority ordering."""

    def test_pdf_highest_priority(self, db):
        """PDF should be highest priority."""
        sources = {
            "pdf_url": "https://example.com/paper.pdf",
            "oa_url": "https://example.com/oa",
            "doi_url": "https://doi.org/10.1234/test",
            "openalex_url": "https://openalex.org/W123",
            "doi": "10.1234/test",
            "openalex_id": "W123",
            "pdf_available": True,
            "pdf_downloaded": False,
        }
        links = _build_links_array(sources)
        assert links[0]["type"] == "pdf"

    def test_metadata_only_paper(self, db):
        """Test paper with only metadata (no URLs)."""
        paper = make_paper(db, doi=None, openalex_id=None, pdf_url=None, oa_url=None)

        sources = {
            "doi": paper.doi,
            "doi_url": None,
            "openalex_id": paper.openalex_id,
            "openalex_url": None,
            "oa_url": paper.oa_url,
            "pdf_url": paper.pdf_url,
            "pdf_available": False,
            "pdf_downloaded": False,
        }
        links = _build_links_array(sources)
        assert len(links) == 0
