"""PostgreSQL schema owned by the global abbreviation glossary."""

ABBREVIATION_SCHEMA_SQL = """
DO $migration$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'abbreviation_glossary_entries'
          AND column_name = 'group_path'
    ) AND to_regclass('public.abbreviation_glossary_entries_scoped') IS NULL THEN
        ALTER TABLE abbreviation_glossary_entries
            RENAME TO abbreviation_glossary_entries_scoped;
    END IF;
END
$migration$;

CREATE TABLE IF NOT EXISTS abbreviation_glossary_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    abbreviation TEXT NOT NULL,
    expansion TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'ui',
    source_document_id UUID NULL REFERENCES documents(id) ON DELETE SET NULL,
    source_page INTEGER NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    created_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT abbreviation_entries_abbreviation_not_blank CHECK (length(btrim(abbreviation)) > 0),
    CONSTRAINT abbreviation_entries_expansion_not_blank CHECK (length(btrim(expansion)) > 0),
    CONSTRAINT abbreviation_entries_source_known CHECK (source_kind IN ('pdf', 'ui')),
    CONSTRAINT abbreviation_entries_source_page_positive CHECK (source_page IS NULL OR source_page > 0),
    CONSTRAINT abbreviation_entries_revision_positive CHECK (revision >= 1)
);

ALTER TABLE abbreviation_glossary_entries
    ADD COLUMN IF NOT EXISTS source_page INTEGER NULL;

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'abbreviation_glossary_entries'::regclass
          AND conname = 'abbreviation_entries_source_page_positive'
    ) THEN
        ALTER TABLE abbreviation_glossary_entries
            ADD CONSTRAINT abbreviation_entries_source_page_positive
            CHECK (source_page IS NULL OR source_page > 0);
    END IF;
END
$migration$;

CREATE UNIQUE INDEX IF NOT EXISTS abbreviation_entries_abbreviation_uidx
    ON abbreviation_glossary_entries (upper(abbreviation));

CREATE TABLE IF NOT EXISTS abbreviation_glossary_sources (
    document_id UUID PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    activated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS abbreviation_glossary_entry_sources (
    entry_id UUID NOT NULL REFERENCES abbreviation_glossary_entries(id) ON DELETE CASCADE,
    source_document_id UUID NOT NULL REFERENCES abbreviation_glossary_sources(document_id) ON DELETE CASCADE,
    source_page INTEGER NULL,
    PRIMARY KEY (entry_id, source_document_id),
    CONSTRAINT abbreviation_entry_sources_page_positive
        CHECK (source_page IS NULL OR source_page > 0)
);

CREATE INDEX IF NOT EXISTS abbreviation_entry_sources_document_idx
    ON abbreviation_glossary_entry_sources (source_document_id);

DO $migration$
DECLARE
    conflicting_definitions BOOLEAN;
BEGIN
    IF to_regclass('public.abbreviation_glossary_entries_scoped') IS NOT NULL THEN
        EXECUTE '
            SELECT EXISTS (
                SELECT 1
                FROM abbreviation_glossary_entries_scoped
                GROUP BY upper(abbreviation)
                HAVING count(DISTINCT lower(expansion)) > 1
            )'
        INTO conflicting_definitions;
        IF conflicting_definitions THEN
            RAISE EXCEPTION
                'Scoped abbreviation definitions conflict; resolve them before migrating to the global glossary.';
        END IF;

        EXECUTE '
            INSERT INTO abbreviation_glossary_entries
                (id, abbreviation, expansion, source_kind, source_document_id,
                 source_page, revision, created_by, updated_by, created_at, updated_at)
            SELECT DISTINCT ON (upper(abbreviation))
                id, abbreviation, expansion, source_kind, source_document_id,
                NULL, revision, created_by, updated_by, created_at, updated_at
            FROM abbreviation_glossary_entries_scoped
            ORDER BY upper(abbreviation), updated_at DESC, id DESC
            ON CONFLICT DO NOTHING';
        DROP TABLE abbreviation_glossary_entries_scoped;
    END IF;

    IF to_regclass('public.abbreviation_glossaries') IS NOT NULL THEN
        DROP TABLE abbreviation_glossaries;
    END IF;
END
$migration$;

INSERT INTO abbreviation_glossary_sources (document_id, activated_at)
SELECT entry.source_document_id, max(entry.updated_at)
FROM abbreviation_glossary_entries entry
JOIN documents document ON document.id = entry.source_document_id
WHERE entry.source_document_id IS NOT NULL
GROUP BY entry.source_document_id
ON CONFLICT (document_id) DO NOTHING;

INSERT INTO abbreviation_glossary_entry_sources
    (entry_id, source_document_id, source_page)
SELECT entry.id, entry.source_document_id, entry.source_page
FROM abbreviation_glossary_entries entry
WHERE entry.source_document_id IS NOT NULL
ON CONFLICT (entry_id, source_document_id) DO NOTHING;
"""
