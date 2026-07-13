"""PostgreSQL schema for query-time claims and conflicts."""

CLAIM_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL,
    entity TEXT NOT NULL,
    attribute TEXT NOT NULL,
    value TEXT NOT NULL,
    entity_norm TEXT GENERATED ALWAYS AS (lower(btrim(entity))) STORED,
    attribute_norm TEXT GENERATED ALWAYS AS (lower(btrim(attribute))) STORED,
    value_norm TEXT GENERATED ALWAYS AS (lower(btrim(value))) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT claims_chunk_id_not_blank CHECK (length(btrim(chunk_id)) > 0),
    CONSTRAINT claims_entity_not_blank CHECK (length(btrim(entity)) > 0),
    CONSTRAINT claims_attribute_not_blank CHECK (length(btrim(attribute)) > 0),
    CONSTRAINT claims_value_not_blank CHECK (length(btrim(value)) > 0)
);

CREATE INDEX IF NOT EXISTS claims_doc_idx ON claims (doc_id, created_at);
CREATE INDEX IF NOT EXISTS claims_lookup_idx ON claims (entity_norm, attribute_norm);

CREATE TABLE IF NOT EXISTS conflicts (
    claim_a_id UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    claim_b_id UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (claim_a_id, claim_b_id),
    CONSTRAINT conflicts_status_known CHECK (status IN ('open', 'resolved')),
    CONSTRAINT conflicts_not_self CHECK (claim_a_id <> claim_b_id)
);

CREATE INDEX IF NOT EXISTS conflicts_status_idx ON conflicts (status, created_at);
"""
