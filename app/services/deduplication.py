"""
Deduplication Engine
=====================
Implements multi-pass deduplication for bibliographic records.

Deduplication order:
1. DOI exact match
2. OpenAlex ID exact match
3. Normalized title + publication year
4. Fuzzy title similarity
5. Author/year similarity

Rules:
- Never delete duplicate records.
- Never merge records automatically when uncertain.
- Every decision is logged.
- Manual override is always allowed.
- Conference version / journal extension / arXiv version are NOT auto-merged.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from difflib import SequenceMatcher

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models.paper import Paper
from app.models.deduplication import DeduplicationLog
from app.models.screening import AuditLog

logger = logging.getLogger(__name__)

# Thresholds for fuzzy matching
FUZZY_TITLE_THRESHOLD = 0.90  # 90% similarity for title fuzzy match
AUTHOR_YEAR_THRESHOLD = 0.80  # 80% author overlap for author/year match


class DeduplicationResult:
    """Result of comparing two papers."""

    def __init__(
        self,
        paper_a_id: int,
        paper_b_id: int,
        match_type: str,
        confidence: float,
        is_duplicate: bool,
        reason: str,
    ):
        self.paper_a_id = paper_a_id
        self.paper_b_id = paper_b_id
        self.match_type = match_type
        self.confidence = confidence
        self.is_duplicate = is_duplicate
        self.reason = reason

    def to_dict(self) -> dict:
        return {
            "paper_a_id": self.paper_a_id,
            "paper_b_id": self.paper_b_id,
            "match_type": self.match_type,
            "confidence": self.confidence,
            "is_duplicate": self.is_duplicate,
            "reason": self.reason,
        }


def _compute_title_similarity(title_a: str, title_b: str) -> float:
    """
    Compute similarity between two titles using SequenceMatcher.
    Returns a float between 0.0 and 1.0.
    """
    if not title_a or not title_b:
        return 0.0
    return SequenceMatcher(None, title_a.lower(), title_b.lower()).ratio()


def _compute_author_overlap(authors_a: list, authors_b: list) -> float:
    """
    Compute the overlap between two author lists.
    Uses Jaccard similarity on normalized author names.
    """
    if not authors_a or not authors_b:
        return 0.0

    set_a = {a.lower().strip() for a in authors_a if a}
    set_b = {b.lower().strip() for b in authors_b if b}

    if not set_a or not set_b:
        return 0.0

    intersection = set_a & set_b
    union = set_a | set_b

    return len(intersection) / len(union) if union else 0.0


def _parse_authors(paper: Paper) -> list:
    """Parse authors from JSON string to list."""
    if not paper.authors:
        return []
    try:
        return json.loads(paper.authors)
    except (json.JSONDecodeError, TypeError):
        return []


def _is_likely_version_relationship(paper_a: Paper, paper_b: Paper) -> bool:
    """
    Check if two papers might be different versions of the same work
    (e.g., conference version vs journal extension, arXiv vs published).
    These should NOT be auto-merged even if titles are very similar.
    """
    # If source types differ (e.g., conference-paper vs journal-article),
    # be cautious about auto-merging
    type_a = (paper_a.source_type or "").lower()
    type_b = (paper_b.source_type or "").lower()

    # Different publication types with similar titles = likely versions, not duplicates
    if type_a != type_b:
        # Check if one is a preprint
        is_preprint_a = type_a in ("preprint", "article") and "arxiv" in (paper_a.source or "").lower()
        is_preprint_b = type_b in ("preprint", "article") and "arxiv" in (paper_b.source or "").lower()

        if is_preprint_a or is_preprint_b:
            return True

        # Conference vs journal = likely extension, not duplicate
        if (type_a == "conference-paper" and type_b == "journal-article") or \
           (type_b == "conference-paper" and type_a == "journal-article"):
            return True

    return False


class DeduplicationEngine:
    """
    Multi-pass deduplication engine.

    Usage:
        engine = DeduplicationEngine(db)
        results = engine.run_deduplication()
        # Review results
        engine.confirm_duplicate(result)
        # Or reject
        engine.reject_duplicate(result)
    """

    def __init__(self, db: Session):
        self.db = db

    def run_deduplication(
        self,
        dry_run: bool = False,
        families: Optional[list[str]] = None,
    ) -> list[DeduplicationResult]:
        """
        Run the full deduplication pipeline.

        Args:
            dry_run: If True, only detect duplicates without marking them.
            families: Optional list of search families to restrict to.

        Returns:
            List of DeduplicationResult objects.
        """
        results = []

        # Get all papers (optionally filtered by search family)
        papers = self._get_papers(families)

        logger.info(f"Running deduplication on {len(papers)} papers...")

        # Pass 1: DOI exact match
        results.extend(self._match_by_doi(papers, dry_run))

        # Pass 2: OpenAlex ID exact match
        results.extend(self._match_by_openalex_id(papers, dry_run))

        # Pass 3: Normalized title + publication year
        results.extend(self._match_by_title_year(papers, dry_run))

        # Pass 4: Fuzzy title similarity
        results.extend(self._match_by_fuzzy_title(papers, dry_run))

        # Pass 5: Author/year similarity
        results.extend(self._match_by_author_year(papers, dry_run))

        logger.info(
            f"Deduplication complete: {len(results)} potential duplicates found."
        )

        return results

    def _get_papers(self, families: Optional[list[str]] = None) -> list[Paper]:
        """Get papers, optionally filtered by search family."""
        query = self.db.query(Paper)

        if families:
            # Only papers found by the specified search families
            from app.models.search_run import SourceProvenance
            query = query.join(
                SourceProvenance, Paper.id == SourceProvenance.paper_id
            ).filter(
                SourceProvenance.search_family.in_(families)
            ).distinct()

        return query.all()

    def _already_compared(self, paper_a_id: int, paper_b_id: int) -> bool:
        """Check if two papers have already been compared."""
        existing = self.db.query(DeduplicationLog).filter(
            or_(
                and_(
                    DeduplicationLog.paper_id_a == paper_a_id,
                    DeduplicationLog.paper_id_b == paper_b_id,
                ),
                and_(
                    DeduplicationLog.paper_id_a == paper_b_id,
                    DeduplicationLog.paper_id_b == paper_a_id,
                ),
            )
        ).first()
        return existing is not None

    def _log_comparison(
        self,
        result: DeduplicationResult,
        status: str,
        canonical_id: Optional[int] = None,
        duplicate_id: Optional[int] = None,
        actor: str = "system",
        notes: str = "",
    ) -> DeduplicationLog:
        """Log a deduplication decision."""
        log = DeduplicationLog(
            paper_id_a=result.paper_a_id,
            paper_id_b=result.paper_b_id,
            match_type=result.match_type,
            match_confidence=result.confidence,
            match_status=status,
            canonical_paper_id=canonical_id,
            duplicate_paper_id=duplicate_id,
            actor=actor,
            notes=notes,
        )
        self.db.add(log)
        return log

    def _mark_duplicate(
        self,
        canonical: Paper,
        duplicate: Paper,
        result: DeduplicationResult,
        dry_run: bool,
    ):
        """Mark one paper as duplicate of another."""
        if dry_run:
            return

        duplicate.duplicate_status = "probable_duplicate"
        duplicate.duplicate_of = canonical.id
        duplicate.duplicate_reason = result.reason
        duplicate.duplicate_confidence = result.confidence
        duplicate.canonical_record_id = canonical.id

    def _match_by_doi(
        self, papers: list[Paper], dry_run: bool
    ) -> list[DeduplicationResult]:
        """Pass 1: DOI exact match."""
        results = []
        doi_map: dict[str, Paper] = {}

        for paper in papers:
            if not paper.doi:
                continue

            if paper.doi in doi_map:
                existing = doi_map[paper.doi]
                result = DeduplicationResult(
                    paper_a_id=existing.id,
                    paper_b_id=paper.id,
                    match_type="doi_exact",
                    confidence=1.0,
                    is_duplicate=True,
                    reason=f"Exact DOI match: {paper.doi}",
                )

                if not self._already_compared(result.paper_a_id, result.paper_b_id):
                    self._log_comparison(result, "auto_detected")
                    self._mark_duplicate(existing, paper, result, dry_run)
                    results.append(result)
                    logger.info(
                        f"DOI match: Paper {existing.id} <-> Paper {paper.id} "
                        f"(DOI: {paper.doi})"
                    )
            else:
                doi_map[paper.doi] = paper

        return results

    def _match_by_openalex_id(
        self, papers: list[Paper], dry_run: bool
    ) -> list[DeduplicationResult]:
        """Pass 2: OpenAlex ID exact match."""
        results = []
        id_map: dict[str, Paper] = {}

        for paper in papers:
            if not paper.openalex_id:
                continue

            if paper.openalex_id in id_map:
                existing = id_map[paper.openalex_id]
                result = DeduplicationResult(
                    paper_a_id=existing.id,
                    paper_b_id=paper.id,
                    match_type="openalex_id_exact",
                    confidence=1.0,
                    is_duplicate=True,
                    reason=f"Exact OpenAlex ID match: {paper.openalex_id}",
                )

                if not self._already_compared(result.paper_a_id, result.paper_b_id):
                    self._log_comparison(result, "auto_detected")
                    self._mark_duplicate(existing, paper, result, dry_run)
                    results.append(result)
            else:
                id_map[paper.openalex_id] = paper

        return results

    def _match_by_title_year(
        self, papers: list[Paper], dry_run: bool
    ) -> list[DeduplicationResult]:
        """Pass 3: Normalized title + publication year exact match."""
        results = []
        # Group by (normalized_title, year)
        groups: dict[tuple, list[Paper]] = {}

        for paper in papers:
            if not paper.normalized_title or not paper.publication_year:
                continue
            # Skip papers already marked as duplicates
            if paper.duplicate_status in ("probable_duplicate", "confirmed_duplicate"):
                continue

            key = (paper.normalized_title, paper.publication_year)
            if key not in groups:
                groups[key] = []
            groups[key].append(paper)

        for key, group in groups.items():
            if len(group) < 2:
                continue

            # Compare all pairs in the group
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    paper_a = group[i]
                    paper_b = group[j]

                    if self._already_compared(paper_a.id, paper_b.id):
                        continue

                    # Check for version relationship (conference vs journal)
                    if _is_likely_version_relationship(paper_a, paper_b):
                        result = DeduplicationResult(
                            paper_a_id=paper_a.id,
                            paper_b_id=paper_b.id,
                            match_type="title_year_exact",
                            confidence=1.0,
                            is_duplicate=False,
                            reason=(
                                "Title+year match but different source types "
                                "(likely version relationship, not duplicate)"
                            ),
                        )
                        self._log_comparison(
                            result, "rejected_not_duplicate",
                            notes="Version relationship detected",
                        )
                        results.append(result)
                        continue

                    result = DeduplicationResult(
                        paper_a_id=paper_a.id,
                        paper_b_id=paper_b.id,
                        match_type="title_year_exact",
                        confidence=1.0,
                        is_duplicate=True,
                        reason=(
                            f"Exact normalized title + year match: "
                            f"'{key[0][:60]}...' ({key[1]})"
                        ),
                    )
                    self._log_comparison(result, "auto_detected")
                    self._mark_duplicate(paper_a, paper_b, result, dry_run)
                    results.append(result)

        return results

    def _match_by_fuzzy_title(
        self, papers: list[Paper], dry_run: bool
    ) -> list[DeduplicationResult]:
        """Pass 4: Fuzzy title similarity (for papers not already matched)."""
        results = []

        # Only consider papers not already marked as duplicates
        candidates = [
            p for p in papers
            if p.duplicate_status not in ("probable_duplicate", "confirmed_duplicate")
            and p.normalized_title
        ]

        # Compare each pair (O(n^2) but manageable for reasonable dataset sizes)
        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                paper_a = candidates[i]
                paper_b = candidates[j]

                if self._already_compared(paper_a.id, paper_b.id):
                    continue

                similarity = _compute_title_similarity(
                    paper_a.normalized_title, paper_b.normalized_title
                )

                if similarity >= FUZZY_TITLE_THRESHOLD:
                    # Additional check: same year or no year conflict
                    year_match = (
                        paper_a.publication_year == paper_b.publication_year
                        or paper_a.publication_year is None
                        or paper_b.publication_year is None
                    )

                    if not year_match:
                        continue

                    # Check for version relationship
                    if _is_likely_version_relationship(paper_a, paper_b):
                        result = DeduplicationResult(
                            paper_a_id=paper_a.id,
                            paper_b_id=paper_b.id,
                            match_type="fuzzy_title",
                            confidence=similarity,
                            is_duplicate=False,
                            reason=(
                                f"Fuzzy title match ({similarity:.2f}) but "
                                f"different source types (likely version relationship)"
                            ),
                        )
                        self._log_comparison(
                            result, "rejected_not_duplicate",
                            notes="Version relationship detected",
                        )
                        results.append(result)
                        continue

                    result = DeduplicationResult(
                        paper_a_id=paper_a.id,
                        paper_b_id=paper_b.id,
                        match_type="fuzzy_title",
                        confidence=similarity,
                        is_duplicate=True,
                        reason=(
                            f"Fuzzy title similarity: {similarity:.2f} "
                            f"(threshold: {FUZZY_TITLE_THRESHOLD})"
                        ),
                    )
                    self._log_comparison(result, "auto_detected")
                    self._mark_duplicate(paper_a, paper_b, result, dry_run)
                    results.append(result)

        return results

    def _match_by_author_year(
        self, papers: list[Paper], dry_run: bool
    ) -> list[DeduplicationResult]:
        """Pass 5: Author/year similarity (high author overlap + same year)."""
        results = []

        candidates = [
            p for p in papers
            if p.duplicate_status not in ("probable_duplicate", "confirmed_duplicate")
            and p.publication_year
        ]

        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                paper_a = candidates[i]
                paper_b = candidates[j]

                if self._already_compared(paper_a.id, paper_b.id):
                    continue

                # Must have same year
                if paper_a.publication_year != paper_b.publication_year:
                    continue

                # Must have authors
                authors_a = _parse_authors(paper_a)
                authors_b = _parse_authors(paper_b)

                if not authors_a or not authors_b:
                    continue

                overlap = _compute_author_overlap(authors_a, authors_b)

                if overlap >= AUTHOR_YEAR_THRESHOLD:
                    # Also check title similarity to reduce false titles
                    title_sim = _compute_title_similarity(
                        paper_a.normalized_title or "",
                        paper_b.normalized_title or "",
                    )

                    # Only flag if titles are at least somewhat similar
                    if title_sim < 0.5:
                        continue

                    result = DeduplicationResult(
                        paper_a_id=paper_a.id,
                        paper_b_id=paper_b.id,
                        match_type="author_year",
                        confidence=overlap,
                        is_duplicate=True,
                        reason=(
                            f"Author overlap: {overlap:.2f}, "
                            f"same year: {paper_a.publication_year}, "
                            f"title similarity: {title_sim:.2f}"
                        ),
                    )
                    self._log_comparison(result, "auto_detected")
                    self._mark_duplicate(paper_a, paper_b, result, dry_run)
                    results.append(result)

        return results

    def confirm_duplicate(
        self, paper_id_a: int, paper_id_b: int, canonical_id: int
    ) -> DeduplicationLog:
        """
        Manually confirm that two papers are duplicates.
        Specify which paper should be the canonical record.
        """
        paper_a = self.db.query(Paper).filter(Paper.id == paper_id_a).first()
        paper_b = self.db.query(Paper).filter(Paper.id == paper_id_b).first()

        if not paper_a or not paper_b:
            raise ValueError("One or both papers not found.")

        # Determine which is canonical and which is duplicate
        if canonical_id == paper_id_a:
            canonical = paper_a
            duplicate = paper_b
        else:
            canonical = paper_b
            duplicate = paper_a

        # Update the duplicate record
        duplicate.duplicate_status = "confirmed_duplicate"
        duplicate.duplicate_of = canonical.id
        duplicate.duplicate_reason = "Manually confirmed duplicate"
        duplicate.duplicate_confidence = 1.0
        duplicate.canonical_record_id = canonical.id

        # Log the decision
        log = DeduplicationLog(
            paper_id_a=paper_id_a,
            paper_id_b=paper_id_b,
            match_type="manual",
            match_confidence=1.0,
            match_status="confirmed_duplicate",
            canonical_paper_id=canonical.id,
            duplicate_paper_id=duplicate.id,
            actor="user",
            notes="Manually confirmed duplicate",
        )
        self.db.add(log)

        # Audit log
        audit = AuditLog(
            action="duplicate_confirmed",
            entity_type="paper",
            entity_id=duplicate.id,
            description=(
                f"Paper {duplicate.id} confirmed as duplicate of "
                f"paper {canonical.id} by user"
            ),
            old_value="unique",
            new_value="confirmed_duplicate",
            actor="user",
            paper_id=duplicate.id,
        )
        self.db.add(audit)
        self.db.commit()

        return log

    def reject_duplicate(
        self, paper_id_a: int, paper_id_b: int, reason: str = ""
    ) -> DeduplicationLog:
        """
        Reject a duplicate detection — mark papers as NOT duplicates.
        """
        paper_a = self.db.query(Paper).filter(Paper.id == paper_id_a).first()
        paper_b = self.db.query(Paper).filter(Paper.id == paper_id_b).first()

        if not paper_a or not paper_b:
            raise ValueError("One or both papers not found.")

        # Reset duplicate status if it was auto-detected
        for paper in [paper_a, paper_b]:
            if paper.duplicate_status == "probable_duplicate":
                paper.duplicate_status = "unique"
                paper.duplicate_of = None
                paper.duplicate_reason = None
                paper.duplicate_confidence = None
                paper.canonical_record_id = None

        # Log the rejection
        log = DeduplicationLog(
            paper_id_a=paper_id_a,
            paper_id_b=paper_id_b,
            match_type="manual_rejection",
            match_confidence=0.0,
            match_status="rejected_not_duplicate",
            is_override=True,
            override_reason=reason or "Manually rejected duplicate",
            overridden_by="user",
            actor="user",
            notes=reason,
        )
        self.db.add(log)

        # Audit log
        audit = AuditLog(
            action="duplicate_rejected",
            entity_type="paper",
            entity_id=paper_b.id,
            description=(
                f"Paper {paper_b.id} rejected as duplicate of "
                f"paper {paper_id_a}. Reason: {reason}"
            ),
            old_value="probable_duplicate",
            new_value="unique",
            actor="user",
            paper_id=paper_b.id,
        )
        self.db.add(audit)
        self.db.commit()

        return log

    def manual_override(
        self,
        paper_id: int,
        new_status: str,
        reason: str,
        canonical_id: Optional[int] = None,
    ) -> DeduplicationLog:
        """
        Manually override the duplicate status of a paper.
        """
        paper = self.db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper:
            raise ValueError(f"Paper {paper_id} not found.")

        old_status = paper.duplicate_status

        paper.duplicate_status = new_status
        if canonical_id:
            paper.duplicate_of = canonical_id
            paper.canonical_record_id = canonical_id
        paper.duplicate_reason = f"Manual override: {reason}"

        # Log
        log = DeduplicationLog(
            paper_id_a=paper_id,
            paper_id_b=canonical_id or 0,
            match_type="manual_override",
            match_confidence=1.0,
            match_status="manually_overridden",
            is_override=True,
            override_reason=reason,
            overridden_by="user",
            canonical_paper_id=canonical_id,
            actor="user",
            notes=reason,
        )
        self.db.add(log)

        # Audit
        audit = AuditLog(
            action="duplicate_override",
            entity_type="paper",
            entity_id=paper_id,
            description=f"Duplicate status manually changed to: {new_status}. Reason: {reason}",
            old_value=old_status,
            new_value=new_status,
            actor="user",
            paper_id=paper_id,
        )
        self.db.add(audit)
        self.db.commit()

        return log

    def get_duplicate_groups(self) -> list[dict]:
        """
        Get all groups of papers that are marked as duplicates.
        Returns groups where each group has a canonical paper and its duplicates.
        """
        # Find all papers that are duplicates
        duplicates = self.db.query(Paper).filter(
            Paper.duplicate_status.in_(["probable_duplicate", "confirmed_duplicate"])
        ).all()

        # Group by canonical_record_id or duplicate_of
        groups: dict[int, dict] = {}
        for dup in duplicates:
            canonical_id = dup.canonical_record_id or dup.duplicate_of
            if not canonical_id:
                continue

            if canonical_id not in groups:
                canonical = self.db.query(Paper).filter(Paper.id == canonical_id).first()
                groups[canonical_id] = {
                    "canonical": canonical,
                    "duplicates": [],
                }

            groups[canonical_id]["duplicates"].append(dup)

        return [
            {
                "canonical_id": canonical_id,
                "canonical_title": group["canonical"].title if group["canonical"] else "Unknown",
                "canonical_year": group["canonical"].publication_year if group["canonical"] else None,
                "duplicate_count": len(group["duplicates"]),
                "duplicates": [
                    {
                        "id": d.id,
                        "title": d.title,
                        "year": d.publication_year,
                        "confidence": d.duplicate_confidence,
                        "reason": d.duplicate_reason,
                        "status": d.duplicate_status,
                    }
                    for d in group["duplicates"]
                ],
            }
            for canonical_id, group in groups.items()
        ]

    def get_deduplication_stats(self) -> dict:
        """Get deduplication statistics."""
        total = self.db.query(Paper).count()
        unique = self.db.query(Paper).filter(Paper.duplicate_status == "unique").count()
        probable = self.db.query(Paper).filter(
            Paper.duplicate_status == "probable_duplicate"
        ).count()
        confirmed = self.db.query(Paper).filter(
            Paper.duplicate_status == "confirmed_duplicate"
        ).count()
        manually_retained = self.db.query(Paper).filter(
            Paper.duplicate_status == "manually_retained"
        ).count()

        # Count by match type
        from sqlalchemy import func
        by_type = (
            self.db.query(
                DeduplicationLog.match_type,
                func.count(DeduplicationLog.id),
            )
            .group_by(DeduplicationLog.match_type)
            .all()
        )

        return {
            "total_papers": total,
            "unique": unique,
            "probable_duplicates": probable,
            "confirmed_duplicates": confirmed,
            "manually_retained": manually_retained,
            "by_match_type": [
                {"type": t, "count": c} for t, c in by_type
            ],
        }
