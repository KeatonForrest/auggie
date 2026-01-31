-- Initial schema: tables and indexes
-- This migration extracts all CREATE TABLE and CREATE INDEX statements from init_database()

-- Enable pgvector extension (conditional on materials_enabled in app code)
-- Note: This should be run when materials_enabled=true in config
-- CREATE EXTENSION IF NOT EXISTS vector;

-- =================================================================
-- Core tables: users, research, feedback
-- =================================================================

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,

    -- Auth
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    picture TEXT,
    google_id TEXT UNIQUE,
    microsoft_id TEXT UNIQUE,

    -- Profile (legacy - kept for backwards compatibility)
    company_name TEXT,
    product_context TEXT,
    industry TEXT,

    -- Enhanced Profile - Product Info
    product_name TEXT,
    product_description TEXT,
    problems_solved TEXT,
    differentiators TEXT,

    -- Enhanced Profile - ICP
    target_company_size TEXT,
    target_industries TEXT,
    target_personas TEXT,

    -- Enhanced Profile - Competition
    competitors TEXT,

    -- Billing
    stripe_customer_id TEXT UNIQUE,
    stripe_subscription_id TEXT,
    subscription_status TEXT DEFAULT 'none'
        CHECK (subscription_status IN ('none', 'active', 'past_due', 'canceled')),

    -- Usage
    searches_used INTEGER DEFAULT 0,
    bonus_credits INTEGER DEFAULT 0,
    billing_period_start TIMESTAMPTZ DEFAULT NOW(),

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS research_documents (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    company_url TEXT NOT NULL,
    company_name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    company_overview TEXT,
    projects_initiatives TEXT,
    confirmed_tech_stack TEXT,
    hiring_signals TEXT,
    business_problems TEXT,
    product_fit TEXT,
    talking_points TEXT,
    recent_news TEXT,
    information_gaps TEXT,
    full_markdown TEXT
);

