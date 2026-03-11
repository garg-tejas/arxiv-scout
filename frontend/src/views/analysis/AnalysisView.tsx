import { useEffect, useMemo, useState } from "react";

import { CuratedPaper, SessionSnapshot } from "../../api/client";

interface AnalysisViewProps {
  snapshot: SessionSnapshot;
  busy: boolean;
  errorMessage: string | null;
  onStartAnalysis: (paperIds: string[]) => Promise<void>;
}

const ANALYSIS_CAP = 8;

function resolveApprovedPapers(snapshot: SessionSnapshot): CuratedPaper[] {
  if (snapshot.approved_paper_details.length > 0) {
    return snapshot.approved_paper_details;
  }
  const shortlistMap = new Map(snapshot.latest_shortlist.map((paper) => [paper.paper_id, paper]));
  return snapshot.approved_papers
    .map((paperId) => shortlistMap.get(paperId))
    .filter((paper): paper is CuratedPaper => Boolean(paper));
}

function summarizeList(items: string[], fallback: string) {
  return items.length > 0 ? items.join(", ") : fallback;
}

function buildGraphPositions(seedCount: number, contextCount: number) {
  const seedSpacing = seedCount > 1 ? 280 / (seedCount - 1) : 0;
  const contextSpacing = contextCount > 1 ? 280 / (contextCount - 1) : 0;
  const seedY = 72;
  const contextY = 212;
  return {
    seedX: (index: number) => 40 + seedSpacing * index,
    contextX: (index: number) => 40 + contextSpacing * index,
    seedY,
    contextY,
  };
}

