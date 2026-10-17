"use client";

import { Component } from "react";
import type { ReactNode } from "react";

type RenderBoundaryProps = {
  /** What is drawn in place of the children once one of them throws. `retry` draws them again. */
  fallback: (error: Error, retry: () => void) => ReactNode;
  /** A new value draws the children again, as when a new read replaces the one that could not be drawn. */
  resetKey?: unknown;
  children: ReactNode;
};

type RenderBoundaryState = {
  readonly error: Error | null;
  readonly resetKey: unknown;
};

/**
 * Keeps a throw while drawing to the part of the page it happened in.
 *
 * React unmounts everything up to the nearest error boundary when a component
 * throws while rendering. With none, one table that met a row it could not
 * draw took the whole page with it, the navigation included.
 */
export class RenderBoundary extends Component<RenderBoundaryProps, RenderBoundaryState> {
  state: RenderBoundaryState = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: unknown): Partial<RenderBoundaryState> {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  static getDerivedStateFromProps(props: RenderBoundaryProps, state: RenderBoundaryState): Partial<RenderBoundaryState> | null {
    return Object.is(props.resetKey, state.resetKey) ? null : { error: null, resetKey: props.resetKey };
  }

  retry = () => this.setState({ error: null });

  render() {
    return this.state.error ? this.props.fallback(this.state.error, this.retry) : this.props.children;
  }
}
