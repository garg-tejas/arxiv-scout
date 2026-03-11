import { SessionSnapshot } from "../../api/client";

interface SurveyViewProps {
  snapshot: SessionSnapshot;
}

export function SurveyView({ snapshot }: SurveyViewProps) {
  return (
    <article className="phase-card">
      <div className="snapshot-pill">Phase: Survey</div>
      <h2>Survey View</h2>
      <p>
        This placeholder reserves the path for the brief form, section review
        loop, and Markdown export UI.
      </p>
      <ul>
        <li>Sections: {snapshot.survey_summary.section_ids.length}</li>
        <li>Completed: {String(snapshot.survey_summary.completed)}</li>
      </ul>
    </article>
  );
}
