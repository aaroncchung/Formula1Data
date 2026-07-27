"use client";

import { AlertTriangle, CheckCircle2, Clock3, Play, RefreshCw, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { SessionTabs, type SessionTabsProps } from "@/components/session/SessionTabs";
import { api, dynamicApi, dynamicApiSourceLabel, isDynamicApiRouteMissing } from "@/lib/api";
import { createRequestGenerationGuard } from "@/lib/request-generation";
import { loadSessionDashboard } from "@/lib/session-dashboard";
import type { ApiErrorPayload, SessionStatusResponse } from "@/types/api";

type LoadState =
  | { state: "idle" | "loading" }
  | { state: "static-only"; detail: string }
  | { state: "error"; error: ApiErrorPayload }
  | { state: "ready"; status: SessionStatusResponse };

type DashboardState =
  | { state: "idle" | "loading" }
  | { state: "error"; detail: string }
  | { state: "ready"; data: SessionTabsProps };

type Props = {
  year: number;
  round: number;
  session: string;
  meetingId?: string | null;
  meetingName?: string | null;
  scheduledStart?: string | null;
  staticCommand: string;
};

export function SessionIngestionPanel({
  year,
  round,
  session,
  meetingId,
  meetingName,
  scheduledStart,
  staticCommand
}: Props) {
  const [statusState, setStatusState] = useState<LoadState>({ state: "idle" });
  const [dashboardState, setDashboardState] = useState<DashboardState>({ state: "idle" });
  const [isQueueing, setIsQueueing] = useState(false);

  // Status polling and the queue action share one ordering guard: both write
  // `statusState`, so the newest of the two must win regardless of which
  // response arrives last. The dashboard load is not part of it -- it is
  // single-shot and gated on `idle`, and a status poll must not supersede it.
  const statusRequests = useMemo(() => createRequestGenerationGuard(), []);

  const loadStatus = useCallback(async () => {
    const token = statusRequests.begin();
    setStatusState({ state: "loading" });
    try {
      const status = await dynamicApi.sessionStatus({ year, round, session });
      if (!statusRequests.isCurrent(token)) {
        return null;
      }
      setStatusState({ state: "ready", status });
      return status;
    } catch (error) {
      if (!statusRequests.isCurrent(token)) {
        return null;
      }
      if (isDynamicApiRouteMissing(error)) {
        setStatusState({
          state: "static-only",
          detail:
            "This deployment is serving committed static JSON artifacts only. On-demand ingestion requires the Cloudflare Worker API."
        });
        return null;
      }
      setStatusState({ state: "error", error: apiError(error) });
      return null;
    }
  }, [round, session, statusRequests, year]);

  const loadDashboard = useCallback(async (sessionId: string) => {
    setDashboardState({ state: "loading" });
    const dashboard = await loadSessionDashboard(api, sessionId);
    if (!dashboard.ok) {
      setDashboardState({ state: "error", detail: dashboard.failure.error.message });
      return;
    }
    setDashboardState({ state: "ready", data: dashboard.data });
  }, []);

  // `loadStatus` changes identity exactly when year/round/session do, so this
  // cleanup runs on unmount and on a move to a different session -- retiring
  // every request made against the previous one, so a late response cannot
  // describe a session the user has already left.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadStatus();
    }, 0);
    return () => {
      window.clearTimeout(timer);
      statusRequests.invalidate();
    };
  }, [loadStatus, statusRequests]);

  const status = statusState.state === "ready" ? statusState.status : null;
  useEffect(() => {
    if (!status || !["queued", "ingesting"].includes(status.status)) {
      return;
    }
    const timer = window.setInterval(() => {
      void loadStatus();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [loadStatus, status]);

  useEffect(() => {
    if (status?.status === "ready" && dashboardState.state === "idle") {
      const timer = window.setTimeout(() => {
        void loadDashboard(status.session_id);
      }, 0);
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [dashboardState.state, loadDashboard, status]);

  const queueLabel = useMemo(() => {
    if (statusState.state === "static-only") {
      return "Worker API required";
    }
    if (status?.status === "failed") {
      return "Retry ingestion";
    }
    if (status?.status === "queued" || status?.status === "ingesting") {
      return "Refresh status";
    }
    return "Queue ingestion";
  }, [status?.status, statusState.state]);

  async function queueIngestion(force = false) {
    if (statusState.state === "static-only") {
      await loadStatus();
      return;
    }
    if (status?.status === "queued" || status?.status === "ingesting") {
      await loadStatus();
      return;
    }
    setIsQueueing(true);
    const token = statusRequests.begin();
    try {
      const response = await dynamicApi.queueSessionIngestion({
        year,
        round,
        session,
        meeting_id: meetingId,
        meeting_name: meetingName,
        scheduled_start: scheduledStart,
        force
      });
      if (!statusRequests.isCurrent(token)) {
        return;
      }
      setStatusState({ state: "ready", status: response.status });
    } catch (error) {
      if (!statusRequests.isCurrent(token)) {
        return;
      }
      setStatusState({ state: "error", error: apiError(error) });
    } finally {
      setIsQueueing(false);
    }
  }

  if (dashboardState.state === "ready") {
    const summary = dashboardState.data.summary;
    return (
      <div>
        <PageHeader
          eyebrow={`${summary.year} Round ${summary.round}`}
          title={`${summary.meeting} - ${summary.session}`}
          description={`${summary.circuit}, ${summary.country}. ${summary.weather_summary}.`}
        />
        <SessionTabs {...dashboardState.data} />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <ChartPanel
        title={`${year} Round ${round} ${session.toUpperCase()}`}
        description={
          statusState.state === "static-only"
            ? "This page can show committed artifacts, but queueing a new ingestion job needs the dynamic API."
            : "This static page can queue on-demand ingestion through the Cloudflare API layer."
        }
      >
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <StatusBadge statusState={statusState} />
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="inline-flex items-center gap-2 rounded border border-line bg-white/[0.04] px-3 py-2 text-sm font-semibold text-white hover:border-aqua/60 disabled:cursor-wait disabled:opacity-60"
              onClick={() => void loadStatus()}
              disabled={statusState.state === "loading"}
            >
              <RefreshCw size={16} />
              {statusState.state === "static-only" ? "Check API" : "Refresh"}
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-2 rounded border border-aqua/40 bg-aqua/10 px-3 py-2 text-sm font-semibold text-white hover:border-aqua disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => void queueIngestion(status?.status === "failed")}
              disabled={isQueueing || statusState.state === "static-only"}
            >
              {status?.status === "failed" ? <RotateCcw size={16} /> : <Play size={16} />}
              {queueLabel}
            </button>
          </div>
        </div>
        {status?.job ? (
          <div className="mt-4 rounded border border-line bg-white/[0.03] p-3 text-sm text-slate-300">
            <div className="font-semibold text-white">{status.job.kind.replace(/_/g, " ")}</div>
            <div className="mt-1">Job {status.job.job_id}</div>
            <div className="mt-1">Attempts: {status.job.attempts}</div>
            {status.job.error_message ? <div className="mt-1 text-amber">{status.job.error_message}</div> : null}
          </div>
        ) : null}
        {statusState.state === "error" ? (
          <div className="mt-4">
            <ErrorState title="Dynamic ingestion API unavailable" detail={statusState.error.message} />
          </div>
        ) : null}
        {statusState.state === "static-only" ? (
          <div className="mt-4">
            <EmptyState
              title="Static-only deployment"
              detail={`${statusState.detail} Historical browsing does not need a backend; it reads the committed files under /data. Dynamic API target checked: ${dynamicApiSourceLabel()}.`}
            />
          </div>
        ) : null}
        {dashboardState.state === "loading" ? (
          <div className="mt-4">
            <EmptyState title="Loading generated artifacts" detail="The session is ready; dashboard data is loading from /data." />
          </div>
        ) : null}
        {dashboardState.state === "error" ? (
          <div className="mt-4">
            <ErrorState title="Generated artifacts are not readable yet" detail={dashboardState.detail} />
          </div>
        ) : null}
      </ChartPanel>
      <ChartPanel title="Local static fallback">
        <pre className="overflow-auto text-sm text-slate-300">{staticCommand}</pre>
      </ChartPanel>
    </div>
  );
}

function StatusBadge({ statusState }: { statusState: LoadState }) {
  if (statusState.state === "loading" || statusState.state === "idle") {
    return (
      <div className="inline-flex items-center gap-2 text-sm font-semibold text-slate-300">
        <Clock3 size={16} />
        Checking session status
      </div>
    );
  }
  if (statusState.state === "error") {
    return (
      <div className="inline-flex items-center gap-2 text-sm font-semibold text-amber">
        <AlertTriangle size={16} />
        API unavailable
      </div>
    );
  }
  if (statusState.state === "static-only") {
    return (
      <div className="inline-flex items-center gap-2 text-sm font-semibold text-slate-300">
        <AlertTriangle size={16} />
        Static-only mode
      </div>
    );
  }
  if (statusState.state !== "ready") {
    return null;
  }
  const status = statusState.status.status;
  const ready = status === "ready";
  return (
    <div className={`inline-flex items-center gap-2 text-sm font-semibold ${ready ? "text-aqua" : "text-amber"}`}>
      {ready ? <CheckCircle2 size={16} /> : <Clock3 size={16} />}
      {statusLabel(status)}
    </div>
  );
}

function statusLabel(status: SessionStatusResponse["status"]) {
  const labels: Record<SessionStatusResponse["status"], string> = {
    missing: "Not generated",
    queued: "Queued",
    ingesting: "Ingesting",
    ready: "Ready",
    failed: "Failed",
    stale: "Stale"
  };
  return labels[status];
}

function apiError(error: unknown): ApiErrorPayload {
  if (error && typeof error === "object" && "payload" in error) {
    return (error as { payload: ApiErrorPayload }).payload;
  }
  return {
    code: "unknown",
    message: error instanceof Error ? error.message : "Unknown error"
  };
}
