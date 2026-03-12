from __future__ import annotations

import json

from integrations.arxiv import ArxivClient
from integrations.llm import LLMRouter
from integrations.semantic_scholar import SemanticScholarClient
from models.discovery import CurationBatchResult, SteeringPreferences
from models.enums import LLMRole
from models.papers import Author, CuratedPaper, MethodExtractionRow, PaperMetadata
from models.session import SearchInterpretation


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
            system_prompt=(
                "You are the Search Agent for an arXiv literature scout. "
                "Interpret the user's research topic into a normalized topic string and 3 to 4 semantically distinct "
                "search angles. Return JSON only. Keep search angles concise, diverse, and arXiv-paper oriented."
            ),
            user_prompt=(
                f"User topic:\n{normalized_topic}\n\n"
                "Requirements:\n"
                "- normalized_topic should be a cleaned-up restatement of the topic\n"
                "- search_angles must contain 3 or 4 distinct strings\n"
                "- angles should emphasize different retrieval views such as method family, benchmark/evaluation, "
                "application area, or limitations/tradeoffs\n"
                "- do not include numbering or commentary"
            ),
            schema_type=SearchInterpretation,
        )
        return self._finalize_interpretation(interpretation)

    @staticmethod
    def _finalize_interpretation(interpretation: SearchInterpretation) -> SearchInterpretation:
        normalized_topic = " ".join((interpretation.normalized_topic or "").split()).strip()
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
            raise ValueError("LLM topic interpretation did not return 3-4 distinct search angles.")

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

        merged = await self.llm_router.generate_structured(
            role=LLMRole.STEERING,
            system_prompt=(
                "You are the Steering Agent for an arXiv literature scout. "
                "Update the user's discovery preferences using the latest nudge and the existing preference state. "
                "Return JSON only."
            ),
            user_prompt=(
                "Current steering preferences:\n"
                f"{json.dumps(current.model_dump(mode='json'), indent=2)}\n\n"
                "Latest user nudge:\n"
                f"{normalized_nudge}\n\n"
                "Rules:\n"
                "- return the full merged preference state\n"
                "- include contains positive hard constraints or things to include\n"
                "- exclude contains things to avoid or skip\n"
                "- emphasize contains soft-focus or prioritization signals\n"
                "- keep entries as short normalized phrases\n"
                "- deduplicate entries\n"
                "- if the latest nudge makes a phrase clearly negative, keep it only in exclude\n"
                "- if the latest nudge makes a phrase clearly positive, keep it only in include or emphasize"
            ),
            schema_type=SteeringPreferences,
        )
        return self._normalize_preferences(merged)

    async def build_shortlist(
        self,
        *,
        topic: str,
        interpretation: SearchInterpretation,
        steering_preferences: SteeringPreferences | None = None,
    ) -> tuple[list[CuratedPaper], list[MethodExtractionRow]]:
        preferences = steering_preferences or SteeringPreferences()
        enriched_candidates = await self.fetch_candidates(
            interpretation=interpretation,
            steering_preferences=preferences,
        )
        if not enriched_candidates:
            return [], []

        curated, method_table = await self.curate_shortlist(
            topic=topic,
            interpretation=interpretation,
            papers=enriched_candidates,
            steering_preferences=preferences,
        )
        shortlist = curated[: self.shortlist_size]
        row_by_id = {row.paper_id: row for row in method_table}
        ordered_rows = [row_by_id[paper.paper_id] for paper in shortlist if paper.paper_id in row_by_id]
        return shortlist, ordered_rows

    async def fetch_candidates(
        self,
        *,
        interpretation: SearchInterpretation,
        steering_preferences: SteeringPreferences,
    ) -> list[PaperMetadata]:
        raw_candidates: list[dict] = []
        for angle in self._build_queries(interpretation, steering_preferences):
            raw_candidates.extend(
                await self.semantic_scholar_client.search(angle, limit=self.results_per_angle)
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

    async def _enrich_and_filter(self, raw_candidates: list[dict]) -> list[PaperMetadata]:
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

        enriched = await self.arxiv_client.resolve_metadata(arxiv_id)
        authors = candidate.get("authors") or []
        author_models = [Author(name=author.get("name", "Unknown")) for author in authors]

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
                paper.authors = [Author.model_validate(author) for author in enriched["authors"]]
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
            system_prompt=(
                "You are the Curation Agent for an arXiv literature scout. "
                "Given a topic, steering preferences, and a batch of arXiv paper candidates, "
                "return the most relevant shortlist in one batch. Return JSON only."
            ),
            user_prompt=(
                f"{json.dumps(prompt_payload, indent=2)}\n\n"
                "Rules:\n"
                "- select at most shortlist_size papers\n"
                "- use only the provided paper_id values\n"
                "- exclude obvious mismatches\n"
                "- assign score between 0.0 and 1.0\n"
                "- rationale should be one concise sentence\n"
                "- infer model_type, dataset, metrics, and benchmarks from title/abstract only\n"
                "- prioritize relevance to the original topic and steering preferences over raw citation count\n"
                "- treat this as one batched shortlist decision, not independent per-paper reviews"
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
        shortlisted_rows = [row for row in method_rows if row.paper_id in shortlisted_ids]
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
