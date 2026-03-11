import { SessionSnapshot } from "../../api/client";

interface AnalysisViewProps {
  snapshot: SessionSnapshot;
}

export function AnalysisView({ snapshot }: AnalysisViewProps) {
  return (
    <article className="phase-card">
      <div className="snapshot-pill">Phase: Analysis</div>
      <h2>Analysis View</h2>
      <p>
        This placeholder keeps the file boundary stable for the analysis
        selection checkpoint, structured summaries, and graph visualization.
      </p>
      <ul>
        <li>Selected papers: {snapshot.analysis_summary.selected_paper_ids.length}</li>
        <li>Completed: {String(snapshot.analysis_summary.completed)}</li>
      </ul>
    </article>
  );
}
