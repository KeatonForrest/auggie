-- Add profile and feature columns to existing tables
-- This migration extracts all ALTER TABLE ADD COLUMN statements from init_database()

-- =================================================================
-- Users table: Enhanced profile columns
-- =================================================================

-- Enhanced Profile - Product Info
ALTER TABLE users ADD COLUMN IF NOT EXISTS product_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS product_description TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS problems_solved TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS differentiators TEXT;

-- Enhanced Profile - ICP
ALTER TABLE users ADD COLUMN IF NOT EXISTS target_company_size TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS target_industries TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS target_personas TEXT;

-- Enhanced Profile - Competition
ALTER TABLE users ADD COLUMN IF NOT EXISTS competitors TEXT;

-- Billing and credits
ALTER TABLE users ADD COLUMN IF NOT EXISTS bonus_credits INTEGER DEFAULT 0;

-- Microsoft OAuth (MSP customers)
ALTER TABLE users ADD COLUMN IF NOT EXISTS microsoft_id TEXT UNIQUE;

-- Admin flag for unlimited usage
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;

-- Product type (saas or msp)
ALTER TABLE users ADD COLUMN IF NOT EXISTS product_type TEXT DEFAULT 'saas';

-- Organization membership
ALTER TABLE users ADD COLUMN IF NOT EXISTS org_id BIGINT REFERENCES organizations(id);

-- Make google_id nullable (for users who sign up with Microsoft only)
ALTER TABLE users ALTER COLUMN google_id DROP NOT NULL;

-- =================================================================
-- Research Documents: Scoring and analysis columns
-- =================================================================

-- News and contacts
ALTER TABLE research_documents ADD COLUMN IF NOT EXISTS recent_news TEXT;
ALTER TABLE research_documents ADD COLUMN IF NOT EXISTS key_contacts TEXT;
ALTER TABLE research_documents ADD COLUMN IF NOT EXISTS existential_data_points TEXT;

-- Opportunity scoring
ALTER TABLE research_documents ADD COLUMN IF NOT EXISTS opportunity_score INTEGER;
ALTER TABLE research_documents ADD COLUMN IF NOT EXISTS pain_score INTEGER;
ALTER TABLE research_documents ADD COLUMN IF NOT EXISTS fit_score INTEGER;
ALTER TABLE research_documents ADD COLUMN IF NOT EXISTS timing_score INTEGER;
ALTER TABLE research_documents ADD COLUMN IF NOT EXISTS score_summary TEXT;
ALTER TABLE research_documents ADD COLUMN IF NOT EXISTS pain_evidence TEXT;
ALTER TABLE research_documents ADD COLUMN IF NOT EXISTS fit_evidence TEXT;
ALTER TABLE research_documents ADD COLUMN IF NOT EXISTS timing_evidence TEXT;

-- Analysis metadata
ALTER TABLE research_documents ADD COLUMN IF NOT EXISTS thinking_content TEXT;
ALTER TABLE research_documents ADD COLUMN IF NOT EXISTS model_used TEXT;

-- =================================================================
-- Research Jobs: Progress tracking and nullable api_key_id
-- =================================================================

-- Make api_key_id nullable (for web-uploaded lists)
ALTER TABLE research_jobs ALTER COLUMN api_key_id DROP NOT NULL;

-- Add progress column for pipeline stage tracking
ALTER TABLE research_jobs ADD COLUMN IF NOT EXISTS progress TEXT;

-- =================================================================
-- Lists: Source tracking and enrichment/outreach status
-- =================================================================

-- Track source (e.g., HubSpot imports)
ALTER TABLE lists ADD COLUMN IF NOT EXISTS source JSONB DEFAULT '{}';

-- =================================================================
-- List Accounts: Enrichment and outreach tracking
-- =================================================================

-- Pipeline status columns
ALTER TABLE list_accounts ADD COLUMN IF NOT EXISTS enrichment_status TEXT DEFAULT 'none';
ALTER TABLE list_accounts ADD COLUMN IF NOT EXISTS outreach_status TEXT DEFAULT 'none';

-- Track where accounts were pushed (e.g., Instantly)
ALTER TABLE list_accounts ADD COLUMN IF NOT EXISTS pushed_to JSONB DEFAULT '{}';

-- =================================================================
-- Fulfilled Sessions: Organization billing audit
-- =================================================================

ALTER TABLE fulfilled_sessions ADD COLUMN IF NOT EXISTS org_id BIGINT REFERENCES organizations(id);

-- =================================================================
-- Organization-shared tables: Add org_id columns
-- =================================================================

ALTER TABLE materials ADD COLUMN IF NOT EXISTS org_id BIGINT REFERENCES organizations(id);
ALTER TABLE material_chunks ADD COLUMN IF NOT EXISTS org_id BIGINT REFERENCES organizations(id);
ALTER TABLE lists ADD COLUMN IF NOT EXISTS org_id BIGINT REFERENCES organizations(id);
ALTER TABLE webhooks ADD COLUMN IF NOT EXISTS org_id BIGINT REFERENCES organizations(id);
