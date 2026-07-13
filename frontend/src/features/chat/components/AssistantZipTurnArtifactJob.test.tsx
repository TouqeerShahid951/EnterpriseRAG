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

    expect(markup).toContain("Drafting cited answer");
    expect(markup).toContain("<strong>Set the tone</strong>");
    expect(markup).toContain('class="rag-inline-citation"');
    expect(markup).not.toContain("**Set the tone**");
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
