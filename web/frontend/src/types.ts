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
