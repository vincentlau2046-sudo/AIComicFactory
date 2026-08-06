CREATE TABLE character_costumes (
  id TEXT PRIMARY KEY,
  character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT 'default',
  description TEXT DEFAULT '',
  reference_image TEXT,
  created_at INTEGER NOT NULL DEFAULT (unixepoch())
);
