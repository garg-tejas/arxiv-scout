export type SessionStatus = "idle" | "running" | "waiting_for_input" | "completed" | "error";
export type PhaseType = "discovery" | "analysis" | "survey" | "none";
export type AllowedAction =
  | "confirm_topic"
  | "update_approved_papers"
  | "nudge_discovery"
  | "start_analysis"
  | "select_analysis_papers"
  | "start_survey"
  | "submit_survey_brief"
  | "skip_survey_brief"
  | "revise_survey_sections"
  | "approve_final_survey"
  | "download_survey_markdown";
export type CheckpointType =
  | "topic_confirmation"
  | "shortlist_review"
  | "analysis_selection"
  | "survey_brief"
  | "survey_review"
  | "none";
export type StreamEventType =
  | "phase_started"
  | "node_update"
  | "interrupt"
  | "artifact_ready"
  | "error"
  | "phase_completed";
export type ArtifactType =
  | "search_interpretation"
  | "shortlist"
  | "preliminary_method_table"
  | "paper_analysis"
  | "citation_graph"
  | "method_comparison_table"
  | "survey_brief"
  | "theme_clusters"
  | "survey_section"
  | "final_survey_markdown";

export interface PendingInterrupt {
  checkpoint: CheckpointType;
  message: string;
  expected_action_types: AllowedAction[];
}

export interface SearchInterpretation {
  normalized_topic: string | null;
  search_angles: string[];
}

export interface SteeringPreferences {
  include: string[];
  exclude: string[];
  emphasize: string[];
}

export interface Author {
  name: string;
}

export interface CuratedPaper {
  paper_id: string;
  arxiv_id: string | null;
  title: string;
  abstract: string | null;
  authors: Author[];
  year: number | null;
  citation_count: number | null;
  rationale: string | null;
  score: number | null;
}

export interface MethodExtractionRow {
  paper_id: string;
  model_type: string | null;
  dataset: string | null;
  metrics: string[];
  benchmarks: string[];
}

export interface PaperAnalysis {
  paper_id: string;
  analysis_quality: "full_text" | "abstract_only";
  core_claim: string | null;
  methodology: string[];
  datasets: string[];
  metrics: string[];
  benchmarks: string[];
  limitations: string[];
  explicit_citations: string[];
}

export interface MethodComparisonRow {
  paper_id: string;
  title: string;
  analysis_quality: "full_text" | "abstract_only";
  model_type: string | null;
  core_claim: string | null;
  methodology_summary: string | null;
  datasets: string[];
  metrics: string[];
  benchmarks: string[];
  primary_limitation: string | null;
}

export interface CitationNode {
  node_id: string;
  title: string;
  role: "seed" | "context";
  paper_id: string | null;
}

export interface CitationEdge {
  edge_id: string;
  source: string;
  target: string;
  relation: "cites" | "cited_by" | "shared_foundation" | "extends";
  evidence_level: "direct" | "inferred";
}

export interface LineagePath {
  node_ids: string[];
  edge_ids: string[];
  evidence_level: "direct" | "inferred";
  summary: string;
}

export interface CitationGraph {
  seed_nodes: CitationNode[];
  context_nodes: CitationNode[];
  edges: CitationEdge[];
  lineage_paths: LineagePath[];
  narrative_summary: string | null;
}

export interface AnalysisSummary {
  selected_paper_ids: string[];
  completed: boolean;
  degraded_paper_ids: string[];
  comparison_row_count: number;
  retained_context_node_count: number;
  lineage_path_count: number;
  citation_graph_summary: string | null;
}

export interface SurveyBrief {
  angle: string | null;
  audience: string | null;
  emphasis: string[];
  comparisons: string[];
}

export interface ThemeCluster {
  cluster_id: string;
  title: string;
  description: string;
  paper_ids: string[];
}

export interface SurveySection {
  section_id: string;
  title: string;
  content_markdown: string;
  paper_ids: string[];
  revision_count: number;
  accepted: boolean;
}

