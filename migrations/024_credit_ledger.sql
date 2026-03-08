-- Credit ledger for audit trail
CREATE TABLE IF NOT EXISTS credit_ledger (
    id BIGSERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    amount_cents INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('charge', 'refund', 'topup')),
    reference_type TEXT,
    reference_id INTEGER,
    api_key_id INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_credit_ledger_org ON credit_ledger (org_id, created_at DESC);
