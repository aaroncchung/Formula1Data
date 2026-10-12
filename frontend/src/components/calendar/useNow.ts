"use client";

import { useState } from "react";

/**
 * The time the component was first rendered, the same on every later render.
 * A page that asked the clock each time it rendered could show a session as
 * scheduled in one place and as run in another.
 */
export function useNow(): number {
  const [now] = useState(() => Date.now());
  return now;
}
