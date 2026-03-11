from __future__ import annotations

import re

from models.analysis import MethodComparisonRow, PaperAnalysis
from models.enums import ArtifactStatusValue, ArtifactType
from models.papers import CuratedPaper


class ArtifactService:
    def build_initial_artifact_status(self) -> dict[str, ArtifactStatusValue]:
        return {artifact.value: ArtifactStatusValue.PENDING for artifact in ArtifactType}

    def build_method_comparison_table(
        self,
        *,
        papers: list[CuratedPaper],
        analyses: list[PaperAnalysis],
    ) -> list[MethodComparisonRow]:
        analysis_map = {analysis.paper_id: analysis for analysis in analyses}
        rows: list[MethodComparisonRow] = []
        for paper in papers:
            analysis = analysis_map.get(paper.paper_id)
            if analysis is None:
                continue
            rows.append(
                MethodComparisonRow(
                    paper_id=paper.paper_id,
                    title=paper.title,
                    analysis_quality=analysis.analysis_quality,
                    model_type=self._infer_model_type(analysis),
                    core_claim=analysis.core_claim,
                    methodology_summary=analysis.methodology[0] if analysis.methodology else None,
                    datasets=analysis.datasets,
                    metrics=analysis.metrics,
                    benchmarks=analysis.benchmarks,
                    primary_limitation=analysis.limitations[0] if analysis.limitations else None,
                )
            )
        return rows

    @staticmethod
    def _infer_model_type(analysis: PaperAnalysis) -> str | None:
        text = " ".join(
            part
            for part in [
                analysis.core_claim or "",
                *analysis.methodology,
            ]
            if part
        ).lower()
        keyword_map = {
            "graph neural network": (r"\bgraph neural network\b", r"\bgnn\b", r"\bgcn\b", r"\bgat\b"),
            "transformer": (r"\btransformer\b", r"\bself-attention\b"),
            "diffusion model": (r"\bdiffusion\b",),
            "large language model": (r"\bllm\b", r"\blarge language model\b"),
            "convolutional network": (r"\bcnn\b", r"\bconvolutional\b"),
            "recurrent network": (r"\brnn\b", r"\blstm\b", r"\bgru\b"),
            "retrieval model": (r"\bretriev(?:al|er)\b",),
        }
        for label, patterns in keyword_map.items():
            if any(re.search(pattern, text) for pattern in patterns):
                return label
        return None
