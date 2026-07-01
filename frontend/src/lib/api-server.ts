import { readFile } from "node:fs/promises";
import path from "node:path";

import {
  ApiClientError,
  artifactError,
  createStaticApi,
  isApiFailure,
  isEmptyState,
  isLiveDisabled,
  safeApi
} from "@/lib/static-api-core";

export {
  ApiClientError,
  isApiFailure,
  isEmptyState,
  isLiveDisabled,
  safeApi
};

export function staticDataRoot(): string {
  return path.join(process.cwd(), "public", "data");
}

export function apiBaseUrl(): string {
  return "public/data";
}

async function readServerArtifact<T>(artifactPath: string): Promise<T> {
  const root = staticDataRoot();
  const fullPath = path.resolve(root, artifactPath);
  const relativePath = path.relative(root, fullPath);
  if (relativePath.startsWith("..") || path.isAbsolute(relativePath)) {
    throw new ApiClientError(
      "Static artifact path escapes public/data",
      {
        code: "artifact_path_invalid",
        message: "Static artifact path escapes public/data",
        details: { artifactPath }
      },
      root
    );
  }

  try {
    const contents = await readFile(fullPath, "utf-8");
    return JSON.parse(contents) as T;
  } catch (error) {
    throw artifactError(artifactPath, root, error);
  }
}

export const api = createStaticApi(readServerArtifact);
