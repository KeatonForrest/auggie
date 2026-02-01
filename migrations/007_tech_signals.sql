CREATE TABLE IF NOT EXISTS tech_signals (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES research_documents(id) ON DELETE CASCADE,
    domain TEXT NOT NULL,
    signal_source TEXT NOT NULL,
    tech_name TEXT NOT NULL,
    tech_category TEXT,
    confidence INTEGER DEFAULT 100,
    version TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tech_signals_document ON tech_signals(document_id);
CREATE INDEX IF NOT EXISTS idx_tech_signals_domain ON tech_signals(domain);

CREATE TABLE IF NOT EXISTS pain_inferences (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES research_documents(id) ON DELETE CASCADE,
    rule_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    severity TEXT NOT NULL,
    confidence INTEGER DEFAULT 0,
    evidence JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pain_inferences_document ON pain_inferences(document_id);
