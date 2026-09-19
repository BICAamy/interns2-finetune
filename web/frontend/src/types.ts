export type SessionStatus =
  | "ready"
  | "parsing"
  | "awaiting_confirmation"
  | "clarification_required"
  | "executing"
  | "moving_to_entry"
  | "verifying_entry"
  | "moving_relative"
  | "planning"
  | "plan_ready"
  | "completed"
  | "stopping"
  | "stopped"
  | "estop"
  | "cancelled"
  | "failed";

export interface SessionSnapshot {
  schema_version: "1.0";
  session_id: string;
  revision: number;
  status: SessionStatus;
  status_label: string;
  created_at_ms: number;
  updated_at_ms: number;
  prompt: string | null;
  input_source: "text" | "voice";
  image_name: string | null;
  asr_transcription: ASRTranscription | null;
  pending_confirmation: boolean;
  active_command_id: string | null;
  raw_model_output: Record<string, unknown> | null;
  normalized_command: Record<string, any> | null;
  current_tcp: Record<string, any> | null;
  execution_events: Array<Record<string, any>>;
  orchestration: Record<string, any> | null;
  message: string;
  error: Record<string, any> | null;
}

export interface ASRStatus {
  backend: string;
  model: string;
  available: boolean;
  loaded: boolean;
  language: string;
  device: string;
  compute_type: string;
  max_audio_bytes: number;
  max_duration_s: number;
  low_confidence_threshold: number;
  supported_mime_types: string[];
  unavailable_reason: string | null;
}

export interface ASRTranscription {
  text: string;
  language: string;
  language_probability: number;
  confidence: number;
  low_confidence: boolean;
  duration_ms: number;
  audio_bytes: number;
  asr_latency_ms: number;
  end_to_end_latency_ms: number | null;
  backend: string;
  model: string;
  safety_action: "stop" | "estop" | null;
}

export interface TextCommandPayload {
  prompt: string;
  image_data_url?: string;
  image_name?: string;
}

export interface Point3D {
  x: number;
  y: number;
  z: number;
  unit: "mm";
  frame: string;
  source?: string | null;
}

export interface SimulationTelemetry {
  schema_version: "1.0";
  type: "telemetry";
  connected: boolean;
  runtime_mode: "simulation" | "real";
  control_mode: string | null;
  provider: string | null;
  freshness: "fresh" | "stale" | "disconnected" | "unknown";
  source_age_ms: number | null;
  connections: Record<string, string>;
  sequence: number;
  received_at_ms: number;
  source_updated_at_ms: number | null;
  state_machine_state: string;
  current_tool: string | null;
  motion_state: string | null;
  estop: boolean;
  active_command_id: string | null;
  current_tcp: Point3D | null;
  actual_tcp_robot_base: {
    translation_mm: [number, number, number];
    rotation_rpy_deg: [number, number, number];
    quaternion_xyzw: [number, number, number, number];
    frame: string;
    unit: string;
  } | null;
  entry_point: Point3D | null;
  target_point: Point3D | null;
  position_error_mm: number | null;
  motion_progress_percent: number | null;
  joint_positions_deg: number[];
  trajectory_mm: [number, number, number][];
  trajectory_total_points: number;
  frame_sequence: number;
  simulation_fps: number | null;
  fsm_code: number | null;
  enabled: boolean | null;
  electrified: boolean | null;
  moving: boolean | null;
  in_position: boolean | null;
  physical_estop_active: boolean | null;
  emergency_stop_circuit_fault: boolean | null;
  safeguard_active: boolean | null;
  safeguard_circuit_fault: boolean | null;
  vendor_fault: Record<string, any> | null;
  mirror_calibrated: boolean | null;
  mirror_warning: string | null;
  mirror_reason: string | null;
  mirror_source_sequence: number | null;
  tool_tcp_calibrated: false;
  error: Record<string, any> | null;
}

export type CameraPreset = "front" | "left" | "right" | "top" | "isometric";

export interface SimulationCameraState {
  schema_version: "1.0";
  preset: CameraPreset | "custom";
  yaw_deg: number;
  pitch_deg: number;
  distance_m: number;
  target_m: [number, number, number];
  position_m: [number, number, number];
  updated_at_ms: number;
}

export type CameraControlPayload =
  | {
      action: "orbit";
      yaw_delta_deg: number;
      pitch_delta_deg: number;
    }
  | {
      action: "zoom";
      distance_delta_m: number;
    }
  | {
      action: "pan";
      pan_right_delta_m: number;
      pan_up_delta_m: number;
    }
  | {
      action: "preset";
      preset: CameraPreset;
    };
