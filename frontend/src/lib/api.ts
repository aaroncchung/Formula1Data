import {
  ApiClientError,
  artifactError,
  createStaticApi,
  isApiFailure,
  isEmptyState,
  isLiveDisabled,
  safeApi
} from "@/lib/static-api-core";

const DEFAULT_STATIC_DATA_BASE_PATH = "/data";
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

