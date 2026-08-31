"""
LLM Extraction Service
=======================
Optional LLM assistance layer for extraction and screening.

IMPORTANT:
- The LLM may recommend but the human researcher remains the final decision maker.
- Every extracted item must contain: value, confidence, evidence_snippet, evidence_location, model, timestamp.
- NEVER accept an LLM-generated value without evidence.
- If unsupported: "Not reported"
- Do not allow the LLM to invent missing information.

Supports:
- OpenAI (gpt-4, etc.)
- Anthropic (claude-sonnet, etc.)
- Local models (via OpenAI-compatible API)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.paper import Paper
from app.models.screening import ScreeningDecision, AuditLog

logger = logging.getLogger(__name__)


class LLMExtractionService:
    """
    Optional LLM assistance for extraction tasks.
    All LLM outputs are stored with evidence and confidence.
    Human verification is always required.
    """

    def __init__(self, db: Session):
        self.db = db
        self.provider = settings.llm_provider
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model

    def is_configured(self) -> bool:
        """Check if LLM is configured."""
        return bool(self.provider and self.api_key and self.model)

    def _get_client(self):
        """Get the appropriate LLM client based on provider."""
        if not self.is_configured():
            raise RuntimeError("LLM not configured. Set LLM_PROVIDER, LLM_API_KEY, and LLM_MODEL in .env")

        if self.provider.lower() in ("openai", "groq"):
            try:
                from openai import OpenAI
                # Groq uses OpenAI-compatible API with custom base URL
                if self.provider.lower() == "groq":
                    return OpenAI(
                        api_key=self.api_key,
                        base_url="https://api.groq.com/openai/v1",
                    )
                return OpenAI(api_key=self.api_key)
            except ImportError:
                raise RuntimeError("openai package not installed. Run: pip install openai")

        elif self.provider.lower() == "anthropic":
            try:
                from anthropic import Anthropic
                return Anthropic(api_key=self.api_key)
            except ImportError:
                raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def _call_llm(self, system_prompt: str, user_prompt: str) -> dict:
        """
        Call the LLM and return structured output.
        
        Returns:
            dict with 'content' (str) and 'model' (str)
        """
        client = self._get_client()

        if self.provider.lower() in ("openai", "groq"):
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,  # Low temperature for factual extraction
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            model = self.model

        elif self.provider.lower() == "anthropic":
            response = client.messages.create(
                model=self.model,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=0.1,
                max_tokens=4096,
            )
            content = response.content[0].text
            model = self.model

        return {"content": content, "model": model}

    def suggest_extraction(
        self,
        paper_id: int,
        extraction_type: str = "full",
    ) -> dict:
        """
        Suggest extraction data for a paper based on its abstract/full text.
        
        Args:
            paper_id: The paper to extract from
            extraction_type: "full", "algorithms", "datasets", "non_iid", "evidence"
            
        Returns:
            dict with suggestions, evidence, confidence, and model info
        """
        paper = self.db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper:
            raise ValueError(f"Paper {paper_id} not found")

        # Build the source text
        source_text = self._build_source_text(paper)

        # Build prompts based on extraction type
        system_prompt = self._get_extraction_system_prompt(extraction_type)
        user_prompt = self._get_extraction_user_prompt(paper, source_text, extraction_type)

        try:
            result = self._call_llm(system_prompt, user_prompt)
            llm_output = json.loads(result["content"])

            # Add metadata
            llm_output["_metadata"] = {
                "model": result["model"],
                "provider": self.provider,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "extraction_type": extraction_type,
                "paper_id": paper_id,
                "source_text_length": len(source_text),
            }

            # Audit log
            audit = AuditLog(
                action="llm_extraction",
                entity_type="paper",
                entity_id=paper_id,
                description=f"LLM extraction suggested ({extraction_type}) using {result['model']}",
                actor="system",
                paper_id=paper_id,
            )
            self.db.add(audit)
            self.db.commit()

            return llm_output

        except json.JSONDecodeError as e:
            logger.error(f"LLM returned invalid JSON: {e}")
            return {
                "error": "LLM returned invalid JSON",
                "_metadata": {
                    "model": result.get("model", self.model),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "extraction_type": extraction_type,
                    "paper_id": paper_id,
                },
            }

        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            return {
                "error": str(e),
                "_metadata": {
                    "model": self.model,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "extraction_type": extraction_type,
                    "paper_id": paper_id,
                },
            }

    def _build_source_text(self, paper: Paper) -> str:
        """Build the source text from paper metadata."""
        parts = []

        if paper.title:
            parts.append(f"Title: {paper.title}")

        if paper.authors:
            try:
                authors = json.loads(paper.authors)
                parts.append(f"Authors: {', '.join(authors)}")
            except:
                pass

        if paper.publication_year:
            parts.append(f"Year: {paper.publication_year}")

        if paper.abstract:
            parts.append(f"\nAbstract:\n{paper.abstract}")

        return "\n".join(parts)

    def _get_extraction_system_prompt(self, extraction_type: str) -> str:
        """Get the system prompt for the extraction type."""
        base_prompt = """You are a systematic review research assistant extracting structured data from academic papers about Federated Learning.

