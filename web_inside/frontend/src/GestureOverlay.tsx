import { useEffect, useRef, useState } from "react";
import type { SimulationTelemetry } from "./types";
import "./gesture.css";

const SAMPLE_GAP_MS = 80;
const HEARTBEAT_MS = 350;
const JPEG_QUALITY = 0.76;
const CONTROL_PANEL_EVENT = "interns2:control-panel-open";

type GestureName =
  | "up" | "down" | "left" | "right" | "forward" | "backward"
  | "stop" | "estop" | "none" | "uncertain";

type GestureDecision =
  | "accepted" | "paused" | "ignored" | "suppressed_voice"
  | "suppressed_busy" | "suppressed_latched" | "suppressed_cooldown"
  | "safety_stop" | "safety_estop";

type GestureControlStatus = {
  active: boolean;
  mode: "simulation" | "real";
  moving: boolean;
  gesture: GestureName | null;
  reason: string;
};

type GestureResponse = {
  recognition: {
    gesture: GestureName;
    confidence: number;
    hand_detected: boolean;
    model: string;
    latency_ms: number;
  };
  decision: GestureDecision;
  message: string;
};

const gestureLabels: Record<GestureName, string> = {
  up: "向上 · +Z",
  down: "向下 · −Z",
  left: "向左 · +Y",
  right: "向右 · −Y",
  forward: "向前 · +X",
  backward: "向后 · −X",
  stop: "停止",
  estop: "紧急停止",
  none: "未检测到手势",
  uncertain: "手势不明确",
};

async function jsonRequest<T>(path: string, method = "GET", body?: object): Promise<T> {
  const response = await fetch(path, {
    method,
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.message ?? payload.detail ?? `请求失败 (${response.status})`);
  }
  return payload as T;
}

