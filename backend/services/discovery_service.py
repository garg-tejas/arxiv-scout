from __future__ import annotations

import json
import logging

from integrations.arxiv import ArxivClient
from integrations.llm import LLMRouter
from integrations.semantic_scholar import SemanticScholarClient
from models.discovery import CurationBatchResult, SteeringPreferences
from models.enums import LLMRole
from models.papers import Author, CuratedPaper, MethodExtractionRow, PaperMetadata
from models.session import SearchInterpretation
from prompts.curation import CURATION_AGENT_SYSTEM_PROMPT, build_curation_user_prompt
from prompts.search import SEARCH_AGENT_SYSTEM_PROMPT, build_search_user_prompt
from prompts.steering import STEERING_AGENT_SYSTEM_PROMPT, build_steering_user_prompt

logger = logging.getLogger(__name__)


class DiscoveryService:
    def __init__(
        self,
        *,
        semantic_scholar_client: SemanticScholarClient,
        arxiv_client: ArxivClient,
        llm_router: LLMRouter,
        results_per_angle: int,
        shortlist_size: int,
    ) -> None:
        self.semantic_scholar_client = semantic_scholar_client
        self.arxiv_client = arxiv_client
        self.llm_router = llm_router
        self.results_per_angle = results_per_angle
        self.shortlist_size = shortlist_size

    async def interpret_topic(self, topic: str) -> SearchInterpretation:
        normalized_topic = " ".join(topic.split()).strip()
        interpretation = await self.llm_router.generate_structured(
            role=LLMRole.SEARCH,
            system_prompt=SEARCH_AGENT_SYSTEM_PROMPT,
            user_prompt=build_search_user_prompt(normalized_topic),
            schema_type=SearchInterpretation,
        )
        return self._finalize_interpretation(interpretation)

    @staticmethod
    def _finalize_interpretation(
        interpretation: SearchInterpretation,
    ) -> SearchInterpretation:
        normalized_topic = " ".join(
            (interpretation.normalized_topic or "").split()
        ).strip()
        seen: set[str] = set()
        search_angles: list[str] = []
        for angle in interpretation.search_angles:
            cleaned = " ".join(angle.split()).strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            search_angles.append(cleaned)

        if not normalized_topic or len(search_angles) < 3 or len(search_angles) > 4:
            raise ValueError(
                "LLM topic interpretation did not return 3-4 distinct search angles."
            )

        return SearchInterpretation(
            normalized_topic=normalized_topic,
            search_angles=search_angles,
        )

    async def merge_steering_preferences(
        self,
        *,
        current: SteeringPreferences,
        nudge_text: str,
    ) -> SteeringPreferences:
        normalized_nudge = " ".join(nudge_text.split()).strip()
        if not normalized_nudge:
            raise ValueError("Nudge text cannot be empty.")

        current_json = json.dumps(current.model_dump(mode="json"), indent=2)
        merged = await self.llm_router.generate_structured(
            role=LLMRole.STEERING,
            system_prompt=STEERING_AGENT_SYSTEM_PROMPT,
            user_prompt=build_steering_user_prompt(current_json, normalized_nudge),
            schema_type=SteeringPreferences,
        )
        return self._normalize_preferences(merged)

    async def fetch_candidates(
        self,
        *,
        interpretation: SearchInterpretation,
        steering_preferences: SteeringPreferences,
    ) -> list[PaperMetadata]:
        raw_candidates: list[dict] = []
        for angle in self._build_queries(interpretation, steering_preferences):
            raw_candidates.extend(
                await self.semantic_scholar_client.search(
                    angle, limit=self.results_per_angle
                )
            )
        return await self._enrich_and_filter(raw_candidates)

    async def curate_shortlist(
        self,
        *,
        topic: str,
        interpretation: SearchInterpretation,
        papers: list[PaperMetadata],
        steering_preferences: SteeringPreferences,
    ) -> tuple[list[CuratedPaper], list[MethodExtractionRow]]:
        return await self._curate(
            topic=topic,
            interpretation=interpretation,
            papers=papers,
            steering_preferences=steering_preferences,
        )

    async def _enrich_and_filter(
        self, raw_candidates: list[dict]
    ) -> list[PaperMetadata]:
        deduped: dict[str, PaperMetadata] = {}
        for candidate in raw_candidates:
            paper = await self._to_paper_metadata(candidate)
            if paper is None:
                continue
            key = paper.arxiv_id or paper.paper_id
            if key not in deduped:
                deduped[key] = paper
        return list(deduped.values())

    async def _to_paper_metadata(self, candidate: dict) -> PaperMetadata | None:
        arxiv_id = self._extract_arxiv_id(candidate)
        if arxiv_id is None:
            return None

        enriched: dict | None = None
        try:
            enriched = await self.arxiv_client.resolve_metadata(arxiv_id)
        except Exception as exc:
            logger.warning(
                "arXiv enrichment failed for %s; using Semantic Scholar metadata fallback: %s",
                arxiv_id,
                exc,
            )
        authors = candidate.get("authors") or []
        author_models = [
            Author(name=author.get("name", "Unknown")) for author in authors
        ]

        paper = PaperMetadata(
            paper_id=candidate.get("paperId") or arxiv_id,
            arxiv_id=arxiv_id,
            title=candidate.get("title") or "",
            abstract=candidate.get("abstract"),
            authors=author_models,
            year=candidate.get("year"),
            citation_count=candidate.get("citationCount"),
        )

        if enriched:
            paper.title = enriched.get("title") or paper.title
            paper.abstract = enriched.get("abstract") or paper.abstract
            if enriched.get("authors"):
                paper.authors = [
                    Author.model_validate(author) for author in enriched["authors"]
                ]
            paper.year = enriched.get("year") or paper.year
        return paper

    async def _curate(
        self,
        *,
        topic: str,
        interpretation: SearchInterpretation,
        papers: list[PaperMetadata],
        steering_preferences: SteeringPreferences,
    ) -> tuple[list[CuratedPaper], list[MethodExtractionRow]]:
        prompt_payload = {
            "topic": topic,
            "normalized_topic": interpretation.normalized_topic,
            "search_angles": interpretation.search_angles,
            "steering_preferences": steering_preferences.model_dump(mode="json"),
            "shortlist_size": self.shortlist_size,
            "candidate_papers": [
                {
                    "paper_id": paper.paper_id,
                    "title": paper.title,
                    "abstract": self._truncate(paper.abstract),
                    "year": paper.year,
                    "citation_count": paper.citation_count,
                    "authors": [author.name for author in paper.authors[:8]],
                }
                for paper in papers
            ],
        }
        batch = await self.llm_router.generate_structured(
            role=LLMRole.CURATION,
            system_prompt=CURATION_AGENT_SYSTEM_PROMPT,
            user_prompt=build_curation_user_prompt(
                json.dumps(prompt_payload, indent=2)
            ),
            schema_type=CurationBatchResult,
        )
        return self._finalize_curated_shortlist(
            papers=papers,
            batch=batch,
        )

    @staticmethod
    def _normalize_preferences(preferences: SteeringPreferences) -> SteeringPreferences:
        def normalize_values(values: list[str]) -> list[str]:
            seen: set[str] = set()
            normalized_values: list[str] = []
            for value in values:
                cleaned = " ".join(value.split()).strip().lower()
                if not cleaned or cleaned in seen:
                    continue
                seen.add(cleaned)
                normalized_values.append(cleaned)
            return normalized_values

        include = normalize_values(preferences.include)
        exclude = normalize_values(preferences.exclude)
        emphasize = normalize_values(preferences.emphasize)

        exclude_set = set(exclude)
        include = [value for value in include if value not in exclude_set]
        emphasize = [value for value in emphasize if value not in exclude_set]
        return SteeringPreferences(
            include=include,
            exclude=exclude,
            emphasize=emphasize,
        )

    def _finalize_curated_shortlist(
        self,
        *,
        papers: list[PaperMetadata],
        batch: CurationBatchResult,
    ) -> tuple[list[CuratedPaper], list[MethodExtractionRow]]:
        paper_map = {paper.paper_id: paper for paper in papers}
        curated: list[CuratedPaper] = []
        method_rows: list[MethodExtractionRow] = []
        seen: set[str] = set()

        for candidate in batch.shortlisted_papers:
            if candidate.paper_id in seen:
                continue
            paper = paper_map.get(candidate.paper_id)
            if paper is None:
                continue
            seen.add(candidate.paper_id)
            curated.append(
                CuratedPaper(
                    **paper.model_dump(),
                    score=round(candidate.score, 4),
                    rationale=candidate.rationale.strip(),
                )
            )
            method_rows.append(
                MethodExtractionRow(
                    paper_id=candidate.paper_id,
                    model_type=candidate.model_type,
                    dataset=candidate.dataset,
                    metrics=self._normalize_strings(candidate.metrics),
                    benchmarks=self._normalize_strings(candidate.benchmarks),
                )
            )

        curated.sort(
            key=lambda paper: (
                paper.score or 0.0,
                paper.citation_count or 0,
                paper.year or 0,
            ),
            reverse=True,
        )
        shortlisted_papers = curated[: self.shortlist_size]
        shortlisted_ids = {paper.paper_id for paper in shortlisted_papers}
        shortlisted_rows = [
            row for row in method_rows if row.paper_id in shortlisted_ids
        ]
        return shortlisted_papers, shortlisted_rows

    @staticmethod
    def _extract_arxiv_id(candidate: dict) -> str | None:
        external_ids = candidate.get("externalIds") or {}
        arxiv_id = external_ids.get("ArXiv") or external_ids.get("Arxiv")
        if arxiv_id:
            return arxiv_id.strip()

        url = candidate.get("url") or ""
        if "arxiv.org/" not in url:
            return None
        suffix = url.split("arxiv.org/", maxsplit=1)[1]
        if suffix.startswith("abs/") or suffix.startswith("pdf/"):
            paper_ref = suffix.split("/", maxsplit=1)[1]
            return paper_ref.split("?", maxsplit=1)[0].replace(".pdf", "")
        return None

    @staticmethod
    def _build_queries(
        interpretation: SearchInterpretation,
        preferences: SteeringPreferences,
    ) -> list[str]:
        queries: list[str] = []
        seen: set[str] = set()

        def add_query(value: str) -> None:
            normalized = " ".join(value.split()).strip()
            if not normalized:
                return
            key = normalized.lower()
            if key in seen:
                return
            seen.add(key)
            queries.append(normalized)

        for angle in interpretation.search_angles:
            add_query(angle)

        base_topic = interpretation.normalized_topic or ""
        for phrase in preferences.emphasize[:2]:
            add_query(f"{base_topic} {phrase}")
        for phrase in preferences.include[:2]:
            add_query(f"{base_topic} {phrase}")
        return queries

    @staticmethod
    def _truncate(text: str | None, limit: int = 900) -> str | None:
        if text is None:
            return None
        normalized = " ".join(text.split())
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit].rstrip() + "..."

    @staticmethod
    def _normalize_strings(values: list[str]) -> list[str]:
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
        return normalized_values
