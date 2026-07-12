import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, AlertTriangle, CheckCircle2, Clock3, CloudUpload, FileClock, FileSearch, FileText, Loader2, Plus, RotateCw, Share2, ShieldCheck, TimerReset, X, XCircle } from "lucide-react";

import { adminApi, documentsApi, ingestJobsApi } from "../api/contracts";
import { canManageSpaces, canUploadToSpace, canWriteDocument, clearanceLevelDescription, clearanceLevelLabel, clearanceLevelsAssignableBy, hasExactGroupScope, isGlobalAdmin } from "../authz";
import { useToast } from "../components/feedback/ToastProvider";
import { InlineMessage } from "../components/layout/Common";
import { PrudentiaWorkspace } from "../components/layout/PrudentiaWorkspace";
import type { RouteId } from "../routes";
import { formatFileSize, mergeDocumentFiles } from "../state/pdfUploadBatch";
import type { ClearanceLevel, Document, GraphRAGStatus, UploadJobStep, User as AuthUser } from "../types/api";
import type { PdfUploadDraft, UploadBatchItemView, UploadJobView } from "../types/chat";
import { errorMessage } from "../utils/format";
import { flattenGroups, userSpacesFromPaths } from "../utils/groups";
import { formatIngestRunLabel, formatSecondaryStageProgress, formatUploadWarning, graphEnrichmentForJob, isUploadCancellableStatus, isUploadTerminalStatus, type GraphEnrichmentChip as GraphEnrichmentChipShape } from "../state/uploadJobProgress";

