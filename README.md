# FL-SLR Automation

> **"Is 'Best' Really Best? A Systematic Review of Evidence Quality Behind Federated Learning Algorithm Superiority Claims under Non-IID Data"**

A local research-assistant application for performing a complete Systematic Literature Review (SLR) pipeline in Federated Learning.

---

## 🎯 Purpose

This tool supports the full SLR workflow:

1. **Search** — Automated discovery via OpenAlex (with architecture for additional sources)
2. **Collect Metadata** — Structured bibliographic data with full provenance
3. **Deduplicate** — Robust deduplication with manual override capability
4. **Find Full Text** — Open-access PDF discovery (no paywall bypass)
5. **Screen** — Title/abstract and full-text screening with structured decisions
6. **Extract** — Claim-level evidence extraction using the SLR Codebook
7. **Assess Quality** — Evidence quality framework (5 independent dimensions)
8. **Track PRISMA** — Automated PRISMA flow tracking
9. **Export** — CSV, XLSX, JSON, RIS, BibTeX

---

## 🛡️ Research Integrity Principles

This software is built for **reproducibility, auditability, and traceability**:

- **No fabrication** — Never invents papers, metadata, DOIs, or results
- **No silent modifications** — All changes are logged in an immutable audit trail
- **No automatic eligibility** — Screening decisions require human judgment
- **No paywall bypass** — Only open/legal full text is collected
- **No hidden scoring** — Evidence quality dimensions are kept independent
- **Reversible decisions** — Every automated decision can be overridden
- **Complete provenance** — Every record retains its full discovery history

---

## 🏗️ Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI |
| Database | SQLite (via SQLAlchemy) |
| HTTP Client | httpx |
| Data Processing | pandas, openpyxl |
| Validation | Pydantic v2 |
| Frontend | React + TypeScript (future phase) |

---

## ✅ Phase 1 Complete

Phase 1 is fully implemented and ready to use:

- ✅ Project structure and configuration
- ✅ SQLAlchemy database with all core models
- ✅ Review configuration system (JSON-based)
- ✅ OpenAlex API connector with pagination, retries, rate-limit handling
- ✅ Paper metadata parser (abstract reconstruction, DOI/title normalization)
- ✅ Search orchestration service with provenance tracking
- ✅ FastAPI endpoints (config, search, papers, screening, dashboard)
- ✅ Audit logging system
- ✅ Demo data loader
- ✅ Comprehensive test suite

---

## ✅ Phase 2 Complete

Phase 2 is fully implemented:

- ✅ Multiple search families (A–F) with combined results
- ✅ Full cursor-based pagination with resumable searches
- ✅ Checkpoint/resume support (auto-saves every 50 records)
- ✅ Retry tracking (counts actual retries from 429s, timeouts, server errors)
- ✅ Enhanced search run logging (duration, pages, retries, year filter)
- ✅ Source provenance tracking (many-to-many: paper ↔ search families)
- ✅ Provenance API endpoints (per-paper, per-family, summary)
- ✅ Paper detail includes provenance history
- ✅ Search log export (JSON, CSV)
- ✅ Candidate list export (JSON, CSV)
- ✅ Audit log export (JSON, CSV)
- ✅ Enhanced dashboard (search family breakdown, search stats, audit count)
- ✅ Comprehensive Phase 2 test suite

### New API Calls

```bash
# Resume a search from checkpoint
curl -X POST http://127.0.0.1:8000/api/search/resume

# View paper provenance (which searches found it)
curl http://127.0.0.1:8000/api/provenance/paper/1

# View papers found by search family A
curl http://127.0.0.1:8000/api/provenance/family/A

# Export search log as CSV
curl "http://127.0.0.1:8000/api/export/search-log?format=csv"

# Export candidates as CSV
curl "http://127.0.0.1:8000/api/export/candidates?format=csv"

# Export audit log as JSON
curl "http://127.0.0.1:8000/api/export/audit-log?format=json"
```

---

## ✅ Phase 3 Complete

Phase 3 is fully implemented:

