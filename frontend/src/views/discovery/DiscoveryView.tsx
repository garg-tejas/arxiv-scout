import { SessionSnapshot } from "../../api/client";

interface DiscoveryViewProps {
  snapshot: SessionSnapshot;
}

export function DiscoveryView({ snapshot }: DiscoveryViewProps) {
  return (
    <article className="phase-card">
      <div className="snapshot-pill">Phase: Discovery</div>
      <h2>Discovery View</h2>
      <p>
        This checkpoint only establishes the component boundary. Topic
        confirmation, shortlist review, approvals, and nudges arrive in later
        checkpoints.
      </p>
      <ul>
        <li>Session status: {snapshot.status}</li>
        <li>Current checkpoint: {snapshot.current_checkpoint}</li>
        <li>Approved papers: {snapshot.approved_papers.length}</li>
      </ul>
    </article>
  );
}
