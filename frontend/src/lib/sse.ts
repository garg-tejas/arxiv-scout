const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class SessionStream {
  private eventSource: EventSource | null = null;

  connect(sessionId: string, onMessage: (event: MessageEvent<string>) => void) {
    this.eventSource = new EventSource(`${API_BASE}/sessions/${sessionId}/stream`);
    this.eventSource.onmessage = onMessage;
    return this.eventSource;
  }

  disconnect() {
    this.eventSource?.close();
    this.eventSource = null;
  }
}
