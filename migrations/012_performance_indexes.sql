-- Performance indexes for scaling to 50+ users

-- Composite index for list account queries that filter on both list_id and status
CREATE INDEX IF NOT EXISTS idx_list_accounts_list_status
    ON list_accounts (list_id, status);

-- Composite index for research document dedup cache (24h lookup by user + URL)
CREATE INDEX IF NOT EXISTS idx_research_docs_user_url_created
    ON research_documents (user_id, company_url, created_at DESC);

-- Index for stale task requeue (worker scans running tasks by started_at)
CREATE INDEX IF NOT EXISTS idx_task_queue_running_started
    ON task_queue (status, started_at)
    WHERE status = 'running';

-- Index for bulk job item status scans
CREATE INDEX IF NOT EXISTS idx_bulk_job_items_status
    ON bulk_job_items (status);
