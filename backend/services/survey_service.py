from __future__ import annotations

from collections import defaultdict
import re

from models.analysis import MethodComparisonRow, PaperAnalysis
from models.citation import CitationGraph
from models.enums import CitationEdgeType, ReviewVerdict
from models.papers import CuratedPaper
from models.session import SessionSnapshot
from models.survey import SectionReviewResult, SurveyBrief, SurveyDocument, SurveySection, ThemeCluster


class SurveyService:
    def synthesize_brief(self, snapshot: SessionSnapshot) -> SurveyBrief:
        comparison_rows = snapshot.method_comparison_table
        model_types = [row.model_type for row in comparison_rows if row.model_type]
        unique_models = list(dict.fromkeys(model_types))
        emphasis = list(dict.fromkeys(snapshot.steering_preferences.emphasize))[:3]
        comparisons: list[str] = []
        if len(unique_models) >= 2:
            comparisons.append(f"compare {unique_models[0]} and {unique_models[1]} approaches")
        if snapshot.citation_graph and snapshot.citation_graph.narrative_summary:
            comparisons.append("trace direct and inferred citation lineage across the approved papers")
        if not comparisons:
            comparisons.append("contrast methodology, datasets, and limitations across the approved set")
        if not emphasis and unique_models:
            emphasis = unique_models[:2]
        return SurveyBrief(
            angle=snapshot.topic or "approved arXiv paper set",
            audience="researchers comparing recent arXiv methods",
            emphasis=emphasis,
            comparisons=comparisons,
        )

    def cluster_themes(
        self,
        *,
        brief: SurveyBrief,
        papers: list[CuratedPaper],
        analyses: list[PaperAnalysis],
        comparison_rows: list[MethodComparisonRow],
        citation_graph: CitationGraph | None,
    ) -> list[ThemeCluster]:
        paper_map = {paper.paper_id: paper for paper in papers}
        row_map = {row.paper_id: row for row in comparison_rows}
        analysis_map = {analysis.paper_id: analysis for analysis in analyses}

        grouped_ids: dict[str, list[str]] = defaultdict(list)
        for paper in papers:
            row = row_map.get(paper.paper_id)
            analysis = analysis_map.get(paper.paper_id)
            label = (
                (row.model_type if row and row.model_type else None)
                or (analysis.datasets[0] if analysis and analysis.datasets else None)
                or "general methods"
            )
            grouped_ids[label].append(paper.paper_id)

        clusters: list[ThemeCluster] = []
        for index, (label, paper_ids) in enumerate(
            sorted(grouped_ids.items(), key=lambda item: (-len(item[1]), item[0]))
        ):
            internal_edges = self._count_internal_edges(citation_graph, set(paper_ids))
            title = self._format_cluster_title(label)
            description = (
                f"This cluster groups papers around {label}. "
                f"It covers {len(paper_ids)} paper(s) and {internal_edges} internal citation linkage(s)."
            )
            if brief.comparisons:
                description = f"{description} The survey brief emphasizes {brief.comparisons[0]}."
            clusters.append(
                ThemeCluster(
                    cluster_id=f"theme-{index + 1}-{self._slugify(label)}",
                    title=title,
                    description=description,
                    paper_ids=paper_ids,
                )
            )
        return clusters

    def draft_section(
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
        paper_map = {paper.paper_id: paper for paper in papers}
        analysis_map = {analysis.paper_id: analysis for analysis in analyses}
        row_map = {row.paper_id: row for row in comparison_rows}

        ordered_ids = sorted(
            cluster.paper_ids,
            key=lambda paper_id: (paper_map.get(paper_id).year or 0, paper_map.get(paper_id).title if paper_map.get(paper_id) else paper_id),
        )
        bullet_lines: list[str] = []
        limitation_pool: list[str] = []
        for paper_id in ordered_ids:
            paper = paper_map.get(paper_id)
            analysis = analysis_map.get(paper_id)
            row = row_map.get(paper_id)
            if paper is None or analysis is None:
                continue
            limitation_pool.extend(analysis.limitations)
            model = row.model_type if row and row.model_type else "unspecified model"
            datasets = ", ".join(analysis.datasets) if analysis.datasets else "unspecified datasets"
            metrics = ", ".join(analysis.metrics) if analysis.metrics else "unspecified metrics"
            bullet_lines.append(
                f"- **{paper.title} ({paper.year or 'n.d.'})** uses {model}, studies {datasets}, "
                f"and reports {metrics}. Core claim: {analysis.core_claim or 'No core claim extracted.'}"
            )

        lineage_lines = self._build_lineage_lines(cluster.paper_ids, citation_graph, paper_map)
        open_problems = self._build_open_problem_lines(limitation_pool, analyses, cluster.paper_ids)

        revision_line = ""
        if revision_feedback:
            revision_line = f"\nRevision focus: {revision_feedback}\n"

        section_markdown = "\n".join(
            [
                f"## {cluster.title}",
                "",
                "### Theme Overview",
                f"{cluster.description} This section is written for {brief.audience or 'research readers'}.{revision_line}".strip(),
                "",
                "### Approach Comparison",
                *bullet_lines,
                "",
                "### Idea Progression",
                *lineage_lines,
                "",
                "### Open Problems",
                *open_problems,
            ]
        )

        return SurveySection(
            section_id=cluster.cluster_id,
            title=cluster.title,
            content_markdown=section_markdown,
            paper_ids=ordered_ids,
            revision_count=revision_count,
            accepted=False,
        )

    def review_section(
        self,
        *,
        section: SurveySection,
        cluster: ThemeCluster,
    ) -> SectionReviewResult:
        feedback: list[str] = []
        content = section.content_markdown
        if "### Approach Comparison" not in content:
            feedback.append("Add a dedicated comparison subsection.")
        if "### Open Problems" not in content:
            feedback.append("Add an explicit open problems subsection.")
        if len(content) < 700 and len(cluster.paper_ids) > 1:
            feedback.append("Expand the section with clearer multi-paper comparison detail.")

        verdict = ReviewVerdict.REVISE if feedback and section.revision_count < 2 else ReviewVerdict.ACCEPT
        return SectionReviewResult(
            verdict=verdict,
            feedback=" ".join(feedback) if feedback else "Section satisfies the survey brief.",
            revision_count=section.revision_count,
        )

    def assemble_document(
        self,
        *,
        brief: SurveyBrief,
        sections: list[SurveySection],
        comparison_rows: list[MethodComparisonRow],
        papers: list[CuratedPaper],
        citation_graph: CitationGraph | None,
    ) -> SurveyDocument:
        intro = (
            f"This survey examines {brief.angle or 'the approved paper set'} for "
            f"{brief.audience or 'research readers'}. It emphasizes "
            f"{', '.join(brief.emphasis) if brief.emphasis else 'methodological comparison'}."
        )
        conclusion = (
            "Across the approved papers, the dominant trade-offs center on dataset coverage, "
            "evaluation depth, and whether newer methods clearly extend or only weakly align with prior work."
        )
        if citation_graph and citation_graph.narrative_summary:
            conclusion = f"{conclusion} {citation_graph.narrative_summary}"

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
            intro,
            "",
            *[section.content_markdown for section in sections],
            "",
            "## Method Comparison Table",
            comparison_markdown,
            "",
            "## Conclusion",
            conclusion,
            "",
            "## References",
            *references,
        ]
        markdown = "\n".join(markdown_parts).strip()
        return SurveyDocument(
            introduction=intro,
            sections=sections,
            conclusion=conclusion,
            references=references,
            markdown=markdown,
        )

    def render_markdown(self, document: SurveyDocument) -> str:
        return document.markdown

    def _build_lineage_lines(
        self,
        paper_ids: list[str],
        citation_graph: CitationGraph | None,
        paper_map: dict[str, CuratedPaper],
    ) -> list[str]:
        if citation_graph is None:
            return ["- No citation graph was available for this theme."]
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
                f"- {source_title} {edge.relation.value.replace('_', ' ')} {target_title} "
                f"({edge.evidence_level.value} evidence)."
            )
        if not lines:
            return ["- No strong within-cluster lineage was identified; the papers are grouped primarily by thematic similarity."]
        return lines[:5]

    def _build_open_problem_lines(
        self,
        limitation_pool: list[str],
        analyses: list[PaperAnalysis],
        cluster_paper_ids: list[str],
    ) -> list[str]:
        cluster_set = set(cluster_paper_ids)
        limitations = []
        for limitation in limitation_pool:
            normalized = limitation.strip()
            if normalized and normalized not in limitations:
                limitations.append(normalized)
        if limitations:
            return [f"- {limitation}" for limitation in limitations[:3]]

        datasets = sorted(
            {
                dataset
                for analysis in analyses
                if analysis.paper_id in cluster_set
                for dataset in analysis.datasets
            }
        )
        metrics = sorted(
            {
                metric
                for analysis in analyses
                if analysis.paper_id in cluster_set
                for metric in analysis.metrics
            }
        )
        return [
            f"- Evaluate the theme on a broader dataset set than {', '.join(datasets[:3]) or 'the currently extracted benchmarks'}.",
            f"- Standardize reporting beyond {', '.join(metrics[:3]) or 'the extracted metrics'} to make cross-paper comparison easier.",
        ]

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
    def _count_internal_edges(citation_graph: CitationGraph | None, paper_ids: set[str]) -> int:
        if citation_graph is None:
            return 0
        return sum(
            1
            for edge in citation_graph.edges
            if edge.source in paper_ids and edge.target in paper_ids
        )

    @staticmethod
    def _format_cluster_title(label: str) -> str:
        if label == "general methods":
            return "General Method Directions"
        if label.endswith("dataset") or label.endswith("datasets"):
            return f"{label.title()} Evaluations"
        return f"{label.title()} Theme"

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "cluster"
