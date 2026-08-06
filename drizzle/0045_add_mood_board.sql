CREATE TABLE mood_board_images (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  image_url TEXT NOT NULL,
  annotation TEXT DEFAULT '',
  extracted_style TEXT DEFAULT '',
  created_at INTEGER NOT NULL DEFAULT (unixepoch())
);
