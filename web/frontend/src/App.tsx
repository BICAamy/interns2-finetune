import { useEffect, useMemo, useRef, useState } from "react";
import type {
  PointerEvent as ReactPointerEvent,
  WheelEvent as ReactWheelEvent,
} from "react";
import { api, fileToDataUrl, openSessionSocket } from "./api";
import type {
  CameraControlPayload,
  CameraPreset,
  Point3D,
  SessionSnapshot,
  SimulationCameraState,
  SimulationTelemetry,
} from "./types";

const SESSION_KEY = "interns2-surgical-session";
const DEFAULT_PROMPT =
  "入点为基座坐标系下(X=500,Y=0,Z=500)毫米，靶点为(X=500,Y=0,Z=550)毫米，请准备穿刺";

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

function JsonPanel({ value, empty }: { value: unknown; empty: string }) {
  return (
    <pre className="json-panel">
      {value ? JSON.stringify(value, null, 2) : empty}
    </pre>
  );
}

function CoordinateCard({ title, point }: { title: string; point: any }) {
  return (
    <div className="coordinate-card">
      <span>{title}</span>
      {point ? (
        <strong>
          X {Number(point.x).toFixed(2)} · Y {Number(point.y).toFixed(2)} · Z{" "}
          {Number(point.z).toFixed(2)} <small>{point.unit ?? "mm"}</small>
        </strong>
      ) : (
        <strong className="muted">未提供</strong>
      )}
      <small>{point?.frame ?? "—"}</small>
    </div>
  );
}

