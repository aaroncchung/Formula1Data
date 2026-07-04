export type ApiErrorPayload = {
  code: string;
  message: string;
  details?: Record<string, unknown> | null;
};

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: ApiErrorPayload; apiBaseUrl: string };

export type SessionIngestionStatus =
  | "missing"
  | "queued"
  | "ingesting"
  | "ready"
  | "failed"
  | "stale";

export type IngestionJobStatus = "queued" | "running" | "succeeded" | "failed";

export type IngestionJob = {
  job_id: string;
  session_id: string;
  kind: "ingest_session" | "refresh_session" | "finalize_live_session";
  status: IngestionJobStatus;
  attempts: number;
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

export type SessionStatusResponse = {
  session_id: string;
  year: number;
  round: number;
  meeting_id?: string | null;
  meeting_name?: string | null;
  session_type: string;
  scheduled_start?: string | null;
  status: SessionIngestionStatus;
  artifact_base_path: string;
  generated_at?: string | null;
  source: string;
  artifact_exists: boolean;
  artifact_path?: string | null;
  size_bytes?: number | null;
  job?: IngestionJob | null;
};

export type QueueIngestionResponse = {
  action: "ready" | "reused" | "queued";
  status: SessionStatusResponse;
  job?: IngestionJob | null;
  message?: Record<string, unknown>;
};

