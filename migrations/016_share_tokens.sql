-- Add share_token to research_documents for secure link sharing.
-- Each document gets a unique UUID token; shared links must include it.

ALTER TABLE research_documents
    ADD COLUMN IF NOT EXISTS share_token TEXT;

-- Backfill existing documents with unique tokens
UPDATE research_documents
SET share_token = gen_random_uuid()::text
WHERE share_token IS NULL;

-- Make NOT NULL after backfill
ALTER TABLE research_documents
    ALTER COLUMN share_token SET NOT NULL,
    ALTER COLUMN share_token SET DEFAULT gen_random_uuid()::text;

-- Index for token lookups
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_share_token
ON research_documents(share_token);
