import type {
  SessionSnapshot,
  SimulationTelemetry,
  TextCommandPayload,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.message || `请求失败（HTTP ${response.status}）`);
  }
  return payload as T;
}

export const api = {
  createSession: () =>
    request<SessionSnapshot>("/api/sessions", { method: "POST" }),
  getSession: (sessionId: string) =>
    request<SessionSnapshot>(`/api/sessions/${sessionId}`),
  submitText: (sessionId: string, payload: TextCommandPayload) =>
    request<SessionSnapshot>(`/api/sessions/${sessionId}/commands/text`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  action: (sessionId: string, action: string) =>
    request<SessionSnapshot>(`/api/sessions/${sessionId}/${action}`, {
      method: "POST",
    }),
  telemetry: (sessionId: string) =>
    request<SimulationTelemetry>(
      `/api/sessions/${sessionId}/simulation/telemetry`,
    ),
  videoUrl: (sessionId: string, attempt = 0) =>
    `/api/sessions/${sessionId}/simulation/stream.mjpeg?attempt=${attempt}`,
};

export function openSessionSocket(
  sessionId: string,
  onSnapshot: (snapshot: SessionSnapshot) => void,
  onTelemetry: (telemetry: SimulationTelemetry) => void,
  onConnection: (connected: boolean) => void,
): WebSocket {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(
    `${protocol}//${window.location.host}/ws/sessions/${sessionId}`,
  );
  socket.onopen = () => onConnection(true);
  socket.onclose = () => onConnection(false);
  socket.onerror = () => socket.close();
  socket.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (payload?.type === "telemetry") onTelemetry(payload);
    else onSnapshot(payload);
  };
  return socket;
}

export function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("读取图片失败"));
    reader.readAsDataURL(file);
  });
}
