import { useEffect, useMemo, useState } from "react";

import {
  confirmTopic,
  createSession,
  getSession,
  nudgeDiscovery,
  SessionSnapshot,
  startTopic,
  StreamEvent,
  updateApprovedPapers,
} from "./api/client";
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
  method_comparison_table: [],
  citation_graph: null,
  analysis_summary: {
    selected_paper_ids: [],
    completed: false,
    degraded_paper_ids: [],
    comparison_row_count: 0,
    retained_context_node_count: 0,
    lineage_path_count: 0,
    citation_graph_summary: null,
  },
  survey_summary: {
    section_ids: [],
    completed: false,
  },
  artifact_status: {},
  last_updated_at: new Date().toISOString(),
};

export function App() {
  const [snapshot, setSnapshot] = useState<SessionSnapshot>(placeholderSnapshot);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [streamEvents, setStreamEvents] = useState<StreamEvent[]>([]);

  useEffect(() => {
    let cancelled = false;

    async function bootstrapSession() {
      try {
        setBusy(true);
        const created = await createSession();
        if (cancelled) {
          return;
        }
        setSessionId(created.session_id);
        const nextSnapshot = await getSession(created.session_id);
        if (!cancelled) {
          setSnapshot(nextSnapshot);
        }
      } catch (error) {
        if (!cancelled) {
          setErrorMessage(error instanceof Error ? error.message : "Failed to bootstrap session.");
        }
      } finally {
        if (!cancelled) {
          setBusy(false);
        }
      }
    }

    void bootstrapSession();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!sessionId) {
      return undefined;
    }

    const stream = new SessionStream();

    const handleStreamEvent = async (event: StreamEvent) => {
      setStreamEvents((current) => [event, ...current].slice(0, 10));
      try {
        const nextSnapshot = await getSession(sessionId);
        setSnapshot(nextSnapshot);
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "Failed to refresh session snapshot.");
      }
    };

    stream.connect(sessionId, handleStreamEvent, () => {
      setErrorMessage("Session stream disconnected.");
    });

    return () => {
      stream.disconnect();
    };
  }, [sessionId]);

  async function runSessionAction(action: () => Promise<SessionSnapshot>) {
    try {
      setBusy(true);
      setErrorMessage(null);
      const nextSnapshot = await action();
      setSnapshot(nextSnapshot);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  }

  const formattedUpdatedAt = useMemo(() => {
    return new Date(snapshot.last_updated_at).toLocaleString();
  }, [snapshot.last_updated_at]);

  return (
    <main className="app-shell">
      <header className="hero">
        <p className="eyebrow">Checkpoint 3.1</p>
        <h1>ArXiv Literature Scout</h1>
        <p className="lede">
          Discovery is now wired to the live backend: interpret the topic, confirm the
          search angles, curate the shortlist, and steer reruns with nudges.
        </p>
        <div className="hero-stats">
          <div>
            <span className="stat-label">Session</span>
            <strong>{sessionId ?? "Creating..."}</strong>
          </div>
          <div>
            <span className="stat-label">Phase</span>
            <strong>{snapshot.current_phase}</strong>
          </div>
          <div>
            <span className="stat-label">Updated</span>
            <strong>{formattedUpdatedAt}</strong>
          </div>
        </div>
      </header>

      <section className="meta-card">
        <h2>Session State</h2>
        <p>
          The app is subscribed to the backend SSE stream and refreshes the snapshot
          as discovery artifacts arrive or interrupts are raised.
        </p>
        <ul>
          <li>Status: <code>{snapshot.status}</code></li>
          <li>Checkpoint: <code>{snapshot.current_checkpoint}</code></li>
          <li>Allowed actions: <code>{snapshot.allowed_actions.join(", ") || "none"}</code></li>
        </ul>
      </section>

      <section className="phase-grid">
        <DiscoveryView
          snapshot={snapshot}
          busy={busy}
          errorMessage={errorMessage}
          onStartTopic={async (topic) => {
            if (!sessionId) {
              return;
            }
            await runSessionAction(() => startTopic(sessionId, topic));
          }}
          onConfirmTopic={async () => {
            if (!sessionId) {
              return;
            }
            await runSessionAction(() => confirmTopic(sessionId));
          }}
          onUpdateApprovedPapers={async (paperIds) => {
            if (!sessionId) {
              return;
            }
            await runSessionAction(() => updateApprovedPapers(sessionId, paperIds));
          }}
          onNudgeDiscovery={async (text) => {
            if (!sessionId) {
              return;
            }
            await runSessionAction(() => nudgeDiscovery(sessionId, text));
          }}
        />
        <AnalysisView snapshot={snapshot} />
        <SurveyView snapshot={snapshot} />
      </section>

      <section className="meta-card">
        <h2>Recent Stream Events</h2>
        {streamEvents.length > 0 ? (
          <div className="event-list">
            {streamEvents.map((event) => (
              <article className="event-card" key={`${event.id ?? "event"}-${event.occurred_at}`}>
                <div className="event-meta">
                  <strong>{event.event_type}</strong>
                  <span>{new Date(event.occurred_at).toLocaleTimeString()}</span>
                </div>
                <p>{event.message ?? "No message."}</p>
              </article>
            ))}
          </div>
        ) : (
          <p className="helper-copy">Waiting for stream events.</p>
        )}
      </section>
    </main>
  );
}
