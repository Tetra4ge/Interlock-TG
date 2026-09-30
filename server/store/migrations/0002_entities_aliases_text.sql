-- 0001 created `entities.aliases_json`, but server/resolve/cluster.py and
-- server/graph/loader.py have always read/written `aliases_text` -- a
-- naming mismatch between the migration and the application code that
-- only surfaces once the resolve/load steps actually run against a real
-- (non-empty) database. Rename to match what the code expects.
ALTER TABLE entities RENAME COLUMN aliases_json TO aliases_text;
