import { type FormEvent, useEffect, useMemo, useState } from "react";

import { CuratedPaper, SessionSnapshot } from "../../api/client";

interface DiscoveryViewProps {
  snapshot: SessionSnapshot;
  busy: boolean;
  errorMessage: string | null;
  onStartTopic: (topic: string) => Promise<void>;
  onConfirmTopic: () => Promise<void>;
  onUpdateApprovedPapers: (paperIds: string[]) => Promise<void>;
  onNudgeDiscovery: (text: string) => Promise<void>;
}

function summarizeAbstract(text: string | null, limit = 220) {
  if (!text) return "No abstract available.";
  if (text.length <= limit) return text;
  return `${text.slice(0, limit).trim()}…`;
}

function resolveApprovedPapers(snapshot: SessionSnapshot): CuratedPaper[] {
  if (snapshot.approved_paper_details.length > 0) {
    return snapshot.approved_paper_details;
  }
  const shortlistMap = new Map(snapshot.latest_shortlist.map((paper) => [paper.paper_id, paper]));
  return snapshot.approved_papers
    .map((paperId) => shortlistMap.get(paperId))
    .filter((paper): paper is CuratedPaper => Boolean(paper));
}

export function DiscoveryView({
  snapshot,
  busy,
  errorMessage,
  onStartTopic,
  onConfirmTopic,
  onUpdateApprovedPapers,
  onNudgeDiscovery,
}: DiscoveryViewProps) {
  const [topicInput, setTopicInput] = useState(snapshot.topic ?? "");
  const [nudgeText, setNudgeText] = useState("");
  const [selectedPaperIds, setSelectedPaperIds] = useState<string[]>(snapshot.approved_papers);

  useEffect(() => {
    setTopicInput(snapshot.topic ?? "");
  }, [snapshot.topic]);

  useEffect(() => {
    setSelectedPaperIds(snapshot.approved_papers);
  }, [snapshot.approved_papers]);

  const approvedPapers = useMemo(() => resolveApprovedPapers(snapshot), [snapshot]);
  const canConfirmTopic = snapshot.allowed_actions.includes("confirm_topic");
  const canUpdateApprovedPapers = snapshot.allowed_actions.includes("update_approved_papers");
  const canNudgeDiscovery = snapshot.allowed_actions.includes("nudge_discovery");

  async function handleTopicSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedTopic = topicInput.trim();
    if (!normalizedTopic) return;
    await onStartTopic(normalizedTopic);
  }

  async function handleApprovedSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onUpdateApprovedPapers(selectedPaperIds);
  }

  async function handleNudgeSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedText = nudgeText.trim();
    if (!normalizedText) return;
    await onNudgeDiscovery(normalizedText);
    setNudgeText("");
  }

  function togglePaper(paperId: string) {
    setSelectedPaperIds((current) =>
      current.includes(paperId)
        ? current.filter((value) => value !== paperId)
        : [...current, paperId],
    );
  }

  return (
    <div className="panel-stack">

      {/* Topic input */}
      <form className="action-panel" onSubmit={handleTopicSubmit}>
        <div className="panel-header">
          <h3>Topic Input</h3>
          <span className={`status-chip status-${snapshot.status}`}>{snapshot.status}</span>
        </div>
        <label className="field-label" htmlFor="topic-input">
          Research topic
        </label>
        <textarea
          id="topic-input"
          className="text-input"
          rows={3}
          value={topicInput}
          onChange={(event) => setTopicInput(event.target.value)}
          placeholder="Example: retrieval-augmented generation for scientific literature review"
          disabled={busy}
        />
        <div className="action-row">
          <button className="primary-button" type="submit" disabled={busy || topicInput.trim().length < 3}>
            {snapshot.topic ? "Reinterpret Topic" : "Start Discovery"}
          </button>
          <span className="helper-copy">Checkpoint: {snapshot.current_checkpoint}</span>
        </div>
      </form>

      {/* Interpreted topic */}
      {snapshot.search_interpretation && (
        <section className="action-panel">
          <div className="panel-header">
            <h3>Interpreted Topic</h3>
            {canConfirmTopic && (
              <button className="primary-button" type="button" onClick={onConfirmTopic} disabled={busy}>
                Confirm and Fetch
              </button>
            )}
          </div>
          <p className="inline-note">
            Normalized topic: <strong>{snapshot.search_interpretation.normalized_topic}</strong>
          </p>
          <div className="angle-grid">
            {snapshot.search_interpretation.search_angles.map((angle) => (
              <div className="angle-card" key={angle}>{angle}</div>
            ))}
          </div>
        </section>
      )}

      {/* Curated shortlist */}
      {snapshot.latest_shortlist.length > 0 && (
        <section className="action-panel">
          <div className="panel-header">
            <h3>Curated Shortlist</h3>
            <span className="helper-copy">{snapshot.latest_shortlist.length} papers shortlisted</span>
          </div>
          <form onSubmit={handleApprovedSubmit}>
            <div className="paper-grid">
              {snapshot.latest_shortlist.map((paper) => {
                const isSelected = selectedPaperIds.includes(paper.paper_id);
                return (
                  <label
                    className={`paper-card ${isSelected ? "paper-card-selected" : ""}`}
                    key={paper.paper_id}
                  >
                    <div className="paper-card-top">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => togglePaper(paper.paper_id)}
                        disabled={busy}
                      />
                      <div>
                        <h4>{paper.title}</h4>
                        <p className="paper-meta">
                          {paper.year ?? "Unknown year"} &nbsp;·&nbsp; {paper.citation_count ?? 0} citations
                        </p>
                      </div>
                    </div>
                    <p className="paper-rationale">{paper.rationale ?? "No rationale available."}</p>
                    <p className="paper-abstract">{summarizeAbstract(paper.abstract)}</p>
                  </label>
                );
              })}
            </div>
            <div className="action-row">
              <button className="primary-button" type="submit" disabled={busy || !canUpdateApprovedPapers}>
                Save Approved Papers
              </button>
              <span className="helper-copy">{selectedPaperIds.length} selected</span>
            </div>
          </form>
        </section>
      )}

      {/* Preliminary method table */}
      {snapshot.preliminary_method_table.length > 0 && (
        <section className="action-panel">
          <div className="panel-header">
            <h3>Preliminary Method Table</h3>
          </div>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Paper</th>
                  <th>Model</th>
                  <th>Dataset</th>
                  <th>Metrics</th>
                  <th>Benchmarks</th>
                </tr>
              </thead>
              <tbody>
                {snapshot.preliminary_method_table.map((row) => (
                  <tr key={row.paper_id}>
                    <td>{row.paper_id}</td>
                    <td>{row.model_type ?? "Unknown"}</td>
                    <td>{row.dataset ?? "Unknown"}</td>
                    <td>{row.metrics.length ? row.metrics.join(", ") : "None found"}</td>
                    <td>{row.benchmarks.length ? row.benchmarks.join(", ") : "None found"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Steering memory */}
      <section className="action-panel">
        <div className="panel-header">
          <h3>Steering Memory</h3>
          <span className="helper-copy">
            include {snapshot.steering_preferences.include.length} &nbsp;·&nbsp;
            exclude {snapshot.steering_preferences.exclude.length} &nbsp;·&nbsp;
            emphasize {snapshot.steering_preferences.emphasize.length}
          </span>
        </div>
        <div className="token-group">
          {snapshot.steering_preferences.include.map((value) => (
            <span className="token include-token" key={`include-${value}`}>+ {value}</span>
          ))}
          {snapshot.steering_preferences.exclude.map((value) => (
            <span className="token exclude-token" key={`exclude-${value}`}>− {value}</span>
          ))}
          {snapshot.steering_preferences.emphasize.map((value) => (
            <span className="token emphasize-token" key={`emphasize-${value}`}>↑ {value}</span>
          ))}
          {snapshot.steering_preferences.include.length === 0 &&
            snapshot.steering_preferences.exclude.length === 0 &&
            snapshot.steering_preferences.emphasize.length === 0 && (
              <span className="helper-copy">No steering nudges applied yet.</span>
          )}
        </div>
        <form onSubmit={handleNudgeSubmit}>
          <label className="field-label" htmlFor="nudge-input">
            Discovery nudge
          </label>
          <textarea
            id="nudge-input"
            className="text-input"
            rows={3}
            value={nudgeText}
            onChange={(event) => setNudgeText(event.target.value)}
            placeholder="Example: focus on benchmark-heavy papers and exclude survey-only works"
            disabled={busy}
          />
          <div className="action-row">
            <button
              className="primary-button"
              type="submit"
              disabled={busy || !canNudgeDiscovery || nudgeText.trim().length < 3}
            >
              Apply Nudge
            </button>
          </div>
        </form>
      </section>

      {/* Approved papers */}
      <section className="action-panel">
        <div className="panel-header">
          <h3>Approved Papers</h3>
          <span className="helper-copy">{approvedPapers.length} retained</span>
        </div>
        {approvedPapers.length > 0 ? (
          <ul className="approved-list">
            {approvedPapers.map((paper) => (
              <li key={paper.paper_id}>
                <strong>{paper.title}</strong>
                <span>{paper.year ?? "Unknown year"}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="helper-copy">No papers approved yet.</p>
        )}
      </section>

      {/* Pending interrupt */}
      {snapshot.pending_interrupt && (
        <section className="interrupt-panel">
          <h3>Pending Interrupt</h3>
          <p>{snapshot.pending_interrupt.message}</p>
        </section>
      )}

      {errorMessage && <p className="error-banner">{errorMessage}</p>}
    </div>
  );
}