- ✅ **5-pass deduplication engine**: DOI exact → OpenAlex ID exact → title+year exact → fuzzy title (90%) → author/year (80%)
- ✅ **Never deletes records**: All duplicates marked, never removed
- ✅ **Version relationship detection**: Conference vs journal, arXiv vs published — NOT auto-merged
- ✅ **Deduplication log**: Every comparison logged with type, confidence, status
- ✅ **Duplicate groups**: View all groups of duplicates with canonical record
- ✅ **Manual confirm/reject/override**: Full human control over duplicate decisions
- ✅ **Dry-run mode**: Preview duplicates without modifying data
- ✅ **Deduplication statistics**: Counts by status and match type
- ✅ **Comprehensive test suite**: 20+ tests covering all match types and edge cases

### Deduplication API Calls

```bash
# Run deduplication (dry run first)
curl -X POST http://127.0.0.1:8000/api/deduplication/run \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'

# Run for real
curl -X POST http://127.0.0.1:8000/api/deduplication/run \
  -H "Content-Type: application/json" \
  -d '{"dry_run": false}'

# View duplicate groups
curl http://127.0.0.1:8000/api/deduplication/groups

# View statistics
curl http://127.0.0.1:8000/api/deduplication/stats

# Review probable duplicates
curl "http://127.0.0.1:8000/api/deduplication/review?status=probable_duplicate"

# Confirm two papers are duplicates (paper 2 → paper 1)
curl -X POST http://127.0.0.1:8000/api/deduplication/confirm \
  -H "Content-Type: application/json" \
  -d '{"paper_id_a": 1, "paper_id_b": 2, "canonical_id": 1}'

# Reject a duplicate detection
curl -X POST http://127.0.0.1:8000/api/deduplication/reject \
  -H "Content-Type: application/json" \
  -d '{"paper_id_a": 1, "paper_id_b": 2, "reason": "Different studies"}'

# Manually override status
curl -X POST http://127.0.0.1:8000/api/deduplication/override \
  -H "Content-Type: application/json" \
  -d '{"paper_id": 2, "new_status": "manually_retained", "reason": "Conference extension"}'

# View deduplication log
curl http://127.0.0.1:8000/api/deduplication/log
```

---

## ✅ Phase 4 Complete

Phase 4 is fully implemented:

- ✅ **Four screening questions** with YES/NO/UNCLEAR answers and help text
- ✅ **Auto-suggestion** based on Q1-Q4 answers (include/exclude/borderline/awaiting)
- ✅ **Manual decisions**: include, exclude, borderline, awaiting_full_text, duplicate
- ✅ **Required exclusion reasons** with 10 standardized categories
- ✅ **Title/abstract screening** stage
- ✅ **Full-text screening** stage (separate workflow)
- ✅ **Screening history** — full audit trail of all decisions per paper
- ✅ **Next paper queue** — automatically skips duplicates and screened papers
- ✅ **Bulk screening** — submit multiple decisions at once
- ✅ **Progress tracking** — percentage complete, exclusion reason breakdown
- ✅ **Screening export** — CSV/JSON export of all screening results

### Screening API Calls

```bash
# Get screening questions (for building UI)
curl http://127.0.0.1:8000/api/screening/questions

# Get next paper to screen
curl http://127.0.0.1:8000/api/screening/next

# Submit a screening decision
curl -X POST http://127.0.0.1:8000/api/screening/submit \
  -H "Content-Type: application/json" \
  -d '{
    "paper_id": 1,
    "q1_fl_comparison": "YES",
    "q2_non_iid": "YES",
    "q3_superiority_claim": "YES",
    "q4_full_text_available": "YES",
    "decision": "include"
  }'

# Submit exclusion (reason required)
curl -X POST http://127.0.0.1:8000/api/screening/submit \
  -H "Content-Type: application/json" \
  -d '{
    "paper_id": 2,
    "q1_fl_comparison": "NO",
    "decision": "exclude",
    "exclusion_reason": "no_fl_algorithm_comparison"
  }'

# Bulk submit
curl -X POST http://127.0.0.1:8000/api/screening/bulk-submit \
  -H "Content-Type: application/json" \
  -d '{"decisions": [{"paper_id": 1, "decision": "include"}, ...]}'

# View screening history
curl http://127.0.0.1:8000/api/screening/history/1

# View progress
curl http://127.0.0.1:8000/api/screening/progress

# List screening queue
curl "http://127.0.0.1:8000/api/screening/list?status=not_screened"

# Full-text screening
curl http://127.0.0.1:8000/api/screening/full-text/1

# Export screening results
curl "http://127.0.0.1:8000/api/export/screening-results?format=csv"
```

