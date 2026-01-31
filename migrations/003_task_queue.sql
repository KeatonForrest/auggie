CREATE TABLE IF NOT EXISTS task_queue (
    id BIGSERIAL PRIMARY KEY,
    task_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 3,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error TEXT,
    claimed_by TEXT
);
CREATE INDEX idx_task_queue_pending ON task_queue (status, created_at) WHERE status = 'pending';
