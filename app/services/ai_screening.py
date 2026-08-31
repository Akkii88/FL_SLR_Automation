"""
AI Screening Service
=====================
Batch AI-assisted first-pass screening for unscreened papers.

IMPORTANT:
- AI assists screening, never makes final scientific decisions.
- All AI outputs include evidence snippets and confidence.
- Human researcher must confirm every inclusion/exclusion.
- Results are cached to avoid redundant API calls.
"""

import json
import logging
import hashlib
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.core.config import settings
from app.models.paper import Paper
from app.models.ai_screening import AIScreeningResult
from app.models.screening import AuditLog

logger = logging.getLogger(__name__)

# Prompt version for tracking changes
PROMPT_VERSION = "1.0"

# Cache: hash of paper metadata → AI result (in-memory for session)
_response_cache = {}


def _make_cache_key(paper: Paper) -> str:
    """Create a cache key from paper metadata that affects screening."""
    content = f"{paper.title}|{paper.abstract}|{paper.publication_year}|{paper.source}"
    return hashlib.md5(content.encode()).hexdigest()


class AIScreeningService:
    """
    Batch AI-assisted screening service.
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
        """Get the appropriate LLM client."""
        if not self.is_configured():
            raise RuntimeError("LLM not configured.")

        if self.provider.lower() in ("openai", "groq"):
            from openai import OpenAI
            if self.provider.lower() == "groq":
                return OpenAI(api_key=self.api_key, base_url="https://api.groq.com/openai/v1")
            return OpenAI(api_key=self.api_key)
        elif self.provider.lower() == "anthropic":
            from anthropic import Anthropic
            return Anthropic(api_key=self.api_key)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    def _call_llm(self, system_prompt: str, user_prompt: str) -> dict:
        """Call LLM and return structured output."""
        client = self._get_client()

        if self.provider.lower() in ("openai", "groq"):
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
        elif self.provider.lower() == "anthropic":
            response = client.messages.create(
                model=self.model,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=0.1,
                max_tokens=4096,
            )
            content = response.content[0].text

        return {"content": content, "model": self.model}

    def _get_system_prompt(self) -> str:
        """System prompt for first-pass screening."""
        return """You are an expert research assistant conducting a systematic literature review on Federated Learning (FL) algorithm comparisons under Non-IID/heterated data.

Your task is to assess whether a paper meets the ELIGIBILITY CRITERIA based ONLY on the provided title, abstract, and metadata.

ELIGIBILITY CRITERIA:
Q1: Does the study EXPERIMENTALLY COMPARE at least two FL algorithms/methods?
   - YES: The paper implements and compares 2+ FL methods with experiments
   - NO: Single method, theoretical only, survey/review, or no experimental comparison
   - UNCLEAR: Cannot determine from abstract alone

Q2: Does it evaluate those methods under NON-IID or HETEROGENEOUS conditions?
   - YES: Explicitly mentions non-IID, heterogeneous, skewed, Dirichlet, etc.
   - NO: Only IID data, or no mention of data distribution
   - UNCLEAR: Cannot determine from abstract

Q3: Does it contain an EXPLICIT COMPARATIVE/SUPERIORITY claim?
   - YES: Claims one method "outperforms", "is superior to", "achieves better results than"
   - NO: No comparative claims, or only reports own results
   - UNCLEAR: Claims improvement but not clearly comparative

Q4: Is enough INFORMATION AVAILABLE to make a first-pass decision?
   - YES: Abstract clearly establishes Q1-Q3
   - NO: Abstract too vague or missing critical information
   - UNCLEAR: Some information present but not definitive

CRITICAL RULES:
1. ONLY use information in the provided title/abstract — NEVER invent facts
2. If information is missing or unclear, return UNCLEAR
3. Words like "improves" or "better" WITHOUT clear algorithm comparison = NO for Q3
4. Surveys, reviews, SoK papers, theoretical papers = likely NO for Q1
5. "Proposes a new method" alone does NOT mean Q1=YES unless it compares with baselines
6. Provide exact text snippets from the abstract as evidence for each answer