---

## ✅ Phase 5 Complete

Phase 5 is fully implemented:

- ✅ **PDF Discovery**: Automatically finds OA PDF URLs from OpenAlex metadata
- ✅ **4-tier availability**: OpenAlex cached / OA PDF / Landing page / None
- ✅ **PDF Download**: Streaming download with timeout, size limits, validation
- ✅ **PDF Validation**: Magic byte check (%PDF-) to verify file integrity
- ✅ **SHA-256 Hashing**: Prevents duplicate downloads
- ✅ **Duplicate prevention**: Won't re-download same URL for same paper
- ✅ **Paper Notes**: Create, update, delete notes linked to papers
- ✅ **Note locations**: Page, section, table, figure references
- ✅ **Enhanced paper detail**: Includes PDF files, screening history, provenance, notes
- ✅ **PDF Serving**: Download and view PDFs through the API

### PDF & Notes API Calls

```bash
# Discover PDF availability for a paper
curl -X POST http://127.0.0.1:8000/api/pdf/discover/1

# Discover for all included papers
curl -X POST "http://127.0.0.1:8000/api/pdf/discover?status_filter=include"

# Download a PDF
curl -X POST http://127.0.0.1:8000/api/pdf/download \
  -H "Content-Type: application/json" \
  -d '{"paper_id": 1, "url": "https://example.org/paper.pdf", "source": "oa_url"}'

# Check PDF status
curl http://127.0.0.1:8000/api/pdf/status/1

# View download statistics
curl http://127.0.0.1:8000/api/pdf/stats

# Serve a downloaded PDF (for viewing)
curl http://127.0.0.1:8000/api/pdf/serve/1

# Create a note
curl -X POST http://127.0.0.1:8000/api/papers/notes \
  -H "Content-Type: application/json" \
  -d '{
    "paper_id": 1,
    "content": "Uses Dirichlet alpha=0.1 for non-IID partition",
    "note_type": "method",
    "page": 5,
    "section": "Experimental Setup"
  }'

# Get all notes for a paper
curl http://127.0.0.1:8000/api/papers/1/notes

# Update a note
curl -X PUT http://127.0.0.1:8000/api/papers/notes/1 \
  -H "Content-Type: application/json" \
  -d '{"content": "Updated note content"}'

# Delete a note
curl -X DELETE http://127.0.0.1:8000/api/papers/notes/1
```

---

## ✅ Phase 6 Complete

Phase 6 is fully implemented:

- ✅ **Claim-level data model**: Analytical unit is the claim, not the paper
- ✅ **SLR Codebook V1.0**: All 24 codebook fields implemented
- ✅ **5 evidence quality dimensions**: Independent (NOT combined into score)
- ✅ **Experiments & Conditions**: Structured experimental data capture
- ✅ **Codebook validation**: All dropdown values validated against codebook
- ✅ **Evidence profile**: Visual representation of 5 quality dimensions
- ✅ **Extraction statistics**: Direct stats count, uncertainty breakdown, ranking distribution
- ✅ **Claims export**: CSV/JSON export with evidence quality data

### Extraction API Calls

