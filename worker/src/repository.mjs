import { ACTIVE_JOB_STATUSES } from "./session-utils.mjs";

export function createRepository(env) {
  if (env.F1_DB?.prepare) {
    return createD1Repository(env.F1_DB);
  }
  throw new Error("Required F1_DB binding is unavailable");
}

export function createD1Repository(db) {
  return {
    async getSession(sessionId) {
      return db.prepare("select * from sessions where session_id = ?").bind(sessionId).first();
    },

    async getSessionByLookup(year, round, sessionType) {
      return db
        .prepare(
          "select * from sessions where year = ? and round = ? and upper(session_type) = upper(?)"
        )
        .bind(year, round, sessionType)
        .first();
    },

    async upsertSession(session) {
      await db
        .prepare(
          `insert into sessions (
            session_id, year, round, meeting_id, meeting_name, session_type,
            scheduled_start, status, artifact_base_path, generated_at, source,
            created_at, updated_at
          ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
          on conflict(session_id) do update set
            year = excluded.year,
            round = excluded.round,
            meeting_id = coalesce(excluded.meeting_id, sessions.meeting_id),
            meeting_name = coalesce(excluded.meeting_name, sessions.meeting_name),
            session_type = excluded.session_type,
            scheduled_start = coalesce(excluded.scheduled_start, sessions.scheduled_start),
            status = excluded.status,
            artifact_base_path = excluded.artifact_base_path,
            generated_at = coalesce(excluded.generated_at, sessions.generated_at),
            source = coalesce(excluded.source, sessions.source),
            updated_at = datetime('now')`
        )
        .bind(
          session.session_id,
          session.year,
          session.round,
          session.meeting_id || null,
          session.meeting_name || null,
          session.session_type,
          session.scheduled_start || null,
          session.status,
          session.artifact_base_path || null,
          session.generated_at || null,
          session.source || null
        )
        .run();
      return this.getSession(session.session_id);
    },

    async getActiveJob(sessionId, kind) {
      const placeholders = ACTIVE_JOB_STATUSES.map(() => "?").join(", ");
      return db
        .prepare(
          `select * from ingestion_jobs
          where session_id = ?
            and kind = ?
            and status in (${placeholders})
          order by created_at desc
          limit 1`
        )
        .bind(sessionId, kind, ...ACTIVE_JOB_STATUSES)
        .first();
    },

    async getLatestJob(sessionId, kind) {
      return db
        .prepare(
          `select * from ingestion_jobs
          where session_id = ?
            and kind = ?
          order by created_at desc
          limit 1`
        )
        .bind(sessionId, kind)
        .first();
    },

    async createJob(job) {
      await db
        .prepare(
          `insert or ignore into ingestion_jobs (
            job_id, session_id, kind, status, attempts, error_message,
            created_at, started_at, finished_at
          ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)`
        )
        .bind(
          job.job_id,
          job.session_id,
          job.kind,
          job.status,
          job.attempts || 0,
          job.error_message || null,
          job.created_at,
          job.started_at || null,
          job.finished_at || null
        )
        .run();
      return this.getJob(job.job_id);
    },

    async getJob(jobId) {
      return db.prepare("select * from ingestion_jobs where job_id = ?").bind(jobId).first();
    },

    async updateJob(jobId, updates) {
      const current = await this.getJob(jobId);
      if (!current) {
        return null;
      }
      const next = { ...current, ...updates };
      await db
        .prepare(
          `update ingestion_jobs
          set status = ?, attempts = ?, error_message = ?, started_at = ?, finished_at = ?
          where job_id = ?`
        )
        .bind(
          next.status,
          next.attempts || 0,
          next.error_message || null,
          next.started_at || null,
          next.finished_at || null,
          jobId
        )
        .run();
      return this.getJob(jobId);
    },

    async incrementJobAttempts(jobId, errorMessage = null) {
      await db
        .prepare(
          `update ingestion_jobs
          set attempts = attempts + 1,
              error_message = coalesce(?, error_message)
          where job_id = ?`
        )
        .bind(errorMessage, jobId)
        .run();
      return this.getJob(jobId);
    },

    async recordArtifacts(sessionId, artifacts) {
      const statements = (artifacts || []).map((artifact) =>
        db
          .prepare(
            `insert into artifacts (
              session_id, kind, path, size_bytes, checksum, generated_at
            ) values (?, ?, ?, ?, ?, ?)
            on conflict(session_id, kind, path) do update set
              size_bytes = excluded.size_bytes,
              checksum = excluded.checksum,
              generated_at = excluded.generated_at`
          )
          .bind(
            sessionId,
            artifact.kind,
            artifact.path,
            artifact.size_bytes ?? null,
            artifact.checksum || null,
            artifact.generated_at || null
          )
      );
      if (statements.length) {
        await db.batch(statements);
      }
    },

    async storeLiveSnapshot(kind, payload, generatedAt) {
      await db
        .prepare(
          `insert into live_snapshots (kind, payload_json, generated_at)
          values (?, ?, ?)
          on conflict(kind) do update set
            payload_json = excluded.payload_json,
            generated_at = excluded.generated_at`
        )
        .bind(kind, JSON.stringify(payload), generatedAt)
        .run();
    }
  };
}

