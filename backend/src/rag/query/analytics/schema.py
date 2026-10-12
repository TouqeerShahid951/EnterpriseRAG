"""PostgreSQL schema owned by query execution analytics."""

ANALYTICS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS query_analytics_executions (
    execution_id UUID PRIMARY KEY,
    trace_id UUID NOT NULL,
    session_id TEXT NOT NULL,
    actor_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    permission_version INTEGER NOT NULL CHECK (permission_version >= 0),
    origin TEXT NOT NULL CHECK (origin IN ('chat', 'query_tracker', 'evaluation', 'other_internal')),
    work_kind TEXT NOT NULL CHECK (work_kind IN ('answer', 'artifact_submission')),
    group_path TEXT NULL,
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ('in_flight', 'terminal')),
    started_at TIMESTAMPTZ NOT NULL,
    reconciliation_deadline_at TIMESTAMPTZ NULL,
    last_heartbeat_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    outcome TEXT NULL CHECK (outcome IN (
        'complete', 'partial', 'clarification', 'abstained', 'system_error',
        'access_denied', 'cancelled', 'interrupted', 'artifact_submitted'
    )),
    answer_status TEXT NULL,
    reason_code TEXT NULL,
    degraded BOOLEAN NULL,
    degraded_reason TEXT NULL,
    requested_source_mode TEXT NULL,
    resolved_source_mode TEXT NULL,
    initial_intent TEXT NULL,
    final_intent TEXT NULL,
    response_mode TEXT NULL,
    latency_ms INTEGER NULL CHECK (latency_ms IS NULL OR latency_ms >= 0),
    verification_status TEXT NULL,
    verification_method TEXT NULL,
    faithfulness_score DOUBLE PRECISION NULL CHECK (faithfulness_score IS NULL OR (faithfulness_score >= 0 AND faithfulness_score <= 1)),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    route_reroute_count INTEGER NOT NULL DEFAULT 0 CHECK (route_reroute_count >= 0),
    retrieved_hit_count INTEGER NULL CHECK (retrieved_hit_count IS NULL OR retrieved_hit_count >= 0),
    evidence_source_count INTEGER NULL CHECK (evidence_source_count IS NULL OR evidence_source_count >= 0),
    cited_source_count INTEGER NULL CHECK (cited_source_count IS NULL OR cited_source_count >= 0),
    max_retrieval_score DOUBLE PRECISION NULL,
    max_rerank_score DOUBLE PRECISION NULL,
    model_cohort TEXT NULL,
    configuration_digest TEXT NULL,
    application_image_digest TEXT NULL,
    cohort_snapshot JSONB NULL,
    retrieval_lineage_status TEXT NOT NULL DEFAULT 'not_captured',
    retrieval_lineage JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT query_analytics_terminal_shape CHECK (
        (lifecycle = 'in_flight' AND finished_at IS NULL AND outcome IS NULL)
        OR (lifecycle = 'terminal' AND finished_at IS NOT NULL AND outcome IS NOT NULL)
    )
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'query_analytics_executions'
          AND column_name = 'session_id'
          AND data_type = 'uuid'
    ) THEN
        ALTER TABLE query_analytics_executions
            ALTER COLUMN session_id TYPE TEXT USING session_id::text;
    END IF;
END
$$;

ALTER TABLE query_analytics_executions
    ADD COLUMN IF NOT EXISTS reconciliation_deadline_at TIMESTAMPTZ NULL;
ALTER TABLE query_analytics_executions
    ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ NULL;
CREATE INDEX IF NOT EXISTS query_analytics_heartbeat_due_idx
    ON query_analytics_executions (reconciliation_deadline_at, execution_id)
    WHERE lifecycle = 'in_flight' AND last_heartbeat_at IS NOT NULL;
ALTER TABLE query_analytics_executions
    ADD COLUMN IF NOT EXISTS reason_code TEXT NULL;
ALTER TABLE query_analytics_executions
    ADD COLUMN IF NOT EXISTS retrieval_lineage_status TEXT NOT NULL DEFAULT 'not_captured';
ALTER TABLE query_analytics_executions
    ADD COLUMN IF NOT EXISTS retrieval_lineage JSONB NULL;
ALTER TABLE query_analytics_executions
    ADD COLUMN IF NOT EXISTS model_cohort TEXT NULL;
ALTER TABLE query_analytics_executions
    ADD COLUMN IF NOT EXISTS configuration_digest TEXT NULL;
ALTER TABLE query_analytics_executions
    ADD COLUMN IF NOT EXISTS application_image_digest TEXT NULL;
ALTER TABLE query_analytics_executions
    ADD COLUMN IF NOT EXISTS cohort_snapshot JSONB NULL;

CREATE INDEX IF NOT EXISTS query_analytics_started_idx
    ON query_analytics_executions (started_at DESC, execution_id DESC);
CREATE INDEX IF NOT EXISTS query_analytics_origin_started_idx
    ON query_analytics_executions (origin, work_kind, started_at DESC);
CREATE INDEX IF NOT EXISTS query_analytics_outcome_started_idx
    ON query_analytics_executions (outcome, started_at DESC);
CREATE INDEX IF NOT EXISTS query_analytics_actor_started_idx
    ON query_analytics_executions (actor_id, started_at DESC);
CREATE INDEX IF NOT EXISTS query_analytics_group_started_idx
    ON query_analytics_executions (group_path, started_at DESC);
CREATE INDEX IF NOT EXISTS query_analytics_configuration_started_idx
    ON query_analytics_executions (configuration_digest, started_at DESC);

CREATE TABLE IF NOT EXISTS query_analytics_boundary_events (
    event_id UUID PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL,
    route_path TEXT NOT NULL,
    status_code INTEGER NOT NULL CHECK (status_code >= 400 AND status_code <= 599),
    reason_code TEXT NOT NULL CHECK (char_length(reason_code) BETWEEN 1 AND 80),
    actor_id UUID NULL REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS query_analytics_boundary_occurred_idx
    ON query_analytics_boundary_events (occurred_at DESC, event_id DESC);
"""
