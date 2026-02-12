-- Watchlist: recurring research on a schedule

CREATE TABLE watchlist_items (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_url TEXT NOT NULL,
    company_name TEXT,
    schedule TEXT NOT NULL DEFAULT 'weekly' CHECK (schedule IN ('weekly', 'biweekly', 'monthly')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'skipped_no_credits')),
    last_document_id INTEGER REFERENCES research_documents(id),
    last_run_at TIMESTAMPTZ,
    next_run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, company_url)
);

CREATE INDEX idx_watchlist_due ON watchlist_items (next_run_at)
    WHERE status = 'active';

CREATE INDEX idx_watchlist_user ON watchlist_items (user_id);

CREATE TABLE watchlist_score_changes (
    id SERIAL PRIMARY KEY,
    watchlist_item_id INTEGER NOT NULL REFERENCES watchlist_items(id) ON DELETE CASCADE,
    old_document_id INTEGER REFERENCES research_documents(id),
    new_document_id INTEGER NOT NULL REFERENCES research_documents(id),
    old_opportunity_score INTEGER,
    new_opportunity_score INTEGER,
    old_pain_score INTEGER,
    new_pain_score INTEGER,
    old_fit_score INTEGER,
    new_fit_score INTEGER,
    old_timing_score INTEGER,
    new_timing_score INTEGER,
    is_significant BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_score_changes_item ON watchlist_score_changes (watchlist_item_id);
