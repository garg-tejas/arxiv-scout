from __future__ import annotations

import re
from collections import OrderedDict

from integrations.arxiv import ArxivClient
from integrations.semantic_scholar import SemanticScholarClient
from models.discovery import SteeringPreferences
from models.papers import Author, CuratedPaper, MethodExtractionRow, PaperMetadata
from models.session import SearchInterpretation

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "using",
    "into",
    "over",
    "under",
    "based",
    "through",
    "study",
    "paper",
    "method",
    "methods",
}

METRIC_PATTERNS = OrderedDict(
    [
        ("accuracy", r"\baccuracy\b"),
        ("f1", r"\bf1(?:-score)?\b"),
        ("precision", r"\bprecision\b"),
        ("recall", r"\brecall\b"),
        ("auroc", r"\bauroc\b|\baoc\b|\broc-auc\b"),
        ("bleu", r"\bbleu\b"),
        ("rouge", r"\brouge\b"),
        ("mse", r"\bmse\b|\bmean squared error\b"),
        ("mae", r"\bmae\b|\bmean absolute error\b"),
        ("perplexity", r"\bperplexity\b"),
    ]
)

MODEL_KEYWORDS = OrderedDict(
    [
        ("graph neural network", [r"\bgraph neural network\b", r"\bgnn\b", r"\bgcn\b", r"\bgat\b"]),
        ("transformer", [r"\btransformer\b", r"\bself-attention\b"]),
        ("diffusion model", [r"\bdiffusion\b"]),
        ("large language model", [r"\bllm\b", r"\blarge language model\b"]),
        ("convolutional network", [r"\bcnn\b", r"\bconvolutional\b"]),
        ("recurrent network", [r"\brnn\b", r"\blstm\b", r"\bgru\b"]),
        ("retrieval model", [r"\bretriev(?:al|er)\b"]),
    ]
)


