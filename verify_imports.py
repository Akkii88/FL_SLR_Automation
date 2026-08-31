#!/usr/bin/env python3
"""Verify all imports work correctly."""
import sys
import os

# Set up path and minimal env
sys.path.insert(0, '/Users/ankit/Desktop/Systematic Literature Review/FL_SLR_Automation')
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')

results = []

def check(name, func):
    try:
        func()
        results.append((name, "OK", ""))
    except Exception as e:
        results.append((name, "FAIL", str(e)))

# Core
check("core.config", lambda: __import__('app.core.config', fromlist=['settings']))
check("core.review_config", lambda: __import__('app.core.review_config', fromlist=['ReviewConfig']))

# DB
check("db.engine", lambda: __import__('app.db.engine', fromlist=['Base', 'init_database']))

# Models
check("models.paper", lambda: __import__('app.models.paper', fromlist=['Paper']))
check("models.search_run", lambda: __import__('app.models.search_run', fromlist=['SearchRun', 'SourceProvenance', 'SearchRunPaper']))
check("models.screening", lambda: __import__('app.models.screening', fromlist=['ScreeningDecision', 'AuditLog']))
check("models.pdf_file", lambda: __import__('app.models.pdf_file', fromlist=['PdfFile']))
check("models.all", lambda: __import__('app.models', fromlist=['Paper', 'SearchRun', 'ScreeningDecision']))

# Services
check("services.openalex", lambda: __import__('app.services.openalex', fromlist=['OpenAlexConnector']))
check("services.paper_parser", lambda: __import__('app.services.paper_parser', fromlist=['parse_openalex_work', 'reconstruct_abstract']))
check("services.search_service", lambda: __import__('app.services.search_service', fromlist=['SearchService']))

# API
check("api.main", lambda: __import__('app.api.main', fromlist=['app']))

# Print results
print("\n=== Import Verification Results ===\n")
all_ok = True
for name, status, error in results:
    if status == "FAIL":
        all_ok = False
    symbol = "✓" if status == "OK" else "✗"
    print(f"  {symbol} {name}: {status}")
    if error:
        print(f"      Error: {error}")

print()
if all_ok:
    print("All imports successful!")
else:
    print("Some imports failed. See above for details.")
    sys.exit(1)
