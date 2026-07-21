import { readFile } from "node:fs/promises";
import path from "node:path";

import type { CatalogArtifact } from "@/lib/static-api-core";

export async function loadRouteCatalog(): Promise<CatalogArtifact> {
  const catalogPath = path.join(process.cwd(), "public", "data", "catalog.json");
  return JSON.parse(await readFile(catalogPath, "utf-8")) as CatalogArtifact;
}
