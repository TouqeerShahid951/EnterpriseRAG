export const legacyDocument = {
  id: "doc-1",
  title: "Legacy document",
  doc_type: "report",
  group_path: "/finance",
  effective_date: "2026-05-25",
  expiry_date: null,
  description: null,
  summary: null,
  language: null,
  topics: [],
  llm_topics: [],
  auto_doc_type: null,
  extracted_dates: {},
  metadata_flags: {},
  entities: [],
  cross_references: [],
  claims: [],
  is_current: true,
  uploaded_by: "local",
  superseded_by: null,
  created_at: "2026-05-25T00:00:00Z",
};

export function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

export function auditSummary() {
  return {
    total: 0,
    document_events: 0,
    auth_events: 0,
    system_events: 0,
    actor_count: 0,
    event_type_count: 0,
    category_counts: {},
    target_type_counts: {},
    event_type_counts: {},
  };
}

export function queryResponse() {
  return {
    trace_id: "trace-1",
    answer: "Done",
    answer_status: "complete",
    coverage: {
      required_slots: [],
      covered_slots: [],
      completeness: "not_applicable",
      warnings: [],
    },
    sources: [],
    artifacts: [],
    artifact_job: null,
    conflict_flag: false,
    conflict_detail: null,
    faithfulness_score: 1,
    faithfulness_status: "checked",
    unfounded_claims: [],
    intent: "aggregation",
    session_id: "session-1",
    latency_ms: 1,
    node_timings: [],
    degraded: false,
    degraded_reason: null,
    source_mode: "db_only",
    source_decision_reason: "composer_selected_database",
    source_expansion: null,
  };
}
