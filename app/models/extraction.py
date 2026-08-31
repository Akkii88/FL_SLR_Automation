"""
Claim-Level Data Models
=========================
The analytical unit is the COMPARATIVE CLAIM, not simply the paper.
One paper may have several claims. Each claim links back to its source paper.

Models:
- Claim: A comparative/superiority claim made in a paper
- Experiment: A specific experimental setup for a claim
- Condition: A specific condition within an experiment (e.g., specific dataset + skew)
- EvidenceQuality: Quality assessment for each claim
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime,
    ForeignKey, Float, Index, Table
)
from sqlalchemy.orm import relationship
from app.db.engine import Base


class Claim(Base):
    """
    A comparative/superiority claim made in a paper.
    
    Example: "FedX outperforms FedAvg on CIFAR-10 with alpha=0.1"
    This is separate from: "FedX outperforms FedAvg on CIFAR-100 with alpha=0.5"
    """

    __tablename__ = "claims"

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)

    # --- Claim Identification ---
    claim_text = Column(Text, nullable=True)  # Verbatim claim text from paper
    claim_scope = Column(String(64), nullable=True)
    # Global Model Accuracy, Personalized Local Model Accuracy,
    # Convergence Speed, Communication Efficiency, Fairness/Worst-Client Utility,
    # Adversarial Robustness, Regression Safety/Error Recovery, Multi-Metric Trade-off

    # --- Algorithms Compared ---
    algorithms_compared = Column(Text, nullable=True)  # JSON list of algorithm names
    winner_algorithm = Column(String(255), nullable=True)  # Which algorithm "wins"

    # --- Claim Details ---
    datasets = Column(Text, nullable=True)  # JSON list of datasets used
    non_iid_type = Column(String(64), nullable=True)
    # Label distribution skew, Feature distribution shift, Quantity skew,
    # Label noise, Temporal/Environmental degradation skew,
    # Systems/Hardware heterogeneity, Combination, Not reported

    partition_method = Column(String(64), nullable=True)
    # Dirichlet, Pathological/shard, Natural institutional,
    # Operational clustering, Power-law quantity allocation, Other, Not reported

    heterogeneity_param = Column(String(255), nullable=True)
    # alpha, beta, shard count, straggler ratio, noise level, etc.

    # --- Evidence Location ---
    evidence_page = Column(Integer, nullable=True)
    evidence_section = Column(String(255), nullable=True)
    evidence_table = Column(String(128), nullable=True)
    evidence_figure = Column(String(128), nullable=True)
    evidence_snippet = Column(Text, nullable=True)  # Quoted evidence (if legally appropriate)

    # --- Metadata ---
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # --- Relationships ---
    paper = relationship("Paper", back_populates="claims")
    experiments = relationship("Experiment", back_populates="claim", cascade="all, delete-orphan")
    evidence_quality = relationship("EvidenceQuality", back_populates="claim", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_claims_paper", "paper_id"),
        Index("ix_claims_scope", "claim_scope"),
        Index("ix_claims_winner", "winner_algorithm"),
    )

    def __repr__(self):
        return f"<Claim(id={self.id}, paper={self.paper_id}, scope={self.claim_scope})>"


class Experiment(Base):
    """
    A specific experimental setup for a claim.
    One claim may have multiple experiments (e.g., different datasets).
    """

    __tablename__ = "experiments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False)

    # --- Experiment Identification ---
    experiment_name = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)

    # --- Dataset & Setup ---
    dataset = Column(String(255), nullable=True)
    dataset_description = Column(Text, nullable=True)

    # --- Non-IID Setup ---
    non_iid_type = Column(String(64), nullable=True)
    partition_method = Column(String(64), nullable=True)
    heterogeneity_param = Column(String(255), nullable=True)

    # --- Experimental Repetition ---
    independent_runs = Column(Integer, nullable=True)
    # Number of independent training runs per unique condition.
    # Do NOT count different datasets, skews, or hyperparameter settings as repeated runs.

    random_seed_reported = Column(String(64), nullable=True)
    # explicitly_reported, random/fixed_but_values_absent, not_reported

    # --- Relationships ---
    claim = relationship("Claim", back_populates="experiments")
    conditions = relationship("Condition", back_populates="experiment", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_experiments_claim", "claim_id"),
    )

    def __repr__(self):
        return f"<Experiment(id={self.id}, claim={self.claim_id}, dataset={self.dataset})>"


class Condition(Base):
    """
    A specific condition within an experiment.
    Example: CIFAR-10, alpha=0.1, FedAvg vs FedX
    """

    __tablename__ = "conditions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    experiment_id = Column(Integer, ForeignKey("experiments.id"), nullable=False)

    # --- Condition Identification ---
    condition_name = Column(String(255), nullable=True)
    algorithm = Column(String(255), nullable=True)
    metric_name = Column(String(255), nullable=True)
    metric_value = Column(String(128), nullable=True)  # Store as string to handle various formats

    # --- Ranking ---
    ranking_position = Column(Integer, nullable=True)
    is_winner = Column(Boolean, default=False)

    # --- Uncertainty ---
    standard_deviation = Column(String(128), nullable=True)
    confidence_interval = Column(String(128), nullable=True)

    # --- Relationships ---
    experiment = relationship("Experiment", back_populates="conditions")

    __table_args__ = (
        Index("ix_conditions_experiment", "experiment_id"),
    )

    def __repr__(self):
        return f"<Condition(id={self.id}, alg={self.algorithm}, metric={self.metric_value})>"


class EvidenceQuality(Base):
    """
    Quality assessment for each claim.
    Five independent dimensions (NOT combined into a single score).

    Dimension 1: Experimental repetition
    Dimension 2: Uncertainty reporting
    Dimension 3: Direct statistical evidence
    Dimension 4: Comparison fairness
    Dimension 5: Ranking robustness
    """

    __tablename__ = "evidence_qualities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False)

    # --- Dimension 1: Experimental Repetition ---
    independent_runs = Column(Integer, nullable=True)
    random_seed_reported = Column(String(64), nullable=True)
    # explicitly_reported, random/fixed_but_values_absent, not_reported

    # --- Dimension 2: Uncertainty Reporting ---
    uncertainty_reporting = Column(String(64), nullable=True)
    # None, SD, CI, SD_CI, Other, Not_reported

    sd_type = Column(String(64), nullable=True)
    # over_independent_runs, over_client_level_metrics, other, not_reported

    ci_level = Column(String(32), nullable=True)
    # 95%, other, not_reported

    # --- Dimension 3: Direct Statistical Evidence ---
    direct_statistical_test = Column(Boolean, default=False)
    # Must be a formal inferential test directly comparing competing algorithm performance.
    # Examples: paired t-test, Wilcoxon, ANOVA, Kruskal-Wallis, permutation test.
    # A mechanism correlation test is NOT sufficient.

    mechanism_level_statistical_test = Column(Boolean, default=False)
    statistical_unit = Column(String(64), nullable=True)
    # independent_trial_runs, folds, clients, other, not_reported

    effect_size_reported = Column(Boolean, default=False)
    effect_size_value = Column(String(128), nullable=True)
    # DO NOT call simple accuracy difference an effect size.

    # --- Dimension 4: Comparison Fairness ---
    matched_client_partition = Column(String(32), nullable=True)
    # YES, NO, NOT_REPORTED

    hyperparameter_tuning_fairness = Column(String(64), nullable=True)
    # matched_tuned_baselines, matched_but_untuned_default, unclear, not_reported

    # --- Dimension 5: Ranking Robustness ---
    ranking_robustness = Column(String(64), nullable=True)
    # Explicitly_Stable, Observationally_Stable, Explicitly_Unstable, Not_Assessable

    # --- Evidence Basis ---
    evidence_basis = Column(Text, nullable=True)
    # JSON list: single_point_estimate, mean_only, mean_SD, mean_CI,
    # repeated_runs_without_uncertainty, direct_statistical_comparison,
    # mechanism_level_statistical_test, bootstrap_ranking_analysis,
    # theoretical_empirical_evidence, combination

    # --- Author Claim vs Evidence ---
    author_claim_vs_evidence = Column(String(64), nullable=True)
    # direct_statistical_test_supports_claim, observational_supporting_evidence_only

    # --- Important Limitation ---
    important_limitation = Column(Text, nullable=True)

    # --- Code/Repository ---
    code_repository_url = Column(String(2048), nullable=True)

    # --- Evidence Location ---
    evidence_page = Column(Integer, nullable=True)
    evidence_section = Column(String(255), nullable=True)
    evidence_table = Column(String(128), nullable=True)
    evidence_figure = Column(String(128), nullable=True)
    evidence_snippet = Column(Text, nullable=True)

    # --- Metadata ---
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # --- Relationships ---
    claim = relationship("Claim", back_populates="evidence_quality")

    __table_args__ = (
        Index("ix_evidence_quality_claim", "claim_id"),
    )

    def __repr__(self):
        return f"<EvidenceQuality(id={self.id}, claim={self.claim_id})>"

    def get_evidence_profile(self) -> dict:
        """
        Return a structured evidence profile for display.
        This is the visual representation of the 5 dimensions.
        """
        return {
            "repetition": {
                "runs": self.independent_runs,
                "seed": self.random_seed_reported,
            },
            "uncertainty": {
                "reporting": self.uncertainty_reporting,
                "sd_type": self.sd_type,
                "ci_level": self.ci_level,
            },
            "direct_statistics": {
                "test": self.direct_statistical_test,
                "unit": self.statistical_unit,
                "effect_size": self.effect_size_reported,
                "effect_size_value": self.effect_size_value,
            },
            "fairness": {
                "matched_partition": self.matched_client_partition,
                "hyperparameter_tuning": self.hyperparameter_tuning_fairness,
            },
            "ranking": {
                "robustness": self.ranking_robustness,
            },
        }
