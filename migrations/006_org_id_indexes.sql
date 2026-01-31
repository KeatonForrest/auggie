CREATE INDEX IF NOT EXISTS idx_users_org ON users(org_id) WHERE org_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lists_org ON lists(org_id);
CREATE INDEX IF NOT EXISTS idx_webhooks_org ON webhooks(org_id);
CREATE INDEX IF NOT EXISTS idx_materials_org ON materials(org_id);
CREATE INDEX IF NOT EXISTS idx_material_chunks_org ON material_chunks(org_id);
CREATE INDEX IF NOT EXISTS idx_fulfilled_sessions_org ON fulfilled_sessions(org_id);
