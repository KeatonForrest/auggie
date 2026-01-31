-- Partial indexes for fan-out child lookups by payload key + non-terminal status.
CREATE INDEX IF NOT EXISTS idx_tq_payload_bulk_job_active
    ON task_queue ((payload->>'bulk_job_id'))
    WHERE status NOT IN ('completed', 'failed');

CREATE INDEX IF NOT EXISTS idx_tq_payload_list_id_active
    ON task_queue ((payload->>'list_id'))
    WHERE status NOT IN ('completed', 'failed');
