import { type ChangeEvent, useEffect, useMemo, useState } from "react";

import { SessionSnapshot, SurveyBrief } from "../../api/client";

interface SurveyViewProps {
  snapshot: SessionSnapshot;
  busy: boolean;
  errorMessage: string | null;
  onStartSurvey: (payload: { skip?: boolean; brief?: SurveyBrief | null }) => Promise<void>;
  onReviseSurvey: (revisions: Array<{ section_id: string; feedback: string }>) => Promise<void>;
  onApproveSurvey: () => Promise<void>;
  onDownloadMarkdown: () => Promise<void>;
}

function parseCommaSeparated(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function SurveyView({
  snapshot,
  busy,
  errorMessage,
  onStartSurvey,
  onReviseSurvey,
  onApproveSurvey,
  onDownloadMarkdown,
}: SurveyViewProps) {
  const [angle, setAngle] = useState("");
  const [audience, setAudience] = useState("");
  const [emphasis, setEmphasis] = useState("");
  const [comparisons, setComparisons] = useState("");
  const [revisionInputs, setRevisionInputs] = useState<Record<string, string>>({});

  useEffect(() => {
    setAngle(snapshot.survey_brief?.angle ?? "");
    setAudience(snapshot.survey_brief?.audience ?? "");
    setEmphasis((snapshot.survey_brief?.emphasis ?? []).join(", "));
    setComparisons((snapshot.survey_brief?.comparisons ?? []).join(", "));
  }, [snapshot.survey_brief]);

  const canStartSurvey =
    snapshot.allowed_actions.includes("start_survey") ||
    snapshot.allowed_actions.includes("submit_survey_brief") ||
    snapshot.allowed_actions.includes("skip_survey_brief") ||
    snapshot.current_checkpoint === "survey_brief";
  const canReviseSurvey = snapshot.allowed_actions.includes("revise_survey_sections");
  const canApproveSurvey = snapshot.allowed_actions.includes("approve_final_survey");
  const canDownloadSurvey =
    snapshot.allowed_actions.includes("download_survey_markdown") ||
    snapshot.survey_summary.markdown_ready;

  const revisionCount = useMemo(() => {
    return Object.values(revisionInputs).filter((value) => value.trim().length > 0).length;
  }, [revisionInputs]);

  async function handleGenerateWithBrief() {
    const brief: SurveyBrief = {
      angle: angle.trim() || null,
      audience: audience.trim() || null,
      emphasis: parseCommaSeparated(emphasis),
      comparisons: parseCommaSeparated(comparisons),
    };
    await onStartSurvey({ brief });
  }

  async function handleOpenBriefCheckpoint() {
    await onStartSurvey({});
  }

  async function handleSkipBrief() {
    await onStartSurvey({ skip: true });
  }

  async function handleSubmitRevisions() {
    const revisions = Object.entries(revisionInputs)
      .map(([section_id, feedback]) => ({ section_id, feedback: feedback.trim() }))
      .filter((item) => item.feedback.length > 0);
    if (revisions.length === 0) return;
    await onReviseSurvey(revisions);
    setRevisionInputs({});
  }

  return (
    <div className="panel-stack">

      {/* Survey brief */}
      <section className="action-panel">
        <div className="panel-header">
          <h3>Survey Brief</h3>
          <span className="helper-copy">
            brief {snapshot.survey_summary.brief_ready ? "ready" : "pending"} &nbsp;·&nbsp;
            clusters {snapshot.survey_summary.cluster_count}
          </span>
        </div>
        <div className="brief-grid">
          <div>
            <label className="field-label" htmlFor="survey-angle">Survey angle</label>
            <input
              id="survey-angle"
              className="text-input"
              value={angle}
              onChange={(event: ChangeEvent<HTMLInputElement>) => setAngle(event.target.value)}
              placeholder="Example: comparing transformer-based methods for vision tasks"
              disabled={busy}
            />
          </div>
          <div>
            <label className="field-label" htmlFor="survey-audience">Audience</label>
            <input
              id="survey-audience"
              className="text-input"
              value={audience}
              onChange={(event: ChangeEvent<HTMLInputElement>) => setAudience(event.target.value)}
              placeholder="Example: researchers planning a benchmark comparison"
              disabled={busy}
            />
          </div>
        </div>
        <label className="field-label" htmlFor="survey-emphasis">Emphasis</label>
        <input
          id="survey-emphasis"
          className="text-input"
          value={emphasis}
          onChange={(event: ChangeEvent<HTMLInputElement>) => setEmphasis(event.target.value)}
          placeholder="Comma-separated emphasis points"
          disabled={busy}
        />
        <label className="field-label" htmlFor="survey-comparisons">Comparisons of interest</label>
        <textarea
          id="survey-comparisons"
          className="text-input"
          rows={3}
          value={comparisons}
          onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setComparisons(event.target.value)}
          placeholder="Comma-separated comparisons, method lineages, or evaluation angles"
          disabled={busy}
        />
        <div className="action-row">
          <button className="primary-button" type="button" onClick={handleOpenBriefCheckpoint} disabled={busy || !canStartSurvey}>
            Open Brief Checkpoint
          </button>
          <button className="primary-button" type="button" onClick={handleGenerateWithBrief} disabled={busy || !canStartSurvey}>
            Generate With Brief
          </button>
          <button className="secondary-button" type="button" onClick={handleSkipBrief} disabled={busy || !canStartSurvey}>
            Skip Brief
          </button>
        </div>
      </section>

      {/* Summary tiles */}
      <div className="survey-summary-grid">
        <article className="summary-tile">
          <span className="stat-label">Sections</span>
          <strong>{snapshot.survey_summary.section_ids.length}</strong>
        </article>
        <article className="summary-tile">
          <span className="stat-label">Clusters</span>
          <strong>{snapshot.survey_summary.cluster_count}</strong>
        </article>
        <article className="summary-tile">
          <span className="stat-label">Markdown</span>
          <strong>{snapshot.survey_summary.markdown_ready ? "ready" : "—"}</strong>
        </article>
        <article className="summary-tile">
          <span className="stat-label">Status</span>
          <strong>{snapshot.status}</strong>
        </article>
      </div>

      {/* Theme clusters */}
      {snapshot.theme_clusters.length > 0 && (
        <section className="action-panel">
          <div className="panel-header">
            <h3>Theme Clusters</h3>
            <span className="helper-copy">{snapshot.theme_clusters.length} clusters</span>
          </div>
          <div className="cluster-grid">
            {snapshot.theme_clusters.map((cluster) => (
              <article className="cluster-card" key={cluster.cluster_id}>
                <h4>{cluster.title}</h4>
                <p>{cluster.description}</p>
                <span className="helper-copy">{cluster.paper_ids.length} paper(s)</span>
              </article>
            ))}
          </div>
        </section>
      )}

      {/* Survey sections */}
      {snapshot.survey_sections.length > 0 && (
        <section className="action-panel">
          <div className="panel-header">
            <h3>Survey Sections</h3>
            <span className="helper-copy">{snapshot.survey_sections.length} drafted</span>
          </div>
          <div className="survey-section-list">
            {snapshot.survey_sections.map((section) => (
              <article className="survey-section-card" key={section.section_id}>
                <div className="panel-header">
                  <div>
                    <h4>{section.title}</h4>
                    <p className="paper-meta">
                      revision {section.revision_count} &nbsp;·&nbsp; {section.accepted ? "accepted" : "draft"}
                    </p>
                  </div>
                  <span className="helper-copy">{section.paper_ids.length} paper(s)</span>
                </div>
                <pre className="markdown-preview markdown-preview-section">{section.content_markdown}</pre>
                <label className="field-label" htmlFor={`revision-${section.section_id}`}>
                  Revision note
                </label>
                <textarea
                  id={`revision-${section.section_id}`}
                  className="text-input"
                  rows={3}
                  value={revisionInputs[section.section_id] ?? ""}
                  onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
                    setRevisionInputs((current: Record<string, string>) => ({
                      ...current,
                      [section.section_id]: event.target.value,
                    }))
                  }
                  placeholder="Example: compare the datasets more directly in this section"
                  disabled={busy || !canReviseSurvey}
                />
              </article>
            ))}
          </div>
          <div className="action-row">
            <button
              className="primary-button"
              type="button"
              onClick={handleSubmitRevisions}
              disabled={busy || !canReviseSurvey || revisionCount === 0}
            >
              Submit Section Revisions
            </button>
            <span className="helper-copy">{revisionCount} section(s) queued</span>
          </div>
        </section>
      )}

      {/* Final survey */}
      {snapshot.final_survey_document && (
        <section className="action-panel">
          <div className="panel-header">
            <h3>Final Survey Markdown</h3>
            <span className="helper-copy">
              {snapshot.final_survey_document.sections.length} section(s)
            </span>
          </div>
          <div className="action-row">
            <button className="primary-button" type="button" onClick={onApproveSurvey} disabled={busy || !canApproveSurvey}>
              Approve Final Survey
            </button>
            <button className="secondary-button" type="button" onClick={onDownloadMarkdown} disabled={busy || !canDownloadSurvey}>
              Download Markdown
            </button>
          </div>
          <pre className="markdown-preview">{snapshot.final_survey_document.markdown}</pre>
        </section>
      )}

      {/* Interrupt */}
      {snapshot.pending_interrupt && snapshot.current_phase === "survey" && (
        <section className="interrupt-panel">
          <h3>Pending Interrupt</h3>
          <p>{snapshot.pending_interrupt.message}</p>
        </section>
      )}

      {errorMessage && <p className="error-banner">{errorMessage}</p>}
    </div>
  );
}