export function AnalysisView({
  snapshot,
  busy,
  errorMessage,
  onStartAnalysis,
}: AnalysisViewProps) {
  const approvedPapers = useMemo(() => resolveApprovedPapers(snapshot), [snapshot]);
  const [selectedPaperIds, setSelectedPaperIds] = useState<string[]>([]);

  useEffect(() => {
    if (snapshot.current_checkpoint === "analysis_selection") {
      if (snapshot.analysis_summary.selected_paper_ids.length > 0) {
        setSelectedPaperIds(snapshot.analysis_summary.selected_paper_ids);
      } else {
        setSelectedPaperIds(approvedPapers.slice(0, ANALYSIS_CAP).map((paper) => paper.paper_id));
      }
      return;
    }
    if (snapshot.analysis_summary.selected_paper_ids.length > 0) {
      setSelectedPaperIds(snapshot.analysis_summary.selected_paper_ids);
      return;
    }
    if (approvedPapers.length <= ANALYSIS_CAP) {
      setSelectedPaperIds(approvedPapers.map((paper) => paper.paper_id));
    } else {
      setSelectedPaperIds(approvedPapers.slice(0, ANALYSIS_CAP).map((paper) => paper.paper_id));
    }
  }, [approvedPapers, snapshot.analysis_summary.selected_paper_ids, snapshot.current_checkpoint]);

  const approvedMap = useMemo(
    () => new Map(approvedPapers.map((paper) => [paper.paper_id, paper])),
    [approvedPapers],
  );
  const canStartAnalysis =
    snapshot.allowed_actions.includes("start_analysis") ||
    snapshot.allowed_actions.includes("select_analysis_papers") ||
    snapshot.current_checkpoint === "analysis_selection";
  const overCap = approvedPapers.length > ANALYSIS_CAP;

  function toggleSelection(paperId: string) {
    setSelectedPaperIds((current) => {
      if (current.includes(paperId)) {
        return current.filter((value) => value !== paperId);
      }
      if (current.length >= ANALYSIS_CAP) {
        return current;
      }
      return [...current, paperId];
    });
  }

  async function handleAnalyzeSelected() {
    if (selectedPaperIds.length === 0) {
      return;
    }
    await onStartAnalysis(selectedPaperIds);
  }

  const seedNodes = snapshot.citation_graph?.seed_nodes ?? [];
  const contextNodes = snapshot.citation_graph?.context_nodes ?? [];
  const graphPositions = buildGraphPositions(seedNodes.length, contextNodes.length);
  const edgeLines = useMemo(() => {
    if (!snapshot.citation_graph) {
      return [];
    }
    const coords = new Map<string, { x: number; y: number }>();
    seedNodes.forEach((node, index) => {
      coords.set(node.node_id, { x: graphPositions.seedX(index), y: graphPositions.seedY });
    });
    contextNodes.forEach((node, index) => {
      coords.set(node.node_id, { x: graphPositions.contextX(index), y: graphPositions.contextY });
    });
    return snapshot.citation_graph.edges
      .map((edge) => {
        const source = coords.get(edge.source);
        const target = coords.get(edge.target);
        if (!source || !target) {
          return null;
        }
        return {
          ...edge,
          x1: source.x,
          y1: source.y,
          x2: target.x,
          y2: target.y,
        };
      })
      .filter((edge): edge is NonNullable<typeof edge> => Boolean(edge));
  }, [contextNodes, graphPositions, seedNodes, snapshot.citation_graph]);

  return (
    <article className="phase-card analysis-card">
      <div className="snapshot-pill">Phase: Analysis</div>
      <h2>Analysis View</h2>
      <p className="phase-copy">
        Choose approved papers to analyze, inspect extracted summaries, and review the
        citation lineage graph built from the analyzed set.
      </p>

      <section className="panel-stack">
        <section className="action-panel">
          <div className="panel-header">
            <h3>Analysis Selection</h3>
            <span className="helper-copy">
              {approvedPapers.length} approved - max {ANALYSIS_CAP} per run
            </span>
          </div>
          {approvedPapers.length > 0 ? (
            <>
              {overCap && (
                <p className="inline-note">
                  More than {ANALYSIS_CAP} papers are approved. Select a subset before
                  starting analysis.
                </p>
              )}
              <div className="selection-grid">
                {approvedPapers.map((paper) => {
                  const selected = selectedPaperIds.includes(paper.paper_id);
                  const disabled = busy || (!selected && selectedPaperIds.length >= ANALYSIS_CAP);
                  return (
                    <label
                      className={`selection-card ${selected ? "selection-card-selected" : ""}`}
                      key={paper.paper_id}
                    >
                      <input
                        type="checkbox"
                        checked={selected}
                        onChange={() => toggleSelection(paper.paper_id)}
                        disabled={disabled}
                      />
                      <div>
                        <strong>{paper.title}</strong>
                        <span className="paper-meta">
                          {paper.year ?? "Unknown year"} - {paper.paper_id}
                        </span>
                      </div>
                    </label>
                  );
                })}
              </div>
              <div className="action-row">
                <button
                  className="primary-button"
                  type="button"
                  onClick={handleAnalyzeSelected}
                  disabled={busy || !canStartAnalysis || selectedPaperIds.length === 0}
                >
                  {snapshot.current_checkpoint === "analysis_selection"
                    ? "Run Selected Papers"
                    : "Start Analysis"}
                </button>
                <span className="helper-copy">{selectedPaperIds.length} selected</span>
              </div>
            </>
          ) : (
            <p className="helper-copy">Approve papers in Discovery before starting analysis.</p>
          )}
        </section>

        <section className="analysis-summary-grid">
          <article className="summary-tile">
            <span className="stat-label">Selected</span>
            <strong>{snapshot.analysis_summary.selected_paper_ids.length}</strong>
          </article>
          <article className="summary-tile">
            <span className="stat-label">Degraded</span>
            <strong>{snapshot.analysis_summary.degraded_paper_ids.length}</strong>
          </article>
          <article className="summary-tile">
            <span className="stat-label">Context Nodes</span>
            <strong>{snapshot.analysis_summary.retained_context_node_count}</strong>
          </article>
          <article className="summary-tile">
            <span className="stat-label">Lineage Paths</span>
            <strong>{snapshot.analysis_summary.lineage_path_count}</strong>
          </article>
        </section>

        {snapshot.paper_analyses.length > 0 && (
          <section className="action-panel">
            <div className="panel-header">
              <h3>Per-Paper Summaries</h3>
              <span className="helper-copy">
                {snapshot.analysis_summary.completed ? "completed" : "running"}
              </span>
            </div>
            <div className="analysis-grid">
              {snapshot.paper_analyses.map((analysis) => {
                const paper = approvedMap.get(analysis.paper_id);
                const degraded = snapshot.analysis_summary.degraded_paper_ids.includes(analysis.paper_id);
                return (
                  <article className="analysis-paper-card" key={analysis.paper_id}>
                    <div className="panel-header">
                      <div>
                        <h4>{paper?.title ?? analysis.paper_id}</h4>
                        <p className="paper-meta">{analysis.paper_id}</p>
                      </div>
                      <span
                        className={`quality-badge ${
                          degraded ? "quality-badge-degraded" : "quality-badge-full"
                        }`}
                      >
                        {analysis.analysis_quality}
                      </span>
                    </div>
                    <p className="analysis-claim">{analysis.core_claim ?? "No core claim extracted."}</p>
                    <ul className="compact-list">
                      <li>Method: {summarizeList(analysis.methodology, "No methodology extracted")}</li>
                      <li>Datasets: {summarizeList(analysis.datasets, "No datasets extracted")}</li>
                      <li>Metrics: {summarizeList(analysis.metrics, "No metrics extracted")}</li>
                      <li>Benchmarks: {summarizeList(analysis.benchmarks, "No benchmarks extracted")}</li>
                      <li>Limitations: {summarizeList(analysis.limitations, "No limitations extracted")}</li>
                    </ul>
                  </article>
                );
              })}
            </div>
          </section>
        )}

        {snapshot.method_comparison_table.length > 0 && (
          <section className="action-panel">
            <div className="panel-header">
              <h3>Method Comparison Table</h3>
              <span className="helper-copy">{snapshot.method_comparison_table.length} rows</span>
            </div>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Paper</th>
                    <th>Quality</th>
                    <th>Model</th>
                    <th>Datasets</th>
                    <th>Metrics</th>
                    <th>Limitation</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.method_comparison_table.map((row) => (
                    <tr key={row.paper_id}>
                      <td>{row.title}</td>
                      <td>{row.analysis_quality}</td>
                      <td>{row.model_type ?? "Unknown"}</td>
                      <td>{summarizeList(row.datasets, "None found")}</td>
                      <td>{summarizeList(row.metrics, "None found")}</td>
                      <td>{row.primary_limitation ?? "None found"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {snapshot.citation_graph && (
          <section className="action-panel">
            <div className="panel-header">
              <h3>Citation Graph</h3>
              <span className="helper-copy">
                {seedNodes.length} seed nodes - {contextNodes.length} context nodes
              </span>
            </div>
            {snapshot.analysis_summary.citation_graph_summary && (
              <p className="inline-note">{snapshot.analysis_summary.citation_graph_summary}</p>
            )}
            <div className="graph-wrap">
              <svg viewBox="0 0 360 260" className="graph-canvas" role="img" aria-label="Citation graph">
                {edgeLines.map((edge) => (
                  <line
                    key={edge.edge_id}
                    x1={edge.x1}
                    y1={edge.y1}
                    x2={edge.x2}
                    y2={edge.y2}
                    className={`graph-edge graph-edge-${edge.evidence_level}`}
                  />
                ))}
                {seedNodes.map((node, index) => (
                  <g key={node.node_id} transform={`translate(${graphPositions.seedX(index)}, ${graphPositions.seedY})`}>
                    <circle r="18" className="graph-node graph-node-seed" />
                    <text y="5" textAnchor="middle" className="graph-label">
                      S{index + 1}
                    </text>
                  </g>
                ))}
                {contextNodes.map((node, index) => (
                  <g
                    key={node.node_id}
                    transform={`translate(${graphPositions.contextX(index)}, ${graphPositions.contextY})`}
                  >
                    <rect x="-18" y="-18" width="36" height="36" rx="8" className="graph-node graph-node-context" />
                    <text y="5" textAnchor="middle" className="graph-label">
                      C{index + 1}
                    </text>
                  </g>
                ))}
              </svg>
              <div className="graph-legend">
                <div>
                  <h4>Seeds</h4>
                  <ul className="compact-list">
                    {seedNodes.map((node, index) => (
                      <li key={node.node_id}>
                        S{index + 1}: {node.title}
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h4>Context</h4>
                  <ul className="compact-list">
                    {contextNodes.map((node, index) => (
                      <li key={node.node_id}>
                        C{index + 1}: {node.title}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
            <div className="edge-grid">
              {snapshot.citation_graph.edges.map((edge) => (
                <article className="edge-card" key={edge.edge_id}>
                  <strong>{edge.relation}</strong>
                  <span>{edge.source} -&gt; {edge.target}</span>
                  <span className="helper-copy">{edge.evidence_level}</span>
                </article>
              ))}
            </div>
            {snapshot.citation_graph.lineage_paths.length > 0 && (
              <div className="lineage-list">
                <h4>Lineage Paths</h4>
                <ul className="compact-list">
                  {snapshot.citation_graph.lineage_paths.map((path, index) => (
                    <li key={`${path.summary}-${index}`}>{path.summary}</li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        )}

        {errorMessage && <p className="error-banner">{errorMessage}</p>}
      </section>
    </article>
  );
}