OUTPUT FORMAT (valid JSON only):
{
  "q1_fl_comparison": "YES" | "NO" | "UNCLEAR",
  "q2_non_iid": "YES" | "NO" | "UNCLEAR",
  "q3_superiority_claim": "YES" | "NO" | "UNCLEAR",
  "q4_info_available": "YES" | "NO" | "UNCLEAR",
  "recommendation": "likely_include" | "likely_exclude" | "unclear",
  "confidence": "high" | "medium" | "low",
  "reasoning": "brief explanation for the recommendation",
  "q1_evidence": "exact text snippet from abstract",
  "q2_evidence": "exact text snippet from abstract",
  "q3_evidence": "exact text snippet from abstract",
  "q4_evidence": "exact text snippet from abstract"
}"""

    def _get_user_prompt(self, paper: Paper) -> str:
        """Build user prompt from paper metadata."""
        parts = [f"Paper ID: {paper.id}"]

        if paper.title:
            parts.append(f"Title: {paper.title}")
        if paper.source:
            parts.append(f"Venue: {paper.source}")
        if paper.publication_year:
            parts.append(f"Year: {paper.publication_year}")
        if paper.authors:
            try:
                authors = json.loads(paper.authors)
                if authors:
                    parts.append(f"Authors: {', '.join(authors[:5])}")
                    if len(authors) > 5:
                        parts[-1] += f" et al. ({len(authors)} authors)"
            except:
                pass
        if paper.abstract:
            parts.append(f"\nAbstract:\n{paper.abstract}")
        else:
            parts.append("\nAbstract: [NOT AVAILABLE]")

        parts.append("\nAssess this paper against the four eligibility criteria based ONLY on the provided information.")

        return "\n".join(parts)

    def _parse_llm_response(self, content: str) -> Optional[dict]:
        """Parse and validate LLM JSON response. Handles Markdown fences and extra text."""
        if not content:
            return None

        # Strip whitespace
        content = content.strip()

        # Handle Markdown code fences (```json ... ``` or ``` ... ```)
        if content.startswith("```"):
            # Remove opening fence
            lines = content.split("\n")
            # Skip first line (```json or ```)
            lines = lines[1:]
            # Remove closing fence if present
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        # Try to find JSON object in the response (handles extra text before/after)
        if not content.startswith("{"):
            # Find the first { and last }
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                content = content[start:end + 1]
            else:
                logger.error(f"No JSON object found in LLM response: {content[:200]}")
                return None

        try:
            data = json.loads(content)

            # Validate required fields
            for field in ["q1_fl_comparison", "q2_non_iid", "q3_superiority_claim", "q4_info_available"]:
                val = str(data.get(field, "")).upper()
                if val not in ("YES", "NO", "UNCLEAR"):
                    data[field] = "UNCLEAR"

            # Validate recommendation
            rec = str(data.get("recommendation", "")).lower()
            if rec not in ("likely_include", "likely_exclude", "unclear"):
                data["recommendation"] = "unclear"

            # Validate confidence
            conf = str(data.get("confidence", "")).lower()
            if conf not in ("high", "medium", "low"):
                data["confidence"] = "medium"

            # Ensure evidence fields are strings
            for ev_field in ["q1_evidence", "q2_evidence", "q3_evidence", "q4_evidence", "reasoning"]:
                if ev_field not in data or data[ev_field] is None:
                    data[ev_field] = ""
                else:
                    data[ev_field] = str(data[ev_field])

            return data

        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}. Content: {content[:300]}")
            return None

    def screen_paper(self, paper_id: int, use_cache: bool = True) -> AIScreeningResult:
        """
        Screen a single paper using AI.
        
        Args:
            paper_id: The paper to screen
            use_cache: Whether to use cached results
            
        Returns:
            AIScreeningResult
        """
        paper = self.db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper:
            raise ValueError(f"Paper {paper_id} not found")

        # Check for existing active result (cache hit)
        if use_cache:
            existing = self.db.query(AIScreeningResult).filter(
                and_(
                    AIScreeningResult.paper_id == paper_id,
                    AIScreeningResult.is_active == True,
                    AIScreeningResult.processing_status == "completed",
                )
            ).first()

            if existing:
                logger.info(f"Cache hit for paper {paper_id}")
                return existing

        # Create a pending result
        result = AIScreeningResult(
            paper_id=paper_id,
            processing_status="processing",
            prompt_version=PROMPT_VERSION,
        )
        self.db.add(result)
        self.db.commit()

        try:
            system_prompt = self._get_system_prompt()
            user_prompt = self._get_user_prompt(paper)

            llm_response = self._call_llm(system_prompt, user_prompt)
            parsed = self._parse_llm_response(llm_response["content"])

            if parsed is None:
                result.processing_status = "failed"
                result.error_message = "LLM returned invalid JSON"
                self.db.commit()
                return result

            # Deactivate any previous active results for this paper
            self.db.query(AIScreeningResult).filter(
                and_(
                    AIScreeningResult.paper_id == paper_id,
                    AIScreeningResult.is_active == True,
                )
            ).update({"is_active": False})

            # Update result
            result.q1_fl_comparison = parsed["q1_fl_comparison"]
            result.q2_non_iid = parsed["q2_non_iid"]
            result.q3_superiority_claim = parsed["q3_superiority_claim"]
            result.q4_info_available = parsed["q4_info_available"]
            result.recommendation = parsed["recommendation"]
            result.confidence = parsed.get("confidence", "medium")
            result.reasoning = parsed.get("reasoning", "")
            result.q1_evidence = parsed.get("q1_evidence", "")
            result.q2_evidence = parsed.get("q2_evidence", "")
            result.q3_evidence = parsed.get("q3_evidence", "")
            result.q4_evidence = parsed.get("q4_evidence", "")
            result.model = llm_response["model"]
            result.provider = self.provider
            result.processing_status = "completed"
            result.is_active = True

            self.db.commit()

            # Audit log
            audit = AuditLog(
                action="ai_screening",
                entity_type="paper",
                entity_id=paper_id,
                description=f"AI screening: {parsed['recommendation']} (conf: {parsed.get('confidence', 'medium')})",
                actor="system",
                paper_id=paper_id,
            )
            self.db.add(audit)
            self.db.commit()

            return result

        except Exception as e:
            logger.error(f"AI screening failed for paper {paper_id}: {e}")
            result.processing_status = "failed"
            result.error_message = str(e)
            self.db.commit()
            return result

    def batch_screen(
        self,
        batch_size: int = 25,
        max_candidates: Optional[int] = None,
    ) -> dict:
        """
        Batch screen unscreened papers.
        
        Args:
            batch_size: Number of papers to process in this batch
            max_candidates: Optional limit on total candidates to consider
            
        Returns:
            dict with batch results summary
        """
        # Find papers that haven't been AI-screened yet
        from sqlalchemy import not_, exists

        already_screened = self.db.query(AIScreeningResult.paper_id).filter(
            AIScreeningResult.is_active == True,
        ).subquery()

        query = self.db.query(Paper).filter(
            ~Paper.id.in_(already_screened)
        ).order_by(Paper.id)

        if max_candidates:
            query = query.limit(max_candidates)

        papers = query.limit(batch_size).all()

        if not papers:
            return {
                "status": "no_papers",
                "message": "No unscreened papers found.",
                "processed": 0,
            }

        results = {
            "status": "completed",
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "recommendations": {
                "likely_include": 0,
                "likely_exclude": 0,
                "unclear": 0,
            },
            "details": [],
        }

        for paper in papers:
            try:
                ai_result = self.screen_paper(paper.id, use_cache=True)
                results["processed"] += 1

                if ai_result.processing_status == "completed":
                    results["succeeded"] += 1
                    rec = ai_result.recommendation or "unclear"
                    results["recommendations"][rec] = results["recommendations"].get(rec, 0) + 1
                    results["details"].append({
                        "paper_id": paper.id,
                        "title": paper.title[:80] if paper.title else "",
                        "recommendation": rec,
                        "confidence": ai_result.confidence,
                    })
                else:
                    results["failed"] += 1
                    results["details"].append({
                        "paper_id": paper.id,
                        "title": paper.title[:80] if paper.title else "",
                        "recommendation": "failed",
                        "error": ai_result.error_message,
                    })

            except Exception as e:
                results["failed"] += 1
                results["details"].append({
                    "paper_id": paper.id,
                    "title": paper.title[:80] if paper.title else "",
                    "recommendation": "error",
                    "error": str(e),
                })

        return results

    def get_screening_summary(self) -> dict:
        """Get summary of AI screening progress."""
        total_papers = self.db.query(Paper).count()
        screened = self.db.query(AIScreeningResult.paper_id).filter(
            AIScreeningResult.is_active == True,
        ).distinct().count()

        by_recommendation = {}
        for rec in ["likely_include", "likely_exclude", "unclear"]:
            count = self.db.query(AIScreeningResult.paper_id).filter(
                and_(
                    AIScreeningResult.is_active == True,
                    AIScreeningResult.recommendation == rec,
                )
            ).distinct().count()
            by_recommendation[rec] = count

        by_confidence = {}
        for conf in ["high", "medium", "low"]:
            count = self.db.query(AIScreeningResult.paper_id).filter(
                and_(
                    AIScreeningResult.is_active == True,
                    AIScreeningResult.confidence == conf,
                )
            ).distinct().count()
            by_confidence[conf] = count

        return {
            "total_papers": total_papers,
            "ai_screened": screened,
            "remaining": total_papers - screened,
            "by_recommendation": by_recommendation,
            "by_confidence": by_confidence,
        }