function Timeline({ events }: { events: Array<Record<string, any>> }) {
  if (!events.length) {
    return <div className="empty-state">提交任务后，这里会显示工具调用时间线。</div>;
  }
  return (
    <ol className="timeline">
      {events.map((event, index) => {
        const name = event.event ?? `${event.tool}.${event.phase}`;
        const status = event.status ?? event.phase;
        return (
          <li key={`${name}-${event.sequence ?? index}-${event.timestamp_ms}`}>
            <span className={`timeline-dot ${status}`} />
            <div>
              <strong>{name}</strong>
              <span>
                {event.timestamp_ms ? new Date(event.timestamp_ms).toLocaleTimeString() : ""}
                {event.duration_ms !== undefined ? ` · ${event.duration_ms} ms` : ""}
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function TrajectoryPlot({ telemetry }: { telemetry: SimulationTelemetry | null }) {
  const trajectory = telemetry?.trajectory_mm ?? [];
  if (trajectory.length < 2) {
    return <div className="trajectory-empty">机械臂运动后显示 X–Z 轨迹</div>;
  }
  const reference = [
    ...trajectory,
    ...(telemetry?.entry_point
      ? [[telemetry.entry_point.x, telemetry.entry_point.y, telemetry.entry_point.z] as [number, number, number]]
      : []),
  ];
  const xs = reference.map((point) => point[0]);
  const zs = reference.map((point) => point[2]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minZ = Math.min(...zs);
  const maxZ = Math.max(...zs);
  const rangeX = Math.max(1, maxX - minX);
  const rangeZ = Math.max(1, maxZ - minZ);
  const project = (point: [number, number, number]) =>
    `${12 + ((point[0] - minX) / rangeX) * 216},${108 - ((point[2] - minZ) / rangeZ) * 96}`;
  const entry = telemetry?.entry_point;
  const current = telemetry?.current_tcp;

  return (
    <div className="trajectory-plot">
      <svg viewBox="0 0 240 120" role="img" aria-label="机械臂 X-Z 平面轨迹">
        <path className="plot-grid" d="M12 12V108H228M12 60H228M120 12V108" />
        <polyline points={trajectory.map(project).join(" ")} />
        {entry && (
          <circle
            className="entry-marker"
            cx={Number(project([entry.x, entry.y, entry.z]).split(",")[0])}
            cy={Number(project([entry.x, entry.y, entry.z]).split(",")[1])}
            r="4"
          />
        )}
        {current && (
          <circle
            className="tcp-marker"
            cx={Number(project([current.x, current.y, current.z]).split(",")[0])}
            cy={Number(project([current.x, current.y, current.z]).split(",")[1])}
            r="3.5"
          />
        )}
      </svg>
      <span>X–Z 平面 · 青色 TCP / 橙色入点</span>
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState<SessionSnapshot | null>(null);
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
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
  const [requestError, setRequestError] = useState<string | null>(null);
  const cameraDrag = useRef<{
    pointerId: number;
    x: number;
    y: number;
    mode: "orbit" | "pan";
  } | null>(null);
  const cameraRequestInFlight = useRef(false);
  const lastCameraSendAt = useRef(0);

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
    if (!session?.session_id) return;
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
  }, [session?.session_id]);

  useEffect(() => {
    if (!videoFailed) return;
    const timer = window.setTimeout(() => {
      setVideoAttempt((value) => value + 1);
      setVideoFailed(false);
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [videoFailed]);

  const command = session?.normalized_command;
  const isBusy = session ? busyStatuses.has(session.status) : true;
  const canSubmit = Boolean(session && prompt.trim() && !isBusy && !session.pending_confirmation);
  const entry = (command?.entry_point ?? telemetry?.entry_point) as Point3D | undefined;
  const target = (command?.target_point ?? telemetry?.target_point) as Point3D | undefined;
  const currentTcp = telemetry?.current_tcp ?? session?.current_tcp;
  const videoUrl = session ? api.videoUrl(session.session_id, videoAttempt) : "";

  const statusTone = useMemo(() => {
    if (!session) return "neutral";
    if (session.status === "estop" || session.status === "failed") return "danger";
    if (session.status === "plan_ready" || session.status === "completed") return "success";
    if (isBusy) return "active";
    return "neutral";
  }, [session, isBusy]);

  async function run(action: () => Promise<SessionSnapshot>) {
    setRequestError(null);
    try {
      setSession(await action());
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : String(error));
    }
  }

  async function updateCamera(payload: CameraControlPayload) {
    if (!session || cameraRequestInFlight.current) return;
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
        yaw_delta_deg: Math.max(-30, Math.min(30, deltaX * 0.3)),
        pitch_delta_deg: Math.max(-30, Math.min(30, -deltaY * 0.3)),
      });
    } else {
      void updateCamera({
        action: "pan",
        pan_right_delta_m: Math.max(-0.2, Math.min(0.2, -deltaX * 0.0015)),
        pan_up_delta_m: Math.max(-0.2, Math.min(0.2, deltaY * 0.0015)),
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

  function zoomCamera(event: ReactWheelEvent<HTMLDivElement>) {
    event.preventDefault();
    if (cameraRequestInFlight.current) return;
    void updateCamera({
      action: "zoom",
      distance_delta_m: event.deltaY > 0 ? 0.14 : -0.14,
    });
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
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">IS</div>
          <div>
            <h1>InternS2 手术导航控制台</h1>
            <p>E05-Pro 仿真定位 · 人工确认模式</p>
          </div>
        </div>
        <div className="topbar-actions">
          <span className={`connection ${connected ? "online" : "offline"}`}>
            {connected ? "状态已连接" : "状态连接中"}
          </span>
          <span className={`connection ${videoConnected ? "online" : "offline"}`}>
            {videoConnected ? "视频已连接" : "视频连接中"}
          </span>
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
      </header>

      <main>
        <section className={`status-banner ${statusTone}`}>
          <div className="status-pulse" />
          <div>
            <span>当前状态</span>
            <strong>{session?.status_label ?? "正在创建安全会话"}</strong>
            {session?.message && <p className="operation-message">{session.message}</p>}
          </div>
          <div className="session-meta">
            <span>仿真模式</span>
            <code>{session?.session_id.slice(-10) ?? "—"}</code>
          </div>
        </section>

        {(requestError || session?.error) && (
          <section className="error-banner">
            <strong>{requestError ?? String(session?.error?.code ?? "任务错误")}</strong>
            <span>{String(session?.error?.message ?? "")}</span>
          </section>
        )}

        <div className="dashboard-grid">
          <section className="panel command-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">01 · 指令输入</span>
                <h2>医生任务</h2>
              </div>
              <span className="step-badge">文本 + 可选图像</span>
            </div>
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              disabled={isBusy}
              aria-label="手术导航文本指令"
            />
            <div className="example-row">
              <button className="text-button" onClick={() => setPrompt(DEFAULT_PROMPT)}>
                填入点/靶点示例
              </button>
              <button
                className="text-button"
                onClick={() => setPrompt("机械臂沿基座坐标系 Z 轴正方向移动 8 毫米")}
              >
                填相对移动示例
              </button>
            </div>
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
                className="button confirm"
                disabled={!session?.pending_confirmation}
                onClick={() => session && run(() => api.action(session.session_id, "confirm"))}
              >
                确认并执行
              </button>
              <button
                className="button secondary"
                disabled={!session?.pending_confirmation}
                onClick={() => session && run(() => api.action(session.session_id, "cancel"))}
              >
                取消
              </button>
              <button
                className="button secondary"
                disabled={session?.status !== "estop"}
                onClick={() => session && run(() => api.action(session.session_id, "reset-estop"))}
              >
                复位急停
              </button>
            </div>
            <div className="safety-note">
              <strong>执行边界</strong>
              <span>确认只会移动机械臂并请求不可执行的路径预览，当前版本不会执行穿刺。</span>
            </div>
          </section>

          <section className="panel coordinates-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">02 · 任务预览</span>
                <h2>坐标与 TCP</h2>
              </div>
              <span className="step-badge">单位：mm</span>
            </div>
            <CoordinateCard title="入点" point={entry} />
            <CoordinateCard title="靶点" point={target} />
            <CoordinateCard title="当前针尖 TCP" point={currentTcp} />
            {command?.relative_motion && (
              <div className="relative-card">
                <span>相对运动</span>
                <strong>
                  {String(command.relative_motion.axis).toUpperCase()} 轴 · {command.relative_motion.direction === "positive" ? "+" : "−"}
                  {command.relative_motion.distance_mm} mm
                </strong>
              </div>
            )}
          </section>

          <section className="panel simulation-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">03 · 远程仿真</span>
                <h2>E05-Pro 实时画面与遥测</h2>
              </div>
              <span className={`step-badge ${telemetry?.connected ? "live" : ""}`}>
                {telemetry?.connected ? `${telemetry.simulation_fps ?? 0} FPS` : "遥测断开"}
              </span>
            </div>
            <div className="simulation-layout">
              <div
                className={`video-stage ${cameraDragging ? "dragging" : ""}`}
                onPointerDown={beginCameraDrag}
                onPointerMove={moveCamera}
                onPointerUp={endCameraDrag}
                onPointerCancel={endCameraDrag}
                onWheel={zoomCamera}
                onDoubleClick={() => void updateCamera({ action: "preset", preset: "front" })}
                onContextMenu={(event) => event.preventDefault()}
                aria-label="可交互的远程 SOFA 相机画面"
              >
                {videoUrl && (
                  <img
                    key={videoUrl}
                    src={videoUrl}
                    alt="远程 SOFA E05-Pro 仿真画面"
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
                <div className="video-overlay top-left">
                  <span className={videoConnected ? "record-dot live" : "record-dot"} />
                  {videoConnected ? "REMOTE SIMULATION" : "RECONNECTING"}
                </div>
                <div className="video-overlay bottom-right">
                  frame {telemetry?.frame_sequence ?? 0}
                </div>
                <div className="camera-hint">
                  左键旋转 · 右键平移 · 滚轮缩放 · 双击复位
                </div>
                <div className="camera-state">
                  {camera
                    ? `方位 ${camera.yaw_deg.toFixed(0)}° · 俯仰 ${camera.pitch_deg.toFixed(0)}° · ${camera.distance_m.toFixed(2)} m`
                    : "正在读取相机状态"}
                </div>
                <div
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
                </div>
                {videoFailed && (
                  <div className="video-fallback">
                    <strong>仿真视频暂时不可用</strong>
                    <span>系统将在 2 秒后自动重连，机械臂控制线程不受影响。</span>
                  </div>
                )}
                {cameraError && <div className="camera-error">{cameraError}</div>}
              </div>

              <aside className="telemetry-board">
                <div className="telemetry-stats">
                  <div><span>位置误差</span><strong>{telemetry?.position_error_mm != null ? `${telemetry.position_error_mm.toFixed(3)} mm` : "—"}</strong></div>
                  <div><span>运动状态</span><strong>{telemetry?.motion_state ?? "—"}</strong></div>
                  <div><span>当前工具</span><strong>{telemetry?.current_tool ?? "空闲"}</strong></div>
                  <div><span>轨迹点</span><strong>{telemetry?.trajectory_total_points ?? 0}</strong></div>
                </div>
                <div className="progress-block">
                  <div><span>运动进度</span><strong>{telemetry?.motion_progress_percent != null ? `${telemetry.motion_progress_percent.toFixed(1)}%` : "等待任务"}</strong></div>
                  <div className="progress-track"><i style={{ width: `${telemetry?.motion_progress_percent ?? 0}%` }} /></div>
                </div>
                <TrajectoryPlot telemetry={telemetry} />
                <div className="joint-strip">
                  {(telemetry?.joint_positions_deg ?? []).map((joint, index) => (
                    <span key={index}>J{index + 1} <strong>{joint.toFixed(1)}°</strong></span>
                  ))}
                </div>
                {telemetry?.error && (
                  <div className="telemetry-error">{String(telemetry.error.message ?? "仿真遥测不可用")}</div>
                )}
              </aside>
            </div>
          </section>

          <section className="panel timeline-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">04 · 确定性编排</span>
                <h2>工具调用时间线</h2>
              </div>
              <span className="step-badge">revision {session?.revision ?? 0}</span>
            </div>
            <Timeline events={session?.execution_events ?? []} />
          </section>

          <section className="panel json-grid-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">05 · 可审计数据</span>
                <h2>InternS2 与规范化结果</h2>
              </div>
            </div>
            <div className="json-grid">
              <div>
                <h3>InternS2 原始工具参数</h3>
                <JsonPanel value={session?.raw_model_output} empty="等待模型解析" />
              </div>
              <div>
                <h3>规范化 ParsedCommand</h3>
                <JsonPanel value={session?.normalized_command} empty="等待结构化任务" />
              </div>
            </div>
          </section>
        </div>
      </main>

      <footer>
        <span>InternS2 Surgical Navigation · Simulation Only</span>
        <strong>当前版本未执行穿刺</strong>
      </footer>
    </div>
  );
}