```bash
# Get codebook values (for UI dropdowns)
curl http://127.0.0.1:8000/api/extraction/codebook

# Create a claim
curl -X POST http://127.0.0.1:8000/api/extraction/claims \
  -H "Content-Type: application/json" \
  -d '{
    "paper_id": 1,
    "claim_text": "FedX outperforms FedAvg on CIFAR-10 alpha=0.1",
    "claim_scope": "Global Model Accuracy",
    "algorithms_compared": ["FedX", "FedAvg"],
    "winner_algorithm": "FedX",
    "non_iid_type": "Label distribution skew",
    "partition_method": "Dirichlet",
    "heterogeneity_param": "alpha=0.1"
  }'

# Create an experiment
curl -X POST http://127.0.0.1:8000/api/extraction/experiments \
  -H "Content-Type: application/json" \
  -d '{"claim_id": 1, "dataset": "CIFAR-10", "independent_runs": 5}'

# Create a condition
curl -X POST http://127.0.0.1:8000/api/extraction/conditions \
  -H "Content-Type: application/json" \
  -d '{"experiment_id": 1, "algorithm": "FedX", "metric_value": "92.5", "is_winner": true}'

# Create evidence quality assessment
curl -X POST http://127.0.0.1:8000/api/extraction/evidence-quality \
  -H "Content-Type: application/json" \
  -d '{
    "claim_id": 1,
    "independent_runs": 5,
    "direct_statistical_test": true,
    "uncertainty_reporting": "SD",
    "ranking_robustness": "Observationally Stable"
  }'

# Get extraction statistics
curl http://127.0.0.1:8000/api/extraction/stats

# Export claims
curl "http://127.0.0.1:8000/api/export/claims?format=csv"
```

---

## ✅ Phase 7 Complete

Phase 7 is fully implemented:

- ✅ **Ranking Stability Engine**: Analyzes ranking consistency across conditions
- ✅ **5-Dimension Evidence Dashboard**: Visual representation of evidence quality
- ✅ **Evidence Summary**: Human-readable summaries for each dimension
- ✅ **Per-Claim Ranking Analysis**: Winner consistency, condition-by-condition breakdown
- ✅ **Overall Evidence Stats**: Aggregated statistics across all assessed claims
- ✅ **Dimension Breakdown**: Filter by repetition/uncertainty/statistics/fairness/ranking
- ✅ **Enhanced Main Dashboard**: Evidence stats integrated into main dashboard

### Evidence Dashboard API Calls

```bash
# Get overall evidence quality overview
curl http://127.0.0.1:8000/api/evidence/overview

# Get evidence summary for a claim
curl http://127.0.0.1:8000/api/evidence/claim/1

# Get ranking stability analysis
curl http://127.0.0.1:8000/api/evidence/ranking-analysis/1

# Get breakdown by dimension
curl http://127.0.0.1:8000/api/evidence/by-dimension/repetition
curl http://127.0.0.1:8000/api/evidence/by-dimension/uncertainty
curl http://127.0.0.1:8000/api/evidence/by-dimension/direct_statistics
curl http://127.0.0.1:8000/api/evidence/by-dimension/fairness
curl http://127.0.0.1:8000/api/evidence/by-dimension/ranking
```

---

---

## 🚀 Running Phase 1

### Step 1: Install and Initialize

```bash
cd "/Users/ankit/Desktop/Systematic Literature Review/FL_SLR_Automation"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
chmod +x run.sh
./run.sh init-db
```

### Step 2: Load Demo Data (Optional)

```bash
./run.sh demo
```

### Step 3: Run Tests

```bash
./run.sh test
```

### Step 4: Start the Server

```bash
./run.sh serve
# API: http://127.0.0.1:8000
# Interactive docs: http://127.0.0.1:8000/docs
```

### Step 5: Run Your First Search

Use the interactive docs at `http://127.0.0.1:8000/docs` or:

```bash
# Run search family A
curl -X POST http://127.0.0.1:8000/api/search/run \
  -H "Content-Type: application/json" \
  -d '{"family": "A", "max_candidates": 100}'

# Run all search families
curl -X POST "http://127.0.0.1:8000/api/search/run-all?max_candidates=100"

# View search history
curl http://127.0.0.1:8000/api/search/history

# View papers
curl http://127.0.0.1:8000/api/papers/

# View dashboard
curl http://127.0.0.1:8000/api/dashboard/
```

