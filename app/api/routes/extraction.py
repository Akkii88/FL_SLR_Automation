"""
API Routes - Extraction
========================
Endpoints for claim-level data extraction, evidence quality coding,
and codebook management.
"""

import json
import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.db.engine import get_db
from app.models.paper import Paper
from app.models.extraction import Claim, Experiment, Condition, EvidenceQuality
from app.services.extraction import ExtractionService

router = APIRouter()
logger = logging.getLogger(__name__)


# --- Request Models ---

class ClaimCreate(BaseModel):
    paper_id: int
    claim_text: Optional[str] = None
    claim_scope: Optional[str] = None
    algorithms_compared: Optional[list] = None
    winner_algorithm: Optional[str] = None
    datasets: Optional[list] = None
    non_iid_type: Optional[str] = None
    partition_method: Optional[str] = None
    heterogeneity_param: Optional[str] = None
    evidence_page: Optional[int] = None
    evidence_section: Optional[str] = None
    evidence_table: Optional[str] = None
    evidence_figure: Optional[str] = None
    evidence_snippet: Optional[str] = None
    notes: Optional[str] = None


class ExperimentCreate(BaseModel):
    claim_id: int
    experiment_name: Optional[str] = None
    description: Optional[str] = None
    dataset: Optional[str] = None
    non_iid_type: Optional[str] = None
    partition_method: Optional[str] = None
    heterogeneity_param: Optional[str] = None
    independent_runs: Optional[int] = None
    random_seed_reported: Optional[str] = None


class ConditionCreate(BaseModel):
    experiment_id: int
    condition_name: Optional[str] = None
    algorithm: Optional[str] = None
    metric_name: Optional[str] = None
    metric_value: Optional[str] = None
    ranking_position: Optional[int] = None
    is_winner: bool = False
    standard_deviation: Optional[str] = None
    confidence_interval: Optional[str] = None


class EvidenceQualityCreate(BaseModel):
    claim_id: int
    independent_runs: Optional[int] = None
    random_seed_reported: Optional[str] = None
    uncertainty_reporting: Optional[str] = None
    sd_type: Optional[str] = None
    ci_level: Optional[str] = None
    direct_statistical_test: bool = False
    mechanism_level_statistical_test: bool = False
    statistical_unit: Optional[str] = None
    effect_size_reported: bool = False
    effect_size_value: Optional[str] = None
    matched_client_partition: Optional[str] = None
    hyperparameter_tuning_fairness: Optional[str] = None
    ranking_robustness: Optional[str] = None
    evidence_basis: Optional[list] = None
    author_claim_vs_evidence: Optional[str] = None
    important_limitation: Optional[str] = None
    code_repository_url: Optional[str] = None
    evidence_page: Optional[int] = None
    evidence_section: Optional[str] = None
    evidence_table: Optional[str] = None
    evidence_figure: Optional[str] = None
    evidence_snippet: Optional[str] = None
    notes: Optional[str] = None


# --- Codebook Endpoint ---

@router.get("/codebook")
async def get_codebook():
    """Get all valid codebook values for building UI dropdowns."""
    service = ExtractionService(None)  # No DB needed for this
    return service.get_codebook_values()


# --- Claim Endpoints ---

