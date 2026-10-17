import ManualControl from "./ManualControl";
import { agentThemeMenu } from "./AgentThemeMenu";
import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { api, fileToDataUrl, openSessionSocket } from "./api";
import type {
  CameraControlPayload,
  CameraPreset,
  Point3D,
  RobotModeSettings,
  SessionSnapshot,
  SimulationCameraState,
  SimulationTelemetry,
} from "./types";

const SESSION_KEY = "interns2-surgical-session";
const DEFAULT_PROMPT = "请画出一张正面是爱心，侧面是星星的图案";

const busyStatuses = new Set([
  "parsing",
  "executing",
  "moving_to_entry",
  "verifying_entry",
  "moving_relative",
  "planning",
  "stopping",
]);

const cameraPresets: Array<{ id: CameraPreset; label: string }> = [
  { id: "front", label: "正视" },
  { id: "left", label: "左视" },
  { id: "right", label: "右视" },
  { id: "top", label: "俯视" },
  { id: "isometric", label: "等轴测" },
];

function AmbientWaveBackground() {
  return (
    <div className="ambient-scene" aria-hidden="true">
      <div className="ambient-glow ambient-glow-a" />
      <div className="ambient-glow ambient-glow-b" />
      <div className="ambient-glow ambient-glow-c" />
      <svg
        className="ambient-waves"
        viewBox="0 0 1600 900"
        preserveAspectRatio="xMidYMid slice"
      >
        <defs>
          <linearGradient id="wave-gradient-a" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#0a4fca" stopOpacity="0" />
            <stop offset="0.35" stopColor="#168cff" stopOpacity="0.62" />
            <stop offset="0.72" stopColor="#11d6dc" stopOpacity="0.48" />
            <stop offset="1" stopColor="#13e6ca" stopOpacity="0" />
          </linearGradient>
          <linearGradient id="wave-gradient-b" x1="1" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#52c9ff" stopOpacity="0" />
            <stop offset="0.42" stopColor="#2585ff" stopOpacity="0.34" />
            <stop offset="0.78" stopColor="#50f0df" stopOpacity="0.22" />
            <stop offset="1" stopColor="#50f0df" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path
          className="ambient-wave ambient-wave-one"
          d="M-220 260 C 80 20, 340 430, 650 225 S 1160 10, 1820 300"
          fill="none"
          stroke="url(#wave-gradient-a)"
          strokeWidth="150"
          strokeLinecap="round"
        />
        <path
          className="ambient-wave ambient-wave-two"
          d="M-180 485 C 180 130, 425 700, 790 390 S 1320 180, 1800 560"
          fill="none"
          stroke="url(#wave-gradient-b)"
          strokeWidth="96"
          strokeLinecap="round"
        />
        <path
          className="ambient-wave ambient-wave-three"
          d="M-180 735 C 130 410, 465 790, 805 590 S 1320 350, 1790 770"
          fill="none"
          stroke="url(#wave-gradient-a)"
          strokeWidth="48"
          strokeLinecap="round"
        />
        <path
          className="ambient-thread ambient-thread-one"
          d="M-120 335 C 250 120, 410 520, 760 305 S 1280 135, 1720 410"
          fill="none"
        />
        <path
          className="ambient-thread ambient-thread-two"
          d="M-100 620 C 260 340, 540 770, 930 505 S 1380 360, 1750 690"
          fill="none"
        />
      </svg>
      <div className="medical-blueprint medical-blueprint-left" />
      <div className="medical-blueprint medical-blueprint-right" />
      <div className="medical-blueprint medical-blueprint-center" />
      <div className="ambient-grid" />
      <div className="ambient-noise" />
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState<SessionSnapshot | null>(null);
  const [runtimeMode, setRuntimeMode] = useState<"simulation" | "real">("simulation");
  const [availableModes, setAvailableModes] = useState<Array<"simulation" | "real">>([
    "simulation",
  ]);
  const [modeSettings, setModeSettings] = useState<
    Partial<Record<"simulation" | "real", RobotModeSettings>>
  >({});
  const [modeBusy, setModeBusy] = useState(false);
  const [enableBusy, setEnableBusy] = useState(false);
  const [trajectoryClearBusy, setTrajectoryClearBusy] = useState(false);
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [randomMotionSummary, setRandomMotionSummary] = useState("");
  const [randomMotionBusy, setRandomMotionBusy] = useState(false);
  const promptRef = useRef<HTMLTextAreaElement | null>(null);
  const [image, setImage] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [telemetry, setTelemetry] = useState<SimulationTelemetry | null>(null);
  const [videoConnected, setVideoConnected] = useState(false);
  const [videoFailed, setVideoFailed] = useState(false);
  const [videoAttempt, setVideoAttempt] = useState(0);
  const [camera, setCamera] = useState<SimulationCameraState | null>(null);
  const [cameraDragging, setCameraDragging] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [autoExecuteRemainingMs, setAutoExecuteRemainingMs] = useState<number | null>(null);
  const [autoExecuting, setAutoExecuting] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const cameraDrag = useRef<{
    pointerId: number;
    x: number;
    y: number;
    mode: "orbit" | "pan";
  } | null>(null);
  const cameraRequestInFlight = useRef(false);
  const lastCameraSendAt = useRef(0);
  const videoStageRef = useRef<HTMLDivElement | null>(null);
  const autoExecuteToken = useRef(0);
  const lastRobotMode = useRef<"simulation" | "real">("simulation");

  useEffect(() => {
    let cancelled = false;
    api.health()
      .then((health) => {
        if (!cancelled) {
          setAvailableModes(health.available_robot_modes);
          setModeSettings(health.robot_mode_settings);
        }
      })
      .catch((error) => {
        if (!cancelled) setRequestError(`无法确认机器人运行模式：${String(error)}`);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!session) return;
    const modeChanged = lastRobotMode.current !== session.robot_mode;
    lastRobotMode.current = session.robot_mode;
    setRuntimeMode(session.robot_mode);
    if (modeChanged) {
      setTelemetry(null);
      setCamera(null);
      setVideoConnected(false);
      setVideoFailed(false);
      setVideoAttempt((value) => value + 1);
    }
  }, [session?.robot_mode]);

  useEffect(() => {
    let cancelled = false;
    async function initialize() {
      const existing = sessionStorage.getItem(SESSION_KEY);
      try {
        const snapshot = existing
          ? await api.getSession(existing).catch(() => api.createSession())
          : await api.createSession();
        if (!cancelled) {
          sessionStorage.setItem(SESSION_KEY, snapshot.session_id);
          setSession(snapshot);
        }
      } catch (error) {
        if (!cancelled) setRequestError(String(error));
      }
    }
    initialize();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!session?.session_id) return;
    let disposed = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;

    const connect = () => {
      socket = openSessionSocket(
        session.session_id,
        setSession,
        setTelemetry,
        (isConnected) => {
          if (disposed) return;
          setConnected(isConnected);
          if (!isConnected && reconnectTimer === null) {
            reconnectTimer = window.setTimeout(() => {
              reconnectTimer = null;
              connect();
            }, 1500);
          }
        },
      );
    };

    connect();
    return () => {
      disposed = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [session?.session_id]);

  useEffect(() => {
    if (!session?.session_id || runtimeMode === null) return;
    let cancelled = false;
    api.camera(session.session_id)
      .then((state) => {
        if (!cancelled) {
          setCamera(state);
          setCameraError(null);
        }
      })
      .catch((error) => {
        if (!cancelled) setCameraError(String(error));
      });
    return () => {
      cancelled = true;
    };
  }, [session?.session_id, runtimeMode]);

  useEffect(() => {
    if (!videoFailed || runtimeMode === null) return;
    const timer = window.setTimeout(() => {
      setVideoAttempt((value) => value + 1);
      setVideoFailed(false);
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [videoFailed, runtimeMode]);

  const proposal = session?.motion_proposal as {
    fingerprint?: string;
    envelope?: {
      expected_start_pose_robot_base?: { translation_mm?: number[] };
      payload?: {
        translation_mm?: number[];
        entry_point?: Point3D;
        speed_mm_s?: number;
      };
    };
  } | null | undefined;
  const isBusy = session ? busyStatuses.has(session.status) : true;
  const realStale = runtimeMode === "real" && telemetry?.connected !== true;
  const canSubmit = Boolean(
    session &&
      prompt.trim() &&
      !isBusy &&
      !session.pending_confirmation &&
      !realStale,
  );
  const activeModeSettings = modeSettings[runtimeMode];
  const workspaceLow = activeModeSettings?.workspace_low_mm;
  const workspaceHigh = activeModeSettings?.workspace_high_mm;
  const canGenerateRandomMotion = Boolean(
    session && !isBusy && !modeBusy && !randomMotionBusy &&
    !session.pending_confirmation && telemetry?.connected && !telemetry.moving &&
    !telemetry.estop && telemetry.current_tcp,
  );
  const videoUrl = session
    ? api.videoUrl(session.session_id, videoAttempt, runtimeMode)
    : "";

  const statusTone = useMemo(() => {
    if (!session) return "neutral";
    if (session.status === "estop" || session.status === "failed") return "danger";
    if (session.status === "plan_ready" || session.status === "completed") return "success";
    if (isBusy) return "active";
    return "neutral";
  }, [session, isBusy]);

  useEffect(() => {
    if (!session?.pending_confirmation || !activeModeSettings) {
      setAutoExecuteRemainingMs(null);
      setAutoExecuting(false);
      return;
    }
    if (runtimeMode === "real" && (telemetry?.enabled !== true || realStale)) {
      setAutoExecuteRemainingMs(null);
      return;
    }

    const token = ++autoExecuteToken.current;
    const delayMs = activeModeSettings.auto_execute_delay_ms;
    const deadline = performance.now() + delayMs;
    setAutoExecuteRemainingMs(delayMs);

    const countdown = window.setInterval(() => {
      setAutoExecuteRemainingMs(Math.max(0, Math.ceil(deadline - performance.now())));
    }, 50);
    const timer = window.setTimeout(async () => {
      window.clearInterval(countdown);
      if (autoExecuteToken.current !== token) return;
      setAutoExecuteRemainingMs(0);
      setAutoExecuting(true);
      setRequestError(null);
      try {
        const snapshot = await api.confirm(session.session_id, proposal?.fingerprint);
        if (autoExecuteToken.current === token) setSession(snapshot);
      } catch (error) {
        if (autoExecuteToken.current === token) {
          setRequestError(error instanceof Error ? error.message : String(error));
        }
      } finally {
        if (autoExecuteToken.current === token) setAutoExecuting(false);
      }
    }, delayMs);

    return () => {
      window.clearInterval(countdown);
      window.clearTimeout(timer);
    };
  }, [
    session?.session_id,
    session?.revision,
    session?.pending_confirmation,
    runtimeMode,
    activeModeSettings?.auto_execute_delay_ms,
    proposal?.fingerprint,
    telemetry?.enabled,
    realStale,
  ]);

  async function run(action: () => Promise<SessionSnapshot>) {
    setRequestError(null);
    try {
      setSession(await action());
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : String(error));
    }
  }

  async function cancelPendingExecution() {
    if (!session?.pending_confirmation || autoExecuting) return;
    autoExecuteToken.current += 1;
    setAutoExecuteRemainingMs(null);
    setAutoExecuting(false);
    await run(() => api.action(session.session_id, "cancel"));
  }

  async function setRobotEnabled(enabled: boolean) {
    if (!session || runtimeMode !== "real" || enableBusy) return;
    setEnableBusy(true);
    setRequestError(null);
    try {
      await api.setRobotEnabled(session.session_id, enabled);
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : String(error));
    } finally {
      setEnableBusy(false);
    }
  }

  async function clearTrajectory() {
    if (!session || trajectoryClearBusy) return;
    setTrajectoryClearBusy(true);
    setRequestError(null);
    try {
      await api.clearTrajectory(session.session_id);
      setTelemetry(await api.telemetry(session.session_id));
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : String(error));
    } finally {
      setTrajectoryClearBusy(false);
    }
  }

  async function selectRobotMode(mode: "simulation" | "real") {
    if (!session || modeBusy || mode === runtimeMode) return;
    setModeBusy(true);
    setRequestError(null);
    try {
      setSession(await api.setRobotMode(session.session_id, mode));
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : String(error));
    } finally {
      setModeBusy(false);
    }
  }

  async function updateCamera(payload: CameraControlPayload) {
    if (!session || runtimeMode === null || cameraRequestInFlight.current) return;
    cameraRequestInFlight.current = true;
    try {
      setCamera(await api.controlCamera(session.session_id, payload));
      setCameraError(null);
    } catch (error) {
      setCameraError(error instanceof Error ? error.message : String(error));
    } finally {
      cameraRequestInFlight.current = false;
    }
  }

  useEffect(() => {
  if (runtimeMode === null) return;
  const element = videoStageRef.current;
  if (!element) return;

  const handleWheel = (event: WheelEvent) => {
    // 鼠标位于仿真画面时，滚轮只控制相机缩放，
    // 禁止浏览器继续滚动整个页面。
    event.preventDefault();

    if (cameraRequestInFlight.current) return;

    void updateCamera({
      action: "zoom",
      distance_delta_m: event.deltaY > 0 ? 0.14 : -0.14,
    });
  };

  element.addEventListener("wheel", handleWheel, {
    passive: false,
  });

  return () => {
    element.removeEventListener("wheel", handleWheel);
  };
}, [session?.session_id, runtimeMode]);

  function beginCameraDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 && event.button !== 2) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    cameraDrag.current = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      mode: event.button === 2 ? "pan" : "orbit",
    };
    lastCameraSendAt.current = 0;
    setCameraDragging(true);
  }

  function moveCamera(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = cameraDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    const now = performance.now();
    if (cameraRequestInFlight.current || now - lastCameraSendAt.current < 50) return;
    const deltaX = event.clientX - drag.x;
    const deltaY = event.clientY - drag.y;
    if (Math.abs(deltaX) + Math.abs(deltaY) < 1) return;
    drag.x = event.clientX;
    drag.y = event.clientY;
    lastCameraSendAt.current = now;
    if (drag.mode === "orbit") {
      void updateCamera({
        action: "orbit",
        yaw_delta_deg: Math.max(-30, Math.min(30, -deltaX * 0.3)),
        pitch_delta_deg: Math.max(-30, Math.min(30, deltaY * 0.3)),
      });
    } else {
      void updateCamera({
        action: "pan",
        pan_right_delta_m: Math.max(-0.2, Math.min(0.2, deltaX * 0.0015)),
        pan_up_delta_m: Math.max(-0.2, Math.min(0.2, -deltaY * 0.0015)),
      });
    }
  }

  function endCameraDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (cameraDrag.current?.pointerId !== event.pointerId) return;
    cameraDrag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setCameraDragging(false);
  }


  async function fillRandomMotion() {
    if (!canGenerateRandomMotion || !session) return;
    setRandomMotionBusy(true);
    setRequestError(null);
    try {
      const generated = await api.randomMotion(session.session_id);
      setPrompt(generated.prompt);
      setRandomMotionSummary(`${generated.name} · ${generated.stepCount} 步 · 可编辑后解析`);
      promptRef.current?.focus({ preventScroll: true });
      promptRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : String(error));
    } finally {
      setRandomMotionBusy(false);
    }
  }

  async function submit() {
    if (!session || !canSubmit) return;
    setRequestError(null);
    try {
      let imageDataUrl: string | undefined;
      if (image) imageDataUrl = await fileToDataUrl(image);
      await run(() =>
        api.submitText(session.session_id, {
          prompt: prompt.trim(),
          image_data_url: imageDataUrl,
          image_name: image?.name,
        }),
      );
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : String(error));
    }
  }

  function selectImage(file: File | null) {
    if (file && file.size > 10 * 1024 * 1024) {
      setRequestError("图像不能超过 10 MiB");
      return;
    }
    setImage(file);
    if (imagePreview) URL.revokeObjectURL(imagePreview);
    setImagePreview(file ? URL.createObjectURL(file) : null);
  }

  return (
    <div className="app-shell robot-workbench">
      <AmbientWaveBackground />
      <header className="tianfu-banner agent-masthead">
        <div className="tianfu-brand"><span className="tianfu-brand-content"><span className="tianfu-logo"><img src="/assets/tianfu-logo.jpg" alt="" width="48" height="48"/></span><span>天府·慧研</span></span><span className="agent-masthead-title">智能实验机械臂Agent</span></div>
        <div className="tianfu-banner-actions" dangerouslySetInnerHTML={{__html: agentThemeMenu}}/>
      </header>
      <main className="robot-workspace">
        <div className="dashboard-grid workbench-grid">
          <section className="panel simulation-panel" aria-label="机器人实时画面">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">实时画面</span>
                <h2>E05-Pro 数字孪生</h2>
              </div>
              <span className={`step-badge ${telemetry?.connected ? "live" : ""}`}>
                {telemetry?.connected ? (runtimeMode === "real" ? `FRESH · ${Math.round(telemetry.source_age_ms ?? 0)} ms` : `${telemetry.simulation_fps ?? 0} FPS`) : (telemetry?.freshness ?? "遥测断开").toUpperCase()}
              </span>
            </div>
              <div
                ref={videoStageRef}
                className={`video-stage ${cameraDragging ? "dragging" : ""} ${realStale ? "stale" : ""}`}
                onPointerDown={runtimeMode !== null ? beginCameraDrag : undefined}
                onPointerMove={runtimeMode !== null ? moveCamera : undefined}
                onPointerUp={runtimeMode !== null ? endCameraDrag : undefined}
                onPointerCancel={runtimeMode !== null ? endCameraDrag : undefined}
              >
                {videoUrl && (
                  <img
                    key={videoUrl}
                    src={videoUrl}
                    alt={runtimeMode === "real" ? "真实反馈驱动的 SOFA E05-Pro 数字孪生" : "远程 SOFA E05-Pro 仿真画面"}
                    draggable={false}
                    onLoad={() => {
                      setVideoConnected(true);
                      setVideoFailed(false);
                    }}
                    onError={() => {
                      setVideoConnected(false);
                      setVideoFailed(true);
                    }}
                  />
                )}
                {runtimeMode === null && (
                  <div className="video-fallback"><strong>运行模式未确认</strong><span>暂不显示机械臂画面。</span></div>
                )}
                {runtimeMode !== null && <div className="video-overlay top-left">
                  <span className={videoConnected ? "record-dot live" : "record-dot"} />
                  {videoConnected ? (runtimeMode === "real" ? "REAL / WEB CONTROL" : "REMOTE SIMULATION") : "RECONNECTING"}
                </div>}
                {runtimeMode !== null && <div className="video-overlay bottom-right">
                  frame {telemetry?.frame_sequence ?? 0}
                </div>}
                {runtimeMode !== null && <div className="camera-hint">
                  左键旋转 · 右键平移 · 滚轮缩放 · 双击复位
                </div>}
                {runtimeMode !== null && <div className="camera-state">
                  {camera
                    ? `方位 ${camera.yaw_deg.toFixed(0)}° · 俯仰 ${camera.pitch_deg.toFixed(0)}° · ${camera.distance_m.toFixed(2)} m`
                    : "正在读取相机状态"}
                </div>}
                {runtimeMode !== null && <div
                  className="camera-presets"
                  onPointerDown={(event) => event.stopPropagation()}
                  onDoubleClick={(event) => event.stopPropagation()}
                >
                  {cameraPresets.map((preset) => (
                    <button
                      key={preset.id}
                      className={camera?.preset === preset.id ? "active" : ""}
                      onClick={() => void updateCamera({ action: "preset", preset: preset.id })}
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>}
                {videoFailed && runtimeMode !== null && (
                  <div className="video-fallback">
                    <strong>数字孪生视频暂时不可用</strong>
                    <span>系统将在 2 秒后自动重连；真实模式不会因此向机械臂发送命令。</span>
                  </div>
                )}
                {realStale && <div className="stale-overlay"><strong>真实机械臂连接恢复中</strong><span>真实操作已暂停；请检查 Mac、10003、10004 和 SSH 隧道</span></div>}
                {runtimeMode === "real" && telemetry?.mirror_warning && <div className="calibration-warning">{telemetry.mirror_warning}</div>}
                {cameraError && <div className="camera-error">{cameraError}</div>}
              </div>
            <div className="viewer-connections" aria-label="连接状态">
          <span className={`connection ${connected ? "online" : "offline"}`}>
            {runtimeMode === "real" ? `网关 ${telemetry?.connections.gateway ?? "未知"} · DataSheet ${telemetry?.connections.datasheet ?? "未知"}` : connected ? "状态已连接" : "状态连接中"}
          </span>
          <span className={`connection ${videoConnected ? "online" : "offline"}`}>
            {videoConnected ? "数字孪生画面已连接" : "视频连接中"}
          </span>
            </div>
          </section>
          <aside className="panel command-console" aria-label="任务操作台">
            <div className="command-controls">
              <div className="command-console-heading">
                <div><span>任务控制</span><h3>实验指令</h3></div>
          <label className="mode-picker">
            <span>运行模式</span>
            <select
              value={runtimeMode}
              disabled={!session || modeBusy || isBusy || session?.pending_confirmation}
              onChange={(event) => void selectRobotMode(
                event.target.value as "simulation" | "real",
              )}
            >
              {availableModes.includes("simulation") && (
                <option value="simulation">仿真</option>
              )}
              {availableModes.includes("real") && (
                <option value="real">真实机械臂</option>
              )}
            </select>
          </label>
              </div>
              <div className="robot-action-buttons">
          {runtimeMode === "real" && (
            <>
              <button
                className="button primary"
                disabled={!session || enableBusy || telemetry?.enabled === true || realStale}
                onClick={() => void setRobotEnabled(true)}
              >
                {enableBusy ? "处理中…" : "使能"}
              </button>
              <button
                className="button secondary"
                disabled={!session || enableBusy || telemetry?.enabled !== true || telemetry?.moving === true || realStale}
                onClick={() => void setRobotEnabled(false)}
              >
                {enableBusy ? "处理中…" : "去使能"}
              </button>
            </>
          )}
          <button
            className="button stop"
            disabled={!session}
            onClick={() => session && run(() => api.action(session.session_id, "stop"))}
          >
            停止
          </button>
          <button
            className="button estop"
            disabled={!session}
            onClick={() => session && run(() => api.action(session.session_id, "estop"))}
          >
            紧急停止
          </button>
              </div>
            </div>
            <div className="command-console-scroll">
        <section className={`status-banner ${statusTone}`}>
          <div className="status-pulse" />
          <div>
            <span>当前状态</span>
            <strong>{session?.status_label ?? "正在创建安全会话"}</strong>
            {session?.message && <p className="operation-message">{session.message}</p>}
          </div>

        </section>
        {(requestError || session?.error) && (
          <section className="error-banner">
            <strong>{requestError ?? String(session?.error?.code ?? "任务错误")}</strong>
            <span>{String(session?.error?.message ?? "")}</span>
          </section>
        )}

        {session?.mode_notice && (
          <section className="mode-notice" role="status">
            <strong>{session.mode_notice}</strong>
          </section>
        )}
                {workspaceLow && workspaceHigh && (
                  <div className="workspace-range" aria-label="Base 坐标系可移动范围">
                    <div>
                      <span>Base 可移动范围</span>
                      <strong>输入坐标须位于以下区间（mm）</strong>
                    </div>
                    {(["X", "Y", "Z"] as const).map((axis, index) => (
                      <span className="workspace-axis" key={axis}>
                        <b>{axis}</b>
                        {workspaceLow[index].toFixed(0)} ～ {workspaceHigh[index].toFixed(0)}
                      </span>
                    ))}
                  </div>
                )}
                <div className="instruction-format">文本 + 可选图像</div>
                <textarea
              ref={promptRef}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              disabled={isBusy}
              aria-label="实验机械臂文本指令"
            />
            <label className="upload-zone">
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={(event) => selectImage(event.target.files?.[0] ?? null)}
              />
              {imagePreview ? (
                <img src={imagePreview} alt="待提交医学图像预览" />
              ) : (
                <div>
                  <strong>添加视觉图像</strong>
                  <span>JPEG / PNG / WebP，最大 10 MiB</span>
                </div>
              )}
            </label>
            <div className="button-row">
              <button className="button primary" disabled={!canSubmit} onClick={submit}>
                {session?.status === "parsing" ? "正在解析…" : "解析任务"}
              </button>
              <button
                className="button secondary"
                disabled={!session?.pending_confirmation || autoExecuting}
                onClick={() => void cancelPendingExecution()}
              >
                {autoExecuting
                  ? "正在提交…"
                  : session?.pending_confirmation
                    ? "取消本次执行"
                    : "取消"}
              </button>
              <button
                className="button secondary"
                disabled={session?.status !== "estop" || runtimeMode !== "simulation"}
                onClick={() => session && run(() => api.action(session.session_id, "reset-estop"))}
              >
                复位急停
              </button>
              <button
                className="button secondary"
                disabled={!session || trajectoryClearBusy}
                onClick={() => void clearTrajectory()}
                title="只清除画面中的历史轨迹，不移动或复位机械臂"
              >
                {trajectoryClearBusy ? "清除中…" : "轨迹清除"}
              </button>
            </div>
            {session?.pending_confirmation && (
              <div className="auto-execute-notice" role="status">
                <span className="auto-execute-spinner" />
                <div>
                  <strong>
                    {autoExecuting
                      ? "正在提交执行"
                      : autoExecuteRemainingMs === null
                        ? "等待真实机械臂进入可执行状态"
                        : `${(autoExecuteRemainingMs / 1000).toFixed(1)} 秒后自动执行`}
                  </strong>
                  <span>如需停止本次任务，请立即点击“取消本次执行”。</span>
                </div>
              </div>
            )}
            <div className="safety-note">
              <strong>执行边界</strong>
              <span>{runtimeMode === "real" ? "所有移动与旋转统一为 MotionSequence；倒计时结束后自动提交 fingerprint，Mac 按每一步真实起点复算并检查 YAML 限制。" : "所有移动与旋转统一为 MotionSequence；解析后按配置倒计时自动执行，穿刺任务只移动到入点并请求不可执行的路径预览。"}</span>
              {runtimeMode === "real" && proposal?.fingerprint && (
                <code>fingerprint {proposal.fingerprint}</code>
              )}
            </div>
          <div className="session-meta">
            <span>{runtimeMode === "real" ? `真实 / ${telemetry?.enabled ? "已使能" : "未使能"}` : runtimeMode === "simulation" ? "仿真模式" : "模式未确认"}</span>
            <code>{session?.session_id.slice(-10) ?? "—"}</code>
          </div>
      <footer>
        <span>天府·慧研 智能实验机械臂Agent · {runtimeMode === "real" ? "REAL / WEB CONTROL" : "SIMULATION"}</span>
        <strong>{runtimeMode === "real" ? "使能状态来自真实反馈 · 解析后按配置自动执行" : "当前版本未执行穿刺"}</strong>
      </footer>
            </div>
            <div className="random-command-footer">
              <button type="button" className="random-command-button" disabled={!canGenerateRandomMotion} onClick={fillRandomMotion}>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M3 6h3c5 0 7 12 12 12h3m-4-4 4 4-4 4M3 18h3c2 0 3-2 4-4m4-4c1-2 2-4 4-4h3m-4-4 4 4-4 4" />
                </svg>
                <span><strong>{randomMotionBusy ? "正在生成…" : "生成随机指令"}</strong><small aria-live="polite">{randomMotionBusy ? "正在试算平移与关节旋转" : randomMotionSummary || "多步立体轨迹 · 仅填入输入框"}</small></span>
                <span className="random-command-arrow" aria-hidden="true">↗</span>
              </button>
            </div>
          </aside>
        </div>
      </main>
      <ManualControl sessionId={session?.session_id ?? null} runtimeMode={runtimeMode} telemetry={telemetry} />
    </div>
  );
}
