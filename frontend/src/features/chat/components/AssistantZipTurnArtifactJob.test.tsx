import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { ArtifactJobSummary, RAGResponse, SourceAnchor } from "@/types/api";
import type { AssistantTurn } from "@/types/chat";
import { sourceCitationLabel } from "@/features/chat/utils/sourceCitation";
import { AssistantZipTurn } from "./AssistantZipTurn";

const baseJob: ArtifactJobSummary = {
  id: "job-1",
  status: "rendering",
  stage: "rendering_pptx_slide",
  progress_pct: 90,
  stage_label: "Rendering files",
  stage_detail: "Building slide 4 of 11",
  stage_progress: { unit: "slides", current: 4, total: 11, label: "Slide 4 of 11" },
  requested_formats: ["pptx"],
  clarification_questions: [],
  artifacts: [],
  error_code: null,
  error_message: null,
  created_at: "2026-06-17T09:00:00+00:00",
  updated_at: "2026-06-17T09:01:00+00:00",
  expires_at: null,
};

describe("AssistantZipTurn artifact job progress", () => {
  it("renders detailed stage labels and progress", () => {
    const markup = renderToStaticMarkup(<AssistantZipTurn documents={[]} onSelectSource={() => undefined} selectedSource={null} turn={turnWithJob(baseJob)} />);

    expect(markup).toContain("Rendering files");
    expect(markup).toContain("Building slide 4 of 11");
    expect(markup).toContain("Slide 4 of 11");
    expect(markup).toContain("PPTX");
  });

  it("falls back to humanized stage text for older job payloads", () => {
    const { stage_label, stage_detail, stage_progress, ...legacyJob } = baseJob;
    void stage_label;
    void stage_detail;
    void stage_progress;
    const markup = renderToStaticMarkup(<AssistantZipTurn documents={[]} onSelectSource={() => undefined} selectedSource={null} turn={turnWithJob(legacyJob)} />);

    expect(markup).toContain("Rendering");
    expect(markup).toContain("Rendering Pptx Slide");
  });

  it("times queued retry jobs from the retry update time", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-17T09:05:10+00:00"));
    try {
      const markup = renderToStaticMarkup(
        <AssistantZipTurn
          documents={[]}
          onSelectSource={() => undefined}
          selectedSource={null}
          turn={turnWithJob({
            ...baseJob,
            status: "queued",
            stage: "queued",
            progress_pct: 0,
            started_at: null,
            updated_at: "2026-06-17T09:05:00+00:00",
          })}
        />,
      );

      expect(markup).toContain("10s");
      expect(markup).not.toContain("5m 10s");
    } finally {
      vi.useRealTimers();
    }
  });

  it("times active retry attempts from started_at", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-17T09:05:10+00:00"));
    try {
      const markup = renderToStaticMarkup(
        <AssistantZipTurn
          documents={[]}
          onSelectSource={() => undefined}
          selectedSource={null}
          turn={turnWithJob({
            ...baseJob,
            started_at: "2026-06-17T09:05:00+00:00",
            updated_at: "2026-06-17T09:05:00+00:00",
          })}
        />,
      );

      expect(markup).toContain("10s");
      expect(markup).not.toContain("5m 10s");
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("AssistantZipTurn pending draft", () => {
  it("renders streamed draft markdown and citations through the cited answer renderer", () => {
    const citation = sourceCitationLabel(source);
    const turn: AssistantTurn = {
      id: "assistant-pending",
      role: "assistant",
      status: "pending",
      question: "What should managers do?",
      createdAt: "2026-06-17T09:00:00+00:00",
      progress: [{ id: "source-1", label: "Evidence source found", kind: "source", source }],
      streamText: `**Set the tone** for risk management ${citation}`,
    };

    const markup = renderToStaticMarkup(<AssistantZipTurn documents={[]} onSelectSource={() => undefined} selectedSource={null} turn={turn} />);

    expect(markup).toContain("Running graph");
    expect(markup).toContain("<strong>Set the tone</strong>");
    expect(markup).toContain('class="rag-inline-citation"');
    expect(markup).not.toContain("**Set the tone**");
  });
});

describe("AssistantZipTurn database clarification", () => {
  it("renders the authorized database choices as buttons", () => {
    const response = responseWithJob(baseJob);
    response.artifact_job = null;
    response.answer = "Which database source should I use?";
    response.answer_status = "clarification";
    response.source_clarification = {
      question: "Do you mean current or archived orders?",
      options: [
        {
          source_id: "connector_catalog:orders",
          name: "Current orders",
          description: "Active order records",
        },
        {
          source_id: "connector_catalog:archive",
          name: "Order archive",
          description: "Historical order records",
        },
      ],
    };
    const markup = renderToStaticMarkup(
      <AssistantZipTurn
        documents={[]}
        onChooseQuerySource={() => undefined}
        onSelectSource={() => undefined}
        selectedSource={null}
        turn={{
          id: "assistant-source-choice",
          role: "assistant",
          status: "complete",
          question: "Show order totals",
          createdAt: "2026-06-17T09:00:00+00:00",
          progress: [],
          response,
        }}
      />,
    );

    expect(markup).toContain("Do you mean current or archived orders?");
    expect(markup).toContain(">Current orders</button>");
    expect(markup).toContain(">Order archive</button>");
    expect(markup).not.toContain("Which database source should I use?");
  });
});

describe("AssistantZipTurn database failure", () => {
  it("shows the safe operational message beside partial document evidence", () => {
    const response = responseWithJob(baseJob);
    response.artifact_job = null;
    response.sources = [source];
    response.degraded = true;
    response.degraded_reason = "sql_generation_unavailable";
    response.operational_failures = [
      {
        stage: "generation",
        code: "sql_generation_unavailable",
        retryable: true,
        source_id: "connector_catalog:cases",
        message: "SQL generation is unavailable for Prudentia Demo Cases.",
      },
    ];

    const markup = renderToStaticMarkup(
      <AssistantZipTurn
        documents={[]}
        onSelectSource={() => undefined}
        selectedSource={null}
        turn={{
          id: "assistant-db-failure",
          role: "assistant",
          status: "complete",
          question: "Compare cases with the manual",
          createdAt: "2026-06-17T09:00:00+00:00",
          progress: [],
          response,
        }}
      />,
    );

    expect(markup).toContain(
      "SQL generation is unavailable for Prudentia Demo Cases.",
    );
    expect(markup).toContain('role="status"');
  });
});

describe("AssistantZipTurn sources", () => {
  it("renders one document card for multiple chunk citations", () => {
    const secondSource: SourceAnchor = {
      ...source,
      chunk_id: "doc-1:chunk-12",
      excerpt: "A second passage from the same document.",
      page: 30,
      page_end: 31,
      page_start: 30,
    };
    const response = responseWithJob(baseJob);
    response.artifact_job = null;
    response.answer = `First ${sourceCitationLabel(source)} and second ${sourceCitationLabel(secondSource)}`;
    response.sources = [source, secondSource];

    const markup = renderToStaticMarkup(
      <AssistantZipTurn
        documents={[]}
        onSelectSource={() => undefined}
        selectedSource={null}
        turn={{
          id: "assistant-sources",
          role: "assistant",
          status: "complete",
          question: "Summarize the evidence",
          createdAt: "2026-06-17T09:00:00+00:00",
          progress: [],
          response,
        }}
      />,
    );

    expect(markup.match(/aria-label="Open citations for/g)).toHaveLength(1);
    expect(markup).toContain("2 citations");
    expect(markup).toContain("Pages 26-27, 30-31");
    expect(markup.match(/class="rag-inline-citation"/g)).toHaveLength(2);
  });
});

const source: SourceAnchor = {
  chunk_id: "doc-1:chunk-7",
  clearance_level: "NATO_RESTRICTED",
  doc_id: "doc-1",
  doc_title: "NIST.AI.100-1.pdf",
  effective_date: "2026-06-04",
  excerpt: "Senior leadership sets the tone for risk management.",
  group_path: "/admin",
  highlight_ranges: [],
  citation_targets: [],
  page: 26,
  page_end: 27,
  page_start: 26,
};

function turnWithJob(job: ArtifactJobSummary): AssistantTurn {
  return {
    id: "assistant-1",
    role: "assistant",
    status: "complete",
    question: "Generate a PPTX",
    createdAt: "2026-06-17T09:00:00+00:00",
    progress: [],
    response: responseWithJob(job),
  };
}

function responseWithJob(job: ArtifactJobSummary): RAGResponse {
  return {
    trace_id: "trace-1",
    answer: "Document generation has been queued.",
    sources: [],
    artifacts: [],
    artifact_job: job,
    conflict_flag: false,
    conflict_detail: null,
    faithfulness_score: 1,
    faithfulness_status: "checked",
    unfounded_claims: [],
    intent: "conversational",
    session_id: "session-1",
    latency_ms: 10,
    node_timings: [],
    degraded: false,
    degraded_reason: null,
  };
}