CREATE TABLE IF NOT EXISTS research_feedback (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES research_documents(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    is_positive BOOLEAN NOT NULL,
    comment TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(document_id, user_id)
);

-- =================================================================
-- API Keys and Usage
-- =================================================================

CREATE TABLE IF NOT EXISTS api_keys (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash TEXT NOT NULL,
    prefix TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT 'Default',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    revoked BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS api_usage (
    id BIGSERIAL PRIMARY KEY,
    api_key_id BIGINT NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    endpoint TEXT NOT NULL,
    credits_used INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =================================================================
-- Enriched Contacts
-- =================================================================

CREATE TABLE IF NOT EXISTS enriched_contacts (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES research_documents(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT,
    first_name TEXT,
    last_name TEXT,
    title TEXT,
    email TEXT,
    email_status TEXT,
    profile_url TEXT,
    company_name TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =================================================================
-- Research Jobs (async API)
-- =================================================================

CREATE TABLE IF NOT EXISTS research_jobs (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    api_key_id BIGINT NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    company_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'processing'
        CHECK (status IN ('processing', 'completed', 'failed')),
    document_id BIGINT REFERENCES research_documents(id) ON DELETE SET NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- =================================================================
-- Webhooks
-- =================================================================

CREATE TABLE IF NOT EXISTS webhooks (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    secret TEXT NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id)
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id BIGSERIAL PRIMARY KEY,
    webhook_id BIGINT NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
    job_id BIGINT NOT NULL REFERENCES research_jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'success', 'failed')),
    http_status INTEGER,
    error_message TEXT,
    attempts INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =================================================================
-- Bulk Jobs
-- =================================================================

CREATE TABLE IF NOT EXISTS bulk_jobs (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    api_key_id BIGINT NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    name TEXT,
    status TEXT NOT NULL DEFAULT 'processing'
        CHECK (status IN ('processing', 'completed', 'partial_failure', 'failed')),
    total_items INTEGER NOT NULL,
    completed_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    credits_reserved INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS bulk_job_items (
    id BIGSERIAL PRIMARY KEY,
    bulk_job_id BIGINT NOT NULL REFERENCES bulk_jobs(id) ON DELETE CASCADE,
    research_job_id BIGINT REFERENCES research_jobs(id) ON DELETE SET NULL,
    company_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    document_id BIGINT REFERENCES research_documents(id) ON DELETE SET NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- =================================================================
-- Lists
-- =================================================================

CREATE TABLE IF NOT EXISTS lists (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    api_key_id BIGINT,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    total_accounts INTEGER DEFAULT 0,
    analyzed_accounts INTEGER DEFAULT 0,
    failed_accounts INTEGER DEFAULT 0,
    credits_reserved INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS list_accounts (
    id BIGSERIAL PRIMARY KEY,
    list_id BIGINT REFERENCES lists(id) ON DELETE CASCADE,
    company_url TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    document_id BIGINT REFERENCES research_documents(id) ON DELETE SET NULL,
    research_job_id BIGINT REFERENCES research_jobs(id) ON DELETE SET NULL,
    pain_score INTEGER,
    fit_score INTEGER,
    timing_score INTEGER,
    composite_score INTEGER,
    company_name TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    analyzed_at TIMESTAMPTZ
);

-- =================================================================
-- Fulfilled Sessions (idempotent Stripe fulfillment)
-- =================================================================

CREATE TABLE IF NOT EXISTS fulfilled_sessions (
    session_id TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credits INTEGER NOT NULL,
    fulfilled_at TIMESTAMPTZ DEFAULT NOW()
);

-- =================================================================
-- Integrations (HubSpot, Instantly, etc.)
-- =================================================================

CREATE TABLE IF NOT EXISTS integrations (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    token_expires_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, provider)
);

-- =================================================================
-- Outreach Drafts
-- =================================================================

CREATE TABLE IF NOT EXISTS outreach_drafts (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES research_documents(id) ON DELETE CASCADE UNIQUE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =================================================================
-- Automation Rules
-- =================================================================

CREATE TABLE IF NOT EXISTS automation_rules (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    trigger_event TEXT NOT NULL,
    conditions JSONB NOT NULL DEFAULT '{}',
    action TEXT NOT NULL,
    action_config JSONB NOT NULL DEFAULT '{}',
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS automation_runs (
    id BIGSERIAL PRIMARY KEY,
    rule_id BIGINT NOT NULL REFERENCES automation_rules(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    list_id BIGINT,
    matched_accounts INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- =================================================================
-- Materials (v2 - for uploaded sales materials)
-- Only create if materials feature is enabled (requires pgvector)
-- =================================================================

CREATE TABLE IF NOT EXISTS materials (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- File info
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_size INTEGER,
    storage_key TEXT NOT NULL,

    -- Classification
    material_type TEXT DEFAULT 'other',

    -- Processing status
    status TEXT DEFAULT 'pending',
    chunk_count INTEGER DEFAULT 0,
    error_message TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS material_chunks (
    id BIGSERIAL PRIMARY KEY,
    material_id BIGINT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536),

    -- Metadata for context
    section_title TEXT,
    material_type TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =================================================================
-- Organizations & Team
-- =================================================================

CREATE TABLE IF NOT EXISTS organizations (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    stripe_customer_id TEXT UNIQUE,
    bonus_credits INTEGER DEFAULT 0,
    billing_period_start TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS org_members (
    id BIGSERIAL PRIMARY KEY,
    org_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member', 'viewer')),
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(org_id, user_id)
);

CREATE TABLE IF NOT EXISTS org_invites (
    id BIGSERIAL PRIMARY KEY,
    org_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member', 'viewer')),
    token TEXT UNIQUE NOT NULL,
    invited_by BIGINT NOT NULL REFERENCES users(id),
    accepted_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(org_id, email)
);

-- =================================================================
-- Indexes
-- =================================================================

CREATE INDEX IF NOT EXISTS idx_documents_user_created
ON research_documents(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_users_google_id
ON users(google_id);

CREATE INDEX IF NOT EXISTS idx_users_stripe_customer
ON users(stripe_customer_id)
WHERE stripe_customer_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_users_microsoft_id
ON users(microsoft_id)
WHERE microsoft_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_documents_user_url
ON research_documents(user_id, company_url);

CREATE INDEX IF NOT EXISTS idx_api_keys_user
ON api_keys(user_id)
WHERE NOT revoked;

CREATE INDEX IF NOT EXISTS idx_api_keys_prefix
ON api_keys(prefix);

CREATE INDEX IF NOT EXISTS idx_api_usage_key
ON api_usage(api_key_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_enriched_contacts_doc
ON enriched_contacts(document_id);

CREATE INDEX IF NOT EXISTS idx_enriched_contacts_user
ON enriched_contacts(user_id);

CREATE INDEX IF NOT EXISTS idx_research_jobs_user
ON research_jobs(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_job
ON webhook_deliveries(job_id);

CREATE INDEX IF NOT EXISTS idx_bulk_jobs_user
ON bulk_jobs(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_bulk_job_items_bulk
ON bulk_job_items(bulk_job_id);

CREATE INDEX IF NOT EXISTS idx_webhooks_user_active
ON webhooks(user_id)
WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_bulk_jobs_status_created
ON bulk_jobs(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_lists_user
ON lists(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_list_accounts_list
ON list_accounts(list_id);

CREATE INDEX IF NOT EXISTS idx_list_accounts_status
ON list_accounts(status);

CREATE INDEX IF NOT EXISTS idx_research_jobs_status_created
ON research_jobs(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_lists_status_created
ON lists(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_integrations_user_provider
ON integrations(user_id, provider);

CREATE INDEX IF NOT EXISTS idx_outreach_drafts_doc
ON outreach_drafts(document_id);

CREATE INDEX IF NOT EXISTS idx_automation_rules_user
ON automation_rules(user_id);

CREATE INDEX IF NOT EXISTS idx_automation_runs_rule
ON automation_runs(rule_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_materials_user
ON materials(user_id);

CREATE INDEX IF NOT EXISTS idx_materials_status
ON materials(user_id, status);

CREATE INDEX IF NOT EXISTS idx_chunks_user
ON material_chunks(user_id);

CREATE INDEX IF NOT EXISTS idx_chunks_material
ON material_chunks(material_id);

-- Vector similarity search index (IVFFlat)
-- Note: This index requires data to exist first, so creation may fail on empty table
-- CREATE INDEX IF NOT EXISTS idx_chunks_embedding
-- ON material_chunks USING ivfflat (embedding vector_cosine_ops)
-- WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_org_members_user
ON org_members(user_id);

CREATE INDEX IF NOT EXISTS idx_org_members_org
ON org_members(org_id);

CREATE INDEX IF NOT EXISTS idx_org_invites_token
ON org_invites(token);

CREATE INDEX IF NOT EXISTS idx_org_invites_email
ON org_invites(email);
