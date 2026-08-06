CREATE TABLE IF NOT EXISTS shot_assets (
  id                 TEXT PRIMARY KEY NOT NULL,
  shot_id            TEXT NOT NULL REFERENCES shots(id) ON DELETE CASCADE,
  type               TEXT NOT NULL,
  sequence_in_type   INTEGER NOT NULL DEFAULT 0,
  asset_version      INTEGER NOT NULL DEFAULT 1,
  is_active          INTEGER NOT NULL DEFAULT 1,
  prompt             TEXT NOT NULL DEFAULT '',
  file_url           TEXT,
  status             TEXT NOT NULL DEFAULT 'pending',
  characters         TEXT,
  model_provider     TEXT,
  model_id           TEXT,
  meta               TEXT,
  created_at         INTEGER NOT NULL,
  updated_at         INTEGER NOT NULL
);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS idx_shot_assets_shot_type ON shot_assets(shot_id, type);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS idx_shot_assets_active ON shot_assets(shot_id, type, sequence_in_type, is_active);
