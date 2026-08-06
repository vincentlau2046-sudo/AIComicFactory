CREATE TABLE character_relations (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  character_a_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
  character_b_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
  relation_type TEXT NOT NULL DEFAULT 'neutral',
  description TEXT DEFAULT '',
  created_at INTEGER NOT NULL DEFAULT (unixepoch())
);
