from __future__ import annotations

import json

from integrations.firecrawl import FirecrawlClient
from integrations.llm import LLMRouter
from models.analysis import PaperAnalysis
from models.enums import AnalysisQuality, LLMRole
from models.papers import CuratedPaper
from prompts.analysis import (
    PAPER_ANALYZER_SYSTEM_PROMPT,
    build_paper_analyzer_user_prompt,
)

SECTION_HINTS = (
    "abstract",
    "introduction",
    "method",
    "approach",
    "results",
    "conclusion",
)


class AnalysisService:
    def __init__(
        self,
        *,
        firecrawl_client: FirecrawlClient,
        llm_router: LLMRouter,
    ) -> None:
        self.firecrawl_client = firecrawl_client
        self.llm_router = llm_router

    async def analyze_paper(self, paper: CuratedPaper) -> PaperAnalysis:
        full_text = None
        if paper.arxiv_id:
            full_text = await self._fetch_full_text(paper.arxiv_id)

        quality = self._classify_quality(full_text)
        source_text: str = (
            full_text
            if full_text and quality == AnalysisQuality.FULL_TEXT
            else self._fallback_text(paper)
        )
        truncated_text = self._truncate(source_text)

        paper_metadata_json = json.dumps(self._build_paper_metadata(paper), indent=2)
        analysis = await self.llm_router.generate_structured(
            role=LLMRole.PAPER_ANALYZER,
            system_prompt=PAPER_ANALYZER_SYSTEM_PROMPT,
            user_prompt=build_paper_analyzer_user_prompt(
                paper_metadata_json=paper_metadata_json,
                quality=quality.value,
                truncated_text=truncated_text,
            ),
            schema_type=PaperAnalysis,
        )
        analysis.paper_id = paper.paper_id
        analysis.analysis_quality = quality
        analysis.methodology = self._normalize_strings(analysis.methodology, limit=4)
        analysis.datasets = self._normalize_strings(analysis.datasets)
        analysis.metrics = self._normalize_strings(analysis.metrics)
        analysis.benchmarks = self._normalize_strings(analysis.benchmarks)
        analysis.limitations = self._normalize_strings(analysis.limitations, limit=4)
        analysis.explicit_citations = self._normalize_strings(
            analysis.explicit_citations, limit=20
        )
        if analysis.core_claim:
            analysis.core_claim = " ".join(analysis.core_claim.split()).strip()
        return analysis

    async def _fetch_full_text(self, arxiv_id: str) -> str | None:
        arxiv_url = f"https://arxiv.org/html/{arxiv_id}"
        payload = await self.firecrawl_client.fetch_paper(arxiv_url)
        if not payload:
            return None

        markdown = (
            payload.get("markdown") or payload.get("content") or payload.get("text")
        )
        if isinstance(markdown, str):
            return markdown.strip()
        return None

    @staticmethod
    def _classify_quality(full_text: str | None) -> AnalysisQuality:
        if not full_text:
            return AnalysisQuality.ABSTRACT_ONLY
        text = full_text.lower()
        heading_hits = sum(1 for hint in SECTION_HINTS if hint in text)
        if len(full_text) >= 1500 and heading_hits >= 3:
            return AnalysisQuality.FULL_TEXT
        return AnalysisQuality.ABSTRACT_ONLY

    @staticmethod
    def _fallback_text(paper: CuratedPaper) -> str:
        return " ".join(part for part in [paper.title, paper.abstract or ""] if part)

    @staticmethod
    def _build_paper_metadata(paper: CuratedPaper) -> dict[str, object]:
        return {
            "paper_id": paper.paper_id,
            "arxiv_id": paper.arxiv_id,
            "title": paper.title,
            "year": paper.year,
            "citation_count": paper.citation_count,
            "authors": [author.name for author in paper.authors],
        }

    @staticmethod
    def _truncate(text: str, limit: int = 18000) -> str:
        normalized = " ".join(text.split())
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit].rstrip() + "..."

    @staticmethod
    def _normalize_strings(values: list[str], *, limit: int | None = None) -> list[str]:
        seen: set[str] = set()
        normalized_values: list[str] = []
        for value in values:
            cleaned = " ".join(value.split()).strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized_values.append(cleaned)
            if limit is not None and len(normalized_values) >= limit:
                break
        return normalized_values