export interface SurveyDocument {
  title: string;
  introduction: string | null;
  sections: SurveySection[];
  conclusion: string | null;
  references: string[];
  markdown: string;
}

export interface SurveySummary {
  section_ids: string[];
  completed: boolean;
  cluster_count: number;
  brief_ready: boolean;
  markdown_ready: boolean;
}

export interface SessionSnapshot {
  session_id: string;
  status: SessionStatus;
  current_phase: PhaseType;
  current_checkpoint: CheckpointType;
  pending_interrupt: PendingInterrupt | null;
  allowed_actions: AllowedAction[];
  topic: string | null;
  search_interpretation: SearchInterpretation | null;
  steering_preferences: SteeringPreferences;
  approved_papers: string[];
  approved_paper_details: CuratedPaper[];
  latest_shortlist: CuratedPaper[];
  preliminary_method_table: MethodExtractionRow[];
  paper_analyses: PaperAnalysis[];
  method_comparison_table: MethodComparisonRow[];
  citation_graph: CitationGraph | null;
  analysis_summary: AnalysisSummary;
  survey_brief: SurveyBrief | null;
  theme_clusters: ThemeCluster[];
  survey_sections: SurveySection[];
  final_survey_document: SurveyDocument | null;
  survey_summary: SurveySummary;
  artifact_status: Record<string, "pending" | "ready" | "failed">;
  last_updated_at: string;
}

export interface CreateSessionResponse {
  session_id: string;
}

export interface StreamEvent {
  id: number | null;
  session_id: string;
  event_type: StreamEventType;
  phase: PhaseType;
  checkpoint: CheckpointType;
  artifact_type: ArtifactType | null;
  message: string | null;
  data: Record<string, unknown>;
  occurred_at: string;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function parseSnapshot(response: Response): Promise<SessionSnapshot> {
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

export async function createSession(): Promise<CreateSessionResponse> {
  const response = await fetch(`${API_BASE}/sessions`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`Failed to create session: ${response.status}`);
  }
  return response.json();
}

export async function getSession(sessionId: string): Promise<SessionSnapshot> {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}`);
  if (!response.ok) {
    throw new Error(`Failed to load session: ${response.status}`);
  }
  return response.json();
}

export async function startTopic(sessionId: string, topic: string): Promise<SessionSnapshot> {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/topic`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ topic }),
  });
  return parseSnapshot(response);
}

export async function confirmTopic(sessionId: string): Promise<SessionSnapshot> {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/discovery/confirm`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ confirmed: true }),
  });
  return parseSnapshot(response);
}

export async function updateApprovedPapers(
  sessionId: string,
  paperIds: string[],
): Promise<SessionSnapshot> {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/discovery/approved-papers`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ paper_ids: paperIds }),
  });
  return parseSnapshot(response);
}

export async function nudgeDiscovery(
  sessionId: string,
  text: string,
): Promise<SessionSnapshot> {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/discovery/nudge`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ text }),
  });
  return parseSnapshot(response);
}

export async function startAnalysis(
  sessionId: string,
  paperIds: string[],
): Promise<SessionSnapshot> {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/analysis/start`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ paper_ids: paperIds }),
  });
  return parseSnapshot(response);
}

export async function startSurvey(
  sessionId: string,
  payload: {
    skip?: boolean;
    brief?: SurveyBrief | null;
  } = {},
): Promise<SessionSnapshot> {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/survey/start`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return parseSnapshot(response);
}

export async function reviseSurvey(
  sessionId: string,
  revisions: Array<{ section_id: string; feedback: string }>,
): Promise<SessionSnapshot> {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/survey/revise`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ revisions }),
  });
  return parseSnapshot(response);
}

export async function approveSurvey(sessionId: string): Promise<SessionSnapshot> {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/survey/approve`, {
    method: "POST",
  });
  return parseSnapshot(response);
}

export async function getSurveyMarkdown(sessionId: string): Promise<string> {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/survey.md`);
  if (!response.ok) {
    throw new Error(`Failed to load survey markdown: ${response.status}`);
  }
  return response.text();
}
