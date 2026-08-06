CREATE TABLE shot_actions (
  id TEXT PRIMARY KEY,
  shot_id TEXT NOT NULL REFERENCES shots(id) ON DELETE CASCADE,
  character_id TEXT REFERENCES characters(id) ON DELETE SET NULL,
  body_part TEXT DEFAULT 'full_body',
  motion TEXT NOT NULL DEFAULT '',
  start_time REAL DEFAULT 0,
  end_time REAL DEFAULT 0,
  intensity TEXT DEFAULT 'normal',
  created_at INTEGER NOT NULL DEFAULT (unixepoch())
);
