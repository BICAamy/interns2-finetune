import { useEffect, useRef, useState } from "react";

const SESSION_KEY = "interns2-surgical-session";
const SAMPLE_INTERVAL_MS = 1100;
const JPEG_QUALITY = 0.78;

type GestureName =
  | "up"
  | "down"
  | "left"
  | "right"
  | "forward"
  | "backward"
  | "stop"
  | "estop"
  | "none"
  | "uncertain";

type GestureDecision =
  | "accepted"
  | "ignored"
  | "suppressed_voice"
  | "suppressed_busy"
  | "suppressed_latched"
  | "suppressed_cooldown"
  | "safety_stop"
  | "safety_estop";

interface GestureResponse {
  recognition: {
    gesture: GestureName;
    confidence: number;
    hand_detected: boolean;
    model: string;
    latency_ms: number;
  };
  decision: GestureDecision;
  message: string;
  mapped_command?: Record<string, any> | null;
  session_snapshot?: Record<string, any> | null;
}

const gestureLabels: Record<GestureName, string> = {
  up: "食指向上",
  down: "食指向下",
  left: "食指向自己的左侧",
  right: "食指向自己的右侧",
  forward: "食指指向摄像头",
  backward: "大拇指指向自己的胸口",
  stop: "圆圈 · 停止",
  estop: "张开手掌 · 急停",
  none: "未检测到手势",
  uncertain: "手势不明确",
};

async function jsonRequest<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.message || `HTTP ${response.status}`);
  }
  return payload as T;
}

function currentSessionId(): string | null {
  return sessionStorage.getItem(SESSION_KEY);
}

