CREATE TABLE prompt_ab_tests (
  id TEXT PRIMARY KEY,
  prompt_key TEXT NOT NULL,
  variant_a TEXT NOT NULL,
  variant_b TEXT NOT NULL,
  shot_id TEXT REFERENCES shots(id) ON DELETE CASCADE,
  result_a_url TEXT,
  result_b_url TEXT,
  preferred TEXT,
  created_at INTEGER NOT NULL DEFAULT (unixepoch())
);
