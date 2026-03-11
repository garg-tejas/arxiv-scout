import { StreamEvent } from "../api/client";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const EVENT_TYPES = [
  "phase_started",
  "node_update",
  "interrupt",
  "artifact_ready",
  "error",
  "phase_completed",
] as const;

export class SessionStream {
  private eventSource: EventSource | null = null;

  connect(
    sessionId: string,
    onEvent: (event: StreamEvent) => void,
    onError?: (event: Event) => void,
  ) {
    this.eventSource = new EventSource(`${API_BASE}/sessions/${sessionId}/stream`);
    const handleMessage = (event: MessageEvent<string>) => {
      try {
        onEvent(JSON.parse(event.data) as StreamEvent);
      } catch (error) {
        console.error("Failed to parse session stream event", error);
      }
    };
    for (const eventType of EVENT_TYPES) {
      this.eventSource.addEventListener(eventType, handleMessage as EventListener);
    }
    this.eventSource.onmessage = handleMessage;
    this.eventSource.onerror = (event) => {
      onError?.(event);
    };
    return this.eventSource;
  }

  disconnect() {
    this.eventSource?.close();
    this.eventSource = null;
  }
}
