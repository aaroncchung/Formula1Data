export type ArtifactSourceOptions = {
  artifactBaseUrl?: string;
  dynamicApiBaseUrl?: string;
  staticDataBasePath?: string;
};

export function resolveArtifactBaseUrl(options: ArtifactSourceOptions = {}): string {
  const explicit = options.artifactBaseUrl?.trim();
  if (explicit) return trimTrailingSlash(explicit);

  const dynamicApi = options.dynamicApiBaseUrl?.trim();
  if (dynamicApi) return `${trimTrailingSlash(dynamicApi)}/data`;

  return trimTrailingSlash(options.staticDataBasePath?.trim() || "/data");
}

export function fetchArtifactResponse(
  source: string,
  path: string,
  signal?: AbortSignal,
  fetcher: typeof fetch = fetch
): Promise<Response> {
  return fetcher(`${trimTrailingSlash(source)}/${path}`, { signal, cache: "no-store" });
}

function trimTrailingSlash(value: string): string {
  return value.length > 1 ? value.replace(/\/+$/, "") : value;
}
