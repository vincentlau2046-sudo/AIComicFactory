CREATE TABLE IF NOT EXISTS "task_logs" (
  "id" text PRIMARY KEY NOT NULL,
  "project_id" text NOT NULL,
  "shot_id" text,
  "task_type" text NOT NULL,
  "run_id" text NOT NULL,
  "step_id" text,
  "step_name" text,
  "started_at" text NOT NULL,
  "completed_at" text,
  "status" text NOT NULL,
  "duration_ms" integer,
  "error" text,
  "error_type" text,
  "retry_count" integer,
  "metadata" text
);