---

## ✅ Phase 8 Complete

Phase 8 is fully implemented:

- ✅ **PRISMA Flow Tracking**: Complete flow data generated from database
- ✅ **PRISMA Counts**: Simplified counts for flow diagram
- ✅ **Professional Excel Export**: Multi-sheet workbook with formatting
- ✅ **NotebookLM Batch Preparation**: Organized PDF batches with manifest
- ✅ **RIS Export**: Citation format for reference managers
- ✅ **BibTeX Export**: LaTeX-compatible citation format

### PRISMA & Export API Calls

```bash
# Get PRISMA flow data
curl http://127.0.0.1:8000/api/prisma/flow

# Get simplified PRISMA counts
curl http://127.0.0.1:8000/api/prisma/counts

# Download Excel export
curl http://127.0.0.1:8000/api/prisma/excel -o fl_slr_export.xlsx

# Prepare NotebookLM batches
curl -X POST "http://127.0.0.1:8000/api/prisma/notebooklm-prep?screening_status=include&batch_size=50"

# Export citations
curl http://127.0.0.1:8000/api/prisma/ris -o references.ris
curl http://127.0.0.1:8000/api/prisma/bibtex -o references.bib
```

---

## ✅ Phase 9 Complete

Phase 9 is fully implemented:

- ✅ **LLM Extraction Suggestions**: Structured data extraction with evidence tracking
- ✅ **LLM Screening Assistance**: Answers to Q1-Q4 with reasoning
- ✅ **Evidence Tracking**: Every LLM output includes evidence snippets and confidence
- ✅ **Human Verification**: LLM suggestions stored separately from human decisions
- ✅ **Multiple Providers**: OpenAI, Anthropic, and Groq support
- ✅ **Configurable**: Optional — works without LLM (set in .env)

### LLM API Calls

```bash
# Check LLM status
curl http://127.0.0.1:8000/api/llm/status

# Get extraction suggestions
curl -X POST http://127.0.0.1:8000/api/llm/extract \
  -H "Content-Type: application/json" \
  -d '{"paper_id": 1, "extraction_type": "full"}'

# Get screening suggestions
curl -X POST http://127.0.0.1:8000/api/llm/screen/1
```

### Configuration

Add to `.env`:

```
LLM_PROVIDER=groq
LLM_API_KEY=gsk-...
LLM_MODEL=llama-3.3-70b-versatile
```

Or for OpenAI:
```
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4
```

Or for Anthropic:
```
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-...
LLM_MODEL=claude-sonnet-4-20250514
```

### Installation

```bash
# 1. Navigate to the project
cd "FL_SLR_Automation"

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy environment template
cp .env.example .env
# Edit .env to add your OpenAlex API key (optional but recommended)
# You can get an API key at: https://openalex.org/api

# 5. Make run.sh executable
chmod +x run.sh

# 6. Initialize the database
./run.sh init-db
```

### Running the Application

```bash
# Start the API server
./run.sh serve
# → API: http://127.0.0.1:8000
# → Docs: http://127.0.0.1:8000/docs

# Load demo/test data
./run.sh demo

# Run tests
./run.sh test
```

---

## 📁 Project Structure

```
FL_SLR_Automation/
├── app/
│   ├── api/              # FastAPI routes
│   │   └── routes/       # Endpoint modules
│   ├── core/             # Configuration, settings
│   ├── db/               # Database engine, initialization
│   ├── models/           # SQLAlchemy ORM models
│   ├── services/         # Business logic (OpenAlex, parsing, search)
│   ├── search/           # Search engine (future expansion)
│   ├── screening/        # Screening logic (future phases)
│   ├── extraction/       # Evidence extraction (future phases)
│   ├── deduplication/    # Deduplication engine (future phases)
│   ├── pdf/              # PDF management (future phases)
│   ├── prisma/           # PRISMA tracking (future phases)
│   └── utils/            # Utilities, demo data
├── frontend/             # React frontend (future phase)
├── data/
│   ├── raw/              # Raw search results
│   ├── processed/        # Processed datasets
│   ├── pdfs/             # Downloaded PDFs
│   ├── exports/          # Export files
│   │   └── notebooklm_batch/  # NotebookLM-compatible batches
│   └── logs/             # Application logs
├── tests/                # Automated tests
├── docs/                 # Documentation
├── .env.example          # Environment template
├── .gitignore
├── README.md
├── requirements.txt
└── run.sh                # Run script
```