export function PrudentiaUploadPage({ batchItems, cancelingJobId, currentDocuments, currentUser, onCancelIngestJob, onClearUploadJobs, onLogout, onNavigate, onPdfDraftChange, onPdfSubmit, pdfDraft, selectionError, uploadPending }: Props) {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const canLoadSpaceDirectory = canManageSpaces(currentUser);
  const groupsQuery = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.listGroups, retry: false, enabled: canLoadSpaceDirectory });
  const uploadSpaceOptions = useMemo(
    () => (canLoadSpaceDirectory ? flattenGroups(groupsQuery.data?.items ?? []) : userSpacesFromPaths(currentUser.group_paths)),
    [canLoadSpaceDirectory, currentUser.group_paths, groupsQuery.data?.items],
  );
  const writableSpacePaths = useMemo(
    () => uploadSpaceOptions
      .filter((space) => canUploadToSpace(currentUser, space.path))
      .map((space) => space.path),
    [currentUser, uploadSpaceOptions],
  );
  const eligibleSharedSpacePaths = useMemo(
    () => uploadShareTargetPaths(currentUser, pdfDraft.groupPath, uploadSpaceOptions),
    [currentUser, pdfDraft.groupPath, uploadSpaceOptions],
  );
  const sharedSpaceOptions = useMemo(
    () => eligibleSharedSpacePaths.filter((path) => !pdfDraft.sharedGroupPaths.includes(path)),
    [eligibleSharedSpacePaths, pdfDraft.sharedGroupPaths],
  );
  const clearanceOptions = useMemo(() => clearanceLevelsAssignableBy(currentUser), [currentUser]);
  const writableCurrentDocuments = currentDocuments.filter((document) => canWriteDocument(currentUser, document.group_path, document.clearance_level));
  const selectedSpaceIsWritable = Boolean(pdfDraft.groupPath && canUploadToSpace(currentUser, pdfDraft.groupPath));
  const selectedSharedSpacesAreValid = pdfDraft.sharedGroupPaths.every((path) => eligibleSharedSpacePaths.includes(path));
  const shouldPollGraphStatus = batchItems.some((item) => item.job?.status === "complete");
  const graphStatusQuery = useQuery({
    queryKey: ["ingest-jobs", "graphrag-status", "upload-batch"],
    queryFn: ingestJobsApi.graphragStatus,
    enabled: shouldPollGraphStatus,
    refetchInterval: shouldPollGraphStatus ? 5000 : false,
    staleTime: 3000,
    retry: false,
  });
  const graphStatusError = graphStatusQuery.isError ? errorMessage(graphStatusQuery.error, "Unable to load graph enrichment status.") : null;
  const retryMutation = useMutation({
    mutationFn: (item: UploadBatchItemView) => {
      if (!item.job?.documentId) throw new Error("This upload has no document to retry.");
      return documentsApi.reingest(item.job.documentId, { retry_of_job_id: item.job.jobId });
    },
    onSuccess: async (response, item) => {
      onClearUploadJobs([item.id]);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["documents"] }),
        queryClient.invalidateQueries({ queryKey: ["ingest-jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["upload"] }),
      ]);
      notify({ title: "Retry queued", description: `${item.fileName} queued as job ${response.job_id}.`, tone: "success" });
    },
    onError: (error) => notify({
      title: "Retry failed",
      description: errorMessage(error, "Unable to retry this upload."),
      tone: "error",
    }),
  });

  useEffect(() => {
    if (pdfDraft.groupPath && !writableSpacePaths.includes(pdfDraft.groupPath)) {
      onPdfDraftChange({ groupPath: "", sharedGroupPaths: [], supersedesText: "" });
      return;
    }
    const nextShared = pdfDraft.sharedGroupPaths.filter((path) => eligibleSharedSpacePaths.includes(path));
    if (nextShared.length !== pdfDraft.sharedGroupPaths.length) {
      onPdfDraftChange({ sharedGroupPaths: nextShared });
    }
  }, [eligibleSharedSpacePaths, onPdfDraftChange, pdfDraft.groupPath, pdfDraft.sharedGroupPaths, writableSpacePaths]);

  function handleFilesSelected(files: FileList | null) {
    if (!files) return;
    onPdfDraftChange({ files: mergeDocumentFiles(pdfDraft.files, Array.from(files)) });
  }

  return (
    <PrudentiaWorkspace activeRoute="upload" onLogout={onLogout} onNavigate={onNavigate} user={currentUser}>
      <main className="sv-page" id="main-content">
        <div className="sv-page-inner sv-page-inner-workbench max-w-6xl">
          <header className="sv-page-header">
            <div>
              <p className="sv-eyebrow">Document Intake</p>
              <h1 className="sv-page-title">Add Files</h1>
              <p className="sv-page-subtitle">Upload one or more PDF, DOCX, JPG, PNG, and JSON files, or schedule folder ingestion into off-peak indexing windows.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => onNavigate("ingestion-jobs")} className="sv-action-secondary">
                <FileClock size={16} />
                Activity
              </button>
              <button type="button" onClick={() => onNavigate("knowledge-spaces")} className="sv-action-secondary">
                <FileText size={16} />
                Knowledge Spaces
              </button>
            </div>
          </header>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
            <form onSubmit={onPdfSubmit} className="sv-panel p-5">
              <div className="mb-5 flex items-start justify-between gap-4 border-b border-surface-border pb-4">
                <div>
                  <h2 className="sv-section-title">Source package</h2>
                  <p className="mt-1 text-body-md text-on-surface-variant">Select a document batch and attach the metadata used by retrieval filters.</p>
                </div>
                <span className="sv-pill sv-pill-success">{pdfDraft.files.length > 0 ? `${pdfDraft.files.length} selected` : "Live pipeline"}</span>
              </div>

              <label className="sv-field">
                <span className="sv-label">Document Files</span>
                <input
                  accept="application/pdf,.pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.docx,image/jpeg,.jpg,.jpeg,image/png,.png,application/json,.json"
                  type="file"
                  multiple
                  disabled={uploadPending}
                  onChange={(event) => {
                    handleFilesSelected(event.target.files);
                    event.target.value = "";
                  }}
                  className="sv-input file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-sm file:font-bold file:text-on-primary"
                />
                <small className="text-secondary">Select multiple PDF, DOCX, JPG, PNG, or JSON files, up to 50 MB each. Every file receives its own ingestion job.</small>
              </label>
              {pdfDraft.files.length > 0 ? (
                <ul className="mt-3 grid gap-2" aria-label="Selected documents">
                  {pdfDraft.files.map((file) => (
                    <li key={`${file.name}:${file.size}:${file.lastModified}`} className="flex items-center gap-3 rounded-md border border-surface-border bg-surface-container-low px-3 py-2">
                      <FileText className="shrink-0 text-primary" size={16} />
                      <span className="min-w-0 flex-1 truncate text-body-md font-bold text-on-surface">{file.name}</span>
                      <span className="shrink-0 text-label-md text-secondary">{formatFileSize(file.size)}</span>
                      <button
                        type="button"
                        disabled={uploadPending}
                        onClick={() => onPdfDraftChange({ files: pdfDraft.files.filter((candidate) => candidate !== file) })}
                        className="rounded p-1 text-secondary hover:bg-surface hover:text-on-surface disabled:opacity-50"
                        aria-label={`Remove ${file.name}`}
                      >
                        <X size={15} />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
              {selectionError ? <InlineMessage tone="warning">{selectionError}</InlineMessage> : null}
              <div className="mt-5 grid items-start gap-4 md:grid-cols-2">
                <SelectField disabled={uploadPending} label="Owner Knowledge Space" value={pdfDraft.groupPath} onChange={(value) => onPdfDraftChange({ groupPath: value, sharedGroupPaths: pdfDraft.sharedGroupPaths.filter((path) => path !== value) })} options={["", ...writableSpacePaths]} emptyLabel={groupsQuery.isLoading && canLoadSpaceDirectory ? "Loading spaces" : "Select upload space"} helper="Primary owner space for governance and retrieval filtering." />
                <ClearanceSelect disabled={uploadPending} value={pdfDraft.clearanceLevel} onChange={(clearanceLevel) => onPdfDraftChange({ clearanceLevel })} options={clearanceOptions} />
                {canShareUploadAcrossSpaces(currentUser, pdfDraft.groupPath) ? (
                  <SharedSpacesField
                    disabled={uploadPending}
                    onAdd={(path) => onPdfDraftChange({ sharedGroupPaths: [...pdfDraft.sharedGroupPaths, path].sort((a, b) => a.localeCompare(b)) })}
                    onRemove={(path) => onPdfDraftChange({ sharedGroupPaths: pdfDraft.sharedGroupPaths.filter((value) => value !== path) })}
                    options={sharedSpaceOptions}
                    values={pdfDraft.sharedGroupPaths}
                  />
                ) : null}
                <label className="sv-field">
                  <span className="sv-label">Effective Date <span className="font-normal text-secondary">(optional)</span></span>
                  <input disabled={uploadPending} type="date" value={pdfDraft.effectiveDate} onChange={(event) => onPdfDraftChange({ effectiveDate: event.target.value })} className="sv-input" />
                  <small className="text-secondary">Optional start date for time-aware retrieval.</small>
                </label>
                <label className="sv-field">
                  <span className="sv-label">Expiry Date</span>
                  <input disabled={uploadPending} type="date" value={pdfDraft.expiryDate} onChange={(event) => onPdfDraftChange({ expiryDate: event.target.value })} className="sv-input" />
                  <small className="text-secondary">Leave blank unless the document should age out of current use.</small>
                </label>
                <label className="sv-field">
                  <span className="sv-label">Supersedes</span>
                  <input disabled={uploadPending || pdfDraft.files.length !== 1} list="supersedes-options" value={pdfDraft.supersedesText} onChange={(event) => onPdfDraftChange({ supersedesText: event.target.value })} placeholder="Comma-separated document IDs" className="sv-input" />
                  <datalist id="supersedes-options">{writableCurrentDocuments.map((doc) => <option key={doc.id} value={doc.id}>{doc.title}</option>)}</datalist>
                  <small className="text-secondary">{pdfDraft.files.length === 1 ? "Optional version relationship for the selected document." : "Available when exactly one document is selected."}</small>
                </label>
              </div>
              <label className="sv-field mt-4">
                <span className="sv-label">Description</span>
                <textarea disabled={uploadPending} value={pdfDraft.description} onChange={(event) => onPdfDraftChange({ description: event.target.value })} placeholder="Optional shared context for library display and reviewer notes" className="sv-input min-h-24" />
                <small className="text-secondary">Shared context appears with the document for reviewers and library users.</small>
              </label>
              {groupsQuery.isError && canLoadSpaceDirectory ? <InlineMessage tone="error">{errorMessage(groupsQuery.error, "Unable to load writable Knowledge Spaces.")}</InlineMessage> : null}
              {!groupsQuery.isLoading && writableSpacePaths.length === 0 ? <InlineMessage tone="warning">No writable Knowledge Spaces are available for this account.</InlineMessage> : null}
              <button type="submit" disabled={uploadPending || pdfDraft.files.length === 0 || !selectedSpaceIsWritable || !selectedSharedSpacesAreValid} className="sv-action-primary mt-5 w-full">
                {uploadPending ? <Loader2 className="animate-spin" size={18} /> : <CloudUpload size={18} />}
                {uploadPending
                  ? "Queueing selected documents"
                  : pdfDraft.files.length === 0
                    ? "Select documents to upload"
                    : `Upload ${pdfDraft.files.length} document${pdfDraft.files.length === 1 ? "" : "s"}`}
              </button>
              {batchItems.length > 0 ? (
                <BatchUploadStatus
                  cancelingJobId={cancelingJobId}
                  currentUser={currentUser}
                  graphStatus={graphStatusQuery.data}
                  graphStatusError={graphStatusError}
                  items={batchItems}
                  onCancelIngestJob={onCancelIngestJob}
                  onClearUploadJobs={onClearUploadJobs}
                  onRetryIngestJob={(item) => retryMutation.mutate(item)}
                  retryingJobId={retryMutation.isPending ? retryMutation.variables?.job?.jobId ?? null : null}
                />
              ) : null}
            </form>

            <aside className="upload-guidance space-y-4">
              <section className="sv-panel p-5 upload-guardrails-panel">
                <h2 className="sv-section-title">Ingestion guardrails</h2>
                <div className="mt-4 space-y-3">
                  <Guardrail icon={<CheckCircle2 size={16} />} title="Access scope" detail="Documents inherit the owner space and optional shared spaces for retrieval filtering." />
                  <Guardrail icon={<ShieldCheck size={16} />} title="Version hygiene" detail="Supersession metadata keeps prior files auditable without mixing current state." />
                  <Guardrail icon={<TimerReset size={16} />} title="Batch status" detail="Every selected file is queued separately and reports its own ingestion progress." />
                </div>
              </section>
              <section className="sv-panel p-5">
                <div className="flex items-start gap-3">
                  <FileSearch className="mt-0.5 text-primary" size={18} />
                  <div>
                    <h2 className="sv-section-title">Hybrid extraction</h2>
                    <p className="mt-2 text-body-md text-on-surface-variant">Layered PyMuPDF and Docling parsing handles PDFs, Docling parses DOCX, and low-confidence OCR waits for review.</p>
                  </div>
                </div>
              </section>
            </aside>
          </div>
        </div>
      </main>
    </PrudentiaWorkspace>
  );
}

function SelectField({ disabled, emptyLabel, helper, label, onChange, options, value }: SelectProps) {
  return (
    <label className="sv-field">
      <span className="sv-label">{label}</span>
      <select disabled={disabled} value={value} onChange={(event) => onChange(event.target.value)} className="sv-select">
        {options.map((option) => <option key={option || "empty"} value={option}>{option || emptyLabel || option}</option>)}
      </select>
      {helper ? <small className="text-secondary">{helper}</small> : null}
    </label>
  );
}

function ClearanceSelect({ disabled, onChange, options, value }: ClearanceSelectProps) {
  return (
    <label className="sv-field">
      <span className="sv-label">Clearance Level</span>
      <select disabled={disabled} value={value} onChange={(event) => onChange(event.target.value as ClearanceLevel)} className="sv-select">
        {options.map((option) => <option key={option} value={option}>{clearanceLevelLabel(option)}</option>)}
      </select>
      <small className="text-secondary">{clearanceLevelDescription(value)}</small>
    </label>
  );
}

function SharedSpacesField({ disabled, onAdd, onRemove, options, values }: SharedSpacesFieldProps) {
  const [candidate, setCandidate] = useState("");
  const canAdd = Boolean(candidate) && !disabled;

  useEffect(() => {
    if (candidate && !options.includes(candidate)) setCandidate("");
  }, [candidate, options]);

  function addCandidate() {
    if (!canAdd) return;
    onAdd(candidate);
    setCandidate("");
  }

  return (
    <div className="sv-field md:col-span-2">
      <span className="sv-label">Shared Knowledge Spaces <span className="font-normal text-secondary">(optional)</span></span>
      {values.length ? (
        <div className="knowledge-topic-chips">
          {values.map((path) => (
            <span key={path} className="sv-pill knowledge-topic-pill">
              {path}
              <button type="button" onClick={() => onRemove(path)} disabled={disabled} aria-label={`Remove ${path}`}>
                <X size={13} />
              </button>
            </span>
          ))}
        </div>
      ) : null}
      <div className="knowledge-topic-form">
        <select
          className="sv-select"
          disabled={disabled || options.length === 0}
          onChange={(event) => setCandidate(event.target.value)}
          value={candidate}
        >
          <option value="">{options.length ? "Select shared space" : "No eligible shared spaces"}</option>
          {options.map((path) => <option key={path} value={path}>{path}</option>)}
        </select>
        <button type="button" className="sv-action-secondary" disabled={!canAdd} onClick={addCandidate}>
          <Plus size={15} /> Add
        </button>
      </div>
      <small className="text-secondary"><Share2 size={12} className="inline align-[-2px]" /> Selected spaces receive read access when the document is indexed.</small>
    </div>
  );
}

function BatchUploadStatus({ cancelingJobId, currentUser, graphStatus, graphStatusError, items, onCancelIngestJob, onClearUploadJobs, onRetryIngestJob, retryingJobId }: BatchUploadStatusProps) {
  const completeCount = items.filter((item) => item.job?.status === "complete").length;
  const attentionCount = items.filter((item) => item.requestState === "failed" || item.job?.status === "failed" || item.job?.status === "human_review" || item.job?.status === "cancelled").length;
  const clearableIds = items.filter(isClearableUploadItem).map((item) => item.id);
  return (
    <section className="mt-6 border-t border-surface-border pt-5" aria-label="Document batch progress" aria-live="polite">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="sv-section-title">Recent upload jobs</h2>
          <p className="text-label-md text-secondary">{completeCount} complete{attentionCount > 0 ? ` · ${attentionCount} need attention` : ""}</p>
        </div>
        <button type="button" className="sv-action-secondary" disabled={clearableIds.length === 0} onClick={() => onClearUploadJobs(clearableIds)}>
          <X size={14} /> Clear finished
        </button>
      </div>
      <ol className="mt-3 grid gap-3">
        {items.map((item) => (
          <BatchUploadRow
            cancelingJobId={cancelingJobId}
            currentUser={currentUser}
            graphStatus={graphStatus}
            graphStatusError={graphStatusError}
            item={item}
            key={item.id}
            onCancelIngestJob={onCancelIngestJob}
            onClearUploadJobs={onClearUploadJobs}
            onRetryIngestJob={onRetryIngestJob}
            retryingJobId={retryingJobId}
          />
        ))}
      </ol>
    </section>
  );
}

function BatchUploadRow({ cancelingJobId, currentUser, graphStatus, graphStatusError, item, onCancelIngestJob, onClearUploadJobs, onRetryIngestJob, retryingJobId }: BatchUploadRowProps) {
  const job = item.job;
  const progressPct = job ? Math.max(0, Math.min(100, job.progressPct)) : item.requestState === "uploading" ? 8 : 0;
  const rowStatus = item.requestState === "failed" ? "failed" : job?.status ?? "processing";
  const canCancel = Boolean(job && isUploadCancellableStatus(job.status) && canWriteDocument(currentUser, item.groupPath, item.clearanceLevel));
  const canRetry = Boolean(job?.documentId && (job.status === "failed" || job.status === "cancelled") && canWriteDocument(currentUser, item.groupPath, item.clearanceLevel));
  const canceling = Boolean(job && cancelingJobId === job.jobId);
  const retrying = Boolean(job && retryingJobId === job.jobId);
  const stageProgress = formatSecondaryStageProgress(job?.stageProgress, job?.stageDetail);
  const graphChip = job ? graphEnrichmentForJob(job, graphStatus, graphStatusError) : null;
  const error = item.uploadError
    ? errorMessage(item.uploadError, "Document upload failed.")
    : item.jobError
      ? errorMessage(item.jobError, "Unable to poll upload status.")
      : job?.errorMessage;
  return (
    <li className={`rounded-lg border p-3 ${jobPanelClass(rowStatus)}`}>
      <div className="flex items-start gap-3">
        <span className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${stageIconClass(rowStatus)}`}>
          {item.requestState === "failed" ? <XCircle aria-hidden="true" size={17} /> : job ? stageIcon(job) : <Loader2 aria-hidden="true" className="animate-spin" size={17} />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="min-w-0 truncate text-body-md font-extrabold text-on-surface">{item.fileName}</h3>
            <strong className={`text-label-md ${progressTextClass(rowStatus)}`}>{progressPct}%</strong>
          </div>
          <p className="mt-0.5 text-label-md text-secondary">
            {[item.fileSize === null ? null : formatFileSize(item.fileSize), item.groupPath, clearanceLevelLabel(item.clearanceLevel), job ? `Job ${job.jobId.slice(0, 8)}` : null].filter(Boolean).join(" · ")}
          </p>
          <p className="mt-1 text-body-md text-on-surface-variant">
            {item.requestState === "uploading" ? "Validating, scanning, and queueing this document." : item.requestState === "failed" ? "The document was not queued." : job?.stageDetail}
          </p>
          {stageProgress ? <p className="mt-1 text-label-md font-extrabold text-primary">{stageProgress}</p> : null}
          {job ? <UploadJobRuntimeDetail job={job} stageProgress={stageProgress} /> : null}
          {graphChip ? <GraphEnrichmentChip chip={graphChip} /> : null}
          <UploadRowActions
            canCancel={canCancel}
            canRetry={canRetry}
            canceling={canceling}
            item={item}
            onCancel={() => {
              if (job) onCancelIngestJob(job.jobId);
            }}
            onClear={() => onClearUploadJobs([item.id])}
            onRetry={() => onRetryIngestJob(item)}
            retrying={retrying}
          />
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface">
            <div
              aria-label={`${item.fileName} ingestion progress`}
              aria-valuemax={100}
              aria-valuemin={0}
              aria-valuenow={progressPct}
              className={`h-full rounded-full transition-all duration-300 ${progressFillClass(rowStatus)}`}
              role="progressbar"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          {error ? <p className="mt-2 text-body-md font-semibold text-error-red">{job?.errorCode ? `${job.errorCode}: ` : ""}{error}</p> : null}
        </div>
      </div>
    </li>
  );
}

function GraphEnrichmentChip({ chip }: { chip: GraphEnrichmentChipShape }) {
  const className = chip.state === "unavailable"
    ? "border-warning-amber/30 bg-warning-amber/10 text-warning-amber"
    : "border-primary/30 bg-primary/10 text-primary";
  return (
    <p className={`mt-2 inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] font-bold ${className}`}>
      {chip.state === "unavailable" ? <AlertTriangle size={12} /> : <Activity className={chip.state === "running" ? "animate-pulse" : ""} size={12} />}
      <span>{chip.label}</span>
      {chip.detail ? <span className="font-semibold opacity-80">{chip.detail}</span> : null}
    </p>
  );
}

function UploadJobRuntimeDetail({ job, stageProgress }: { job: UploadJobView; stageProgress: string | null }) {
  const isActive = job.status === "scheduled" || job.status === "queued" || job.status === "processing";
  const currentStep = currentJobStep(job);
  const nextStep = nextJobStep(job);
  const activeStageNote = activeStageProgressNote(job, stageProgress);
  const parserSummary = parserSummaryText(job);
  const elapsedLabel = elapsedText(job);
  const durationLabel = durationTakenText(job);
  return (
    <div className="mt-3 rounded-md border border-surface-border bg-surface/45 p-2.5">
      <div className="flex flex-wrap items-center gap-2 text-label-md text-secondary">
        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 font-bold ${jobActivityClass(job)}`}>
          {isActive ? <Activity className="animate-pulse" size={13} /> : terminalDetailIcon(job)}
          {jobActivityText(job)}
        </span>
        {elapsedLabel ? (
          <span className="inline-flex items-center gap-1">
            <Clock3 size={13} />
            {elapsedLabel}
          </span>
        ) : null}
        {durationLabel ? (
          <span className="inline-flex items-center gap-1">
            <TimerReset size={13} />
            {durationLabel}
          </span>
        ) : null}
        <span>{formatIngestRunLabel(job)}</span>
      </div>
      {currentStep ? (
        <p className="mt-2 text-label-md text-on-surface-variant">
          <strong className="text-on-surface">{currentStep.label}:</strong> {currentStep.detail}
          {nextStep ? <span className="text-secondary"> Next: {nextStep.label}.</span> : null}
        </p>
      ) : null}
      {activeStageNote ? <p className="mt-1 text-label-md text-secondary">{activeStageNote}</p> : null}
      {parserSummary ? <p className="mt-1 text-label-md text-secondary">{parserSummary}</p> : null}
      <ol className="mt-2 flex flex-wrap gap-1.5" aria-label="Ingestion pipeline step status">
        {job.steps.map((step) => (
          <li key={step.id} className={`inline-flex min-h-7 items-center gap-1 rounded-full border px-2 py-1 text-[11px] font-bold ${stepChipClass(step.state)}`}>
            {stepStateIcon(step)}
            <span>{step.label}</span>
          </li>
        ))}
      </ol>
      {job.warnings.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {job.warnings.map((warning) => (
            <span className="inline-flex items-center gap-1 rounded-full border border-warning-amber/30 bg-warning-amber/10 px-2 py-1 text-[11px] font-bold text-warning-amber" key={warning}>
              <AlertTriangle size={12} />
              {formatUploadWarning(warning)}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function UploadRowActions({ canCancel, canRetry, canceling, item, onCancel, onClear, onRetry, retrying }: UploadRowActionsProps) {
  const [confirmCancel, setConfirmCancel] = useState(false);
  const clearable = isClearableUploadItem(item);
  if (!canCancel && !canRetry && !clearable) return null;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-label-md">
      {canRetry ? (
        <button
          className="inline-flex items-center gap-1 rounded-md border border-surface-border px-2 py-1 font-bold text-secondary hover:bg-surface hover:text-primary disabled:opacity-50"
          disabled={retrying}
          onClick={onRetry}
          type="button"
        >
          {retrying ? <Loader2 className="animate-spin" size={13} /> : <RotateCw size={13} />}
          {retrying ? "Queueing" : "Retry"}
        </button>
      ) : null}
      {canCancel ? (
        <CancelIngestControl
          confirming={confirmCancel}
          disabled={canceling}
          onCancel={onCancel}
          onConfirmingChange={setConfirmCancel}
        />
      ) : null}
      {clearable ? (
        <button
          className="inline-flex items-center gap-1 rounded-md border border-surface-border px-2 py-1 font-bold text-secondary hover:bg-surface hover:text-on-surface"
          onClick={onClear}
          type="button"
        >
          <X size={13} /> Clear
        </button>
      ) : null}
    </div>
  );
}

function CancelIngestControl({ confirming, disabled, onCancel, onConfirmingChange }: { confirming: boolean; disabled: boolean; onCancel: () => void; onConfirmingChange: (value: boolean) => void }) {
  if (confirming) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-error-red">Cancel this ingestion job?</span>
        <button
          className="rounded-md border border-error-red/30 px-2 py-1 font-bold text-error-red hover:bg-error-container disabled:opacity-50"
          disabled={disabled}
          onClick={() => {
            onCancel();
            onConfirmingChange(false);
          }}
          type="button"
        >
          {disabled ? "Cancelling" : "Cancel job"}
        </button>
        <button className="rounded-md border border-surface-border px-2 py-1 font-bold text-secondary hover:bg-surface" disabled={disabled} onClick={() => onConfirmingChange(false)} type="button">
          Keep running
        </button>
      </div>
    );
  }
  return (
    <button
      className="inline-flex items-center gap-1 rounded-md border border-surface-border px-2 py-1 font-bold text-secondary hover:bg-surface hover:text-error-red disabled:opacity-50"
      disabled={disabled}
      onClick={() => onConfirmingChange(true)}
      type="button"
    >
      <XCircle size={13} />
      {disabled ? "Cancelling" : "Cancel job"}
    </button>
  );
}

function isClearableUploadItem(item: UploadBatchItemView) {
  return item.requestState === "failed" || isUploadTerminalStatus(item.job?.status);
}

function Guardrail({ detail, icon, title }: { detail: string; icon: JSX.Element; title: string }) {
  return (
    <div className="upload-guardrail">
      <div className="flex items-center gap-2 text-body-md font-bold text-on-surface"><span className="text-primary">{icon}</span>{title}</div>
      <p className="mt-1 text-body-md text-on-surface-variant">{detail}</p>
    </div>
  );
}

export function canShareUploadAcrossSpaces(user: AuthUser, ownerGroupPath: string) {
  if (!ownerGroupPath) return false;
  return isGlobalAdmin(user) || (user.account_type === "space_admin" && hasExactGroupScope(user, ownerGroupPath));
}

export function uploadShareTargetPaths(user: AuthUser, ownerGroupPath: string, spaces: Array<{ path: string }>) {
  if (!ownerGroupPath || !canShareUploadAcrossSpaces(user, ownerGroupPath)) return [];
  const targets = spaces.filter((space) => space.path !== ownerGroupPath);
  if (isGlobalAdmin(user)) return targets.map((space) => space.path);
  return targets.filter((space) => hasExactGroupScope(user, space.path)).map((space) => space.path);
}

type SelectProps = { disabled?: boolean; emptyLabel?: string; helper?: string; label: string; onChange: (value: string) => void; options: string[]; value: string };
type ClearanceSelectProps = { disabled?: boolean; onChange: (value: ClearanceLevel) => void; options: ClearanceLevel[]; value: ClearanceLevel };
type SharedSpacesFieldProps = { disabled?: boolean; onAdd: (path: string) => void; onRemove: (path: string) => void; options: string[]; values: string[] };
type Props = {
  batchItems: UploadBatchItemView[]; cancelingJobId: string | null; currentDocuments: Document[]; currentUser: AuthUser;
  onCancelIngestJob: (jobId: string) => void; onClearUploadJobs: (itemIds: string[]) => void; onLogout: () => void; onNavigate: (route: RouteId) => void; onPdfDraftChange: (patch: Partial<PdfUploadDraft>) => void;
  onPdfSubmit: (event: FormEvent<HTMLFormElement>) => void; pdfDraft: PdfUploadDraft; selectionError: string | null; uploadPending: boolean;
};
type BatchUploadStatusProps = { cancelingJobId: string | null; currentUser: AuthUser; graphStatus: GraphRAGStatus | undefined; graphStatusError: string | null; items: UploadBatchItemView[]; onCancelIngestJob: (jobId: string) => void; onClearUploadJobs: (itemIds: string[]) => void; onRetryIngestJob: (item: UploadBatchItemView) => void; retryingJobId: string | null };
type BatchUploadRowProps = Omit<BatchUploadStatusProps, "items"> & { item: UploadBatchItemView };
type UploadRowActionsProps = { canCancel: boolean; canRetry: boolean; canceling: boolean; item: UploadBatchItemView; onCancel: () => void; onClear: () => void; onRetry: () => void; retrying: boolean };

function stageIcon(job: UploadJobView) {
  if (job.status === "complete") return <CheckCircle2 aria-hidden="true" size={18} />;
  if (job.status === "failed") return <XCircle aria-hidden="true" size={18} />;
  if (job.status === "cancelled") return <XCircle aria-hidden="true" size={18} />;
  if (job.status === "human_review") return <AlertTriangle aria-hidden="true" size={18} />;
  return <Loader2 aria-hidden="true" className="animate-spin" size={18} />;
}

function jobPanelClass(status: UploadJobView["status"] | "processing") {
  if (status === "complete") return "border-success/30 bg-success/10";
  if (status === "failed") return "border-error-red/25 bg-error-container";
  if (status === "cancelled") return "border-warning-amber/30 bg-warning-amber/10";
  if (status === "human_review") return "border-warning-amber/30 bg-warning-amber/10";
  return "border-surface-border bg-surface-container-low";
}

function progressFillClass(status: UploadJobView["status"] | "processing") {
  if (status === "complete") return "bg-success";
  if (status === "failed") return "bg-error-red";
  if (status === "cancelled") return "bg-warning-amber";
  if (status === "human_review") return "bg-warning-amber";
  return "bg-primary";
}

function progressTextClass(status: UploadJobView["status"] | "processing") {
  if (status === "complete") return "text-success";
  if (status === "failed") return "text-error-red";
  if (status === "cancelled") return "text-warning-amber";
  if (status === "human_review") return "text-warning-amber";
  return "text-primary";
}

function stageIconClass(status: UploadJobView["status"] | "processing") {
  if (status === "complete") return "bg-success/10 text-success";
  if (status === "failed") return "bg-error-container text-error-red";
  if (status === "cancelled") return "bg-warning-amber/10 text-warning-amber";
  if (status === "human_review") return "bg-warning-amber/10 text-warning-amber";
  return "bg-primary/10 text-primary";
}

function currentJobStep(job: UploadJobView): UploadJobStep | null {
  return job.steps.find((step) => step.state === "active" || step.state === "failed" || step.state === "needs_review")
    ?? job.steps.find((step) => step.id === job.stage)
    ?? null;
}

function nextJobStep(job: UploadJobView): UploadJobStep | null {
  return job.steps.find((step) => step.state === "pending") ?? null;
}

function jobActivityText(job: UploadJobView): string {
  if (job.status === "complete") return job.warnings.length > 0 ? "Indexed with warnings" : "Indexed";
  if (job.status === "failed") return "Failed";
  if (job.status === "cancelled") return "Cancelled";
  if (job.status === "human_review") return "Needs review";
  if (job.status === "scheduled") return "Scheduled";
  if (job.status === "queued") return "Waiting for worker";
  const heartbeat = relativeAge(job.lastHeartbeatAt);
  if (!heartbeat) return "Worker starting";
  if (heartbeat.seconds <= 75) return `Worker active ${agoText(heartbeat.label)}`;
  if (heartbeat.seconds <= 180) return `Last worker update ${agoText(heartbeat.label)}`;
  return `No worker update for ${heartbeat.label}`;
}

function jobActivityClass(job: UploadJobView): string {
  if (job.status === "complete") return "bg-success/10 text-success";
  if (job.status === "failed") return "bg-error-container text-error-red";
  if (job.status === "cancelled") return "bg-warning-amber/10 text-warning-amber";
  if (job.status === "human_review") return "bg-warning-amber/10 text-warning-amber";
  const heartbeat = relativeAge(job.lastHeartbeatAt);
  if (job.status === "processing" && heartbeat && heartbeat.seconds > 180) return "bg-warning-amber/10 text-warning-amber";
  return "bg-primary/10 text-primary";
}

function elapsedText(job: UploadJobView): string | null {
  const started = relativeAge(job.createdAt);
  if (!started) return null;
  if (job.status === "complete" || job.status === "failed" || job.status === "human_review" || job.status === "cancelled") return `Started ${agoText(started.label)}`;
  return `Running ${started.label}`;
}

function durationTakenText(job: UploadJobView): string | null {
  if (job.status !== "complete" && job.status !== "failed" && job.status !== "human_review" && job.status !== "cancelled") return null;
  const seconds = secondsBetween(job.createdAt, job.completedAt ?? job.updatedAt);
  if (seconds === null) return null;
  return `Took ${exactDurationLabel(seconds)}`;
}

function activeStageProgressNote(job: UploadJobView, stageProgress: string | null): string | null {
  if (job.status !== "processing") return null;
  if (job.stage !== "parsing_document") return stageProgress;
  return parserProgressNote(job, stageProgress);
}

function parserProgressNote(job: UploadJobView, stageProgress: string | null): string | null {
  if (job.status !== "processing" || job.stage !== "parsing_document") return null;
  if (stageProgress && stageProgress.toLowerCase().includes("docling")) {
    return "Docling is repairing selected pages before metadata generation starts.";
  }
  if (job.stageProgress?.unit === "pages" && job.stageProgress.total <= 1 && job.stageProgress.current >= job.stageProgress.total) {
    return "Page parsing is complete; OCR, layout, and table structure can still run before metadata starts.";
  }
  if (stageProgress) return "Scanned pages, handwriting, and dense tables may spend extra time in this stage.";
  return "The parser is extracting text, layout, tables, and hierarchy.";
}

function parserSummaryText(job: UploadJobView): string | null {
  const provenance = job.parserProvenance;
  if (!provenance) return null;
  const parser = provenance.secondary_parser ? `${provenance.primary_parser} + ${provenance.secondary_parser}` : provenance.primary_parser;
  const pages = provenance.page_count ? `${provenance.page_count} page${provenance.page_count === 1 ? "" : "s"}` : "page count pending";
  return `Parser route: ${labelize(provenance.routing_mode)} via ${parser}; ${pages}.`;
}

function stepChipClass(state: UploadJobStep["state"]): string {
  if (state === "complete") return "border-success/30 bg-success/10 text-success";
  if (state === "active") return "border-primary/40 bg-primary/10 text-primary";
  if (state === "failed") return "border-error-red/30 bg-error-container text-error-red";
  if (state === "cancelled") return "border-warning-amber/30 bg-warning-amber/10 text-warning-amber";
  if (state === "needs_review") return "border-warning-amber/30 bg-warning-amber/10 text-warning-amber";
  return "border-surface-border bg-surface-container-low text-secondary";
}

function stepStateIcon(step: UploadJobStep) {
  if (step.state === "complete") return <CheckCircle2 aria-hidden="true" size={12} />;
  if (step.state === "failed") return <XCircle aria-hidden="true" size={12} />;
  if (step.state === "cancelled") return <XCircle aria-hidden="true" size={12} />;
  if (step.state === "needs_review") return <AlertTriangle aria-hidden="true" size={12} />;
  if (step.state === "active") return <Loader2 aria-hidden="true" className="animate-spin" size={12} />;
  return <span aria-hidden="true" className="h-2 w-2 rounded-full bg-current opacity-40" />;
}

function terminalDetailIcon(job: UploadJobView) {
  if (job.status === "complete") return <CheckCircle2 aria-hidden="true" size={13} />;
  if (job.status === "failed") return <XCircle aria-hidden="true" size={13} />;
  if (job.status === "cancelled") return <XCircle aria-hidden="true" size={13} />;
  if (job.status === "human_review") return <AlertTriangle aria-hidden="true" size={13} />;
  return <Activity aria-hidden="true" size={13} />;
}

function relativeAge(value: string | null): { seconds: number; label: string } | null {
  if (!value) return null;
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return null;
  const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  return { seconds, label: durationLabel(seconds) };
}

function durationLabel(totalSeconds: number): string {
  if (totalSeconds < 5) return "just now";
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes > 0 ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
}

function exactDurationLabel(totalSeconds: number): string {
  if (totalSeconds < 1) return "<1s";
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const seconds = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  if (totalMinutes < 60) return seconds > 0 ? `${totalMinutes}m ${seconds}s` : `${totalMinutes}m`;
  const minutes = totalMinutes % 60;
  const hours = Math.floor(totalMinutes / 60);
  return seconds > 0 ? `${hours}h ${minutes}m ${seconds}s` : `${hours}h ${minutes}m`;
}

function secondsBetween(startValue: string | null, endValue: string | null): number | null {
  if (!startValue || !endValue) return null;
  const start = Date.parse(startValue);
  const end = Date.parse(endValue);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  return Math.max(0, Math.round((end - start) / 1000));
}

function agoText(label: string): string {
  return label === "just now" ? label : `${label} ago`;
}

function labelize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
