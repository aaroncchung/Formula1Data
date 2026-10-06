/**
 * The readers the calendar, standings and summary pages share.
 *
 * `publishedSource` is the published-data client with one difference: callers
 * that ask for the calendar at the same moment share one request. A session
 * is opened through it unchanged, so a view still reads its pointer once and
 * pins one generation.
 */

import { publishedData } from "./published/browser.ts";
import type { PublishedClient } from "./published/client.ts";
import { publishedDataBaseUrl } from "./published/config.ts";
import { createStandingsReader } from "./published/standings.ts";
import { shareWhilePending } from "./shared-request.ts";

export const publishedSource: PublishedClient = Object.freeze({
  index: shareWhilePending(() => publishedData.index()),
  openSession: (sessionKey, options) => publishedData.openSession(sessionKey, options)
});

export const publishedStandings = createStandingsReader({
  baseUrl: publishedDataBaseUrl(),
  // Looked up when a request is made, not when this module loads: the module
  // is also evaluated while the static shell is built, where nothing is
  // fetched.
  fetch: (url, init) => fetch(url, init)
});