class DiscoveryService:
    def __init__(
        self,
        *,
        semantic_scholar_client: SemanticScholarClient,
        arxiv_client: ArxivClient,
        results_per_angle: int,
        shortlist_size: int,
    ) -> None:
        self.semantic_scholar_client = semantic_scholar_client
        self.arxiv_client = arxiv_client
        self.results_per_angle = results_per_angle
        self.shortlist_size = shortlist_size

    async def build_shortlist(
        self,
        *,
        topic: str,
        interpretation: SearchInterpretation,
        steering_preferences: SteeringPreferences | None = None,
    ) -> tuple[list[CuratedPaper], list[MethodExtractionRow]]:
        preferences = steering_preferences or SteeringPreferences()
        raw_candidates: list[dict] = []
        for angle in self._build_queries(interpretation, preferences):
            raw_candidates.extend(
                await self.semantic_scholar_client.search(angle, limit=self.results_per_angle)
            )

        enriched_candidates = await self._enrich_and_filter(raw_candidates)
        curated = self._curate(
            topic=topic,
            papers=enriched_candidates,
            steering_preferences=preferences,
        )
        shortlist = curated[: self.shortlist_size]
        method_table = [self._extract_method_row(paper) for paper in shortlist]
        return shortlist, method_table

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

    def _curate(
        self,
        *,
        topic: str,
        papers: list[PaperMetadata],
        steering_preferences: SteeringPreferences,
    ) -> list[CuratedPaper]:
        curated: list[CuratedPaper] = []
        topic_terms = set(self._tokenize(topic))
        for paper in papers:
            combined_text = f"{paper.title} {paper.abstract or ''}"
            title_terms = set(self._tokenize(paper.title))
            abstract_terms = set(self._tokenize(paper.abstract or ""))
            title_overlap = topic_terms & title_terms
            abstract_overlap = topic_terms & abstract_terms
            include_matches = self._count_phrase_matches(
                combined_text,
                steering_preferences.include,
            )
            emphasize_matches = self._count_phrase_matches(
                combined_text,
                steering_preferences.emphasize,
            )
            exclude_matches = self._count_phrase_matches(
                combined_text,
                steering_preferences.exclude,
            )

            score = (
                0.7 * (len(title_overlap) / max(1, len(topic_terms)))
                + 0.3 * (len(abstract_overlap) / max(1, len(topic_terms)))
            )
            score += 0.08 * include_matches
            score += 0.12 * emphasize_matches
            score -= 0.35 * exclude_matches
            if paper.citation_count:
                score += min(paper.citation_count / 1000, 0.1)

            if exclude_matches > 0 and include_matches == 0 and emphasize_matches == 0:
                continue

            rationale = self._build_rationale(
                title_overlap=title_overlap,
                abstract_overlap=abstract_overlap,
                steering_preferences=steering_preferences,
                include_matches=include_matches,
                emphasize_matches=emphasize_matches,
            )
            curated.append(
                CuratedPaper(
                    **paper.model_dump(),
                    score=round(score, 4),
                    rationale=rationale,
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
        return curated

    def _build_rationale(
        self,
        *,
        title_overlap: set[str],
        abstract_overlap: set[str],
        steering_preferences: SteeringPreferences,
        include_matches: int,
        emphasize_matches: int,
    ) -> str:
        matched_terms = sorted(title_overlap | abstract_overlap)
        steering_notes: list[str] = []
        if include_matches:
            steering_notes.append("matches include preferences")
        if emphasize_matches:
            steering_notes.append("aligns with emphasized terms")

        if matched_terms:
            preview = ", ".join(matched_terms[:3])
            base = f"Matches key topic terms in the title/abstract: {preview}."
            if steering_notes:
                return f"{base} It also {' and '.join(steering_notes)}."
            return base
        if title_overlap:
            return "Matches the interpreted topic strongly in the title."
        if steering_notes:
            return f"Retained because it {' and '.join(steering_notes)}."
        return "Retrieved from the interpreted search angles and retained after arXiv filtering."

    def _extract_method_row(self, paper: CuratedPaper) -> MethodExtractionRow:
        text = f"{paper.title} {paper.abstract or ''}"
        lower_text = text.lower()

        model_type = None
        for label, patterns in MODEL_KEYWORDS.items():
            if any(re.search(pattern, lower_text) for pattern in patterns):
                model_type = label
                break

        metrics = [name for name, pattern in METRIC_PATTERNS.items() if re.search(pattern, lower_text)]
        datasets = self._extract_named_entities(
            text,
            r"([A-Z][A-Za-z0-9+\-/]*(?:\s+[A-Z][A-Za-z0-9+\-/]*){0,3})\s+(?:dataset|datasets|corpus)",
        )
        benchmarks = self._extract_named_entities(
            text,
            r"([A-Z][A-Za-z0-9+\-/]*(?:\s+[A-Z][A-Za-z0-9+\-/]*){0,3})\s+(?:benchmark|benchmarks)",
        )

        dataset = datasets[0] if datasets else None
        return MethodExtractionRow(
            paper_id=paper.paper_id,
            model_type=model_type,
            dataset=dataset,
            metrics=metrics,
            benchmarks=benchmarks,
        )

    @staticmethod
    def _extract_named_entities(text: str, pattern: str) -> list[str]:
        seen: list[str] = []
        for match in re.finditer(pattern, text):
            value = " ".join(match.group(1).split())
            if value not in seen:
                seen.append(value)
        return seen

    @staticmethod
    def _extract_arxiv_id(candidate: dict) -> str | None:
        external_ids = candidate.get("externalIds") or {}
        arxiv_id = external_ids.get("ArXiv") or external_ids.get("Arxiv")
        if arxiv_id:
            return arxiv_id.strip()

        url = candidate.get("url") or ""
        match = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", url)
        if match:
            return match.group(1).replace(".pdf", "")
        return None

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        return [token for token in tokens if len(token) > 2 and token not in STOPWORDS]

    @staticmethod
    def _count_phrase_matches(text: str, phrases: list[str]) -> int:
        lower_text = text.lower()
        return sum(1 for phrase in phrases if phrase and phrase.lower() in lower_text)

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
            if key not in seen:
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
