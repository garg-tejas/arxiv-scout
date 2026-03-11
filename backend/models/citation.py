from __future__ import annotations

from pydantic import BaseModel, Field

from models.enums import CitationEdgeType, EvidenceLevel, GraphNodeRole


class CitationNode(BaseModel):
    node_id: str
    title: str
    role: GraphNodeRole
    paper_id: str | None = None


class CitationEdge(BaseModel):
    edge_id: str
    source: str
    target: str
    relation: CitationEdgeType
    evidence_level: EvidenceLevel


class LineagePath(BaseModel):
    node_ids: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)
    evidence_level: EvidenceLevel
    summary: str


class CitationGraph(BaseModel):
    seed_nodes: list[CitationNode] = Field(default_factory=list)
    context_nodes: list[CitationNode] = Field(default_factory=list)
    edges: list[CitationEdge] = Field(default_factory=list)
    lineage_paths: list[LineagePath] = Field(default_factory=list)
    narrative_summary: str | None = None