export default function GestureOverlay({ sessionId, runtimeMode, telemetry }: {
  sessionId: string | null;
  runtimeMode: "real" | "simulation";
  telemetry: SimulationTelemetry | null;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<number | null>(null);
  const inFlightRef = useRef(false);
  const activeRef = useRef(false);
  const mountedRef = useRef(true);
  const fabRef = useRef<HTMLButtonElement | null>(null);
  const drawerRef = useRef<HTMLElement | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(false);
  const [starting, setStarting] = useState(false);
  const [cameraReady, setCameraReady] = useState(false);
  const [status, setStatus] = useState<GestureControlStatus | null>(null);
  const [result, setResult] = useState<GestureResponse | null>(null);
  const [error, setError] = useState("");

  const endpoint = (suffix = "") =>
    `/api/sessions/${encodeURIComponent(sessionId ?? "")}/gesture${suffix}`;

  const stopCamera = () => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = null;
    streamRef.current?.getTracks().forEach(track => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    inFlightRef.current = false;
    activeRef.current = false;
    setActive(false);
    setCameraReady(false);
  };

  const release = async (close = false) => {
    stopCamera();
    if (sessionId) {
      try {
        await jsonRequest(endpoint("/reset"), "POST", {});
      } catch (caught) {
        if (mountedRef.current) setError(caught instanceof Error ? caught.message : String(caught));
      }
    }
    if (mountedRef.current) {
      setStatus(null);
      setResult(null);
      if (close) {
        setOpen(false);
        window.requestAnimationFrame(() => fabRef.current?.focus());
      }
    }
  };

  const captureAndClassify = async () => {
    if (!activeRef.current || inFlightRef.current || document.hidden || !sessionId) return;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || video.readyState < 2) return;
    const width = Math.min(512, video.videoWidth || 512);
    const sourceWidth = video.videoWidth || width;
    const sourceHeight = video.videoHeight || 384;
    const height = Math.max(1, Math.round((sourceHeight / sourceWidth) * width));
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) return;
    context.save();
    context.translate(width, 0);
    context.scale(-1, 1);
    context.drawImage(video, 0, 0, width, height);
    context.restore();
    inFlightRef.current = true;
    try {
      const response = await jsonRequest<GestureResponse>(
        `/api/sessions/${encodeURIComponent(sessionId)}/commands/gesture`,
        "POST",
        { image_data_url: canvas.toDataURL("image/jpeg", JPEG_QUALITY), captured_at_ms: Date.now() },
      );
      if (mountedRef.current && activeRef.current) {
        setResult(response);
        setError("");
      }
    } catch (caught) {
      if (mountedRef.current && activeRef.current) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    } finally {
      inFlightRef.current = false;
      if (activeRef.current) {
        timerRef.current = window.setTimeout(() => void captureAndClassify(), SAMPLE_GAP_MS);
      }
    }
  };

  const start = async () => {
    if (!sessionId || starting) return;
    setStarting(true);
    setError("");
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setError("摄像头需要通过 localhost 或 HTTPS 打开页面。请使用 SSH 隧道后的本机地址。");
      setStarting(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 20, max: 30 } },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      const acquired = await jsonRequest<GestureControlStatus>(endpoint("/acquire"), "POST", {});
      if (!mountedRef.current) return;
      setStatus(acquired);
      setCameraReady(true);
      activeRef.current = true;
      setActive(true);
      void captureAndClassify();
    } catch (caught) {
      stopCamera();
      setError(caught instanceof Error ? caught.message : String(caught));
      if (sessionId) void jsonRequest(endpoint("/reset"), "POST", {}).catch(() => undefined);
    } finally {
      if (mountedRef.current) setStarting(false);
    }
  };

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    if (!active || !sessionId) return;
    let heartbeatBusy = false;
    const beat = async () => {
      if (heartbeatBusy || !activeRef.current) return;
      heartbeatBusy = true;
      try {
        const next = await jsonRequest<GestureControlStatus>(endpoint("/heartbeat"), "POST", {});
        if (mountedRef.current) setStatus(next);
      } catch (caught) {
        if (mountedRef.current) setError(caught instanceof Error ? caught.message : String(caught));
        stopCamera();
      } finally {
        heartbeatBusy = false;
      }
    };
    const heartbeat = window.setInterval(() => void beat(), HEARTBEAT_MS);
    return () => window.clearInterval(heartbeat);
  }, [active, sessionId]);

  useEffect(() => {
    const onPanelOpen = (event: Event) => {
      const selected = (event as CustomEvent<string>).detail;
      if (selected === "manual" && open) void release(true);
    };
    window.addEventListener(CONTROL_PANEL_EVENT, onPanelOpen);
    return () => window.removeEventListener(CONTROL_PANEL_EVENT, onPanelOpen);
  }, [open, sessionId]);

  useEffect(() => {
    const onHidden = () => { if (document.hidden && activeRef.current) void release(false); };
    window.addEventListener("blur", onHidden);
    document.addEventListener("visibilitychange", onHidden);
    return () => {
      window.removeEventListener("blur", onHidden);
      document.removeEventListener("visibilitychange", onHidden);
    };
  }, [sessionId]);

  useEffect(() => {
    void release(false);
  }, [sessionId, runtimeMode]);

  useEffect(() => () => {
    stopCamera();
    if (sessionId) {
      void fetch(endpoint("/reset"), { method: "POST", keepalive: true, headers: { "Content-Type": "application/json" }, body: "{}" }).catch(() => undefined);
    }
  }, [sessionId]);

  const point = telemetry?.actual_tcp_robot_base?.translation_mm
    ?? (telemetry?.current_tcp ? [telemetry.current_tcp.x, telemetry.current_tcp.y, telemetry.current_tcp.z] : null);

  return <>
    {!open && <button ref={fabRef} type="button" className="gesture-fab" aria-label="手势控制" aria-expanded={false}
      onClick={() => {
        window.dispatchEvent(new CustomEvent(CONTROL_PANEL_EVENT, { detail: "gesture" }));
        setOpen(true); setError("");
      }}>
      <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M8.5 6 10 4h4l1.5 2H19a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h3.5Z"/><circle cx="12" cy="12.5" r="3.5"/></svg>
      <strong>手势控制</strong>
    </button>}
    {open && <aside ref={drawerRef} className="gesture-drawer" aria-label="手势控制面板" tabIndex={-1}>
      <div className="gesture-header">
        <div><span>VISION CONTROL</span><h2>手势控制</h2></div>
        <span className="gesture-mode">{runtimeMode === "simulation" ? "仿真" : "真机"}</span>
        <button type="button" className="gesture-close" aria-label="关闭手势控制" onClick={() => void release(true)}>×</button>
      </div>
      <div className="gesture-ownership">
        <span role="status">{active ? (result?.decision === "paused" ? "识别暂停" : "正在随动") : "未接管"}</span>
        <button type="button" disabled={starting || !sessionId} onClick={() => active ? void release(false) : void start()}>
          {starting ? "正在连接…" : active ? "退出手势控制" : "启动手势控制"}
        </button>
      </div>
      <div className="gesture-scroll">
        <section className="gesture-camera-stage">
          <video ref={videoRef} muted playsInline className="gesture-preview" />
          {!cameraReady && <div><strong>摄像头尚未启动</strong><span>启动后，识别结果将直接驱动机械臂</span></div>}
          {active && <span className="gesture-live"><i /> LIVE</span>}
        </section>
        <canvas ref={canvasRef} hidden />
        <section className="gesture-follow-rule">
          <strong>同步随动</strong>
          <span>识别到方向立即运动 · 手势丢失立即暂停 · 改变手势立即换向</span>
          <small>普通方向无需二次确认；停止与急停手势始终优先。</small>
        </section>
        {result && <section className={`gesture-result ${result.decision}`}>
          <div><strong>{gestureLabels[result.recognition.gesture]}</strong><b>{(result.recognition.confidence * 100).toFixed(0)}%</b></div>
          <span>InternS2 视觉识别 · {result.recognition.latency_ms} ms</span>
          <p>{result.message}</p>
        </section>}
        {error && <div className="gesture-error" role="alert">{error}</div>}
        <details className="gesture-protocol">
          <summary>固定手势说明</summary>
          <div className="gesture-protocol-grid">
            <span>☝ 上：+Z</span><span>👇 下：−Z</span>
            <span>👈 左：+Y</span><span>👉 右：−Y</span>
            <span>👍 前：+X</span><span>👎 后：−X</span>
            <span>👌 停止</span><span>✋ 紧急停止</span>
          </div>
        </details>
        <div className="gesture-position">{point ? point.map((value, index) => <span key={index}>{["X", "Y", "Z"][index]} <b>{Number(value).toFixed(2)}</b> mm</span>) : "正在读取实际位置"}</div>
      </div>
      <div className="gesture-footer">
        <button type="button" className="gesture-stop" disabled={!active} onClick={() => void release(false)}>■ 停止手势随动</button>
        <small>{status?.reason || "手势与手动、文本任务互斥 · 不经过文本模型解析"}</small>
      </div>
    </aside>}
  </>;
}