CRITICAL RULES:
1. ONLY extract information explicitly stated in the provided text.
2. If information is not present, use "Not reported" — NEVER invent or infer missing information.
3. For each extracted field, provide the exact evidence snippet from the text that supports it.
4. Rate your confidence in each extraction (0.0 to 1.0).
5. Simple accuracy differences are NOT effect sizes.
6. Cross-validation folds are NOT independent random-seed repetitions.
7. Multiple datasets do NOT count as repeated runs.
8. Do NOT infer Non-IID type when not specified.
9. Do NOT infer ranking stability from higher numbers alone.

Output valid JSON only."""

        type_prompts = {
            "full": """

Extract the following information:
{
  "algorithms_compared": ["list of algorithm names"],
  "datasets": ["list of dataset names"],
  "non_iid_type": "type of non-IID/heterogeneity or 'Not reported'",
  "partition_method": "partition method or 'Not reported'",
  "heterogeneity_params": "alpha, beta, shard count, etc. or 'Not reported'",
  "independent_runs": number or null,
  "random_seed": "explicitly_reported, random/fixed_but_values_absent, or not_reported",
  "uncertainty_reporting": "None, SD, CI, SD_CI, Other, or Not reported",
  "direct_statistical_test": true/false,
  "statistical_test_type": "type of test or 'Not reported'",
  "effect_size_reported": true/false,
  "matched_partition": "YES, NO, or NOT_REPORTED",
  "hyperparameter_tuning": "matched/tuned_baselines, matched_but_untuned/default, unclear, or not_reported",
  "superiority_claims": ["list of explicit superiority claims"],
  "evidence_locations": [{"page": number, "section": string, "table": string, "figure": string}],
  "confidence": 0.0-1.0,
  "evidence_snippets": {"field": "supporting text snippet"}
}""",

            "algorithms": """

Extract algorithm names mentioned in the paper:
{
  "algorithms": ["list of algorithm names"],
  "baselines": ["list of baseline methods"],
  "proposed_method": "name of the proposed method or 'Not reported'",
  "confidence": 0.0-1.0,
  "evidence_snippets": {"field": "supporting text snippet"}
}""",

            "datasets": """

Extract dataset information:
{
  "datasets": ["list of dataset names"],
  "dataset_descriptions": "brief descriptions or 'Not reported'",
  "confidence": 0.0-1.0,
  "evidence_snippets": {"field": "supporting text snippet"}
}""",

            "non_iid": """

Extract Non-IID/heterogeneity setup:
{
  "non_iid_type": "type or 'Not reported'",
  "partition_method": "method or 'Not reported'",
  "heterogeneity_params": "parameters or 'Not reported'",
  "confidence": 0.0-1.0,
  "evidence_snippets": {"field": "supporting text snippet"}
}""",

            "evidence": """

Extract evidence quality indicators:
{
  "independent_runs": number or null,
  "random_seed": "explicitly_reported, random/fixed_but_values_absent, or not_reported",
  "uncertainty_reporting": "None, SD, CI, SD_CI, Other, or Not reported",
  "direct_statistical_test": true/false,
  "statistical_test_type": "type or 'Not reported'",
  "effect_size_reported": true/false,
  "matched_partition": "YES, NO, or NOT_REPORTED",
  "confidence": 0.0-1.0,
  "evidence_snippets": {"field": "supporting text snippet"}
}""",
        }

        return base_prompt + type_prompts.get(extraction_type, type_prompts["full"])

    def _get_extraction_user_prompt(
        self,
        paper: Paper,
        source_text: str,
        extraction_type: str,
    ) -> str:
        """Build the user prompt with paper text."""
        return f"""Please extract structured data from the following paper information.

