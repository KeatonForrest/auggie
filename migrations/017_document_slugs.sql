-- Add slug column to research_documents for vanity URLs.
-- Slugs are derived from company_name and unique per user.

ALTER TABLE research_documents
    ADD COLUMN IF NOT EXISTS slug TEXT;

-- Backfill existing documents: lowercase company_name, strip non-alphanum to hyphens, max 80 chars.
UPDATE research_documents
SET slug = left(
    regexp_replace(
        regexp_replace(
            lower(company_name),
            '[^a-z0-9]+', '-', 'g'
        ),
        '^-+|-+$', '', 'g'
    ),
    80
)
WHERE slug IS NULL;

-- Handle empty slugs (all-special-char names)
UPDATE research_documents
SET slug = 'untitled'
WHERE slug IS NULL OR slug = '';

-- Deduplicate per user: append -2, -3, etc. using window function
WITH dupes AS (
    SELECT id, user_id, slug,
           row_number() OVER (PARTITION BY user_id, slug ORDER BY created_at, id) AS rn
    FROM research_documents
)
UPDATE research_documents rd
SET slug = rd.slug || '-' || dupes.rn
FROM dupes
WHERE rd.id = dupes.id AND dupes.rn > 1;

-- Make NOT NULL after backfill
ALTER TABLE research_documents
    ALTER COLUMN slug SET NOT NULL;

-- Unique index: each user's slugs must be unique
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_user_slug
ON research_documents(user_id, slug);
