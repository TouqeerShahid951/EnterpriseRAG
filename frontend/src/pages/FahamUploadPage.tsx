import { useEffect, useMemo, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, CheckCircle2, Clock3, CloudUpload, FileClock, FileSearch, FileText, Loader2, ShieldCheck, TimerReset, X, XCircle } from "lucide-react";

import { adminApi } from "../api/contracts";
import { canManageSpaces, canUploadToSpace, canWriteDocument } from "../authz";
import { InlineMessage } from "../components/layout/Common";
import { FahamWorkspace } from "../components/layout/FahamWorkspace";
import type { RouteId } from "../routes";
import { formatFileSize, mergeDocumentFiles } from "../state/pdfUploadBatch";
import type { DocType, Document, UploadJobStep, User as AuthUser } from "../types/api";
import type { PdfUploadDraft, UploadBatchItemView, UploadJobView } from "../types/chat";
import { errorMessage } from "../utils/format";
import { flattenGroups, userSpacesFromPaths } from "../utils/groups";
import { formatStageProgress } from "../state/uploadJobProgress";

export function FahamUploadPage({ batchItems, currentDocuments, currentUser, onLogout, onNavigate, onPdfDraftChange, onPdfSubmit, pdfDraft, selectionError, uploadPending }: Props) {
  const docTypes: DocType[] = ["policy", "procedure", "report", "contract", "memo", "manual", "other"];
  const canLoadSpaceDirectory = canManageSpaces(currentUser);
  const groupsQuery = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.listGroups, retry: false, enabled: canLoadSpaceDirectory });
  const uploadSpaceOptions = useMemo(
    () => (canLoadSpaceDirectory ? flattenGroups(groupsQuery.data?.items ?? []) : userSpacesFromPaths(currentUser.group_paths)),
    [canLoadSpaceDirectory, currentUser.group_paths, groupsQuery.data?.items],
  );
  const writableSpacePaths = uploadSpaceOptions
    .filter((space) => canUploadToSpace(currentUser, space.path))
    .map((space) => space.path);
  const writableCurrentDocuments = currentDocuments.filter((document) => canWriteDocument(currentUser, document.group_path));
  const selectedSpaceIsWritable = Boolean(pdfDraft.groupPath && canUploadToSpace(currentUser, pdfDraft.groupPath));

  useEffect(() => {
    if (pdfDraft.groupPath && !writableSpacePaths.includes(pdfDraft.groupPath)) {
      onPdfDraftChange({ groupPath: "", supersedesText: "" });
    }
  }, [onPdfDraftChange, pdfDraft.groupPath, writableSpacePaths]);

  function handleFilesSelected(files: FileList | null) {
    if (!files) return;
    onPdfDraftChange({ files: mergeDocumentFiles(pdfDraft.files, Array.from(files)) });
  }

  return (
    <FahamWorkspace activeRoute="upload" onLogout={onLogout} onNavigate={onNavigate} user={currentUser}>
      <main className="sv-page" id="main-content">
        <div className="sv-page-inner max-w-6xl">
          <header className="sv-page-header">
            <div>
              <p className="sv-eyebrow">Document Intake</p>
              <h1 className="sv-page-title">Add Files</h1>
              <p className="sv-page-subtitle">Upload one or more PDF, DOCX, JPG, and PNG files, or schedule folder ingestion into off-peak indexing windows.</p>
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

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
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
                  accept="application/pdf,.pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.docx,image/jpeg,.jpg,.jpeg,image/png,.png"
                  type="file"
                  multiple
                  disabled={uploadPending}
                  onChange={(event) => {
                    handleFilesSelected(event.target.files);
                    event.target.value = "";
                  }}
                  className="sv-input file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-sm file:font-bold file:text-on-primary"
                />
                <small className="text-secondary">Select multiple PDF, DOCX, JPG, or PNG files, up to 50 MB each. Every file receives its own ingestion job.</small>
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
              <div className="mt-5 grid gap-4 md:grid-cols-2">
                <SelectField disabled={uploadPending} label="Knowledge Space" value={pdfDraft.groupPath} onChange={(value) => onPdfDraftChange({ groupPath: value })} options={["", ...writableSpacePaths]} emptyLabel={groupsQuery.isLoading && canLoadSpaceDirectory ? "Loading spaces" : "Select upload space"} />
                <label className="sv-field"><span className="sv-label">Effective Date <span className="font-normal text-secondary">(optional)</span></span><input disabled={uploadPending} type="date" value={pdfDraft.effectiveDate} onChange={(event) => onPdfDraftChange({ effectiveDate: event.target.value })} className="sv-input" /></label>
                <label className="sv-field"><span className="sv-label">Expiry Date</span><input disabled={uploadPending} type="date" value={pdfDraft.expiryDate} onChange={(event) => onPdfDraftChange({ expiryDate: event.target.value })} className="sv-input" /></label>
                <SelectField disabled={uploadPending} label="Document Type" value={pdfDraft.docType} onChange={(value) => onPdfDraftChange({ docType: value as DocType })} options={docTypes} />
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
              </label>
              {groupsQuery.isError && canLoadSpaceDirectory ? <InlineMessage tone="error">{errorMessage(groupsQuery.error, "Unable to load writable Knowledge Spaces.")}</InlineMessage> : null}
              {!groupsQuery.isLoading && writableSpacePaths.length === 0 ? <InlineMessage tone="warning">No writable Knowledge Spaces are available for this account.</InlineMessage> : null}
              <button type="submit" disabled={uploadPending || pdfDraft.files.length === 0 || !selectedSpaceIsWritable} className="sv-action-primary mt-5 w-full">
                {uploadPending ? <Loader2 className="animate-spin" size={18} /> : <CloudUpload size={18} />}
                {uploadPending
                  ? "Queueing selected documents"
                  : pdfDraft.files.length === 0
                    ? "Select documents to upload"
                    : `Upload ${pdfDraft.files.length} document${pdfDraft.files.length === 1 ? "" : "s"}`}
              </button>
              {batchItems.length > 0 ? <BatchUploadStatus items={batchItems} /> : null}
            </form>

            <aside className="space-y-4">
              <section className="sv-panel p-5">
                <h2 className="sv-section-title">Ingestion guardrails</h2>
                <div className="mt-4 space-y-3">
                  <Guardrail icon={<CheckCircle2 size={16} />} title="Access scope" detail="Documents inherit the selected Knowledge Space for retrieval filtering." />
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
    </FahamWorkspace>
  );
}