export function createMemoryRepository(state = memoryState) {
  return {
    async getSession(sessionId) {
      return state.sessions.get(sessionId) || null;
    },

    async getSessionByLookup(year, round, sessionType) {
      for (const session of state.sessions.values()) {
        if (
          Number(session.year) === Number(year) &&
          Number(session.round) === Number(round) &&
          String(session.session_type).toUpperCase() === String(sessionType).toUpperCase()
        ) {
          return session;
        }
      }
      return null;
    },

    async upsertSession(session) {
      const previous = state.sessions.get(session.session_id) || {};
      const next = {
        ...previous,
        ...session,
        meeting_id: session.meeting_id || previous.meeting_id || null,
        meeting_name: session.meeting_name || previous.meeting_name || null,
        scheduled_start: session.scheduled_start || previous.scheduled_start || null,
        generated_at: session.generated_at || previous.generated_at || null,
        source: session.source || previous.source || null,
        updated_at: new Date().toISOString(),
        created_at: previous.created_at || new Date().toISOString()
      };
      state.sessions.set(session.session_id, next);
      return next;
    },

    async getActiveJob(sessionId, kind) {
      return (
        Array.from(state.jobs.values())
          .filter(
            (job) =>
              job.session_id === sessionId &&
              job.kind === kind &&
              ACTIVE_JOB_STATUSES.includes(job.status)
          )
          .sort((left, right) => String(right.created_at).localeCompare(String(left.created_at)))[0] || null
      );
    },

    async getLatestJob(sessionId, kind) {
      return (
        Array.from(state.jobs.values())
          .filter((job) => job.session_id === sessionId && job.kind === kind)
          .sort((left, right) => String(right.created_at).localeCompare(String(left.created_at)))[0] || null
      );
    },

    async createJob(job) {
      state.jobs.set(job.job_id, { ...job });
      return state.jobs.get(job.job_id);
    },

    async getJob(jobId) {
      return state.jobs.get(jobId) || null;
    },

    async updateJob(jobId, updates) {
      const current = state.jobs.get(jobId);
      if (!current) {
        return null;
      }
      const next = { ...current, ...updates };
      state.jobs.set(jobId, next);
      return next;
    },

    async incrementJobAttempts(jobId, errorMessage = null) {
      const current = state.jobs.get(jobId);
      if (!current) {
        return null;
      }
      const next = {
        ...current,
        attempts: Number(current.attempts || 0) + 1,
        error_message: errorMessage || current.error_message || null
      };
      state.jobs.set(jobId, next);
      return next;
    },

    async recordArtifacts(sessionId, artifacts) {
      for (const artifact of artifacts || []) {
        state.artifacts.set(`${sessionId}:${artifact.kind}:${artifact.path}`, { session_id: sessionId, ...artifact });
      }
    },

    async storeLiveSnapshot(kind, payload, generatedAt) {
      state.liveSnapshots.set(kind, { kind, payload_json: JSON.stringify(payload), generated_at: generatedAt });
    }
  };
}
