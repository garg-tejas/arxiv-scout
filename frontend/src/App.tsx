import { createSession, getSession, SessionSnapshot } from "./api/client";
import { SessionStream } from "./lib/sse";
import { AnalysisView } from "./views/analysis/AnalysisView";
import { DiscoveryView } from "./views/discovery/DiscoveryView";
import { SurveyView } from "./views/survey/SurveyView";

const placeholderSnapshot: SessionSnapshot = {
  session_id: "not-created",
  status: "idle",
  current_phase: "none",
  current_checkpoint: "none",
  pending_interrupt: null,
  allowed_actions: [],
  topic: null,
  search_interpretation: null,
  steering_preferences: {
    include: [],
    exclude: [],
    emphasize: [],
  },
  approved_papers: [],
  approved_paper_details: [],
  latest_shortlist: [],
  preliminary_method_table: [],
  paper_analyses: [],
  citation_graph: null,
  analysis_summary: {
    selected_paper_ids: [],
    completed: false,
    degraded_paper_ids: [],
  },
  survey_summary: {
    section_ids: [],
    completed: false,
  },
  artifact_status: {},
  last_updated_at: new Date().toISOString(),
};

export function App() {
  return (
    <main className="app-shell">
      <header className="hero">
        <p className="eyebrow">Checkpoint 1.1</p>
        <h1>ArXiv Literature Scout</h1>
        <p className="lede">
          Frontend scaffold for the discovery, analysis, and survey workflow.
        </p>
      </header>

      <section className="meta-card">
        <h2>Frontend Scaffolding</h2>
        <p>
          API helpers are stubbed in <code>frontend/src/api</code> and SSE wiring
          lives in <code>frontend/src/lib</code>. The phase views below are
          placeholders for later checkpoints.
        </p>
        <ul>
          <li><code>createSession()</code> and <code>getSession()</code> are defined.</li>
          <li><code>SessionStream</code> wraps the backend SSE endpoint.</li>
          <li>Discovery, Analysis, and Survey views have stable component paths.</li>
        </ul>
      </section>

      <section className="phase-grid">
        <DiscoveryView snapshot={placeholderSnapshot} />
        <AnalysisView snapshot={placeholderSnapshot} />
        <SurveyView snapshot={placeholderSnapshot} />
      </section>

      <section className="meta-card">
        <h2>Next Checkpoint Hooks</h2>
        <p>
          These imports intentionally keep the initial API and stream contracts
          visible so the next checkpoint can start consuming the backend without
          reshuffling frontend structure.
        </p>
        <pre>{`createSession(): ${typeof createSession}
getSession(): ${typeof getSession}
SessionStream endpoint: ${SessionStream.name}`}</pre>
      </section>
    </main>
  );
}
