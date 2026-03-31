"""Centralized LLM prompts for ArXiv Literature Scout.

This module provides all system prompts and user prompt builders
for the multi-agent pipeline:
- Discovery: search interpretation, steering, curation
- Analysis: paper analysis
- Survey: orchestration, clustering, section writing, review, assembly
"""

from prompts.analysis import (
    PAPER_ANALYZER_SYSTEM_PROMPT,
    build_paper_analyzer_user_prompt,
)
from prompts.curation import (
    CURATION_AGENT_SYSTEM_PROMPT,
    build_curation_user_prompt,
)
from prompts.search import (
    SEARCH_AGENT_SYSTEM_PROMPT,
    build_search_user_prompt,
)
from prompts.steering import (
    STEERING_AGENT_SYSTEM_PROMPT,
    build_steering_user_prompt,
)
from prompts.survey import (
    SECTION_REVIEWER_SYSTEM_PROMPT,
    SECTION_WRITER_SYSTEM_PROMPT,
    SURVEY_ASSEMBLER_SYSTEM_PROMPT,
    SURVEY_ORCHESTRATOR_SYSTEM_PROMPT,
    THEMATIC_CLUSTERING_SYSTEM_PROMPT,
    build_section_reviewer_user_prompt,
    build_section_writer_user_prompt,
    build_survey_assembler_user_prompt,
    build_survey_orchestrator_user_prompt,
    build_thematic_clustering_user_prompt,
)

__all__ = [
    # Search
    "SEARCH_AGENT_SYSTEM_PROMPT",
    "build_search_user_prompt",
    # Steering
    "STEERING_AGENT_SYSTEM_PROMPT",
    "build_steering_user_prompt",
    # Curation
    "CURATION_AGENT_SYSTEM_PROMPT",
    "build_curation_user_prompt",
    # Analysis
    "PAPER_ANALYZER_SYSTEM_PROMPT",
    "build_paper_analyzer_user_prompt",
    # Survey
    "SURVEY_ORCHESTRATOR_SYSTEM_PROMPT",
    "build_survey_orchestrator_user_prompt",
    "THEMATIC_CLUSTERING_SYSTEM_PROMPT",
    "build_thematic_clustering_user_prompt",
    "SECTION_WRITER_SYSTEM_PROMPT",
    "build_section_writer_user_prompt",
    "SECTION_REVIEWER_SYSTEM_PROMPT",
    "build_section_reviewer_user_prompt",
    "SURVEY_ASSEMBLER_SYSTEM_PROMPT",
    "build_survey_assembler_user_prompt",
]
