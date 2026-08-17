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
  image_name: string | null;
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
  sequence: number;
  received_at_ms: number;
  source_updated_at_ms: number | null;
  state_machine_state: string;
  current_tool: string | null;
  motion_state: string | null;
  estop: boolean;
  active_command_id: string | null;
  current_tcp: Point3D | null;
  entry_point: Point3D | null;
  target_point: Point3D | null;
  position_error_mm: number | null;
  motion_progress_percent: number | null;
  joint_positions_deg: number[];
  trajectory_mm: [number, number, number][];
  trajectory_total_points: number;
  frame_sequence: number;
  simulation_fps: number | null;
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
