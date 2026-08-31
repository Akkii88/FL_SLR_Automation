"""
Screening Service
==================
Encapsulates screening decision logic, validation, and auto-suggestion
based on the four screening questions.

Screening questions:
Q1: Does the study experimentally compare at least two FL algorithms/methods?
Q2: Does it evaluate those methods under Non-IID or heterogeneous conditions?
Q3: Does it contain an explicit comparative/superiority claim?
Q4: Is enough full text available to verify eligibility?

Decisions:
- include
- exclude
- borderline
- awaiting_full_text
- duplicate

Exclusion reasons (required when decision = exclude):
- not_primary_empirical_study
- no_fl_algorithm_comparison
- iid_only
- no_non_iid_heterogeneity_evaluation
- no_explicit_comparative_superiority_claim
- framework_only_comparison
- theoretical_only
- insufficient_full_text
- duplicate
- other
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func

from app.models.paper import Paper
from app.models.screening import ScreeningDecision, AuditLog

logger = logging.getLogger(__name__)

# Valid values
VALID_ANSWERS = {"YES", "NO", "UNCLEAR", "NOT YET CHECKED"}
VALID_DECISIONS = {"include", "exclude", "borderline", "awaiting_full_text", "duplicate"}
VALID_EXCLUSION_REASONS = {
    "not_primary_empirical_study",
    "no_fl_algorithm_comparison",
    "iid_only",
    "no_non_iid_heterogeneity_evaluation",
    "no_explicit_comparative_superiority_claim",
    "framework_only_comparison",
    "theoretical_only",
    "insufficient_full_text",
    "duplicate",
    "other",
}

# Screening stage constants
STAGE_TITLE_ABSTRACT = "title_abstract"
STAGE_FULL_TEXT = "full_text"
VALID_STAGES = {STAGE_TITLE_ABSTRACT, STAGE_FULL_TEXT}


class ScreeningService:
    """
    Service for managing screening decisions.
    Provides validation, auto-suggestion, and audit logging.
    """

    def __init__(self, db: Session):
        self.db = db

    def submit_decision(
        self,
        paper_id: int,
        stage: str = STAGE_TITLE_ABSTRACT,
        q1: Optional[str] = None,
        q2: Optional[str] = None,
        q3: Optional[str] = None,
        q4: Optional[str] = None,
        decision: Optional[str] = None,
        exclusion_reason: Optional[str] = None,
        exclusion_reason_detail: Optional[str] = None,
        notes: Optional[str] = None,
        actor: str = "user",
    ) -> dict:
        """
        Submit a screening decision for a paper.

        Args:
            paper_id: The paper being screened
            stage: Screening stage (title_abstract or full_text)
            q1-q4: Answers to screening questions (YES, NO, UNCLEAR)
            decision: Final decision (include, exclude, borderline, awaiting_full_text, duplicate)
            exclusion_reason: Required if decision is 'exclude'
            exclusion_reason_detail: Free-text detail for exclusion reason
            notes: Free-text notes
            actor: Who made the decision (user, system)

        Returns:
            dict with status and details
        """
        paper = self.db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper:
            raise ValueError(f"Paper {paper_id} not found")

        # Validate stage
        if stage not in VALID_STAGES:
            raise ValueError(f"Invalid stage: {stage}. Must be one of {VALID_STAGES}")

        # Validate answers
        for i, q in enumerate([q1, q2, q3, q4], 1):
            if q and q.upper() not in VALID_ANSWERS:
                raise ValueError(f"Invalid Q{i} answer: {q}. Must be one of {VALID_ANSWERS}")

        # Validate decision
        if decision and decision.lower() not in VALID_DECISIONS:
            raise ValueError(f"Invalid decision: {decision}. Must be one of {VALID_DECISIONS}")

        # Validate exclusion reason
        if decision and decision.lower() == "exclude":
            if not exclusion_reason:
                raise ValueError("Exclusion reason is required when decision is 'exclude'")
            if exclusion_reason.lower() not in VALID_EXCLUSION_REASONS:
                raise ValueError(
                    f"Invalid exclusion reason: {exclusion_reason}. "
                    f"Must be one of {VALID_EXCLUSION_REASONS}"
                )

        # Auto-suggest decision based on questions
        suggested_decision = self._suggest_decision(q1, q2, q3, q4)

        # Record screening decision
        screening_decision = ScreeningDecision(
            paper_id=paper_id,
            stage=stage,
            q1_fl_comparison=q1.upper() if q1 else None,
            q2_non_iid=q2.upper() if q2 else None,
            q3_superiority_claim=q3.upper() if q3 else None,
            q4_full_text_available=q4.upper() if q4 else None,
            decision=decision.lower() if decision else None,
            exclusion_reason=exclusion_reason.lower() if exclusion_reason else None,
            notes=notes,
            decided_by=actor,
        )
        self.db.add(screening_decision)

        # Update paper screening status
        old_status = paper.screening_status
        if decision:
            paper.screening_status = decision.lower()
            paper.screening_decision = decision.lower()
            if exclusion_reason:
                paper.exclusion_reason = (
                    f"{exclusion_reason}"
                    + (f": {exclusion_reason_detail}" if exclusion_reason_detail else "")
                )

        # Audit log
        audit = AuditLog(
            action="screening_decision",
            entity_type="paper",
            entity_id=paper.id,
            description=(
                f"Screening ({stage}): decision={decision}. "
                f"Q1={q1}, Q2={q2}, Q3={q3}, Q4={q4}. "
                f"Reason: {exclusion_reason or 'N/A'}"
            ),
            old_value=old_status,
            new_value=paper.screening_status,
            actor=actor,
            paper_id=paper.id,
        )
        self.db.add(audit)
        self.db.commit()

        return {
            "status": "recorded",
            "paper_id": paper_id,
            "stage": stage,
            "decision": decision,
            "suggested_decision": suggested_decision,
            "auto_suggested": decision is None and suggested_decision is not None,
        }

    def _suggest_decision(
        self,
        q1: Optional[str],
        q2: Optional[str],
        q3: Optional[str],
        q4: Optional[str],
    ) -> Optional[str]:
        """
        Auto-suggest a screening decision based on answers to the four questions.

        Rules:
        - If Q1=NO → suggest exclude (no FL comparison)
        - If Q2=NO → suggest exclude (no Non-IID evaluation)
        - If Q3=NO → suggest exclude (no superiority claim)
        - If Q4=NO → suggest awaiting_full_text
        - If all Q1-Q3=YES and Q4=YES → suggest include
        - If any Q=UNCLEAR → suggest borderline
        - If any Q not answered → no suggestion
        """
        answers = [q1, q2, q3, q4]

        # If any question not answered, no suggestion
        if any(q is None for q in answers):
            return None

        # Normalize
        q1_a = q1.upper() if q1 else None
        q2_a = q2.upper() if q2 else None
        q3_a = q3.upper() if q3 else None
        q4_a = q4.upper() if q4 else None

        # If any UNCLEAR → borderline
        if any(q == "UNCLEAR" for q in [q1_a, q2_a, q3_a, q4_a]):
            return "borderline"

        # Q4=NO → awaiting full text
        if q4_a == "NO":
            return "awaiting_full_text"

        # Q1=NO → exclude
        if q1_a == "NO":
            return "exclude"

        # Q2=NO → exclude
        if q2_a == "NO":
            return "exclude"

        # Q3=NO → exclude
        if q3_a == "NO":
            return "exclude"

        # All YES → include
        if q1_a == "YES" and q2_a == "YES" and q3_a == "YES" and q4_a == "YES":
            return "include"

        return None

    def get_screening_history(self, paper_id: int) -> list[dict]:
        """Get the full screening history for a paper (all decisions over time)."""
        decisions = (
            self.db.query(ScreeningDecision)
            .filter(ScreeningDecision.paper_id == paper_id)
            .order_by(ScreeningDecision.created_at)
            .all()
        )

        return [
            {
                "id": d.id,
                "stage": d.stage,
                "q1": d.q1_fl_comparison,
                "q2": d.q2_non_iid,
                "q3": d.q3_superiority_claim,
                "q4": d.q4_full_text_available,
                "decision": d.decision,
                "exclusion_reason": d.exclusion_reason,
                "notes": d.notes,
                "decided_by": d.decided_by,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in decisions
        ]

    def get_next_paper_to_screen(
        self,
        stage: str = STAGE_TITLE_ABSTRACT,
    ) -> Optional[Paper]:
        """
        Get the next paper that needs screening.
        Returns papers in order: not_screened first, then borderline.
        """
        if stage == STAGE_TITLE_ABSTRACT:
            # For title/abstract: get not_screened papers
            paper = (
                self.db.query(Paper)
                .filter(
                    and_(
                        Paper.screening_status == "not_screened",
                        Paper.duplicate_status.not_in(
                            ["probable_duplicate", "confirmed_duplicate"]
                        ),
                    )
                )
                .order_by(Paper.id)
                .first()
            )
            if paper:
                return paper

            # Then borderline
            paper = (
                self.db.query(Paper)
                .filter(
                    and_(
                        Paper.screening_status == "borderline",
                        Paper.duplicate_status.not_in(
                            ["probable_duplicate", "confirmed_duplicate"]
                        ),
                    )
                )
                .order_by(Paper.id)
                .first()
            )
            return paper

        else:
            # For full-text: get papers that passed title/abstract screening
            # but haven't been full-text screened yet
            paper = (
                self.db.query(Paper)
                .outerjoin(
                    ScreeningDecision,
                    and_(
                        ScreeningDecision.paper_id == Paper.id,
                        ScreeningDecision.stage == STAGE_FULL_TEXT,
                    ),
                )
                .filter(
                    and_(
                        Paper.screening_status == "include",
                        ScreeningDecision.id.is_(None),
                    )
                )
                .order_by(Paper.id)
                .first()
            )
            return paper

    def get_screening_progress(self) -> dict:
        """Get screening progress statistics."""
        total = self.db.query(func.count(Paper.id)).filter(
            Paper.duplicate_status.not_in(
                ["probable_duplicate", "confirmed_duplicate"]
            )
        ).scalar()

        not_screened = self.db.query(func.count(Paper.id)).filter(
            and_(
                Paper.screening_status == "not_screened",
                Paper.duplicate_status.not_in(
                    ["probable_duplicate", "confirmed_duplicate"]
                ),
            )
        ).scalar()

        included = self.db.query(func.count(Paper.id)).filter(
            Paper.screening_status == "include"
        ).scalar()

        excluded = self.db.query(func.count(Paper.id)).filter(
            Paper.screening_status == "exclude"
        ).scalar()

        borderline = self.db.query(func.count(Paper.id)).filter(
            Paper.screening_status == "borderline"
        ).scalar()

        awaiting = self.db.query(func.count(Paper.id)).filter(
            Paper.screening_status == "awaiting_full_text"
        ).scalar()

        # Exclusion reason breakdown
        exclusion_reasons = (
            self.db.query(
                Paper.exclusion_reason,
                func.count(Paper.id),
            )
            .filter(Paper.screening_status == "exclude")
            .group_by(Paper.exclusion_reason)
            .all()
        )

        # Full-text screening progress
        full_text_screened = (
            self.db.query(func.count(func.distinct(ScreeningDecision.paper_id)))
            .filter(ScreeningDecision.stage == STAGE_FULL_TEXT)
            .scalar()
        )

        return {
            "total_candidates": total,
            "not_screened": not_screened,
            "included": included,
            "excluded": excluded,
            "borderline": borderline,
            "awaiting_full_text": awaiting,
            "screened_count": total - not_screened,
            "screening_progress_pct": (
                round((total - not_screened) / total * 100, 1) if total > 0 else 0
            ),
            "exclusion_reasons": [
                {"reason": r or "unspecified", "count": c}
                for r, c in exclusion_reasons
            ],
            "full_text_screened": full_text_screened,
        }

    def bulk_submit(
        self,
        decisions: list[dict],
        actor: str = "user",
    ) -> dict:
        """
        Submit multiple screening decisions at once.

        Each dict in decisions should have:
        - paper_id (required)
        - stage (optional, default title_abstract)
        - q1, q2, q3, q4 (optional)
        - decision (required)
        - exclusion_reason (required if decision=exclude)
        - notes (optional)

        Returns:
            dict with success count and errors
        """
        success_count = 0
        errors = []

        for item in decisions:
            try:
                self.submit_decision(
                    paper_id=item["paper_id"],
                    stage=item.get("stage", STAGE_TITLE_ABSTRACT),
                    q1=item.get("q1"),
                    q2=item.get("q2"),
                    q3=item.get("q3"),
                    q4=item.get("q4"),
                    decision=item.get("decision"),
                    exclusion_reason=item.get("exclusion_reason"),
                    exclusion_reason_detail=item.get("exclusion_reason_detail"),
                    notes=item.get("notes"),
                    actor=actor,
                )
                success_count += 1
            except Exception as e:
                errors.append({
                    "paper_id": item.get("paper_id"),
                    "error": str(e),
                })

        return {
            "total": len(decisions),
            "success_count": success_count,
            "error_count": len(errors),
            "errors": errors,
        }
