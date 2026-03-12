from __future__ import annotations

import json
import re

from integrations.llm import LLMRouter
from models.analysis import MethodComparisonRow, PaperAnalysis
from models.citation import CitationGraph
from models.enums import CitationEdgeType, LLMRole
from models.papers import CuratedPaper
from models.session import SessionSnapshot
from models.survey import (
    SectionReviewResult,
    SurveyAssemblyDraft,
    SurveyBrief,
    SurveyDocument,
    SurveySection,
    SurveySectionDraft,
    ThemeCluster,
    ThemeClusterBatch,
)


class SurveyService:
    def __init__(self, *, llm_router: LLMRouter) -> None:
        self.llm_router = llm_router

    async def synthesize_brief(self, snapshot: SessionSnapshot) -> SurveyBrief:
        payload = {
            "topic": snapshot.topic,
            "steering_preferences": snapshot.steering_preferences.model_dump(mode="json"),
            "analysis_summary": snapshot.analysis_summary.model_dump(mode="json"),
            "method_comparison_table": [
                {
                    "paper_id": row.paper_id,
                    "title": row.title,
                    "model_type": row.model_type,
                    "datasets": row.datasets,
                    "metrics": row.metrics,
                    "primary_limitation": row.primary_limitation,
                }
                for row in snapshot.method_comparison_table
            ][:8],
            "citation_graph_summary": snapshot.citation_graph.narrative_summary if snapshot.citation_graph else None,
        }
        brief = await self.llm_router.generate_structured(
            role=LLMRole.SURVEY_ORCHESTRATOR,
            system_prompt=(
                "You are the Survey Orchestrator Agent for an arXiv literature scout. "
                "Synthesize a concise survey brief from the session context. Return JSON only."
            ),
            user_prompt=(
                f"{json.dumps(payload, indent=2)}\n\n"
                "Rules:\n"
                "- angle should state the survey angle clearly\n"
                "- audience should be a short target-reader description\n"
                "- emphasis should contain 1 to 4 short focus points\n"
                "- comparisons should contain 1 to 4 specific comparisons or lineages to emphasize\n"
                "- keep fields concise and grounded in the provided context"
            ),
            schema_type=SurveyBrief,
        )
        return self._normalize_brief(brief, fallback_topic=snapshot.topic or "approved arXiv paper set")

    async def cluster_themes(
        self,
        *,
        brief: SurveyBrief,
        papers: list[CuratedPaper],
        analyses: list[PaperAnalysis],
        comparison_rows: list[MethodComparisonRow],
        citation_graph: CitationGraph | None,
    ) -> list[ThemeCluster]:
        payload = {
            "brief": brief.model_dump(mode="json"),
            "papers": [
                {
                    "paper_id": paper.paper_id,
                    "title": paper.title,
                    "year": paper.year,
                }
                for paper in papers
            ],
            "analyses": [
                {
                    "paper_id": analysis.paper_id,
                    "core_claim": analysis.core_claim,
                    "datasets": analysis.datasets,
                    "metrics": analysis.metrics,
                    "methodology": analysis.methodology[:3],
                }
                for analysis in analyses
            ],
            "comparison_rows": [
                {
                    "paper_id": row.paper_id,
                    "model_type": row.model_type,
                    "datasets": row.datasets,
                    "metrics": row.metrics,
                }
                for row in comparison_rows
            ],
            "citation_edges": self._build_cluster_edge_payload(citation_graph),
        }
        batch = await self.llm_router.generate_structured(
            role=LLMRole.THEMATIC_CLUSTERING,
            system_prompt=(
                "You are the Thematic Clustering Agent for an arXiv literature scout. "
                "Group papers into coherent survey themes using the structured analysis and citation context. "
                "Return JSON only."
            ),
            user_prompt=(
                f"{json.dumps(payload, indent=2)}\n\n"
                "Rules:\n"
                "- assign every paper_id to exactly one cluster\n"
                "- return between 1 and 6 clusters\n"
                "- cluster_id must be stable, lowercase, and slug-like\n"
                "- title should be concise and presentation-ready\n"
                "- description should explain the common method or lineage in 1 to 2 sentences\n"
                "- prefer thematic coherence plus citation relationship, not just lexical similarity"
            ),
            schema_type=ThemeClusterBatch,
        )
        return self._normalize_clusters(batch.clusters, papers)

    async def draft_section(
        self,
        *,
        cluster: ThemeCluster,
        papers: list[CuratedPaper],
        analyses: list[PaperAnalysis],
        comparison_rows: list[MethodComparisonRow],
        brief: SurveyBrief,
        citation_graph: CitationGraph | None,
        revision_feedback: str | None = None,
        revision_count: int = 0,
    ) -> SurveySection:
        ordered_ids = self._ordered_cluster_ids(cluster.paper_ids, papers)
        payload = {
            "brief": brief.model_dump(mode="json"),
            "cluster": cluster.model_dump(mode="json"),
            "papers": self._build_cluster_paper_payload(ordered_ids, papers, analyses, comparison_rows),
            "cluster_lineage": self._build_lineage_lines(ordered_ids, citation_graph, {paper.paper_id: paper for paper in papers}),
            "revision_feedback": revision_feedback,
        }
        draft = await self.llm_router.generate_structured(
            role=LLMRole.SECTION_WRITER,
            system_prompt=(
                "You are the Section Writer Agent for an arXiv literature scout. "
                "Write one survey section from structured paper analyses only. Return JSON only."
            ),
            user_prompt=(
                f"{json.dumps(payload, indent=2)}\n\n"
                "Rules:\n"
                "- content_markdown must be valid markdown\n"
                "- include these headings in order: '## <title>', '### Theme Overview', '### Approach Comparison', "
                "'### Idea Progression', '### Open Problems'\n"
                "- compare approaches across papers rather than summarizing each in isolation\n"
                "- use the citation/lineage context when available\n"
                "- mention open problems grounded in the provided limitations and evaluation gaps\n"
                "- if revision_feedback is present, address it directly"
            ),
            schema_type=SurveySectionDraft,
            provider_override=None,
        )
        title = " ".join(draft.title.split()).strip() or cluster.title
        content_markdown = draft.content_markdown.strip()
        if not content_markdown.startswith("## "):
            content_markdown = f"## {title}\n\n{content_markdown}"
        return SurveySection(
            section_id=cluster.cluster_id,
            title=title,
            content_markdown=content_markdown,
            paper_ids=ordered_ids,
            revision_count=revision_count,
            accepted=False,
        )

    async def review_section(
        self,
        *,
        section: SurveySection,
        cluster: ThemeCluster,
        brief: SurveyBrief,
    ) -> SectionReviewResult:
        payload = {
            "brief": brief.model_dump(mode="json"),
            "cluster": cluster.model_dump(mode="json"),
            "section": {
                "title": section.title,
                "content_markdown": section.content_markdown,
                "paper_ids": section.paper_ids,
                "revision_count": section.revision_count,
            },
        }
        review = await self.llm_router.generate_structured(
            role=LLMRole.SECTION_REVIEWER,
            system_prompt=(
                "You are the Section Reviewer Agent for an arXiv literature scout. "
                "Review a drafted survey section against the survey brief and cluster intent. Return JSON only."
            ),
            user_prompt=(
                f"{json.dumps(payload, indent=2)}\n\n"
                "Rules:\n"
                "- verdict must be ACCEPT or REVISE\n"
                "- REVISE only when the section materially misses comparison depth, lineage clarity, or open problems\n"
                "- feedback should be one concise paragraph the writer can act on immediately\n"
                "- keep revision_count unchanged; it will be set by the caller"
            ),
            schema_type=SectionReviewResult,
        )
        review.revision_count = section.revision_count
        return review

    async def assemble_document(
        self,
        *,
        brief: SurveyBrief,
        sections: list[SurveySection],
        comparison_rows: list[MethodComparisonRow],
        papers: list[CuratedPaper],
        citation_graph: CitationGraph | None,
    ) -> SurveyDocument:
        payload = {
            "brief": brief.model_dump(mode="json"),
            "section_titles": [section.title for section in sections],
            "citation_graph_summary": citation_graph.narrative_summary if citation_graph else None,
            "comparison_rows": [
                {
                    "title": row.title,
                    "model_type": row.model_type,
                    "datasets": row.datasets,
                    "metrics": row.metrics,
                    "primary_limitation": row.primary_limitation,
                }
                for row in comparison_rows[:8]
            ],
        }
        draft = await self.llm_router.generate_structured(
            role=LLMRole.SURVEY_ASSEMBLER,
            system_prompt=(
                "You are the Survey Assembler Agent for an arXiv literature scout. "
                "Write the introduction and conclusion for a structured survey. Return JSON only."
            ),
            user_prompt=(
                f"{json.dumps(payload, indent=2)}\n\n"
                "Rules:\n"
                "- introduction should orient the reader to the survey angle and comparison priorities\n"
                "- conclusion should synthesize the main tradeoffs, progressions, and open directions\n"
                "- do not invent references or paper details beyond the provided context"
            ),
            schema_type=SurveyAssemblyDraft,
        )

        references = []
        for paper in papers:
            if paper.arxiv_id:
                references.append(f"- {paper.title} ([arXiv:{paper.arxiv_id}](https://arxiv.org/abs/{paper.arxiv_id}))")
            else:
                references.append(f"- {paper.title}")

        comparison_markdown = self._render_method_comparison_markdown(comparison_rows)
        markdown_parts = [
            "# ArXiv Literature Scout Survey",
            "",
            "## Introduction",
            (draft.introduction or "").strip(),
            "",
            *[section.content_markdown for section in sections],
            "",
            "## Method Comparison Table",
            comparison_markdown,
            "",
            "## Conclusion",
            (draft.conclusion or "").strip(),
            "",
            "## References",
            *references,
        ]
        markdown = "\n".join(part for part in markdown_parts if part is not None).strip()
        return SurveyDocument(
            introduction=(draft.introduction or "").strip() or None,
            sections=sections,
            conclusion=(draft.conclusion or "").strip() or None,
            references=references,
            markdown=markdown,
        )

    def render_markdown(self, document: SurveyDocument) -> str:
        return document.markdown

    @staticmethod
    def _normalize_brief(brief: SurveyBrief, *, fallback_topic: str) -> SurveyBrief:
        return SurveyBrief(
            angle=" ".join((brief.angle or fallback_topic).split()).strip(),
            audience=" ".join((brief.audience or "research readers").split()).strip(),
            emphasis=SurveyService._normalize_strings(brief.emphasis, limit=4),
            comparisons=SurveyService._normalize_strings(brief.comparisons, limit=4),
        )

    def _normalize_clusters(
        self,
        clusters: list[ThemeCluster],
        papers: list[CuratedPaper],
    ) -> list[ThemeCluster]:
        valid_ids = {paper.paper_id for paper in papers}
        assigned: set[str] = set()
        normalized: list[ThemeCluster] = []

        for index, cluster in enumerate(clusters, start=1):
            paper_ids = [paper_id for paper_id in cluster.paper_ids if paper_id in valid_ids and paper_id not in assigned]
            if not paper_ids:
                continue
            assigned.update(paper_ids)
            cluster_id = self._slugify(cluster.cluster_id or cluster.title or f"theme-{index}")
            normalized.append(
                ThemeCluster(
                    cluster_id=cluster_id,
                    title=" ".join(cluster.title.split()).strip() or f"Theme {index}",
                    description=" ".join(cluster.description.split()).strip(),
                    paper_ids=paper_ids,
                )
            )

        remaining = [paper.paper_id for paper in papers if paper.paper_id not in assigned]
        if remaining:
            normalized.append(
                ThemeCluster(
                    cluster_id=self._slugify("general-method-directions"),
                    title="General Method Directions",
                    description="This cluster groups papers that were not cleanly assigned to a more specific theme.",
                    paper_ids=remaining,
                )
            )

        return normalized or [
            ThemeCluster(
                cluster_id=self._slugify("general-method-directions"),
                title="General Method Directions",
                description="This cluster groups the approved papers into one general theme.",
                paper_ids=[paper.paper_id for paper in papers],
            )
        ]

    @staticmethod
    def _ordered_cluster_ids(cluster_ids: list[str], papers: list[CuratedPaper]) -> list[str]:
        paper_map = {paper.paper_id: paper for paper in papers}
        return sorted(
            cluster_ids,
            key=lambda paper_id: (
                paper_map.get(paper_id).year or 0 if paper_map.get(paper_id) else 0,
                paper_map.get(paper_id).title if paper_map.get(paper_id) else paper_id,
            ),
        )

    @staticmethod
    def _build_cluster_paper_payload(
        ordered_ids: list[str],
        papers: list[CuratedPaper],
        analyses: list[PaperAnalysis],
        comparison_rows: list[MethodComparisonRow],
    ) -> list[dict[str, object]]:
        paper_map = {paper.paper_id: paper for paper in papers}
        analysis_map = {analysis.paper_id: analysis for analysis in analyses}
        row_map = {row.paper_id: row for row in comparison_rows}
        payload: list[dict[str, object]] = []
        for paper_id in ordered_ids:
            paper = paper_map.get(paper_id)
            analysis = analysis_map.get(paper_id)
            row = row_map.get(paper_id)
            if paper is None or analysis is None:
                continue
            payload.append(
                {
                    "paper_id": paper_id,
                    "title": paper.title,
                    "year": paper.year,
                    "model_type": row.model_type if row else None,
                    "core_claim": analysis.core_claim,
                    "methodology": analysis.methodology,
                    "datasets": analysis.datasets,
                    "metrics": analysis.metrics,
                    "benchmarks": analysis.benchmarks,
                    "limitations": analysis.limitations,
                }
            )
        return payload

    @staticmethod
    def _build_cluster_edge_payload(citation_graph: CitationGraph | None) -> list[dict[str, str]]:
        if citation_graph is None:
            return []
        return [
            {
                "source": edge.source,
                "target": edge.target,
                "relation": edge.relation.value,
                "evidence_level": edge.evidence_level.value,
            }
            for edge in citation_graph.edges
        ]

    def _build_lineage_lines(
        self,
        paper_ids: list[str],
        citation_graph: CitationGraph | None,
        paper_map: dict[str, CuratedPaper],
    ) -> list[str]:
        if citation_graph is None:
            return ["No citation graph was available for this theme."]
        cluster_set = set(paper_ids)
        lines: list[str] = []
        for edge in citation_graph.edges:
            if edge.source not in cluster_set or edge.target not in cluster_set:
                continue
            if edge.relation not in {CitationEdgeType.EXTENDS, CitationEdgeType.CITES, CitationEdgeType.SHARED_FOUNDATION}:
                continue
            source_title = paper_map.get(edge.source).title if paper_map.get(edge.source) else edge.source
            target_title = paper_map.get(edge.target).title if paper_map.get(edge.target) else edge.target
            lines.append(
                f"{source_title} {edge.relation.value.replace('_', ' ')} {target_title} ({edge.evidence_level.value} evidence)."
            )
        if not lines:
            return ["No strong within-cluster lineage was identified; the papers are grouped primarily by thematic similarity."]
        return lines[:6]

    def _render_method_comparison_markdown(self, rows: list[MethodComparisonRow]) -> str:
        header = "| Paper | Quality | Model | Datasets | Metrics | Limitation |\n| --- | --- | --- | --- | --- | --- |"
        body = [
            f"| {row.title} | {row.analysis_quality.value} | {row.model_type or 'Unknown'} | "
            f"{', '.join(row.datasets) or 'None'} | {', '.join(row.metrics) or 'None'} | "
            f"{row.primary_limitation or 'None'} |"
            for row in rows
        ]
        return "\n".join([header, *body]) if body else f"{header}\n| No analyzed papers | - | - | - | - | - |"

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

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "cluster"
