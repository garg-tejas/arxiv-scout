from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from integrations.semantic_scholar import SemanticScholarClient
from models.analysis import PaperAnalysis
from models.citation import CitationEdge, CitationGraph, CitationNode, LineagePath
from models.enums import CitationEdgeType, EvidenceLevel, GraphNodeRole
from models.papers import CuratedPaper


@dataclass(slots=True)
class ContextCandidate:
    paper_id: str
    title: str
    year: int | None = None
    citation_count: int = 0
    referenced_by: set[str] = field(default_factory=set)
    cites: set[str] = field(default_factory=set)
    bridge_seeds: set[str] = field(default_factory=set)
    high_signal_seeds: set[str] = field(default_factory=set)


class CitationGraphService:
    def __init__(self, *, semantic_scholar_client: SemanticScholarClient) -> None:
        self.semantic_scholar_client = semantic_scholar_client

    async def build_graph(
        self,
        *,
        seed_papers: list[CuratedPaper],
        analyses: list[PaperAnalysis],
    ) -> CitationGraph:
        seed_map = {paper.paper_id: paper for paper in seed_papers}
        analysis_map = {analysis.paper_id: analysis for analysis in analyses}

        contexts_by_seed: dict[str, dict] = {}
        for paper in seed_papers:
            contexts_by_seed[paper.paper_id] = await self.semantic_scholar_client.get_paper_context(
                paper.paper_id
            )

        context_candidates: dict[str, ContextCandidate] = {}
        cite_edges: dict[tuple[str, str, CitationEdgeType], CitationEdge] = {}
        extends_edges: dict[tuple[str, str, CitationEdgeType], CitationEdge] = {}

        high_signal_context_ids = self._collect_high_signal_context_ids(contexts_by_seed)

        for seed_id, payload in contexts_by_seed.items():
            references = payload.get("references") or []
            citations = payload.get("citations") or []

            for reference in references:
                ref_id = reference.get("paperId")
                if not ref_id:
                    continue
                if ref_id in seed_map:
                    self._add_edge(
                        cite_edges,
                        source=seed_id,
                        target=ref_id,
                        relation=CitationEdgeType.CITES,
                        evidence_level=EvidenceLevel.DIRECT,
                    )
                    if self._is_direct_extension(
                        seed_map[seed_id],
                        seed_map[ref_id],
                        analysis_map.get(seed_id),
                        analysis_map.get(ref_id),
                    ):
                        self._add_edge(
                            extends_edges,
                            source=seed_id,
                            target=ref_id,
                            relation=CitationEdgeType.EXTENDS,
                            evidence_level=EvidenceLevel.DIRECT,
                        )
                    continue

                candidate = self._get_or_create_context(context_candidates, reference)
                candidate.referenced_by.add(seed_id)
                if ref_id in high_signal_context_ids:
                    candidate.high_signal_seeds.add(seed_id)

            for citation in citations:
                cit_id = citation.get("paperId")
                if not cit_id:
                    continue
                if cit_id in seed_map:
                    self._add_edge(
                        cite_edges,
                        source=seed_id,
                        target=cit_id,
                        relation=CitationEdgeType.CITED_BY,
                        evidence_level=EvidenceLevel.DIRECT,
                    )
                    continue

                candidate = self._get_or_create_context(context_candidates, citation)
                candidate.cites.add(seed_id)
                if cit_id in high_signal_context_ids:
                    candidate.high_signal_seeds.add(seed_id)

        retained_context_ids = self._retain_context_nodes(context_candidates)
        retained_contexts = {
            context_id: context_candidates[context_id]
            for context_id in retained_context_ids
        }

        context_nodes = [
            CitationNode(
                node_id=context.paper_id,
                title=context.title,
                role=GraphNodeRole.CONTEXT,
                paper_id=context.paper_id,
            )
            for context in retained_contexts.values()
        ]
        seed_nodes = [
            CitationNode(
                node_id=paper.paper_id,
                title=paper.title,
                role=GraphNodeRole.SEED,
                paper_id=paper.paper_id,
            )
            for paper in seed_papers
        ]

        for context in retained_contexts.values():
            for seed_id in context.referenced_by:
                self._add_edge(
                    cite_edges,
                    source=seed_id,
                    target=context.paper_id,
                    relation=CitationEdgeType.CITES,
                    evidence_level=EvidenceLevel.DIRECT,
                )
            for seed_id in context.cites:
                self._add_edge(
                    cite_edges,
                    source=seed_id,
                    target=context.paper_id,
                    relation=CitationEdgeType.CITED_BY,
                    evidence_level=EvidenceLevel.DIRECT,
                )

        lineage_paths: list[LineagePath] = []
        shared_foundation_edges = self._build_shared_foundation_edges(
            retained_contexts=retained_contexts,
            cite_edges=cite_edges,
            lineage_paths=lineage_paths,
        )
        inferred_extension_edges = self._build_inferred_extensions(
            retained_contexts=retained_contexts,
            analysis_map=analysis_map,
            seed_map=seed_map,
            lineage_paths=lineage_paths,
        )

        all_edges = [
            *cite_edges.values(),
            *shared_foundation_edges.values(),
            *extends_edges.values(),
            *inferred_extension_edges.values(),
        ]
        narrative_summary = self._build_narrative_summary(
            direct_extensions=list(extends_edges.values()),
            inferred_extensions=list(inferred_extension_edges.values()),
            lineage_paths=lineage_paths,
            seed_map=seed_map,
            retained_contexts=retained_contexts,
        )

        return CitationGraph(
            seed_nodes=seed_nodes,
            context_nodes=context_nodes,
            edges=all_edges,
            lineage_paths=lineage_paths,
            narrative_summary=narrative_summary,
        )

    @staticmethod
    def _get_or_create_context(
        context_candidates: dict[str, ContextCandidate],
        paper_data: dict,
    ) -> ContextCandidate:
        paper_id = paper_data["paperId"]
        if paper_id not in context_candidates:
            context_candidates[paper_id] = ContextCandidate(
                paper_id=paper_id,
                title=paper_data.get("title") or paper_id,
                year=paper_data.get("year"),
                citation_count=paper_data.get("citationCount") or 0,
            )
        return context_candidates[paper_id]

    @staticmethod
    def _add_edge(
        edge_store: dict[tuple[str, str, CitationEdgeType], CitationEdge],
        *,
        source: str,
        target: str,
        relation: CitationEdgeType,
        evidence_level: EvidenceLevel,
    ) -> None:
        key = (source, target, relation)
        if key not in edge_store:
            edge_store[key] = CitationEdge(
                edge_id=f"{relation.value}:{source}:{target}",
                source=source,
                target=target,
                relation=relation,
                evidence_level=evidence_level,
            )

    @staticmethod
    def _collect_high_signal_context_ids(contexts_by_seed: dict[str, dict]) -> set[str]:
        high_signal_ids: set[str] = set()
        for payload in contexts_by_seed.values():
            related = []
            for item in (payload.get("references") or []) + (payload.get("citations") or []):
                if item.get("paperId"):
                    related.append(item)
            related.sort(key=lambda item: item.get("citationCount") or 0, reverse=True)
            for item in related[:2]:
                if (item.get("citationCount") or 0) >= 25:
                    high_signal_ids.add(item["paperId"])
        return high_signal_ids

    @staticmethod
    def _retain_context_nodes(context_candidates: dict[str, ContextCandidate]) -> set[str]:
        retained: set[str] = set()
        for context_id, candidate in context_candidates.items():
            connected_seeds = candidate.referenced_by | candidate.cites
            has_bridge = bool(candidate.referenced_by and candidate.cites and len(connected_seeds) >= 2)
            shared_across_seeds = len(connected_seeds) >= 2
            high_signal = bool(candidate.high_signal_seeds) and candidate.citation_count >= 25
            if shared_across_seeds or has_bridge or high_signal:
                retained.add(context_id)
        return retained

    def _build_shared_foundation_edges(
        self,
        *,
        retained_contexts: dict[str, ContextCandidate],
        cite_edges: dict[tuple[str, str, CitationEdgeType], CitationEdge],
        lineage_paths: list[LineagePath],
    ) -> dict[tuple[str, str, CitationEdgeType], CitationEdge]:
        shared_edges: dict[tuple[str, str, CitationEdgeType], CitationEdge] = {}
        context_to_seed_refs: dict[str, list[str]] = defaultdict(list)
        for context in retained_contexts.values():
            for seed_id in sorted(context.referenced_by):
                context_to_seed_refs[context.paper_id].append(seed_id)

        for context_id, seeds in context_to_seed_refs.items():
            if len(seeds) < 2:
                continue
            for index, source in enumerate(seeds):
                for target in seeds[index + 1 :]:
                    self._add_edge(
                        shared_edges,
                        source=source,
                        target=target,
                        relation=CitationEdgeType.SHARED_FOUNDATION,
                        evidence_level=EvidenceLevel.INFERRED,
                    )
                    edge_id_a = f"{CitationEdgeType.CITES.value}:{source}:{context_id}"
                    edge_id_b = f"{CitationEdgeType.CITES.value}:{target}:{context_id}"
                    lineage_paths.append(
                        LineagePath(
                            node_ids=[source, context_id, target],
                            edge_ids=[edge_id_a, edge_id_b],
                            evidence_level=EvidenceLevel.INFERRED,
                            summary=f"{source} and {target} share foundational context in {context_id}.",
                        )
                    )
        return shared_edges

    def _build_inferred_extensions(
        self,
        *,
        retained_contexts: dict[str, ContextCandidate],
        analysis_map: dict[str, PaperAnalysis],
        seed_map: dict[str, CuratedPaper],
        lineage_paths: list[LineagePath],
    ) -> dict[tuple[str, str, CitationEdgeType], CitationEdge]:
        inferred_edges: dict[tuple[str, str, CitationEdgeType], CitationEdge] = {}
        for context in retained_contexts.values():
            if not context.referenced_by or not context.cites:
                continue
            for source in sorted(context.cites):
                for target in sorted(context.referenced_by):
                    if source == target:
                        continue
                    if not self._has_method_overlap(
                        analysis_map.get(source),
                        analysis_map.get(target),
                    ):
                        continue
                    self._add_edge(
                        inferred_edges,
                        source=source,
                        target=target,
                        relation=CitationEdgeType.EXTENDS,
                        evidence_level=EvidenceLevel.INFERRED,
                    )
                    lineage_paths.append(
                        LineagePath(
                            node_ids=[source, context.paper_id, target],
                            edge_ids=[
                                f"{CitationEdgeType.CITED_BY.value}:{source}:{context.paper_id}",
                                f"{CitationEdgeType.CITES.value}:{target}:{context.paper_id}",
                            ],
                            evidence_level=EvidenceLevel.INFERRED,
                            summary=(
                                f"{seed_map[source].title} appears to extend ideas connected through "
                                f"{context.title} toward {seed_map[target].title}."
                            ),
                        )
                    )
        return inferred_edges

    @staticmethod
    def _is_direct_extension(
        source_paper: CuratedPaper,
        target_paper: CuratedPaper,
        source_analysis: PaperAnalysis | None,
        target_analysis: PaperAnalysis | None,
    ) -> bool:
        if source_paper.year and target_paper.year and source_paper.year < target_paper.year:
            return False
        return CitationGraphService._has_method_overlap(source_analysis, target_analysis)

    @staticmethod
    def _has_method_overlap(
        source_analysis: PaperAnalysis | None,
        target_analysis: PaperAnalysis | None,
    ) -> bool:
        if source_analysis is None or target_analysis is None:
            return False

        source_signals = {
            *[item.lower() for item in source_analysis.datasets],
            *[item.lower() for item in source_analysis.metrics],
            *CitationGraphService._tokenize_analysis(source_analysis.methodology),
        }
        target_signals = {
            *[item.lower() for item in target_analysis.datasets],
            *[item.lower() for item in target_analysis.metrics],
            *CitationGraphService._tokenize_analysis(target_analysis.methodology),
        }
        return len(source_signals & target_signals) > 0

    @staticmethod
    def _tokenize_analysis(methodology: list[str]) -> set[str]:
        tokens: set[str] = set()
        for sentence in methodology:
            for token in sentence.lower().split():
                cleaned = token.strip(".,:;()[]{}")
                if len(cleaned) > 3:
                    tokens.add(cleaned)
        return tokens

    @staticmethod
    def _build_narrative_summary(
        *,
        direct_extensions: list[CitationEdge],
        inferred_extensions: list[CitationEdge],
        lineage_paths: list[LineagePath],
        seed_map: dict[str, CuratedPaper],
        retained_contexts: dict[str, ContextCandidate],
    ) -> str:
        summary_parts: list[str] = []
        if direct_extensions:
            direct_sentences = []
            for edge in direct_extensions[:3]:
                direct_sentences.append(
                    f"{seed_map[edge.source].title} directly builds on {seed_map[edge.target].title}."
                )
            summary_parts.append("Direct lineage: " + " ".join(direct_sentences))

        inferred_sentences = []
        for edge in inferred_extensions[:3]:
            inferred_sentences.append(
                f"{seed_map[edge.source].title} shows inferred method continuity with {seed_map[edge.target].title}."
            )
        if inferred_sentences:
            summary_parts.append("Inferred lineage: " + " ".join(inferred_sentences))

        if retained_contexts:
            shared_context_titles = ", ".join(
                context.title for context in list(retained_contexts.values())[:3]
            )
            summary_parts.append(
                f"Retained one-hop context nodes include {shared_context_titles}, which connect multiple approved papers."
            )

        if not summary_parts and lineage_paths:
            summary_parts.append(lineage_paths[0].summary)
        if not summary_parts:
            return "No strong citation lineage was identified among the selected papers."
        return " ".join(summary_parts)
