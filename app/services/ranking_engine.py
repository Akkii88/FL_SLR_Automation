"""
Ranking Stability Engine
=========================
Implements structured RQ5 support for ranking robustness analysis.

For each claim/study, records:
- condition
- algorithm
- metric
- ranking position
- winner
- whether ranking changed
- author's explicit discussion
- evidence location

Rules:
- Do NOT infer instability merely because numbers differ.
- Do NOT infer stability merely because one algorithm is highest in multiple tables.
- The researcher must explicitly mark: Explicitly Stable, Observationally Stable,
  Explicitly Unstable, Not Assessable
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.paper import Paper
from app.models.extraction import Claim, Experiment, Condition, EvidenceQuality
from app.models.screening import AuditLog

logger = logging.getLogger(__name__)


class RankingStabilityEngine:
    """
    Analyzes ranking stability across conditions for claims.
    """

    def __init__(self, db: Session):
        self.db = db

    def analyze_claim_rankings(self, claim_id: int) -> dict:
        """
        Analyze ranking stability for a claim across its experiments and conditions.
        
        Returns a structured analysis of:
        - Which algorithms are compared
        - How rankings change across conditions
        - Whether the winner is consistent
        """
        claim = self.db.query(Claim).filter(Claim.id == claim_id).first()
        if not claim:
            raise ValueError(f"Claim {claim_id} not found")

        experiments = self.db.query(Experiment).filter(
            Experiment.claim_id == claim_id
        ).all()

        # Collect all conditions with their rankings
        all_conditions = []
        algorithms = set()
        winners_by_condition = {}

        for exp in experiments:
            conditions = self.db.query(Condition).filter(
                Condition.experiment_id == exp.id
            ).all()

            for cond in conditions:
                if cond.algorithm:
                    algorithms.add(cond.algorithm)

                all_conditions.append({
                    "experiment_id": exp.id,
                    "experiment_name": exp.experiment_name,
                    "dataset": exp.dataset,
                    "condition_id": cond.id,
                    "algorithm": cond.algorithm,
                    "metric_name": cond.metric_name,
                    "metric_value": cond.metric_value,
                    "ranking_position": cond.ranking_position,
                    "is_winner": cond.is_winner,
                    "standard_deviation": cond.standard_deviation,
                })

                # Track winners by dataset/condition
                key = f"{exp.dataset}_{cond.metric_name}"
                if cond.is_winner:
                    if key not in winners_by_condition:
                        winners_by_condition[key] = []
                    winners_by_condition[key].append(cond.algorithm)

        # Check winner consistency
        winner_algorithms = set()
        for key, winners in winners_by_condition.items():
            winner_algorithms.update(winners)

        winner_consistent = len(winner_algorithms) <= 1
        winner_name = list(winner_algorithms)[0] if winner_consistent else None

        return {
            "claim_id": claim_id,
            "algorithms_compared": list(algorithms),
            "total_conditions": len(all_conditions),
            "winner_consistent_across_conditions": winner_consistent,
            "consistent_winner": winner_name,
            "winners_by_condition": winners_by_condition,
            "conditions": all_conditions,
        }

    def get_evidence_summary(self, claim_id: int) -> dict:
        """
        Get a structured evidence summary for a claim.
        This is the visual evidence profile for the dashboard.
        """
        claim = self.db.query(Claim).filter(Claim.id == claim_id).first()
        if not claim:
            raise ValueError(f"Claim {claim_id} not found")

        eq = self.db.query(EvidenceQuality).filter(
            EvidenceQuality.claim_id == claim_id
        ).first()

        if not eq:
            return {
                "claim_id": claim_id,
                "has_assessment": False,
                "message": "No evidence quality assessment yet.",
            }

        return {
            "claim_id": claim_id,
            "has_assessment": True,
            "profile": eq.get_evidence_profile(),
            "summary": {
                "repetition": self._summarize_repetition(eq),
                "uncertainty": self._summarize_uncertainty(eq),
                "direct_statistics": self._summarize_direct_stats(eq),
                "fairness": self._summarize_fairness(eq),
                "ranking": self._summarize_ranking(eq),
            },
            "author_claim_vs_evidence": eq.author_claim_vs_evidence,
            "important_limitation": eq.important_limitation,
            "code_repository": eq.code_repository_url,
        }

    def _summarize_repetition(self, eq: EvidenceQuality) -> str:
        runs = eq.independent_runs
        seed = eq.random_seed_reported

        if runs is None:
            return "Not reported"

        parts = [f"{runs} runs"]
        if seed == "explicitly_reported":
            parts.append("seed reported")
        elif seed == "random/fixed_but_values_absent":
            parts.append("seed not reported")
        else:
            parts.append("seed not reported")

        return ", ".join(parts)

    def _summarize_uncertainty(self, eq: EvidenceQuality) -> str:
        reporting = eq.uncertainty_reporting
        if reporting is None or reporting == "None" or reporting == "Not reported":
            return "None"

        parts = []
        if reporting in ("SD", "SD_CI"):
            sd_type = eq.sd_type or "unknown"
            parts.append(f"SD ({sd_type})")
        if reporting in ("CI", "SD_CI"):
            ci = eq.ci_level or "unknown"
            parts.append(f"CI ({ci})")
        if reporting == "Other":
            parts.append("Other")

        return ", ".join(parts) if parts else reporting

    def _summarize_direct_stats(self, eq: EvidenceQuality) -> str:
        if eq.direct_statistical_test:
            unit = eq.statistical_unit or "unknown unit"
            return f"Yes ({unit})"
        elif eq.mechanism_level_statistical_test:
            return "Mechanism-level only"
        else:
            return "No"

    def _summarize_fairness(self, eq: EvidenceQuality) -> str:
        parts = []

        partition = eq.matched_client_partition
        if partition == "YES":
            parts.append("Matched partitions")
        elif partition == "NO":
            parts.append("Unmatched partitions")
        else:
            parts.append("Partition matching not reported")

        hp = eq.hyperparameter_tuning_fairness
        if hp == "matched/tuned_baselines":
            parts.append("tuned baselines")
        elif hp == "matched_but_untuned/default":
            parts.append("default baselines")
        elif hp == "unclear":
            parts.append("tuning unclear")
        else:
            parts.append("tuning not reported")

        return ", ".join(parts)

    def _summarize_ranking(self, eq: EvidenceQuality) -> str:
        robustness = eq.ranking_robustness
        if robustness is None:
            return "Not assessed"
        return robustness

    def get_overall_evidence_stats(self) -> dict:
        """
        Get overall evidence quality statistics across all claims.
        For the main dashboard.
        """
        total_claims = self.db.query(func.count(Claim.id)).scalar()
        assessed_claims = self.db.query(func.count(EvidenceQuality.id)).scalar()

        # Dimension 1: Repetition
        runs_distribution = (
            self.db.query(
                EvidenceQuality.independent_runs,
                func.count(EvidenceQuality.id),
            )
            .filter(EvidenceQuality.independent_runs.isnot(None))
            .group_by(EvidenceQuality.independent_runs)
            .order_by(EvidenceQuality.independent_runs)
            .all()
        )

        # Dimension 2: Uncertainty
        uncertainty_dist = (
            self.db.query(
                EvidenceQuality.uncertainty_reporting,
                func.count(EvidenceQuality.id),
            )
            .group_by(EvidenceQuality.uncertainty_reporting)
            .all()
        )

        # Dimension 3: Direct statistics
        direct_stats_count = self.db.query(func.count(EvidenceQuality.id)).filter(
            EvidenceQuality.direct_statistical_test == True
        ).scalar()
        mechanism_only_count = self.db.query(func.count(EvidenceQuality.id)).filter(
            EvidenceQuality.mechanism_level_statistical_test == True,
            EvidenceQuality.direct_statistical_test == False,
        ).scalar()

        # Dimension 4: Fairness
        matched_partition_count = self.db.query(func.count(EvidenceQuality.id)).filter(
            EvidenceQuality.matched_client_partition == "YES"
        ).scalar()
        tuned_baselines_count = self.db.query(func.count(EvidenceQuality.id)).filter(
            EvidenceQuality.hyperparameter_tuning_fairness == "matched/tuned_baselines"
        ).scalar()

        # Dimension 5: Ranking robustness
        ranking_dist = (
            self.db.query(
                EvidenceQuality.ranking_robustness,
                func.count(EvidenceQuality.id),
            )
            .group_by(EvidenceQuality.ranking_robustness)
            .all()
        )

        # Author claim vs evidence
        claim_vs_evidence_dist = (
            self.db.query(
                EvidenceQuality.author_claim_vs_evidence,
                func.count(EvidenceQuality.id),
            )
            .group_by(EvidenceQuality.author_claim_vs_evidence)
            .all()
        )

        return {
            "total_claims": total_claims,
            "assessed_claims": assessed_claims,
            "assessment_coverage_pct": (
                round(assessed_claims / total_claims * 100, 1)
                if total_claims > 0 else 0
            ),
            "dimension_1_repetition": {
                "distribution": [
                    {"runs": r, "count": c} for r, c in runs_distribution
                ],
            },
            "dimension_2_uncertainty": {
                "distribution": [
                    {"type": t or "unspecified", "count": c}
                    for t, c in uncertainty_dist
                ],
            },
            "dimension_3_direct_statistics": {
                "direct_test": direct_stats_count,
                "mechanism_only": mechanism_only_count,
                "total_with_any_test": direct_stats_count + mechanism_only_count,
            },
            "dimension_4_fairness": {
                "matched_partitions": matched_partition_count,
                "tuned_baselines": tuned_baselines_count,
            },
            "dimension_5_ranking": {
                "distribution": [
                    {"type": t or "unspecified", "count": c}
                    for t, c in ranking_dist
                ],
            },
            "author_claim_vs_evidence": {
                "distribution": [
                    {"type": t or "unspecified", "count": c}
                    for t, c in claim_vs_evidence_dist
                ],
            },
        }
