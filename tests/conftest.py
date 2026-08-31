"""
Test Configuration
===================
Sets up test database and fixtures.
"""

import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.engine import Base, get_db
from app.core.review_config import ReviewConfig

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="session")
def engine():
    """Create a test database engine."""
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db(engine):
    """Create a fresh database session for each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def sample_review_config():
    """Provide a sample review configuration for testing."""
    return ReviewConfig.default_config()


@pytest.fixture
def sample_openalex_work():
    """Provide a sample OpenAlex work record for testing."""
    return {
        "id": "https://openalex.org/W1234567890",
        "doi": "10.1234/example.2023.001",
        "title": "A Comparative Study of Federated Learning Algorithms",
        "display_name": "A Comparative Study of Federated Learning Algorithms",
        "publication_date": "2023-06-15",
        "publication_year": 2023,
        "abstract_inverted_index": {
            "federated": [0],
            "learning": [1],
            "is": [2],
            "a": [3],
            "distributed": [4],
            "approach": [5],
            "to": [6],
            "machine": [7],
            "learning": [8],
        },
        "authorships": [
            {
                "author": {
                    "display_name": "John Doe",
                    "id": "https://openalex.org/A123",
                },
                "institutions": [
                    {"display_name": "MIT", "id": "https://openalex.org/I123"}
                ],
            },
            {
                "author": {
                    "display_name": "Jane Smith",
                    "id": "https://openalex.org/A456",
                },
                "institutions": [],
            },
        ],
        "host_venue": {
            "display_name": "International Conference on Machine Learning",
        },
        "primary_location": {
            "landing_page_url": "https://example.org/paper",
            "pdf_url": "https://example.org/paper.pdf",
            "source": {"display_name": "ICML"},
        },
        "type": "conference-paper",
        "language": "en",
        "cited_by_count": 42,
        "open_access": {
            "is_oa": True,
            "oa_status": "gold",
            "oa_url": "https://example.org/paper.pdf",
        },
        "locations": [
            {
                "landing_page_url": "https://example.org/paper",
                "pdf_url": "https://example.org/paper.pdf",
                "version": "publishedVersion",
            }
        ],
        "is_retracted": False,
    }
