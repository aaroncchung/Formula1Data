import {
  ApiClientError,
  artifactError,
  createStaticApi,
  isApiFailure,
  isEmptyState,
  isLiveDisabled,
  safeApi
} from "@/lib/static-api-core";
import type { QueueIngestionResponse, SessionStatusResponse } from "@/types/api";
import type { LiveDisabledResponse } from "@/types/domain";

const DEFAULT_STATIC_DATA_BASE_PATH = "/data";
const DEFAULT_DYNAMIC_API_BASE_PATH = "";
const REQUEST_TIMEOUT_MS = 12000;

export {
  ApiClientError,
  isApiFailure,
  isEmptyState,
  isLiveDisabled,
  safeApi
};

export function staticDataBasePath(): string {
  return process.env.NEXT_PUBLIC_STATIC_DATA_BASE_PATH || DEFAULT_STATIC_DATA_BASE_PATH;
}

export function apiBaseUrl(): string {
  return staticDataBasePath();
}

export function dynamicApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_DYNAMIC_API_BASE_URL || DEFAULT_DYNAMIC_API_BASE_PATH;
}

async function readBrowserArtifact<T>(path: string): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const source = staticDataBasePath();
  try {
    const response = await fetch(`${source}/${path}`, {
      signal: controller.signal,
      cache: "force-cache",
      headers: { "Content-Type": "application/json" }
    });
    if (!response.ok) {
      throw new ApiClientError(
        response.status === 404 ? "Static artifact was not generated" : "Static artifact could not be loaded",
        {
          code: response.status === 404 ? "artifact_not_found" : "artifact_unavailable",
          message: response.statusText,
          details: { path, source, status: response.status }
        },
        source
      );
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error;
    }
    throw artifactError(path, source, error);
  } finally {
    clearTimeout(timeout);
  }
}

export const api = createStaticApi(readBrowserArtifact);

export const dynamicApi = {
  sessionStatus: (params: { year: number; round: number; session: string }) => {
    const search = new URLSearchParams({
      year: String(params.year),
      round: String(params.round),
      session: params.session
    });
    return readDynamicJson<SessionStatusResponse>(`/api/session-status?${search}`);
  },
  queueSessionIngestion: (payload: {
    year: number;
    round: number;
    session: string;
    meeting_id?: string | null;
    meeting_name?: string | null;
    scheduled_start?: string | null;
    force?: boolean;
  }) =>
    readDynamicJson<QueueIngestionResponse>("/api/ingestion/session", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  ingestionJob: (jobId: string) =>
    readDynamicJson<SessionStatusResponse["job"]>(`/api/ingestion/jobs/${encodeURIComponent(jobId)}`),
  liveCurrentSession: () => readDynamicJson<Record<string, unknown> | LiveDisabledResponse>("/api/live/current-session"),
  liveTiming: () => readDynamicJson<Record<string, unknown> | LiveDisabledResponse>("/api/live/timing"),
  liveRaceControl: () => readDynamicJson<Record<string, unknown> | LiveDisabledResponse>("/api/live/race-control"),
  livePositions: () => readDynamicJson<Record<string, unknown> | LiveDisabledResponse>("/api/live/positions"),
  liveWeather: () => readDynamicJson<Record<string, unknown> | LiveDisabledResponse>("/api/live/weather")
};

async function readDynamicJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const source = dynamicApiBaseUrl();
  const target = `${source.replace(/\/$/, "")}${path}`;
  try {
    const response = await fetch(target, {
      ...init,
      signal: controller.signal,
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        ...(init.headers || {})
      }
    });
    const payload = await readResponseJson(response);
    if (!response.ok) {
      const errorPayload = {
        code: payloadCode(payload),
        message: payloadMessage(payload, response.statusText),
        details: typeof payload === "object" && payload !== null ? (payload as Record<string, unknown>) : null
      };
      throw new ApiClientError(errorPayload.message, errorPayload, source || "same-origin");
    }
    return payload as T;
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error;
    }
    throw new ApiClientError(
      "Dynamic API is unavailable",
      {
        code: "dynamic_api_unavailable",
        message: error instanceof Error ? error.message : "Dynamic API is unavailable",
        details: { path, source: source || "same-origin" }
      },
      source || "same-origin"
    );
  } finally {
    clearTimeout(timeout);
  }
}

async function readResponseJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch {
    return { message: text };
  }
}

function payloadCode(payload: unknown): string {
  return typeof payload === "object" && payload !== null && "code" in payload
    ? String((payload as { code?: unknown }).code)
    : "dynamic_api_error";
}

function payloadMessage(payload: unknown, fallback: string): string {
  return typeof payload === "object" && payload !== null && "message" in payload
    ? String((payload as { message?: unknown }).message)
    : fallback || "Dynamic API request failed";
}

