import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const runtimeViews = [
  "src/app/page.tsx",
  "src/app/standings/page.tsx",
  "src/app/seasons/page.tsx",
  "src/app/seasons/[year]/SeasonPageClient.tsx",
  "src/app/seasons/[year]/[round]/MeetingPageClient.tsx",
  "src/components/session/SessionIngestionPanel.tsx"
];

test("catalog, navigation, standings, and session views load through the browser artifact API", async () => {
  for (const path of runtimeViews) {
    const source = await readFile(new URL(`../${path}`, import.meta.url), "utf-8");
    assert.match(source, /@\/lib\/api/);
    assert.doesNotMatch(source, /@\/lib\/api-server/);
  }
});

test("scheduled session route shells do not depend on checked-in generated sessions", async () => {
  const source = await readFile(
    new URL("../src/app/seasons/[year]/[round]/[session]/page.tsx", import.meta.url),
    "utf-8"
  );
  assert.match(source, /meeting\.sessions_available/);
  assert.match(source, /SessionIngestionPanel/);
});

test("the stable explore shell renders season, meeting, and session views", async () => {
  const source = await readFile(
    new URL("../src/app/seasons/explore/ExplorePageClient.tsx", import.meta.url),
    "utf-8"
  );
  assert.match(source, /parseExploreTarget/);
  assert.match(source, /SeasonPageClient/);
  assert.match(source, /MeetingPageClient/);
  assert.match(source, /SessionIngestionPanel/);
});

test("runtime navigation uses stable explore href helpers", async () => {
  const navigationFiles = [
    "src/app/page.tsx",
    "src/app/seasons/page.tsx",
    "src/app/circuits/page.tsx",
    "src/app/seasons/[year]/SeasonPageClient.tsx",
    "src/app/seasons/[year]/[round]/MeetingPageClient.tsx",
    "src/components/app-shell/GlobalSessionPicker.tsx"
  ];
  for (const path of navigationFiles) {
    const source = await readFile(new URL(`../${path}`, import.meta.url), "utf-8");
    assert.match(source, /@\/lib\/season-routes/);
    assert.doesNotMatch(source, /`\/seasons\/\$\{/);
  }
});