Paper ID: {paper.id}
Source: {paper.source or 'Unknown'}
DOI: {paper.doi or 'Not available'}

{source_text}

Extract the requested information following the system prompt rules."""

    def suggest_screening(
        self,
        paper_id: int,
    ) -> dict:
        """
        Suggest a screening decision based on the paper's abstract.
        
        Returns:
            dict with recommendation, reasoning, and evidence
        """
        paper = self.db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper:
            raise ValueError(f"Paper {paper_id} not found")

        source_text = self._build_source_text(paper)

        system_prompt = """You are a systematic review research assistant helping screen papers for inclusion.

Review these four questions:
Q1: Does the study experimentally compare at least two FL algorithms/methods?
Q2: Does it evaluate those methods under Non-IID or heterogeneous conditions?
Q3: Does it contain an explicit comparative/superiority claim?
Q4: Is enough full text available to verify eligibility?

Rules:
- Only answer based on the provided text.
- If information is unclear, mark as UNCLEAR.
- Do NOT assume information not present.
- Provide exact evidence snippets for each answer.

Output valid JSON:
{
  "q1_fl_comparison": "YES, NO, or UNCLEAR",
  "q2_non_iid": "YES, NO, or UNCLEAR",
  "q3_superiority_claim": "YES, NO, or UNCLEAR",
  "q4_full_text_available": "YES, NO, or UNCLEAR",
  "recommended_decision": "likely_include, likely_exclude, or borderline",
  "reasoning": "brief explanation",
  "evidence_snippets": {
    "q1": "supporting text",
    "q2": "supporting text",
    "q3": "supporting text",
    "q4": "supporting text"
  },
  "confidence": 0.0-1.0
}"""

        user_prompt = f"""Screen the following paper:

Paper ID: {paper.id}
Title: {paper.title or 'Unknown'}
Abstract: {paper.abstract or 'No abstract available'}

Answer the four screening questions based ONLY on the provided abstract."""

        try:
            result = self._call_llm(system_prompt, user_prompt)
            llm_output = json.loads(result["content"])

            # Store the LLM recommendation
            llm_recommendation = llm_output.get("recommended_decision", "borderline")
            llm_reason = llm_output.get("reasoning", "")

            # Map to screening decision values
            recommendation_map = {
                "likely_include": "include",
                "likely_exclude": "exclude",
                "borderline": "borderline",
            }

            # Update screening decision record with LLM recommendation
            screening_decision = ScreeningDecision(
                paper_id=paper_id,
                stage="title_abstract",
                q1_fl_comparison=llm_output.get("q1_fl_comparison"),
                q2_non_iid=llm_output.get("q2_non_iid"),
                q3_superiority_claim=llm_output.get("q3_superiority_claim"),
                q4_full_text_available=llm_output.get("q4_full_text_available"),
                llm_recommendation=recommendation_map.get(llm_recommendation, "borderline"),
                llm_reason=llm_reason,
                llm_model=result["model"],
                llm_timestamp=datetime.now(timezone.utc),
                decided_by="llm_suggestion",
            )
            self.db.add(screening_decision)
            self.db.commit()

            # Audit log
            audit = AuditLog(
                action="llm_screening_suggestion",
                entity_type="paper",
                entity_id=paper_id,
                description=f"LLM screening suggestion: {llm_recommendation}",
                actor="system",
                paper_id=paper_id,
            )
            self.db.add(audit)
            self.db.commit()

            llm_output["_metadata"] = {
                "model": result["model"],
                "provider": self.provider,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "paper_id": paper_id,
            }

            return llm_output

        except Exception as e:
            logger.error(f"LLM screening suggestion failed: {e}")
            return {
                "error": str(e),
                "_metadata": {
                    "model": self.model,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "paper_id": paper_id,
                },
            }
