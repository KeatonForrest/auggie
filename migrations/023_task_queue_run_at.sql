-- Add run_at column for retry backoff scheduling
ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS run_at TIMESTAMPTZ DEFAULT now();

-- Index for efficient claim_next queries
CREATE INDEX IF NOT EXISTS idx_task_queue_run_at ON task_queue (run_at) WHERE status = 'pending';
