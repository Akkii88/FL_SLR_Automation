"""
Demo Data Loader
=================
Loads clearly-labeled TEST DATA for development and demonstration.
All records are marked as TEST DATA and are not real research papers.
"""

import json
import logging
from datetime import datetime

from app.db.engine import SessionLocal, init_database
from app.models.paper import Paper
from app.models.screening import AuditLog

logger = logging.getLogger(__name__)

# Clearly fictional test papers for development
TEST_PAPERS = [
    {
        "openalex_id": "TEST_W0000000001",
        "doi": "10.0000/test.001",
        "title": "[TEST DATA] A Comparative Study of Federated Learning Algorithms under Non-IID Data Distributions",
        "abstract": "[TEST DATA] This is a fictional paper created for testing purposes only. "
                    "It compares FedAvg, FedProx, and SCAFFOLD under Dirichlet-partitioned CIFAR-10.",
        "publication_year": 2023,
        "authors": json.dumps(["Test Author A", "Test Author B"]),
        "institutions": json.dumps(["Test University"]),
        "source": "Test Conference Proceedings",
        "source_type": "conference-paper",
        "language": "en",
        "citation_count": 42,
        "is_open_access": True,
        "oa_status": "gold",
        "pdf_url": None,
    },
    {
        "openalex_id": "TEST_W0000000002",
        "doi": "10.0000/test.002",
        "title": "[TEST DATA] Personalized Federated Learning: A Benchmark Under Heterogeneous Conditions",
        "abstract": "[TEST DATA] This is a fictional paper. It evaluates personalized FL methods "
                    "using pathological Non-IID splits on medical imaging datasets.",
        "publication_year": 2024,
        "authors": json.dumps(["Test Author C"]),
        "institutions": json.dumps(["Test Institute"]),
        "source": "Test Journal of Machine Learning",
        "source_type": "journal-article",
        "language": "en",
        "citation_count": 15,
        "is_open_access": False,
        "oa_status": "closed",
        "pdf_url": None,
    },
    {
        "openalex_id": "TEST_W0000000003",
        "doi": "10.0000/test.003",
        "title": "[TEST DATA] Communication-Efficient Federated Optimization with Gradient Correction",
        "abstract": None,  # Test missing abstract handling
        "publication_year": 2022,
        "authors": json.dumps(["Test Author D", "Test Author E", "Test Author F"]),
        "institutions": json.dumps(["Test Lab A", "Test Lab B"]),
        "source": "Test Workshop on FL",
        "source_type": "conference-paper",
        "language": "en",
        "citation_count": 88,
        "is_open_access": True,
        "oa_status": "green",
        "pdf_url": "https://example.org/test_paper.pdf",
    },
    {
        "openalex_id": "TEST_W0000000004",
        "doi": "10.0000/test.004",
        "title": "[TEST DATA] Robust Federated Learning Against Byzantine Clients: A Comparative Analysis",
        "abstract": "[TEST DATA] This fictional paper studies robustness of FL algorithms "
                    "under adversarial conditions with heterogeneous data.",
        "publication_year": 2023,
        "authors": json.dumps(["Test Author G"]),
        "institutions": json.dumps(["Test Security Lab"]),
        "source": "Test Symposium on Security",
        "source_type": "conference-paper",
        "language": "en",
        "citation_count": 0,
        "is_open_access": True,
        "oa_status": "gold",
        "pdf_url": None,
    },
    {
        "openalex_id": "TEST_W0000000005",
        "doi": "10.0000/test.005",
        "title": "[TEST DATA] Federated Learning for Image Classification: An Empirical Study",
        "abstract": "[TEST DATA] This fictional paper evaluates multiple FL baselines "
                    "on standard vision benchmarks with various data partitioning strategies.",
        "publication_year": 2021,
        "authors": json.dumps(["Test Author H", "Test Author I"]),
        "institutions": json.dumps(["Test AI Research Center"]),
        "source": "Test AI Conference",
        "source_type": "conference-paper",
        "language": "en",
        "citation_count": 156,
        "is_open_access": False,
        "oa_status": "closed",
        "pdf_url": None,
    },
]


def load_demo_data():
    """Load test/demo data into the database."""
    init_database()
    db = SessionLocal()

    try:
        # Check if test data already exists
        existing = db.query(Paper).filter(
            Paper.openalex_id.like("TEST_%")
        ).first()

        if existing:
            print("[DEMO] Test data already exists. Skipping.")
            return

        print("[DEMO] Loading test data...")

        for paper_data in TEST_PAPERS:
            paper = Paper(**paper_data)
            paper.normalized_title = paper_data["title"].lower()
            paper.screening_status = "not_screened"
            paper.duplicate_status = "unique"
            db.add(paper)

        # Audit log
        audit = AuditLog(
            action="demo_data_loaded",
            entity_type="system",
            entity_id=0,
            description=f"Loaded {len(TEST_PAPERS)} test papers for demonstration",
            actor="system",
        )
        db.add(audit)

        db.commit()
        print(f"[DEMO] Loaded {len(TEST_PAPERS)} test papers successfully.")
        print("[DEMO] NOTE: All records are clearly marked as TEST DATA.")

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to load demo data: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    load_demo_data()
