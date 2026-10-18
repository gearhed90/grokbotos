-- App registry schema. Field list matches ROADMAP.md 2.3 exactly.
--
-- Vector index (tier-2 embedding similarity) is NOT part of this schema yet
-- -- ROADMAP.md 2.3 leaves the engine choice open (sqlite-vec recommended,
-- LanceDB as the alternative) pending an embedding model decision. When
-- that's chosen, a `sqlite-vec` virtual table keyed by app_id gets added
-- alongside this table rather than replacing it.

CREATE TABLE IF NOT EXISTS apps (
    app_id              TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    description         TEXT NOT NULL,
    capability_tags     TEXT NOT NULL,  -- JSON array of strings
    input_schema        TEXT NOT NULL,  -- JSON Schema
    output_schema       TEXT NOT NULL,  -- JSON Schema
    exec_manifest       TEXT NOT NULL,  -- JSON: {entrypoint, runtime, sandbox_profile_id, dependencies}
    creation_source     TEXT NOT NULL CHECK (creation_source IN ('generated', 'opensource_installed', 'hybrid')),
    source_ref          TEXT,
    version             TEXT NOT NULL,
    created_at          TEXT NOT NULL,  -- ISO 8601
    updated_at          TEXT NOT NULL,  -- ISO 8601
    usage_count         INTEGER NOT NULL DEFAULT 0,
    last_used_at        TEXT,
    success_rate        REAL NOT NULL DEFAULT 0.0
);

-- Supports the tier-1 capability_tags pre-filter (ROADMAP.md 2.3 step 1).
-- SQLite can't index into a JSON array column directly; app-side code
-- extracts distinct tags into this table so a plain indexed lookup works
-- without requiring the JSON1 extension.
CREATE TABLE IF NOT EXISTS app_tags (
    app_id TEXT NOT NULL REFERENCES apps(app_id) ON DELETE CASCADE,
    tag    TEXT NOT NULL,
    PRIMARY KEY (app_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_app_tags_tag ON app_tags(tag);
