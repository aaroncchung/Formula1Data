"use client";

import { useEffect, useState } from "react";

export type RuntimeDataState<T> =
  | { state: "loading" }
  | { state: "error"; detail: string }
  | { state: "ready"; data: T };

export function useRuntimeData<T>(loader: () => Promise<T>): RuntimeDataState<T> {
  const [state, setState] = useState<RuntimeDataState<T>>({ state: "loading" });

  useEffect(() => {
    let ignore = false;
    loader()
      .then((data) => {
        if (!ignore) setState({ state: "ready", data });
      })
      .catch((error) => {
        if (!ignore) {
          setState({ state: "error", detail: error instanceof Error ? error.message : "Data could not be loaded" });
        }
      });
    return () => {
      ignore = true;
    };
  }, [loader]);

  return state;
}
