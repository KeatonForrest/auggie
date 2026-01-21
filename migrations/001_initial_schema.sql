-- Migration 001: Initial PostgreSQL Schema
-- Run this manually or via init_database() which creates tables if not exists

-- Users table (Google OAuth + profile + billing)
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,

    -- Auth (from Google OAuth)
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    picture TEXT,
    google_id TEXT UNIQUE NOT NULL,

    -- Profile (filled during onboarding)
    company_name TEXT,
    product_context TEXT,
    industry TEXT,

    -- Billing (Stripe)
    stripe_customer_id TEXT UNIQUE,
    stripe_subscription_id TEXT,
    subscription_status TEXT DEFAULT 'none'
        CHECK (subscription_status IN ('none', 'active', 'past_due', 'canceled')),

    -- Usage tracking
    searches_used INTEGER DEFAULT 0,
    billing_period_start TIMESTAMPTZ DEFAULT NOW(),

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Research documents (scoped to users)
CREATE TABLE IF NOT EXISTS research_documents (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    company_url TEXT NOT NULL,
    company_name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- AI-generated sections
    company_overview TEXT,
    projects_initiatives TEXT,
    confirmed_tech_stack TEXT,
    hiring_signals TEXT,
    business_problems TEXT,
    product_fit TEXT,
    talking_points TEXT,
    information_gaps TEXT,
    full_markdown TEXT
);

-- Indexes for query patterns
CREATE INDEX IF NOT EXISTS idx_documents_user_created ON research_documents(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id);
CREATE INDEX IF NOT EXISTS idx_users_stripe_customer ON users(stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;
