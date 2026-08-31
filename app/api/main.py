"""
FL-SLR API Main Application
=============================
FastAPI application entry point.
"""

import logging
import traceback
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import settings
from app.api.routes import search, papers, screening, config, dashboard, provenance, export, deduplication, pdf, extraction, evidence, prisma, llm, ai_screening

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="FL-SLR Automation",
    description=(
        "Systematic Literature Review automation tool for "
        "\"Is 'Best' Really Best?\" — Federated Learning evidence quality review."
    ),
    version="1.0.0",
)

# CORS (for future frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global exception handler: ensures ALL errors return JSON, never HTML
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Return JSON for all unhandled exceptions."""
    logger = logging.getLogger(__name__)
    logger.error(f"Unhandled exception: {exc}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "message": str(exc),
            "details": traceback.format_exc() if settings.app_env == "development" else None,
        },
    )


# Include routers
app.include_router(config.router, prefix="/api/config", tags=["Configuration"])
app.include_router(search.router, prefix="/api/search", tags=["Search"])
app.include_router(papers.router, prefix="/api/papers", tags=["Papers"])
app.include_router(screening.router, prefix="/api/screening", tags=["Screening"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(provenance.router, prefix="/api/provenance", tags=["Provenance"])
app.include_router(export.router, prefix="/api/export", tags=["Export"])
app.include_router(deduplication.router, prefix="/api/deduplication", tags=["Deduplication"])
app.include_router(pdf.router, prefix="/api/pdf", tags=["PDF"])
app.include_router(extraction.router, prefix="/api/extraction", tags=["Extraction"])
app.include_router(evidence.router, prefix="/api/evidence", tags=["Evidence"])
app.include_router(prisma.router, prefix="/api/prisma", tags=["PRISMA"])
app.include_router(llm.router, prefix="/api/llm", tags=["LLM"])
app.include_router(ai_screening.router, prefix="/api/ai-screening", tags=["AI Screening"])


@app.get("/")
async def root():
    """Serve the frontend UI."""
    frontend_path = settings.project_root / "frontend" / "index.html"
    if frontend_path.exists():
        return FileResponse(frontend_path)
    return {
        "app": "FL-SLR Automation",
        "project": "Is 'Best' Really Best?",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "ok", "environment": settings.app_env}
