-- 0051: Add project/episode style columns + character phase fields
ALTER TABLE projects ADD COLUMN visual_style TEXT DEFAULT '';
ALTER TABLE projects ADD COLUMN visual_style_key TEXT DEFAULT '';
ALTER TABLE projects ADD COLUMN era_aesthetic TEXT DEFAULT '';
ALTER TABLE projects ADD COLUMN mood_direction TEXT DEFAULT '';
ALTER TABLE episodes ADD COLUMN visual_style TEXT DEFAULT '';
ALTER TABLE episodes ADD COLUMN era_aesthetic TEXT DEFAULT '';
ALTER TABLE episodes ADD COLUMN mood_direction TEXT DEFAULT '';
ALTER TABLE episodes ADD COLUMN screenplay TEXT DEFAULT '';

-- Phase fields on characters table (unified: template + phase + instance)
ALTER TABLE characters ADD COLUMN phase_name TEXT;
ALTER TABLE characters ADD COLUMN episode_start INTEGER;
ALTER TABLE characters ADD COLUMN episode_end INTEGER;
ALTER TABLE characters ADD COLUMN visual_changes TEXT;

-- Drop character_phases if it exists (from intermediate migration)
DROP TABLE IF EXISTS character_phases;