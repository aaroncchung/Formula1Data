/**
 * The client the pages share: the configured base URL and the browser's own
 * `fetch`. It holds no state, so one is enough.
 */

import { createPublishedClient } from "./client.ts";
import { publishedDataBaseUrl } from "./config.ts";

export const publishedData = createPublishedClient({
  baseUrl: publishedDataBaseUrl(),
  // Looked up when a request is made, not when this module loads: the module
  // is also evaluated while the static shell is built, where nothing is
  // fetched.
  fetch: (url, init) => fetch(url, init)
});
