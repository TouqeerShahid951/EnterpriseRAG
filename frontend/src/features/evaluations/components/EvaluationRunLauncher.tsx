import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Info, Loader2, Play } from "lucide-react";
import { ragEvaluationsApi, type EvaluationRunCreateRequest } from "@/lib/api/contracts";
import { useToast } from "@/components/feedback/ToastProvider";
import { EmptyPanel, InlineMessage, Skeleton } from "@/components/layout/Common";
import { resolveEvaluationDatasetId, splitCsv } from "@/features/evaluations/utils/evaluationPageUtils";
import type { EvaluationDatasetSummary } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";

export function NewRunScreen({ datasets, datasetsLoading, initialDatasetId, onRunCreated }: { datasets: EvaluationDatasetSummary[]; datasetsLoading: boolean; initialDatasetId: string | null; onRunCreated: (runId: string) => void }) {
  return (
    <div className="rag-eval-screen rag-eval-new-run-grid">
      <RunLauncherPanel datasets={datasets} datasetsLoading={datasetsLoading} initialDatasetId={initialDatasetId} onRunCreated={onRunCreated} />
      <section className="sv-panel p-5">
        <div className="rag-eval-panel-header">
          <span><Info size={18} /> Before queueing</span>
        </div>
        <div className="rag-eval-guidance-list">
          <p><strong>Scope is part of the result.</strong><span>Knowledge Space and document IDs are captured with the run.</span></p>
          <p><strong>Permission context is captured.</strong><span>Results reflect the submitter's visible corpus at launch time.</span></p>
          <p><strong>Case IDs and limit are exclusive.</strong><span>Use one when you want a targeted or sampled run.</span></p>
        </div>
      </section>
    </div>
  );
}

function RunLauncherPanel({ datasets, datasetsLoading, initialDatasetId, onRunCreated }: { datasets: EvaluationDatasetSummary[]; datasetsLoading: boolean; initialDatasetId: string | null; onRunCreated: (runId: string) => void }) {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [datasetId, setDatasetId] = useState(() => resolveEvaluationDatasetId(datasets, initialDatasetId, ""));
  const [groupPath, setGroupPath] = useState("");
  const [documentIds, setDocumentIds] = useState("");
  const [caseIds, setCaseIds] = useState("");
  const [limit, setLimit] = useState("");
  const selectedDataset = datasets.find((dataset) => dataset.id === datasetId) ?? datasets[0] ?? null;

  useEffect(() => {
    const resolvedDatasetId = resolveEvaluationDatasetId(datasets, initialDatasetId, datasetId);
    if (resolvedDatasetId !== datasetId) setDatasetId(resolvedDatasetId);
  }, [datasetId, datasets, initialDatasetId]);

  const createRunMutation = useMutation({
    mutationFn: ragEvaluationsApi.createRun,
    onSuccess: async (run) => {
      onRunCreated(run.id);
      await queryClient.invalidateQueries({ queryKey: ["rag-evaluations", "runs"] });
      notify({ title: "Evaluation queued", description: `${run.dataset_name} has ${run.case_count} cases.`, tone: "success" });
    },
    onError: (error) => notify({ title: "Run failed to queue", description: errorMessage(error, "Unable to queue evaluation run."), tone: "error" }),
  });
  const parsedCaseIds = splitCsv(caseIds);
  const parsedLimit = limit.trim() ? Number(limit) : null;
  const canRun = Boolean(selectedDataset) && !createRunMutation.isPending && !(parsedCaseIds.length > 0 && parsedLimit);

  function submitRun() {
    if (!selectedDataset) return;
    const request: EvaluationRunCreateRequest = {
      dataset_id: selectedDataset.id,
      group_path: groupPath.trim() || null,
      document_ids: splitCsv(documentIds),
      case_ids: parsedCaseIds,
      limit: parsedLimit,
    };
    createRunMutation.mutate(request);
  }

  return (
    <section className="sv-panel p-5">
      <div className="rag-eval-panel-header">
        <span><Play size={18} /> Launch Run</span>
        <small>{selectedDataset ? `${selectedDataset.case_count} cases available` : "No dataset"}</small>
      </div>
      {datasetsLoading ? <Skeleton className="mt-4 h-10 w-full" /> : null}
      {!datasetsLoading && datasets.length === 0 ? <EmptyPanel>Import a JSON or JSONL evaluation dataset before launching a run.</EmptyPanel> : null}
      {datasets.length > 0 ? (
        <div className="rag-eval-form-grid items-start">
          <label className="sv-field">
            <span className="sv-label">Dataset</span>
            <select value={selectedDataset?.id ?? ""} onChange={(event) => setDatasetId(event.target.value)} className="sv-input">
              {datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}
            </select>
            <small className="text-secondary">Choose the imported case set for this run.</small>
          </label>
          <label className="sv-field">
            <span className="sv-label">Knowledge Space</span>
            <input value={groupPath} onChange={(event) => setGroupPath(event.target.value)} className="sv-input" placeholder="/manuals" />
            <small className="text-secondary">Optional retrieval scope; leave blank to use all visible spaces.</small>
          </label>
          <label className="sv-field">
            <span className="sv-label">Document IDs</span>
            <input value={documentIds} onChange={(event) => setDocumentIds(event.target.value)} className="sv-input" placeholder="Optional, comma-separated" />
            <small className="text-secondary">Optional comma-separated document IDs to force scope.</small>
          </label>
          <label className="sv-field">
            <span className="sv-label">Case IDs</span>
            <input value={caseIds} onChange={(event) => setCaseIds(event.target.value)} className="sv-input" placeholder="Optional, comma-separated" />
            <small className="text-secondary">Optional comma-separated case IDs; cannot be combined with a limit.</small>
          </label>
          <label className="sv-field">
            <span className="sv-label">Limit</span>
            <input value={limit} onChange={(event) => setLimit(event.target.value)} min={1} type="number" className="sv-input" placeholder="Optional" />
            <small className="text-secondary">Optional number of cases to sample from the selected dataset.</small>
          </label>
        </div>
      ) : null}
      {parsedCaseIds.length > 0 && parsedLimit ? <InlineMessage tone="warning">Use either case IDs or a limit, not both.</InlineMessage> : null}
      <button type="button" className="sv-action-primary mt-4" disabled={!canRun} onClick={submitRun}>
        {createRunMutation.isPending ? <Loader2 className="animate-spin" size={16} /> : <Play size={16} />}
        {createRunMutation.isPending ? "Queueing" : "Run evaluation"}
      </button>
    </section>
  );
}