---

## 🔌 API Endpoints

### Configuration
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/config/` | Get review configuration |
| PUT | `/api/config/` | Update configuration |

### Search
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/search/run` | Run a single search family |
| POST | `/api/search/run-all` | Run all enabled families |
| POST | `/api/search/resume` | Resume from last checkpoint |
| GET | `/api/search/history` | View search history (with duration, retries, pages) |

### Papers
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/papers/` | List papers (paginated, filterable) |
| GET | `/api/papers/{id}` | Get paper details (with provenance) |

### Provenance
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/provenance/paper/{id}` | Get paper's discovery sources |
| GET | `/api/provenance/family/{name}` | Get papers found by a search family |
| GET | `/api/provenance/summary` | Get provenance summary |

### Screening
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/screening/submit` | Submit screening decision |

### Dashboard
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/dashboard/` | Get dashboard statistics (with family breakdown) |

### Export
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/export/search-log?format=json\|csv` | Export search log |
| GET | `/api/export/candidates?format=json\|csv` | Export candidate list |
| GET | `/api/export/audit-log?format=json\|csv` | Export audit log |

### Deduplication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/deduplication/run` | Run deduplication engine |
| GET | `/api/deduplication/groups` | Get duplicate groups |
| GET | `/api/deduplication/stats` | Get deduplication statistics |
| GET | `/api/deduplication/review?status=probable_duplicate` | Review potential duplicates |
| POST | `/api/deduplication/confirm` | Confirm two papers are duplicates |
| POST | `/api/deduplication/reject` | Reject a duplicate detection |
| POST | `/api/deduplication/override` | Manually override duplicate status |
| GET | `/api/deduplication/log` | View deduplication log |

### Screening
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/screening/questions` | Get screening questions with help text |
| GET | `/api/screening/next` | Get next paper to screen |
| POST | `/api/screening/submit` | Submit screening decision |
| POST | `/api/screening/bulk-submit` | Submit multiple decisions at once |
| GET | `/api/screening/history/{paper_id}` | Get screening history for a paper |
| GET | `/api/screening/progress` | Get screening progress statistics |
| GET | `/api/screening/list` | List papers in screening queue |
| GET | `/api/screening/full-text/{paper_id}` | Get full-text screening details |

### PDF Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/pdf/discover/{paper_id}` | Discover PDF availability for a paper |
| POST | `/api/pdf/discover` | Discover PDFs for all papers |
| POST | `/api/pdf/download` | Download a PDF from URL |
| POST | `/api/pdf/download/{pdf_file_id}` | Download using PdfFile record |
| GET | `/api/pdf/status/{paper_id}` | Get PDF status for a paper |
| GET | `/api/pdf/stats` | Get download statistics |
| GET | `/api/pdf/pending` | List pending downloads |
| GET | `/api/pdf/serve/{pdf_file_id}` | Serve a downloaded PDF |

### Paper Notes
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/papers/notes` | Create a note for a paper |
| PUT | `/api/papers/notes/{note_id}` | Update a note |
| DELETE | `/api/papers/notes/{note_id}` | Delete a note |
| GET | `/api/papers/{paper_id}/notes` | Get all notes for a paper |

### Extraction & Claims
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/extraction/codebook` | Get all valid codebook values |
| POST | `/api/extraction/claims` | Create a claim |
| GET | `/api/extraction/claims` | List all claims |
| GET | `/api/extraction/claims/{id}` | Get claim detail with experiments & evidence |
| POST | `/api/extraction/experiments` | Create an experiment |
| POST | `/api/extraction/conditions` | Create a condition |
| POST | `/api/extraction/evidence-quality` | Create evidence quality assessment |
| GET | `/api/extraction/stats` | Get extraction statistics |

