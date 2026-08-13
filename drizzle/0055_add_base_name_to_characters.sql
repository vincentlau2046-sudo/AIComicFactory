ALTER TABLE characters ADD COLUMN base_name TEXT NOT NULL DEFAULT '';
UPDATE characters SET base_name = name WHERE base_name = '';