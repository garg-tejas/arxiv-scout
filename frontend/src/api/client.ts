export type SessionStatus = "idle" | "running" | "waiting_for_input" | "completed" | "error";
export type PhaseType = "discovery" | "analysis" | "survey" | "none";
export type CheckpointType =
  | "topic_confirmation"
  | "shortlist_review"
  | "analysis_selection"
  | "survey_brief"
  | "survey_review"
  | "none";

export interface PendingInterrupt {
  checkpoint: CheckpointType;
  message: string;
  expected_action_types: string[];
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
}

export interface SurveySummary {
  section_ids: string[];
  completed: boolean;
}

export interface SessionSnapshot {
  session_id: string;
  status: SessionStatus;
  current_phase: PhaseType;
  current_checkpoint: CheckpointType;
  pending_interrupt: PendingInterrupt | null;
  allowed_actions: string[];
  topic: string | null;
  search_interpretation: SearchInterpretation | null;
  steering_preferences: SteeringPreferences;
  approved_papers: string[];
  approved_paper_details: CuratedPaper[];
  latest_shortlist: CuratedPaper[];
  preliminary_method_table: MethodExtractionRow[];
  paper_analyses: PaperAnalysis[];
  citation_graph: CitationGraph | null;
  analysis_summary: AnalysisSummary;
  survey_summary: SurveySummary;
  artifact_status: Record<string, "pending" | "ready" | "failed">;
  last_updated_at: string;
}

export interface CreateSessionResponse {
  session_id: string;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

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
