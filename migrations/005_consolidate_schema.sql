-- Consolidate remaining inline DDL from _pool.py init_database()
-- Migration 002 already covers all ALTER TABLE ADD COLUMN / ALTER COLUMN statements.
-- This migration handles the bonus_credits cents data migration that was inline.

-- Migrate bonus_credits to cents (1 credit = 100 cents)
-- Only affects users with credits in old format (1-99 range)
UPDATE users SET bonus_credits = bonus_credits * 100
WHERE bonus_credits > 0 AND bonus_credits < 100;