function SelectField({ disabled, emptyLabel, label, onChange, options, value }: SelectProps) {
  return <label className="sv-field"><span className="sv-label">{label}</span><select disabled={disabled} value={value} onChange={(event) => onChange(event.target.value)} className="sv-select">{options.map((option) => <option key={option || "empty"} value={option}>{option || emptyLabel || option}</option>)}</select></label>;
}

function BatchUploadStatus({ items }: { items: UploadBatchItemView[] }) {
  const completeCount = items.filter((item) => item.job?.status === "complete").length;
  const attentionCount = items.filter((item) => item.requestState === "failed" || item.job?.status === "failed" || item.job?.status === "human_review").length;
  return (
    <section className="mt-6 border-t border-surface-border pt-5" aria-label="Document batch progress" aria-live="polite">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="sv-section-title">Recent upload jobs</h2>
        <p className="text-label-md text-secondary">{completeCount} complete{attentionCount > 0 ? ` · ${attentionCount} need attention` : ""}</p>
      </div>
      <ol className="mt-3 grid gap-3">
        {items.map((item) => <BatchUploadRow item={item} key={item.id} />)}
      </ol>
    </section>
  );
}

function BatchUploadRow({ item }: { item: UploadBatchItemView }) {
  const job = item.job;
  const progressPct = job ? Math.max(0, Math.min(100, job.progressPct)) : item.requestState === "uploading" ? 8 : 0;
  const rowStatus = item.requestState === "failed" ? "failed" : job?.status ?? "processing";
  const stageProgress = formatStageProgress(job?.stageProgress);
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
          <p className="mt-0.5 text-label-md text-secondary">{formatFileSize(item.fileSize)} · {item.groupPath}{job ? ` · Job ${job.jobId.slice(0, 8)}` : ""}</p>
          <p className="mt-1 text-body-md text-on-surface-variant">
            {item.requestState === "uploading" ? "Validating, scanning, and queueing this document." : item.requestState === "failed" ? "The document was not queued." : job?.stageDetail}
          </p>
          {stageProgress ? <p className="mt-1 text-label-md font-extrabold text-primary">{stageProgress}</p> : null}
          {job ? <UploadJobRuntimeDetail job={job} stageProgress={stageProgress} /> : null}
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

function UploadJobRuntimeDetail({ job, stageProgress }: { job: UploadJobView; stageProgress: string | null }) {
  const isActive = job.status === "scheduled" || job.status === "queued" || job.status === "processing";
  const currentStep = currentJobStep(job);
  const nextStep = nextJobStep(job);
  const parserNote = parserProgressNote(job, stageProgress);
  const parserSummary = parserSummaryText(job);
  return (
    <div className="mt-3 rounded-md border border-surface-border bg-surface/45 p-2.5">
      <div className="flex flex-wrap items-center gap-2 text-label-md text-secondary">
        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 font-bold ${jobActivityClass(job)}`}>
          {isActive ? <Activity className="animate-pulse" size={13} /> : terminalDetailIcon(job)}
          {jobActivityText(job)}
        </span>
        {elapsedText(job) ? (
          <span className="inline-flex items-center gap-1">
            <Clock3 size={13} />
            {elapsedText(job)}
          </span>
        ) : null}
        <span>Attempt {Math.max(1, job.attemptCount || 1)} of {job.maxAttempts || 3}</span>
      </div>
      {currentStep ? (
        <p className="mt-2 text-label-md text-on-surface-variant">
          <strong className="text-on-surface">{currentStep.label}:</strong> {currentStep.detail}
          {nextStep ? <span className="text-secondary"> Next: {nextStep.label}.</span> : null}
        </p>
      ) : null}
      {parserNote ? <p className="mt-1 text-label-md text-secondary">{parserNote}</p> : null}
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
              {labelize(warning)}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Guardrail({ detail, icon, title }: { detail: string; icon: JSX.Element; title: string }) {
  return (
    <div className="rounded-lg border border-surface-border bg-surface-container-low p-3">
      <div className="flex items-center gap-2 text-body-md font-bold text-on-surface"><span className="text-primary">{icon}</span>{title}</div>
      <p className="mt-1 text-body-md text-on-surface-variant">{detail}</p>
    </div>
  );
}

type SelectProps = { disabled?: boolean; emptyLabel?: string; label: string; onChange: (value: string) => void; options: string[]; value: string };
type Props = {
  batchItems: UploadBatchItemView[]; currentDocuments: Document[]; currentUser: AuthUser;
  onLogout: () => void; onNavigate: (route: RouteId) => void; onPdfDraftChange: (patch: Partial<PdfUploadDraft>) => void;
  onPdfSubmit: (event: FormEvent<HTMLFormElement>) => void; pdfDraft: PdfUploadDraft; selectionError: string | null; uploadPending: boolean;
};

function stageIcon(job: UploadJobView) {
  if (job.status === "complete") return <CheckCircle2 aria-hidden="true" size={18} />;
  if (job.status === "failed") return <XCircle aria-hidden="true" size={18} />;
  if (job.status === "human_review") return <AlertTriangle aria-hidden="true" size={18} />;
  return <Loader2 aria-hidden="true" className="animate-spin" size={18} />;
}

function jobPanelClass(status: UploadJobView["status"] | "processing") {
  if (status === "complete") return "border-success/30 bg-success/10";
  if (status === "failed") return "border-error-red/25 bg-error-container";
  if (status === "human_review") return "border-warning-amber/30 bg-warning-amber/10";
  return "border-surface-border bg-surface-container-low";
}

function progressFillClass(status: UploadJobView["status"] | "processing") {
  if (status === "complete") return "bg-success";
  if (status === "failed") return "bg-error-red";
  if (status === "human_review") return "bg-warning-amber";
  return "bg-primary";
}

function progressTextClass(status: UploadJobView["status"] | "processing") {
  if (status === "complete") return "text-success";
  if (status === "failed") return "text-error-red";
  if (status === "human_review") return "text-warning-amber";
  return "text-primary";
}

function stageIconClass(status: UploadJobView["status"] | "processing") {
  if (status === "complete") return "bg-success/10 text-success";
  if (status === "failed") return "bg-error-container text-error-red";
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
  if (job.status === "human_review") return "bg-warning-amber/10 text-warning-amber";
  const heartbeat = relativeAge(job.lastHeartbeatAt);
  if (job.status === "processing" && heartbeat && heartbeat.seconds > 180) return "bg-warning-amber/10 text-warning-amber";
  return "bg-primary/10 text-primary";
}

function elapsedText(job: UploadJobView): string | null {
  const started = relativeAge(job.createdAt);
  if (!started) return null;
  if (job.status === "complete" || job.status === "failed" || job.status === "human_review") return `Started ${agoText(started.label)}`;
  return `Running ${started.label}`;
}

function parserProgressNote(job: UploadJobView, stageProgress: string | null): string | null {
  if (job.status !== "processing" || job.stage !== "parsing_document") return null;
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
  if (state === "needs_review") return "border-warning-amber/30 bg-warning-amber/10 text-warning-amber";
  return "border-surface-border bg-surface-container-low text-secondary";
}

function stepStateIcon(step: UploadJobStep) {
  if (step.state === "complete") return <CheckCircle2 aria-hidden="true" size={12} />;
  if (step.state === "failed") return <XCircle aria-hidden="true" size={12} />;
  if (step.state === "needs_review") return <AlertTriangle aria-hidden="true" size={12} />;
  if (step.state === "active") return <Loader2 aria-hidden="true" className="animate-spin" size={12} />;
  return <span aria-hidden="true" className="h-2 w-2 rounded-full bg-current opacity-40" />;
}

function terminalDetailIcon(job: UploadJobView) {
  if (job.status === "complete") return <CheckCircle2 aria-hidden="true" size={13} />;
  if (job.status === "failed") return <XCircle aria-hidden="true" size={13} />;
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

function agoText(label: string): string {
  return label === "just now" ? label : `${label} ago`;
}

function labelize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
