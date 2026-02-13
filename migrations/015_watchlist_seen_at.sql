-- Track when a user has seen a significant score change so the badge can be dismissed.

ALTER TABLE watchlist_score_changes ADD COLUMN seen_at TIMESTAMPTZ;
