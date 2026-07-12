-- Keep the newest active job if older deployments already admitted duplicates.
update ingestion_jobs as current
set status = 'failed',
    error_message = coalesce(error_message, 'Superseded by a newer active ingestion job'),
    finished_at = coalesce(finished_at, datetime('now'))
where current.status in ('queued', 'running')
  and exists (
    select 1
    from ingestion_jobs as newer
    where newer.session_id = current.session_id
      and newer.kind = current.kind
      and newer.status in ('queued', 'running')
      and (
        newer.created_at > current.created_at
        or (newer.created_at = current.created_at and newer.job_id > current.job_id)
      )
  );

create unique index if not exists idx_ingestion_jobs_one_active
  on ingestion_jobs (session_id, kind)
  where status in ('queued', 'running');