export default function GestureOverlay() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<number | null>(null);
  const requestInFlight = useRef(false);
  const voiceActiveRef = useRef(false);
  const [enabled, setEnabled] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [result, setResult] = useState<GestureResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cameraReady, setCameraReady] = useState(false);

  async function reportVoiceActivity(active: boolean) {
    const sessionId = currentSessionId();
    if (!sessionId || voiceActiveRef.current === active) return;
    voiceActiveRef.current = active;
    try {
      await jsonRequest(
        `/api/sessions/${sessionId}/gesture/voice-activity`,
        { method: "PUT", body: JSON.stringify({ active }) },
      );
    } catch {
      // Voice reporting must never break the existing Step 13 microphone UI.
    }
  }

  useEffect(() => {
    if (!enabled) return;
    const observer = new MutationObserver(() => {
      const recording = Boolean(document.querySelector("button.voice.recording"));
      void reportVoiceActivity(recording);
    });
    observer.observe(document.body, {
      attributes: true,
      childList: true,
      subtree: true,
      attributeFilter: ["class"],
    });
    void reportVoiceActivity(Boolean(document.querySelector("button.voice.recording")));
    return () => {
      observer.disconnect();
      void reportVoiceActivity(false);
    };
  }, [enabled]);

  async function captureAndClassify() {
    if (!enabled || requestInFlight.current || document.hidden) return;
    if (voiceActiveRef.current) return;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    const sessionId = currentSessionId();
    if (!video || !canvas || !sessionId || video.readyState < 2) return;
    const width = Math.min(640, video.videoWidth || 640);
    const sourceWidth = video.videoWidth || width;
    const sourceHeight = video.videoHeight || 480;
    const height = Math.max(1, Math.round((sourceHeight / sourceWidth) * width));
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) return;

    // Deliberately do NOT mirror the canvas. The visible preview is mirrored by
    // CSS only; InternS2 receives the raw frame so operator-view left/right is
    // stable and auditable.
    context.drawImage(video, 0, 0, width, height);
    const imageDataUrl = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
    requestInFlight.current = true;
    try {
      const response = await jsonRequest<GestureResponse>(
        `/api/sessions/${sessionId}/commands/gesture`,
        {
          method: "POST",
          body: JSON.stringify({
            image_data_url: imageDataUrl,
            captured_at_ms: Date.now(),
          }),
        },
      );
      setResult(response);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      requestInFlight.current = false;
    }
  }

  async function start() {
    setError(null);
    if (!window.isSecureContext) {
      setError("摄像头要求安全页面，请通过 SSH 转发后使用 localhost 打开控制台。");
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("当前浏览器不支持摄像头访问。");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: "user",
          width: { ideal: 640 },
          height: { ideal: 480 },
          frameRate: { ideal: 15, max: 20 },
        },
        audio: false,
      });
      streamRef.current = stream;
      const video = videoRef.current;
      if (video) {
        video.srcObject = stream;
        await video.play();
      }
      setCameraReady(true);
      setEnabled(true);
      const sessionId = currentSessionId();
      if (sessionId) {
        await jsonRequest(`/api/sessions/${sessionId}/gesture/reset`, {
          method: "POST",
          body: "{}",
        }).catch(() => undefined);
      }
    } catch (caught) {
      const name = caught instanceof DOMException ? caught.name : "";
      setError(
        name === "NotAllowedError"
          ? "摄像头权限被拒绝；文本和语音功能不受影响。"
          : "无法打开摄像头，请确认设备没有被其他程序占用。",
      );
      setCameraReady(false);
      setEnabled(false);
    }
  }

  function stop() {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraReady(false);
    setEnabled(false);
    requestInFlight.current = false;
    void reportVoiceActivity(false);
    const sessionId = currentSessionId();
    if (sessionId) {
      void jsonRequest(`/api/sessions/${sessionId}/gesture/reset`, {
        method: "POST",
        body: "{}",
      }).catch(() => undefined);
    }
  }

  useEffect(() => {
    if (!enabled || !cameraReady) return;
    timerRef.current = window.setInterval(() => void captureAndClassify(), SAMPLE_INTERVAL_MS);
    void captureAndClassify();
    return () => {
      if (timerRef.current !== null) {
        window.clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [enabled, cameraReady]);

  useEffect(() => {
    const onVisibility = () => {
      if (document.hidden) {
        const sessionId = currentSessionId();
        if (sessionId) {
          void jsonRequest(`/api/sessions/${sessionId}/gesture/reset`, {
            method: "POST",
            body: "{}",
          }).catch(() => undefined);
        }
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => () => stop(), []);

  return (
    <aside className={`gesture-overlay ${collapsed ? "collapsed" : ""}`}>
      <div className="gesture-overlay-heading">
        <div>
          <strong>Step 14 · 手势控制</strong>
          <span>InternS2 视觉识别 · 操作者自身视角</span>
        </div>
        <button onClick={() => setCollapsed((value) => !value)}>
          {collapsed ? "展开" : "收起"}
        </button>
      </div>
      {!collapsed && (
        <>
          <div className="gesture-camera-stage">
            <video ref={videoRef} muted playsInline className="gesture-preview" />
            {!cameraReady && <span>摄像头未启用</span>}
          </div>
          <canvas ref={canvasRef} hidden />
          <div className="gesture-actions">
            <button className="button primary" onClick={enabled ? stop : start}>
              {enabled ? "关闭手势摄像头" : "启用手势摄像头"}
            </button>
            <span>{enabled ? "约 1 FPS 低频采样" : "不会影响文本/语音"}</span>
          </div>
          {result && (
            <div className={`gesture-result ${result.decision}`}>
              <strong>{gestureLabels[result.recognition.gesture]}</strong>
              <span>
                置信度 {(result.recognition.confidence * 100).toFixed(1)}% · InternS2 {result.recognition.latency_ms} ms
              </span>
              <p>{result.message}</p>
            </div>
          )}
          {error && <div className="gesture-error">{error}</div>}
          <details className="gesture-protocol">
            <summary>查看固定手势协议</summary>
            <ol>
              <li>up：食指向上</li>
              <li>down：食指向下</li>
              <li>left：食指向自己的左侧</li>
              <li>right：食指向自己的右侧</li>
              <li>forward：食指指向摄像头</li>
              <li>backward：大拇指指向自己的胸口</li>
              <li>stop：拇指和食指组成圆圈</li>
              <li>estop：五指张开且掌心正对摄像头</li>
            </ol>
          </details>
        </>
      )}
    </aside>
  );
}
