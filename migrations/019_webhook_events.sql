-- Webhook event types and event log

ALTER TABLE webhooks ADD COLUMN IF NOT EXISTS event_types TEXT[] DEFAULT NULL;
-- NULL = subscribe to all events (backward compatible default)

CREATE TABLE IF NOT EXISTS webhook_events (
    id TEXT PRIMARY KEY,  -- "evt_" prefix + random hex
    webhook_id INTEGER REFERENCES webhooks(id),
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhook_events_webhook_id ON webhook_events(webhook_id);
CREATE INDEX IF NOT EXISTS idx_webhook_events_created_at ON webhook_events(created_at);
