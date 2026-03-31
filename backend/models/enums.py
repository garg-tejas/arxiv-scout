from __future__ import annotations

from enum import Enum


class SessionStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    COMPLETED = "completed"
    ERROR = "error"


class PhaseType(str, Enum):
    DISCOVERY = "discovery"
    ANALYSIS = "analysis"
    SURVEY = "survey"
    NONE = "none"


class CheckpointType(str, Enum):
    TOPIC_CONFIRMATION = "topic_confirmation"
    SHORTLIST_REVIEW = "shortlist_review"
    ANALYSIS_SELECTION = "analysis_selection"
    SURVEY_BRIEF = "survey_brief"
    SURVEY_REVIEW = "survey_review"
    NONE = "none"


class AllowedAction(str, Enum):
    CONFIRM_TOPIC = "confirm_topic"
    UPDATE_APPROVED_PAPERS = "update_approved_papers"
    NUDGE_DISCOVERY = "nudge_discovery"
    START_ANALYSIS = "start_analysis"
    SELECT_ANALYSIS_PAPERS = "select_analysis_papers"
    START_SURVEY = "start_survey"
    SUBMIT_SURVEY_BRIEF = "submit_survey_brief"
    SKIP_SURVEY_BRIEF = "skip_survey_brief"
    REVISE_SURVEY_SECTIONS = "revise_survey_sections"
    APPROVE_FINAL_SURVEY = "approve_final_survey"
    DOWNLOAD_SURVEY_MARKDOWN = "download_survey_markdown"


class ArtifactStatusValue(str, Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class ArtifactType(str, Enum):
    SEARCH_INTERPRETATION = "search_interpretation"
    SHORTLIST = "shortlist"
    PRELIMINARY_METHOD_TABLE = "preliminary_method_table"
    PAPER_ANALYSIS = "paper_analysis"
    CITATION_GRAPH = "citation_graph"
    METHOD_COMPARISON_TABLE = "method_comparison_table"
    SURVEY_BRIEF = "survey_brief"
    THEME_CLUSTERS = "theme_clusters"
    SURVEY_SECTION = "survey_section"
    FINAL_SURVEY_MARKDOWN = "final_survey_markdown"


class StreamEventType(str, Enum):
    PHASE_STARTED = "phase_started"
    NODE_UPDATE = "node_update"
    INTERRUPT = "interrupt"
    ARTIFACT_READY = "artifact_ready"
    ERROR = "error"
    PHASE_COMPLETED = "phase_completed"


class AnalysisQuality(str, Enum):
    FULL_TEXT = "full_text"
    ABSTRACT_ONLY = "abstract_only"


class GraphNodeRole(str, Enum):
    SEED = "seed"
    CONTEXT = "context"


class CitationEdgeType(str, Enum):
    CITES = "cites"
    CITED_BY = "cited_by"
    SHARED_FOUNDATION = "shared_foundation"
    EXTENDS = "extends"


class EvidenceLevel(str, Enum):
    DIRECT = "direct"
    INFERRED = "inferred"


class ReviewVerdict(str, Enum):
    ACCEPT = "ACCEPT"
    REVISE = "REVISE"


class LLMProvider(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class LLMRole(str, Enum):
    SEARCH = "search"
    CURATION = "curation"
    STEERING = "steering"
    PAPER_ANALYZER = "paper_analyzer"
    SURVEY_ORCHESTRATOR = "survey_orchestrator"
    THEMATIC_CLUSTERING = "thematic_clustering"
    SECTION_WRITER = "section_writer"
    SECTION_REVIEWER = "section_reviewer"
    SURVEY_ASSEMBLER = "survey_assembler"
    SMOKE_TEST = "smoke_test"
