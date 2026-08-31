#!/usr/bin/env python3
"""Run the test suite."""
import sys
import os

# Ensure we're in the right directory
os.chdir('/Users/ankit/Desktop/Systematic Literature Review/FL_SLR_Automation')
sys.path.insert(0, '/Users/ankit/Desktop/Systematic Literature Review/FL_SLR_Automation')

# Set minimal env vars
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('APP_ENV', 'testing')

try:
    import pytest
    sys.exit(pytest.main(['tests/', '-v', '--tb=short', '-x']))
except ImportError:
    print("pytest not installed. Trying to import modules directly...")
    
    # Try importing key modules to check for errors
    errors = []
    try:
        from app.core.config import settings
        print("✓ config imported")
    except Exception as e:
        errors.append(f"config: {e}")
        print(f"✗ config: {e}")
    
    try:
        from app.core.review_config import ReviewConfig
        config = ReviewConfig.default_config()
        print(f"✓ review_config imported, {len(config.search_families)} families")
    except Exception as e:
        errors.append(f"review_config: {e}")
        print(f"✗ review_config: {e}")
    
    try:
        from app.db.engine import Base, init_database
        from app.models.paper import Paper
        from app.models.search_run import SearchRun, SearchRunPaper, SourceProvenance
        from app.models.screening import ScreeningDecision, AuditLog
        from app.models.pdf_file import PdfFile
        print("✓ all models imported")
    except Exception as e:
        errors.append(f"models: {e}")
        print(f"✗ models: {e}")
    
    try:
        from app.services.openalex import OpenAlexConnector, OpenAlexError
        print("✓ openalex imported")
    except Exception as e:
        errors.append(f"openalex: {e}")
        print(f"✗ openalex: {e}")
    
    try:
        from app.services.paper_parser import parse_openalex_work, reconstruct_abstract, normalize_doi, normalize_title
        print("✓ paper_parser imported")
    except Exception as e:
        errors.append(f"paper_parser: {e}")
        print(f"✗ paper_parser: {e}")
    
    try:
        from app.api.main import app
        print("✓ api.main imported")
    except Exception as e:
        errors.append(f"api.main: {e}")
        print(f"✗ api.main: {e}")
    
    if errors:
        print(f"\n{len(errors)} import(s) failed")
        sys.exit(1)
    else:
        print("\nAll imports successful!")
        sys.exit(0)
