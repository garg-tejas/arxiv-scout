from __future__ import annotations

import re

from integrations.firecrawl import FirecrawlClient
from models.analysis import PaperAnalysis
from models.enums import AnalysisQuality
from models.papers import CuratedPaper

SECTION_HINTS = ("abstract", "introduction", "method", "approach", "results", "conclusion")
METRIC_PATTERNS = {
    "accuracy": r"\baccuracy\b",
    "f1": r"\bf1(?:-score)?\b",
    "precision": r"\bprecision\b",
    "recall": r"\brecall\b",
    "auroc": r"\bauroc\b|\broc-auc\b",
    "bleu": r"\bbleu\b",
    "rouge": r"\brouge\b",
    "mse": r"\bmse\b|\bmean squared error\b",
    "mae": r"\bmae\b|\bmean absolute error\b",
    "perplexity": r"\bperplexity\b",
}


class AnalysisService:
    def __init__(self, *, firecrawl_client: FirecrawlClient) -> None:
        self.firecrawl_client = firecrawl_client

    async def analyze_paper(self, paper: CuratedPaper) -> PaperAnalysis:
        full_text = None
        if paper.arxiv_id:
            full_text = await self._fetch_full_text(paper.arxiv_id)

        quality = self._classify_quality(full_text)
        source_text = full_text if quality == AnalysisQuality.FULL_TEXT else self._fallback_text(paper)

        return PaperAnalysis(
            paper_id=paper.paper_id,
            analysis_quality=quality,
            core_claim=self._extract_core_claim(source_text),
            methodology=self._extract_methodology(source_text),
            datasets=self._extract_named_entities(
                source_text,
                r"([A-Z][A-Za-z0-9+\-/]*(?:\s+[A-Z][A-Za-z0-9+\-/]*){0,3})\s+(?:dataset|datasets|corpus)",
            ),
            metrics=self._extract_metrics(source_text),
            benchmarks=self._extract_named_entities(
                source_text,
                r"([A-Z][A-Za-z0-9+\-/]*(?:\s+[A-Z][A-Za-z0-9+\-/]*){0,3})\s+(?:benchmark|benchmarks)",
            ),
            limitations=self._extract_limitations(source_text),
            explicit_citations=self._extract_citations(source_text),
        )

    async def _fetch_full_text(self, arxiv_id: str) -> str | None:
        arxiv_url = f"https://arxiv.org/html/{arxiv_id}"
        payload = await self.firecrawl_client.fetch_paper(arxiv_url)
        if not payload:
            return None

        markdown = payload.get("markdown") or payload.get("content") or payload.get("text")
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
    def _extract_core_claim(text: str) -> str | None:
        sentences = AnalysisService._split_sentences(text)
        for sentence in sentences:
            lowered = sentence.lower()
            if any(token in lowered for token in ("we propose", "we present", "this paper", "we introduce", "our method")):
                return sentence
        return sentences[0] if sentences else None

    @staticmethod
    def _extract_methodology(text: str) -> list[str]:
        keywords = ("method", "approach", "model", "architecture", "framework", "pipeline", "algorithm")
        selected: list[str] = []
        for sentence in AnalysisService._split_sentences(text):
            lowered = sentence.lower()
            if any(keyword in lowered for keyword in keywords):
                selected.append(sentence)
            if len(selected) == 3:
                break
        return selected

    @staticmethod
    def _extract_metrics(text: str) -> list[str]:
        lowered = text.lower()
        return [name for name, pattern in METRIC_PATTERNS.items() if re.search(pattern, lowered)]

    @staticmethod
    def _extract_limitations(text: str) -> list[str]:
        limitation_tokens = ("limitation", "however", "future work", "challenge", "restrict", "costly", "expensive")
        selected: list[str] = []
        for sentence in AnalysisService._split_sentences(text):
            lowered = sentence.lower()
            if any(token in lowered for token in limitation_tokens):
                selected.append(sentence)
            if len(selected) == 3:
                break
        return selected

    @staticmethod
    def _extract_citations(text: str) -> list[str]:
        citations = re.findall(r"\[(\d{1,3})\]", text)
        seen: list[str] = []
        for citation in citations:
            if citation not in seen:
                seen.append(citation)
        return seen[:20]

    @staticmethod
    def _extract_named_entities(text: str, pattern: str) -> list[str]:
        matches: list[str] = []
        for match in re.finditer(pattern, text):
            value = " ".join(match.group(1).split())
            if value not in matches:
                matches.append(value)
        return matches

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        normalized = " ".join(text.split())
        if not normalized:
            return []
        sentences = re.split(r"(?<=[.!?])\s+", normalized)
        return [sentence.strip() for sentence in sentences if sentence.strip()]
