import {
  ApiClientError,
  artifactError,
  createStaticApi,
  isApiFailure,
  isEmptyState,
  safeApi
} from "@/lib/static-api-core";
import type { QueueIngestionResponse, SessionStatusResponse } from "@/types/api";

const DEFAULT_STATIC_DATA_BASE_PATH = "/data";
const DEFAULT_DYNAMIC_API_BASE_PATH = "";
const REQUEST_TIMEOUT_MS = 12000;

export {
  ApiClientError,
  isApiFailure,
  isEmptyState,
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

export function dynamicApiSourceLabel(): string {
  return dynamicApiBaseUrl() || "same-origin /api";
}

export function isDynamicApiUnavailable(error: unknown): error is ApiClientError {
  return error instanceof ApiClientError && error.payload.code === "dynamic_api_unavailable";
}

export function isDynamicApiRouteMissing(error: unknown): boolean {
  return (
    isDynamicApiUnavailable(error) &&
    typeof error.payload.details === "object" &&
    error.payload.details !== null &&
    error.payload.details.reason === "missing_route"
  );
}

async function readBrowserArtifact<T>(path: string): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const source = staticDataBasePath();
  try {
    const response = await fetch(`${source}/${path}`, {
      signal: controller.signal,
      cache: "default"
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
    readDynamicJson<SessionStatusResponse["job"]>(`/api/ingestion/jobs/${encodeURIComponent(jobId)}`)
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
    const payload = await readResponsePayload(response);
    if (!response.ok) {
      const unavailable = isMissingDynamicRoute(response, payload);
      const errorPayload = {
        code: unavailable ? "dynamic_api_unavailable" : payloadCode(payload.value),
        message: unavailable
          ? "Dynamic API routes are not configured for this deployment."
          : payloadMessage(payload.value, response.statusText),
        details: dynamicErrorDetails(path, source, response, payload.value, unavailable ? "missing_route" : undefined)
      };
      throw new ApiClientError(errorPayload.message, errorPayload, source || "same-origin");
    }
    return payload.value as T;
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error;
    }
    throw new ApiClientError(
      "Dynamic API is unavailable from this deployment.",
      {
        code: "dynamic_api_unavailable",
        message:
          error instanceof DOMException && error.name === "AbortError"
            ? "Dynamic API request timed out."
            : "Dynamic API is unavailable from this deployment.",
        details: {
          path,
          source: source || "same-origin",
          reason: error instanceof DOMException && error.name === "AbortError" ? "timeout" : "request_failed"
        }
      },
      source || "same-origin"
    );
  } finally {
    clearTimeout(timeout);
  }
}

type ResponsePayload = {
  value: unknown;
  isJson: boolean;
};

async function readResponsePayload(response: Response): Promise<ResponsePayload> {
  const text = await response.text();
  if (!text) {
    return { value: {}, isJson: false };
  }
  try {
    return { value: JSON.parse(text), isJson: true };
  } catch {
    return {
      value: {
        message: response.statusText || "Dynamic API request failed"
      },
      isJson: false
    };
  }
}

function isMissingDynamicRoute(response: Response, payload: ResponsePayload): boolean {
  return response.status === 404 && !payload.isJson;
}

function dynamicErrorDetails(
  path: string,
  source: string,
  response: Response,
  payload: unknown,
  reason?: string
): Record<string, unknown> | null {
  const details: Record<string, unknown> = {
    path,
    source: source || "same-origin",
    status: response.status
  };
  if (reason) {
    details.reason = reason;
  }
  if (typeof payload === "object" && payload !== null) {
    details.payload = payload;
  }
  return details;
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