### Evidence Dashboard
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/evidence/overview` | Overall evidence quality statistics |
| GET | `/api/evidence/claim/{id}` | Evidence summary for a claim |
| GET | `/api/evidence/ranking-analysis/{id}` | Ranking stability analysis |
| GET | `/api/evidence/by-dimension/{dim}` | Breakdown by dimension |

### PRISMA & Exports
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/prisma/flow` | Complete PRISMA flow data |
| GET | `/api/prisma/counts` | Simplified PRISMA counts |
| GET | `/api/prisma/excel` | Download full Excel export |
| POST | `/api/prisma/notebooklm-prep` | Prepare PDF batches for NotebookLM |
| GET | `/api/prisma/ris` | Export citations in RIS format |
| GET | `/api/prisma/bibtex` | Export citations in BibTeX format |

### LLM Assistance (Optional)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/llm/status` | Check if LLM is configured |
| GET | `/api/llm/config` | Get LLM configuration |
| POST | `/api/llm/extract` | Get extraction suggestions |
| POST | `/api/llm/screen/{paper_id}` | Get screening suggestions |

---

## 🔍 Search Families

The system implements 6 search families for comprehensive coverage:

| Family | Focus |
|--------|-------|
| **A** | Core FL + Non-IID + Comparison |
| **B** | FL algorithm names + heterogeneity |
| **C** | Non-IID construction methods + FL |
| **D** | Benchmark/comparative FL terminology |
| **E** | Personalized FL + heterogeneity |
| **F** | Robust/async/optimization FL + heterogeneity |

---

## 📊 Evidence Quality Framework

Five independent dimensions (NOT combined into a single score):

1. **Experimental Repetition** — Number of independent runs
2. **Uncertainty Reporting** — SD, CI, or other measures
3. **Direct Statistical Evidence** — Formal inferential tests
4. **Comparison Fairness** — Hyperparameter tuning parity
5. **Ranking Robustness** — Stability across conditions

---

## 🧪 Testing

```bash
# Run all tests
./run.sh test

# Run specific test file
python -m pytest tests/test_paper_parser.py -v

# Run with coverage
python -m pytest tests/ --cov=app --cov-report=html
```

---

## 📋 Development Phases

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ Complete | Project setup, DB, config, OpenAlex, single search |
| 2 | ✅ Complete | Multiple search families, pagination, provenance, search log, checkpoint/resume, exports |
| 3 | ✅ Complete | Deduplication engine (5-pass), manual override, dedup log, groups |
| 4 | ✅ Complete | Screening interface, manual decisions, exclusion reasons, bulk submit, progress |
| 5 | ✅ Complete | PDF discovery/download, paper detail page, notes system |
| 6 | ✅ Complete | Extraction system, codebook V1.0, claim-level data, evidence quality |
| 7 | ✅ Complete | Ranking stability engine, evidence dashboard, 5-dimension visualization |
| 8 | ✅ Complete | PRISMA flow, Excel exports, NotebookLM prep, RIS/BibTeX |
| 9 | ✅ Complete | LLM-assisted extraction, screening suggestions, evidence tracking |
| 10 | ⏳ Planned | Tests, docs, packaging |

---

## ⚠️ Methodological Safeguards

The software will NEVER:

1. Assume a superiority claim is statistically proven
2. Treat SD as hypothesis testing
3. Treat multiple datasets as repeated runs
4. Treat cross-validation folds as independent random-seed repetitions
5. Infer Non-IID type when not specified
6. Infer ranking instability from missing information
7. Infer ranking stability from higher numbers alone
8. Call a mechanism-level test a direct superiority test
9. Auto-exclude papers solely for lacking statistical testing
10. Delete excluded papers from the dataset

---

## 📝 License

Academic research use. Built for reproducibility and integrity.

---

## 🙋 Support

For issues, questions, or contributions, please refer to the project documentation in the `docs/` directory.
