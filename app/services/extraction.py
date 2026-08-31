"""
Extraction Service
===================
Manages claim-level data extraction with codebook validation.

The analytical unit is the COMPARATIVE CLAIM, not the paper.
Each claim must link back to its source paper.

Validation rules:
- Do NOT call simple accuracy difference an effect size.
- Do NOT count cross-validation folds as independent random-seed repetitions.
- Do NOT treat multiple datasets as repeated runs.
- Do NOT infer Non-IID type when not specified.
- Do NOT infer ranking instability from missing information.
- Do NOT infer ranking stability simply because one method has a higher number.
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

# Valid codebook values
VALID_CLAIM_SCOPES = {
    "Global Model Accuracy",
    "Personalized Local Model Accuracy",
    "Convergence Speed",
    "Communication Efficiency",
    "Fairness/Worst-Client Utility",
    "Adversarial Robustness",
    "Regression Safety/Error Recovery",
    "Multi-Metric Trade-off",
}

VALID_NON_IID_TYPES = {
    "Label distribution skew",
    "Feature distribution shift",
    "Quantity skew",
    "Label noise",
    "Temporal/Environmental degradation skew",
    "Systems/Hardware heterogeneity",
    "Combination",
    "Not reported",
}

VALID_PARTITION_METHODS = {
    "Dirichlet",
    "Pathological/shard",
    "Natural institutional",
    "Operational clustering",
    "Power-law quantity allocation",
    "Other",
    "Not reported",
}

VALID_UNCERTAINTY_REPORTING = {
    "None", "SD", "CI", "SD_CI", "Other", "Not reported",
}

VALID_SD_TYPES = {
    "over independent runs",
    "over client-level metrics",
    "other",
    "not reported",
}

VALID_CI_LEVELS = {
    "95%", "other", "not reported",
}

VALID_SEED_REPORTING = {
    "explicitly_reported",
    "random/fixed_but_values_absent",
    "not_reported",
}

VALID_STATISTICAL_UNITS = {
    "independent trial runs",
    "folds",
    "clients",
    "other",
    "not reported",
}

VALID_MATCHED_PARTITION = {
    "YES", "NO", "NOT_REPORTED",
}

VALID_HP_TUNING = {
    "matched/tuned_baselines",
    "matched_but_untuned/default",
    "unclear",
    "not_reported",
}

VALID_RANKING_ROBUSTNESS = {
    "Explicitly Stable",
    "Observationally Stable",
    "Explicitly Unstable",
    "Not Assessable",
}

VALID_EVIDENCE_BASIS = {
    "single point estimate",
    "mean only",
    "mean + SD",
    "mean + CI",
    "repeated runs without uncertainty",
    "direct statistical comparison",
    "mechanism-level statistical test",
    "bootstrap/ranking analysis",
    "theoretical + empirical evidence",
    "combination",
}

VALID_AUTHOR_CLAIM_VS_EVIDENCE = {
    "direct statistical test supports claim",
    "observational/supporting evidence only",
}


class ExtractionService:
    """
    Service for managing claim-level extraction data.
    """

    def __init__(self, db: Session):
        self.db = db

    # --- Claim CRUD ---

    def create_claim(
        self,
        paper_id: int,
        claim_text: Optional[str] = None,
        claim_scope: Optional[str] = None,
        algorithms_compared: Optional[list] = None,
        winner_algorithm: Optional[str] = None,
        datasets: Optional[list] = None,
        non_iid_type: Optional[str] = None,
        partition_method: Optional[str] = None,
        heterogeneity_param: Optional[str] = None,
        evidence_page: Optional[int] = None,
        evidence_section: Optional[str] = None,
        evidence_table: Optional[str] = None,
        evidence_figure: Optional[str] = None,
        evidence_snippet: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Claim:
        """Create a new claim record."""
        paper = self.db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper:
            raise ValueError(f"Paper {paper_id} not found")

        # Validate codebook values
        if claim_scope and claim_scope not in VALID_CLAIM_SCOPES:
            raise ValueError(f"Invalid claim_scope: {claim_scope}. Must be one of {VALID_CLAIM_SCOPES}")
        if non_iid_type and non_iid_type not in VALID_NON_IID_TYPES:
            raise ValueError(f"Invalid non_iid_type: {non_iid_type}")
        if partition_method and partition_method not in VALID_PARTITION_METHODS:
            raise ValueError(f"Invalid partition_method: {partition_method}")

        claim = Claim(
            paper_id=paper_id,
            claim_text=claim_text,
            claim_scope=claim_scope,
            algorithms_compared=json.dumps(algorithms_compared) if algorithms_compared else None,
            winner_algorithm=winner_algorithm,
            datasets=json.dumps(datasets) if datasets else None,
            non_iid_type=non_iid_type,
            partition_method=partition_method,
            heterogeneity_param=heterogeneity_param,
            evidence_page=evidence_page,
            evidence_section=evidence_section,
            evidence_table=evidence_table,
            evidence_figure=evidence_figure,
            evidence_snippet=evidence_snippet,
            notes=notes,
        )
        self.db.add(claim)
        self.db.commit()

        # Audit log
        audit = AuditLog(
            action="claim_created",
            entity_type="claim",
            entity_id=claim.id,
            description=f"Claim created for paper {paper_id}: {claim_scope}",
            actor="user",
            paper_id=paper_id,
        )
        self.db.add(audit)
        self.db.commit()

        return claim

    def get_claims_for_paper(self, paper_id: int) -> list[Claim]:
        """Get all claims for a paper."""
        return self.db.query(Claim).filter(Claim.paper_id == paper_id).all()

    def get_all_claims(self) -> list[Claim]:
        """Get all claims across all papers."""
        return self.db.query(Claim).order_by(Claim.paper_id, Claim.id).all()

    # --- Experiment CRUD ---

    def create_experiment(
        self,
        claim_id: int,
        experiment_name: Optional[str] = None,
        description: Optional[str] = None,
        dataset: Optional[str] = None,
        non_iid_type: Optional[str] = None,
        partition_method: Optional[str] = None,
        heterogeneity_param: Optional[str] = None,
        independent_runs: Optional[int] = None,
        random_seed_reported: Optional[str] = None,
    ) -> Experiment:
        """Create a new experiment for a claim."""
        claim = self.db.query(Claim).filter(Claim.id == claim_id).first()
        if not claim:
            raise ValueError(f"Claim {claim_id} not found")

        if random_seed_reported and random_seed_reported not in VALID_SEED_REPORTING:
            raise ValueError(f"Invalid random_seed_reported: {random_seed_reported}")

        experiment = Experiment(
            claim_id=claim_id,
            experiment_name=experiment_name,
            description=description,
            dataset=dataset,
            non_iid_type=non_iid_type,
            partition_method=partition_method,
            heterogeneity_param=heterogeneity_param,
            independent_runs=independent_runs,
            random_seed_reported=random_seed_reported,
        )
        self.db.add(experiment)
        self.db.commit()
        return experiment

    # --- Condition CRUD ---

    def create_condition(
        self,
        experiment_id: int,
        condition_name: Optional[str] = None,
        algorithm: Optional[str] = None,
        metric_name: Optional[str] = None,
        metric_value: Optional[str] = None,
        ranking_position: Optional[int] = None,
        is_winner: bool = False,
        standard_deviation: Optional[str] = None,
        confidence_interval: Optional[str] = None,
    ) -> Condition:
        """Create a new condition for an experiment."""
        experiment = self.db.query(Experiment).filter(Experiment.id == experiment_id).first()
        if not experiment:
            raise ValueError(f"Experiment {experiment_id} not found")

        condition = Condition(
            experiment_id=experiment_id,
            condition_name=condition_name,
            algorithm=algorithm,
            metric_name=metric_name,
            metric_value=metric_value,
            ranking_position=ranking_position,
            is_winner=is_winner,
            standard_deviation=standard_deviation,
            confidence_interval=confidence_interval,
        )
        self.db.add(condition)
        self.db.commit()
        return condition

    # --- Evidence Quality CRUD ---

    def create_evidence_quality(
        self,
        claim_id: int,
        independent_runs: Optional[int] = None,
        random_seed_reported: Optional[str] = None,
        uncertainty_reporting: Optional[str] = None,
        sd_type: Optional[str] = None,
        ci_level: Optional[str] = None,
        direct_statistical_test: bool = False,
        mechanism_level_statistical_test: bool = False,
        statistical_unit: Optional[str] = None,
        effect_size_reported: bool = False,
        effect_size_value: Optional[str] = None,
        matched_client_partition: Optional[str] = None,
        hyperparameter_tuning_fairness: Optional[str] = None,
        ranking_robustness: Optional[str] = None,
        evidence_basis: Optional[list] = None,
        author_claim_vs_evidence: Optional[str] = None,
        important_limitation: Optional[str] = None,
        code_repository_url: Optional[str] = None,
        evidence_page: Optional[int] = None,
        evidence_section: Optional[str] = None,
        evidence_table: Optional[str] = None,
        evidence_figure: Optional[str] = None,
        evidence_snippet: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> EvidenceQuality:
        """Create evidence quality assessment for a claim."""
        claim = self.db.query(Claim).filter(Claim.id == claim_id).first()
        if not claim:
            raise ValueError(f"Claim {claim_id} not found")

        # Validate codebook values
        if random_seed_reported and random_seed_reported not in VALID_SEED_REPORTING:
            raise ValueError(f"Invalid random_seed_reported: {random_seed_reported}")
        if uncertainty_reporting and uncertainty_reporting not in VALID_UNCERTAINTY_REPORTING:
            raise ValueError(f"Invalid uncertainty_reporting: {uncertainty_reporting}")
        if sd_type and sd_type not in VALID_SD_TYPES:
            raise ValueError(f"Invalid sd_type: {sd_type}")
        if ci_level and ci_level not in VALID_CI_LEVELS:
            raise ValueError(f"Invalid ci_level: {ci_level}")
        if statistical_unit and statistical_unit not in VALID_STATISTICAL_UNITS:
            raise ValueError(f"Invalid statistical_unit: {statistical_unit}")
        if matched_client_partition and matched_client_partition not in VALID_MATCHED_PARTITION:
            raise ValueError(f"Invalid matched_client_partition: {matched_client_partition}")
        if hyperparameter_tuning_fairness and hyperparameter_tuning_fairness not in VALID_HP_TUNING:
            raise ValueError(f"Invalid hyperparameter_tuning_fairness: {hyperparameter_tuning_fairness}")
        if ranking_robustness and ranking_robustness not in VALID_RANKING_ROBUSTNESS:
            raise ValueError(f"Invalid ranking_robustness: {ranking_robustness}")
        if author_claim_vs_evidence and author_claim_vs_evidence not in VALID_AUTHOR_CLAIM_VS_EVIDENCE:
            raise ValueError(f"Invalid author_claim_vs_evidence: {author_claim_vs_evidence}")

        eq = EvidenceQuality(
            claim_id=claim_id,
            independent_runs=independent_runs,
            random_seed_reported=random_seed_reported,
            uncertainty_reporting=uncertainty_reporting,
            sd_type=sd_type,
            ci_level=ci_level,
            direct_statistical_test=direct_statistical_test,
            mechanism_level_statistical_test=mechanism_level_statistical_test,
            statistical_unit=statistical_unit,
            effect_size_reported=effect_size_reported,
            effect_size_value=effect_size_value,
            matched_client_partition=matched_client_partition,
            hyperparameter_tuning_fairness=hyperparameter_tuning_fairness,
            ranking_robustness=ranking_robustness,
            evidence_basis=json.dumps(evidence_basis) if evidence_basis else None,
            author_claim_vs_evidence=author_claim_vs_evidence,
            important_limitation=important_limitation,
            code_repository_url=code_repository_url,
            evidence_page=evidence_page,
            evidence_section=evidence_section,
            evidence_table=evidence_table,
            evidence_figure=evidence_figure,
            evidence_snippet=evidence_snippet,
            notes=notes,
        )
        self.db.add(eq)
        self.db.commit()

        # Audit log
        audit = AuditLog(
            action="evidence_quality_created",
            entity_type="evidence_quality",
            entity_id=eq.id,
            description=f"Evidence quality assessed for claim {claim_id}",
            actor="user",
            paper_id=claim.paper_id,
        )
        self.db.add(audit)
        self.db.commit()

        return eq

    def get_evidence_quality_for_claim(self, claim_id: int) -> Optional[EvidenceQuality]:
        """Get evidence quality for a claim."""
        return self.db.query(EvidenceQuality).filter(EvidenceQuality.claim_id == claim_id).first()

    # --- Statistics ---

    def get_extraction_stats(self) -> dict:
        """Get extraction statistics."""
        total_claims = self.db.query(func.count(Claim.id)).scalar()
        total_experiments = self.db.query(func.count(Experiment.id)).scalar()
        total_conditions = self.db.query(func.count(Condition.id)).scalar()
        total_eq = self.db.query(func.count(EvidenceQuality.id)).scalar()

        # Papers with claims
        papers_with_claims = self.db.query(
            func.count(func.distinct(Claim.paper_id))
        ).scalar()

        # Direct statistical test count
        direct_stats = self.db.query(func.count(EvidenceQuality.id)).filter(
            EvidenceQuality.direct_statistical_test == True
        ).scalar()

        # Uncertainty reporting breakdown
        uncertainty_breakdown = (
            self.db.query(
                EvidenceQuality.uncertainty_reporting,
                func.count(EvidenceQuality.id),
            )
            .group_by(EvidenceQuality.uncertainty_reporting)
            .all()
        )

        # Ranking robustness breakdown
        ranking_breakdown = (
            self.db.query(
                EvidenceQuality.ranking_robustness,
                func.count(EvidenceQuality.id),
            )
            .group_by(EvidenceQuality.ranking_robustness)
            .all()
        )

        return {
            "total_claims": total_claims,
            "total_experiments": total_experiments,
            "total_conditions": total_conditions,
            "total_evidence_quality": total_eq,
            "papers_with_claims": papers_with_claims,
            "direct_statistical_tests": direct_stats,
            "uncertainty_reporting": [
                {"type": t or "unspecified", "count": c}
                for t, c in uncertainty_breakdown
            ],
            "ranking_robustness": [
                {"type": t or "unspecified", "count": c}
                for t, c in ranking_breakdown
            ],
        }

    def get_codebook_values(self) -> dict:
        """Return all valid codebook values for building UI dropdowns."""
        return {
            "claim_scopes": sorted(VALID_CLAIM_SCOPES),
            "non_iid_types": sorted(VALID_NON_IID_TYPES),
            "partition_methods": sorted(VALID_PARTITION_METHODS),
            "uncertainty_reporting": sorted(VALID_UNCERTAINTY_REPORTING),
            "sd_types": sorted(VALID_SD_TYPES),
            "ci_levels": sorted(VALID_CI_LEVELS),
            "seed_reporting": sorted(VALID_SEED_REPORTING),
            "statistical_units": sorted(VALID_STATISTICAL_UNITS),
            "matched_partition": sorted(VALID_MATCHED_PARTITION),
            "hp_tuning": sorted(VALID_HP_TUNING),
            "ranking_robustness": sorted(VALID_RANKING_ROBUSTNESS),
            "evidence_basis": sorted(VALID_EVIDENCE_BASIS),
            "author_claim_vs_evidence": sorted(VALID_AUTHOR_CLAIM_VS_EVIDENCE),
        }
