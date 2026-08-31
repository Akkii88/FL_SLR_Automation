"""
Search Orchestration Service
=============================
Coordinates running searches across multiple search families,
storing results and tracking provenance.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.review_config import ReviewConfig
from app.models.paper import Paper
from app.models.search_run import SearchRun, SearchRunPaper, SourceProvenance
from app.models.screening import AuditLog
from app.services.openalex import OpenAlexConnector
from app.services.paper_parser import parse_openalex_work
from app.services.checkpoint import save_checkpoint, load_checkpoint, clear_checkpoint, has_checkpoint

logger = logging.getLogger(__name__)


class SearchService:
    """Orchestrates search operations across sources and families."""

    def __init__(self, db: Session, config: ReviewConfig):
        self.db = db
        self.config = config
        self.connector = OpenAlexConnector()

    def run_search_family(
        self,
        family_name: str,
        max_candidates: Optional[int] = None,
        resume: bool = False,
    ) -> dict:
        """
        Execute a single search family against OpenAlex.

        Args:
            family_name: The search family identifier (A, B, C, etc.)
            max_candidates: Override for max results
            resume: Whether to resume from a previous checkpoint

        Returns:
            dict with search run summary
        """
        # Find the search family config
        family = None
        for sf in self.config.search_families:
            if sf.name == family_name and sf.enabled:
                family = sf
                break

        if not family:
            return {"error": f"Search family '{family_name}' not found or disabled."}

        max_results = max_candidates or self.config.max_candidates_per_family

        # Create search run record
        search_run = SearchRun(
            source="OpenAlex",
            search_family=family_name,
            exact_query=family.query,
            search_date=datetime.now(timezone.utc),
            start_time=datetime.now(timezone.utc),
            year_filter=f"{self.config.start_date.year}-{self.config.end_date.year}",
            software_version="1.0.0",
            config_version=self.config.version,
        )
        self.db.add(search_run)
        self.db.flush()

        # Audit log
        self._log_audit(
            action="search_started",
            entity_type="search_run",
            entity_id=search_run.id,
            description=f"Started OpenAlex search: family {family_name}, max={max_results}",
        )

        records_saved = 0
        records_parsed = 0
        records_failed = 0
        records_deduplicated = 0
        errors = []
        total_new = 0
        start_cursor = None

        # Check if we should resume from a checkpoint
        if resume and has_checkpoint():
            checkpoint = load_checkpoint()
            if checkpoint and checkpoint.get("family_name") == family_name:
                start_cursor = checkpoint.get("cursor")
                logger.info(f"Resuming search from checkpoint: cursor={start_cursor[:20]}...")

        try:
            # Run the search generator
            generator = self.connector.search_works(
                query=family.query,
                max_results=max_results,
                year_from=self.config.start_date.year,
                year_to=self.config.end_date.year,
                start_cursor=start_cursor,
            )

            for work in generator:
                # Safety check: stop if we've reached max_results
                if records_parsed >= max_results:
                    logger.info(f"Reached max_results limit ({max_results}), stopping.")
                    break
                try:
                    # Attempt to parse the work first
                    from app.services.paper_parser import parse_openalex_work
                    paper = parse_openalex_work(work)

                    if paper is None:
                        # Parsing failed (e.g., missing title)
                        records_failed += 1
                        openalex_id = work.get("id", "unknown") if isinstance(work, dict) else "unknown"
                        logger.warning(
                            f"Failed to parse work (missing required fields): "
                            f"openalex_id={openalex_id}"
                        )
                        continue

                    records_parsed += 1

                    # Store the parsed paper
                    result = self._store_work(paper, search_run)
                    if result:
                        total_new += 1
                    else:
                        records_deduplicated += 1

                    records_saved += 1

                    # Save checkpoint every 50 records
                    if records_saved % 50 == 0:
                        save_checkpoint(
                            search_run_id=search_run.id,
                            cursor=self.connector.current_cursor or "*",
                            records_retrieved=records_saved,
                            pages_retrieved=0,
                            family_name=family_name,
                            query=family.query,
                        )
                except Exception as e:
                    records_failed += 1
                    errors.append(str(e))
                    logger.error(f"Error storing work: {e}", exc_info=True)

        except Exception as e:
            errors.append(str(e))
            logger.error(f"Search family {family_name} failed: {e}", exc_info=True)

        # Get the OpenAlex summary (pages, total_count, duration, etc.)
        oa_summary = self.connector.last_search_summary or {}

        # Log diagnostic info
        logger.info(
            f"Search family {family_name} summary: "
            f"total_count={oa_summary.get('total_count', 'N/A')}, "
            f"records_seen={records_saved}, "
            f"records_new={total_new}, "
            f"pages={oa_summary.get('pages', 0)}, "
            f"errors={len(errors)}"
        )

        # Clear checkpoint on successful completion
        if not errors:
            clear_checkpoint()

        # Update search run
        search_run.end_time = datetime.now(timezone.utc)
        search_run.total_matching_count = oa_summary.get("total_count")  # NULL if unavailable
        search_run.results_retrieved = oa_summary.get("records_retrieved", records_parsed + records_failed)
        search_run.records_parsed = records_parsed
        search_run.records_failed = records_failed
        search_run.records_deduplicated = records_deduplicated
        search_run.records_saved = total_new
        search_run.pages_retrieved = oa_summary.get("pages", 0)
        search_run.retries = oa_summary.get("retries", 0)
        search_run.duration_seconds = oa_summary.get("duration_seconds")
        search_run.errors = json.dumps(errors) if errors else None

        self.db.commit()

        # Audit log
        self._log_audit(
            action="search_completed",
            entity_type="search_run",
            entity_id=search_run.id,
            description=f"Completed OpenAlex search: family {family_name}, new={total_new}, total_seen={records_saved}",
        )

        return {
            "search_run_id": search_run.id,
            "family": family_name,
            "query": family.query,
            "records_saved": total_new,
            "records_seen": records_parsed + records_failed,
            "records_parsed": records_parsed,
            "records_failed": records_failed,
            "records_deduplicated": records_deduplicated,
            "errors": errors,
        }

    def _store_work(self, paper: Paper, search_run: SearchRun) -> bool:
        """
        Store a parsed paper into the database.
        Handles deduplication-by-insert (DOI/ID check).
        Returns True if new record, False if duplicate.
        """
        # Check for existing paper by OpenAlex ID or DOI
        existing = None
        if paper.openalex_id:
            existing = self.db.query(Paper).filter(
                Paper.openalex_id == paper.openalex_id
            ).first()

        if not existing and paper.doi:
            existing = self.db.query(Paper).filter(
                Paper.doi == paper.doi
            ).first()

        if existing:
            # Paper already exists - just add provenance link
            existing_search = self.db.query(SearchRunPaper).filter(
                SearchRunPaper.search_run_id == search_run.id,
                SearchRunPaper.paper_id == existing.id,
            ).first()

            if not existing_search:
                link = SearchRunPaper(
                    search_run_id=search_run.id,
                    paper_id=existing.id,
                )
                self.db.add(link)

            # Add source provenance
            existing_prov = self.db.query(SourceProvenance).filter(
                SourceProvenance.paper_id == existing.id,
                SourceProvenance.search_family == search_run.search_family,
            ).first()

            if not existing_prov:
                prov = SourceProvenance(
                    paper_id=existing.id,
                    source=search_run.source,
                    search_family=search_run.search_family,
                    retrieval_timestamp=search_run.search_date,
                )
                self.db.add(prov)

            self.db.flush()
            return False  # Not a new record

        # New paper - save it
        self.db.add(paper)
        self.db.flush()

        # Link to search run
        link = SearchRunPaper(
            search_run_id=search_run.id,
            paper_id=paper.id,
        )
        self.db.add(link)

        # Add source provenance
        prov = SourceProvenance(
            paper_id=paper.id,
            source=search_run.source,
            search_family=search_run.search_family,
            retrieval_timestamp=search_run.search_date,
        )
        self.db.add(prov)

        self.db.flush()
        return True

    def _log_audit(
        self,
        action: str,
        entity_type: str,
        entity_id: int,
        description: str,
        actor: str = "system",
    ):
        """Create an audit log entry."""
        log = AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description,
            actor=actor,
        )
        self.db.add(log)

    def close(self):
        """Close the connector."""
        self.connector.close()