@router.post("/claims")
async def create_claim(claim: ClaimCreate, db: Session = Depends(get_db)):
    """Create a new claim for a paper."""
    service = ExtractionService(db)
    try:
        new_claim = service.create_claim(
            paper_id=claim.paper_id,
            claim_text=claim.claim_text,
            claim_scope=claim.claim_scope,
            algorithms_compared=claim.algorithms_compared,
            winner_algorithm=claim.winner_algorithm,
            datasets=claim.datasets,
            non_iid_type=claim.non_iid_type,
            partition_method=claim.partition_method,
            heterogeneity_param=claim.heterogeneity_param,
            evidence_page=claim.evidence_page,
            evidence_section=claim.evidence_section,
            evidence_table=claim.evidence_table,
            evidence_figure=claim.evidence_figure,
            evidence_snippet=claim.evidence_snippet,
            notes=claim.notes,
        )
        return {
            "status": "created",
            "claim_id": new_claim.id,
            "paper_id": new_claim.paper_id,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/claims")
async def list_claims(
    paper_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """List claims, optionally filtered by paper."""
    service = ExtractionService(db)
    if paper_id:
        claims = service.get_claims_for_paper(paper_id)
    else:
        claims = service.get_all_claims()

    return {
        "total": len(claims),
        "claims": [
            {
                "id": c.id,
                "paper_id": c.paper_id,
                "claim_text": c.claim_text,
                "claim_scope": c.claim_scope,
                "algorithms_compared": json.loads(c.algorithms_compared) if c.algorithms_compared else [],
                "winner_algorithm": c.winner_algorithm,
                "datasets": json.loads(c.datasets) if c.datasets else [],
                "non_iid_type": c.non_iid_type,
                "partition_method": c.partition_method,
                "heterogeneity_param": c.heterogeneity_param,
                "evidence_page": c.evidence_page,
                "evidence_section": c.evidence_section,
                "evidence_table": c.evidence_table,
                "evidence_figure": c.evidence_figure,
                "notes": c.notes,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in claims
        ],
    }


@router.get("/claims/{claim_id}")
async def get_claim_detail(claim_id: int, db: Session = Depends(get_db)):
    """Get full claim detail with experiments, conditions, and evidence quality."""
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    experiments = db.query(Experiment).filter(Experiment.claim_id == claim_id).all()
    evidence_quality = db.query(EvidenceQuality).filter(EvidenceQuality.claim_id == claim_id).first()

    return {
        "claim": {
            "id": claim.id,
            "paper_id": claim.paper_id,
            "claim_text": claim.claim_text,
            "claim_scope": claim.claim_scope,
            "algorithms_compared": json.loads(claim.algorithms_compared) if claim.algorithms_compared else [],
            "winner_algorithm": claim.winner_algorithm,
            "datasets": json.loads(claim.datasets) if claim.datasets else [],
            "non_iid_type": claim.non_iid_type,
            "partition_method": claim.partition_method,
            "heterogeneity_param": claim.heterogeneity_param,
            "evidence_page": claim.evidence_page,
            "evidence_section": claim.evidence_section,
            "evidence_table": claim.evidence_table,
            "evidence_figure": claim.evidence_figure,
            "evidence_snippet": claim.evidence_snippet,
            "notes": claim.notes,
        },
        "experiments": [
            {
                "id": e.id,
                "experiment_name": e.experiment_name,
                "dataset": e.dataset,
                "non_iid_type": e.non_iid_type,
                "partition_method": e.partition_method,
                "heterogeneity_param": e.heterogeneity_param,
                "independent_runs": e.independent_runs,
                "random_seed_reported": e.random_seed_reported,
                "conditions": [
                    {
                        "id": c.id,
                        "algorithm": c.algorithm,
                        "metric_name": c.metric_name,
                        "metric_value": c.metric_value,
                        "ranking_position": c.ranking_position,
                        "is_winner": c.is_winner,
                        "standard_deviation": c.standard_deviation,
                        "confidence_interval": c.confidence_interval,
                    }
                    for c in e.conditions
                ],
            }
            for e in experiments
        ],
        "evidence_quality": {
            "id": evidence_quality.id,
            "profile": evidence_quality.get_evidence_profile(),
            "direct_statistical_test": evidence_quality.direct_statistical_test,
            "mechanism_level_statistical_test": evidence_quality.mechanism_level_statistical_test,
            "effect_size_reported": evidence_quality.effect_size_reported,
            "effect_size_value": evidence_quality.effect_size_value,
            "evidence_basis": json.loads(evidence_quality.evidence_basis) if evidence_quality.evidence_basis else [],
            "author_claim_vs_evidence": evidence_quality.author_claim_vs_evidence,
            "important_limitation": evidence_quality.important_limitation,
            "code_repository_url": evidence_quality.code_repository_url,
            "notes": evidence_quality.notes,
        } if evidence_quality else None,
    }


# --- Experiment Endpoints ---

@router.post("/experiments")
async def create_experiment(experiment: ExperimentCreate, db: Session = Depends(get_db)):
    """Create a new experiment for a claim."""
    service = ExtractionService(db)
    try:
        exp = service.create_experiment(
            claim_id=experiment.claim_id,
            experiment_name=experiment.experiment_name,
            description=experiment.description,
            dataset=experiment.dataset,
            non_iid_type=experiment.non_iid_type,
            partition_method=experiment.partition_method,
            heterogeneity_param=experiment.heterogeneity_param,
            independent_runs=experiment.independent_runs,
            random_seed_reported=experiment.random_seed_reported,
        )
        return {"status": "created", "experiment_id": exp.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Condition Endpoints ---

@router.post("/conditions")
async def create_condition(condition: ConditionCreate, db: Session = Depends(get_db)):
    """Create a new condition for an experiment."""
    service = ExtractionService(db)
    try:
        cond = service.create_condition(
            experiment_id=condition.experiment_id,
            condition_name=condition.condition_name,
            algorithm=condition.algorithm,
            metric_name=condition.metric_name,
            metric_value=condition.metric_value,
            ranking_position=condition.ranking_position,
            is_winner=condition.is_winner,
            standard_deviation=condition.standard_deviation,
            confidence_interval=condition.confidence_interval,
        )
        return {"status": "created", "condition_id": cond.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Evidence Quality Endpoints ---

@router.post("/evidence-quality")
async def create_evidence_quality(eq: EvidenceQualityCreate, db: Session = Depends(get_db)):
    """Create evidence quality assessment for a claim."""
    service = ExtractionService(db)
    try:
        new_eq = service.create_evidence_quality(
            claim_id=eq.claim_id,
            independent_runs=eq.independent_runs,
            random_seed_reported=eq.random_seed_reported,
            uncertainty_reporting=eq.uncertainty_reporting,
            sd_type=eq.sd_type,
            ci_level=eq.ci_level,
            direct_statistical_test=eq.direct_statistical_test,
            mechanism_level_statistical_test=eq.mechanism_level_statistical_test,
            statistical_unit=eq.statistical_unit,
            effect_size_reported=eq.effect_size_reported,
            effect_size_value=eq.effect_size_value,
            matched_client_partition=eq.matched_client_partition,
            hyperparameter_tuning_fairness=eq.hyperparameter_tuning_fairness,
            ranking_robustness=eq.ranking_robustness,
            evidence_basis=eq.evidence_basis,
            author_claim_vs_evidence=eq.author_claim_vs_evidence,
            important_limitation=eq.important_limitation,
            code_repository_url=eq.code_repository_url,
            evidence_page=eq.evidence_page,
            evidence_section=eq.evidence_section,
            evidence_table=eq.evidence_table,
            evidence_figure=eq.evidence_figure,
            evidence_snippet=eq.evidence_snippet,
            notes=eq.notes,
        )
        return {"status": "created", "evidence_quality_id": new_eq.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Statistics ---

@router.get("/stats")
async def get_extraction_stats(db: Session = Depends(get_db)):
    """Get extraction statistics."""
    service = ExtractionService(db)
    return service.get_extraction_stats()
