create table if not exists sessions (
  session_id text primary key,
  year integer not null,
  round integer not null,
  meeting_id text,
  meeting_name text,
  session_type text not null,
  scheduled_start text,
  status text not null default 'missing'
    check (status in ('missing', 'queued', 'ingesting', 'ready', 'failed', 'stale')),
  artifact_base_path text,
  generated_at text,
  source text,
  created_at text not null default (datetime('now')),
  updated_at text not null default (datetime('now'))
);

create index if not exists idx_sessions_year_round_type
  on sessions (year, round, session_type);

create index if not exists idx_sessions_status
  on sessions (status);

create table if not exists ingestion_jobs (
  job_id text primary key,
  session_id text not null references sessions(session_id) on delete cascade,
  kind text not null
    check (kind in ('ingest_session', 'refresh_session', 'finalize_live_session')),
  status text not null
    check (status in ('queued', 'running', 'succeeded', 'failed')),
  attempts integer not null default 0,
  error_message text,
  created_at text not null default (datetime('now')),
  started_at text,
  finished_at text
);

create index if not exists idx_ingestion_jobs_session_kind_status
  on ingestion_jobs (session_id, kind, status);

create index if not exists idx_ingestion_jobs_status_created
  on ingestion_jobs (status, created_at);

create table if not exists artifacts (
  session_id text not null references sessions(session_id) on delete cascade,
  kind text not null,
  path text not null,
  size_bytes integer,
  checksum text,
  generated_at text,
  primary key (session_id, kind, path)
);

create index if not exists idx_artifacts_session_kind
  on artifacts (session_id, kind);

create table if not exists live_snapshots (
  kind text primary key,
  payload_json text not null,
  generated_at text not null
);

create index if not exists idx_live_snapshots_generated
  on live_snapshots (generated_at);
