import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileJson, Info, Loader2 } from "lucide-react";
import { ragEvaluationsApi, type EvaluationDatasetImportRequest } from "@/lib/api/contracts";
import { useToast } from "@/components/feedback/ToastProvider";
import { EmptyPanel, Skeleton } from "@/components/layout/Common";
import type { EvaluationDatasetSummary } from "@/types/api";
import { errorMessage, formatDateTime } from "@/lib/utils/format";

export function DatasetsScreen({ datasets, loading, onUseDataset }: { datasets: EvaluationDatasetSummary[]; loading: boolean; onUseDataset: (datasetId: string) => void }) {
  return (
    <div className="rag-eval-screen rag-eval-datasets-grid">
      <DatasetImportPanel />
      <DatasetLibraryPanel datasets={datasets} loading={loading} onUseDataset={onUseDataset} />
    </div>
  );
}

function DatasetLibraryPanel({ datasets, loading, onUseDataset }: { datasets: EvaluationDatasetSummary[]; loading: boolean; onUseDataset: (datasetId: string) => void }) {
  return (
    <section className="sv-panel rag-eval-dataset-library">
      <div className="rag-eval-section-header">
        <div>
          <h2 className="sv-section-title">Dataset library</h2>
          <p>Imported case sets available for evaluation runs.</p>
        </div>
        <span className="sv-pill">{loading ? "Loading" : `${datasets.length} datasets`}</span>
      </div>
      {loading ? <div className="p-4 grid gap-3"><Skeleton className="h-16" /><Skeleton className="h-16" /></div> : null}
      {!loading && datasets.length === 0 ? <div className="p-4"><EmptyPanel>Import a JSON or JSONL dataset to start evaluating RAG answers.</EmptyPanel></div> : null}
      <div className="rag-eval-dataset-list">
        {datasets.map((dataset) => (
          <article key={dataset.id} className="rag-eval-dataset-row">
            <div>
              <strong>{dataset.name}</strong>
              <small>{dataset.case_count} cases / {dataset.source_format} / {formatDateTime(dataset.created_at)}</small>
              {dataset.description ? <p>{dataset.description}</p> : null}
            </div>
            <button type="button" className="sv-action-secondary" onClick={() => onUseDataset(dataset.id)}>Use dataset</button>
          </article>
        ))}
      </div>
    </section>
  );
}

function DatasetImportPanel() {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [sourceFormat, setSourceFormat] = useState<EvaluationDatasetImportRequest["source_format"]>("auto");
  const importMutation = useMutation({
    mutationFn: ragEvaluationsApi.importDataset,
    onSuccess: async (dataset) => {
      setName("");
      setContent("");
      setSourceFormat("auto");
      await queryClient.invalidateQueries({ queryKey: ["rag-evaluations", "datasets"] });
      notify({ title: "Dataset imported", description: `${dataset.case_count} cases normalized.`, tone: "success" });
    },
    onError: (error) => notify({ title: "Import failed", description: errorMessage(error, "Unable to import evaluation dataset."), tone: "error" }),
  });
  const canImport = content.trim().length > 0 && !importMutation.isPending;

  async function handleFile(file: File | undefined) {
    if (!file) return;
    setContent(await file.text());
    if (!name.trim()) setName(file.name.replace(/\.(jsonl?|txt)$/i, ""));
  }

  return (
    <section className="sv-panel p-5">
      <div className="rag-eval-panel-header">
        <span><FileJson size={18} /> Dataset Import</span>
        <div className="rag-eval-format-meta">
          <small>JSON or JSONL</small>
          <div className="rag-eval-format-help">
            <button
              type="button"
              className="rag-eval-tooltip-trigger"
              aria-label="Expected JSON format"
              aria-describedby="rag-eval-json-format-tooltip"
            >
              <Info size={14} aria-hidden="true" />
            </button>
            <div className="rag-eval-format-tooltip" id="rag-eval-json-format-tooltip" role="tooltip">
              <strong>Expected JSON format</strong>
              <p>Import a JSON array of cases, one JSON object per JSONL line, or a fixture object with generation_cases.</p>
              <code>{`[{"id":"case_1","question":"What does the policy require?","expected_source_docs":["Policy.pdf"],"must_include":["approval"],"must_cite_source":true}]`}</code>
              <small>Required: question or query. Recommended: stable id or case_id. Optional: expected_answer, must_include, must_not_include, expected_source_docs, acceptable_source_pages, min_sources, min_faithfulness_score, latency_threshold_ms.</small>
            </div>
          </div>
        </div>
      </div>
      <div className="rag-eval-form-grid items-start">
        <label className="sv-field">
          <span className="sv-label">Dataset name</span>
          <input value={name} onChange={(event) => setName(event.target.value)} className="sv-input" placeholder="Dell R630 smoke set" />
          <small className="text-secondary">Optional; file name is used when left blank.</small>
        </label>
        <label className="sv-field">
          <span className="sv-label">Format</span>
          <select value={sourceFormat} onChange={(event) => setSourceFormat(event.target.value as EvaluationDatasetImportRequest["source_format"])} className="sv-input">
            <option value="auto">Auto detect</option>
            <option value="json">JSON</option>
            <option value="jsonl">JSONL</option>
          </select>
          <small className="text-secondary">Auto detects JSON arrays, JSONL, or fixture objects.</small>
        </label>
      </div>
      <label className="sv-field mt-3">
        <span className="sv-label">Upload file</span>
        <input type="file" accept=".json,.jsonl,application/json,text/plain" onChange={(event) => void handleFile(event.target.files?.[0])} className="sv-input" />
        <small className="text-secondary">Loads JSON or JSONL into the content field for review.</small>
      </label>
      <label className="sv-field mt-3">
        <span className="sv-label">Dataset content</span>
        <textarea value={content} onChange={(event) => setContent(event.target.value)} rows={6} className="sv-textarea rag-eval-textarea" placeholder='[{"id":"smoke_1","question":"What does the policy require?","expected_source_docs":["Policy.pdf"]}]' />
        <small className="text-secondary">Paste cases with question or query plus optional expectations.</small>
      </label>
      <button
        type="button"
        className="sv-action-primary mt-4"
        disabled={!canImport}
        onClick={() => importMutation.mutate({ name: name.trim() || null, content, source_format: sourceFormat })}
      >
        {importMutation.isPending ? <Loader2 className="animate-spin" size={16} /> : <FileJson size={16} />}
        {importMutation.isPending ? "Importing" : "Import dataset"}
      </button>
    </section>
  );
}
