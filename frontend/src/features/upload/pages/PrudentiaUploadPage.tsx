import { useEffect, useMemo, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, CloudUpload, FileClock, FileSearch, FileText, Loader2, ShieldCheck, TimerReset, X } from "lucide-react";

import { abbreviationsApi, adminApi, documentsApi, ingestJobsApi } from "@/lib/api/contracts";
import { canManageSpaces, canUploadToSpace, canWriteDocument, clearanceLevelsAssignableBy, hasExactGroupScope, isGlobalAdmin } from "@/lib/auth/authz";
import { useToast } from "@/components/feedback/ToastProvider";
import { InlineMessage } from "@/components/layout/Common";
import { PrudentiaWorkspace } from "@/components/layout/PrudentiaWorkspace";
import type { RouteId } from "@/routes/routes";
import { formatFileSize, mergeDocumentFiles } from "@/features/upload/state/pdfUploadBatch";
import { graphEnrichmentTaskForJob } from "@/features/upload/state/uploadJobProgress";
import type { Document, User as AuthUser } from "@/types/api";
import type { PdfUploadDraft, UploadBatchItemView } from "@/types/chat";
import { errorMessage } from "@/lib/utils/format";
import { flattenGroups, userSpacesFromPaths } from "@/lib/utils/groups";
import { ClearanceSelect, Guardrail, SelectField, SharedSpacesField } from "@/features/upload/components/UploadFormFields";
import { BatchUploadStatus } from "@/features/upload/components/BatchUploadStatus";
import { AbbreviationGlossaryManager } from "@/features/upload/components/AbbreviationGlossaryManager";


export function PrudentiaUploadPage({ batchItems, cancelingJobId, currentDocuments, currentUser, mode = "documents", onCancelIngestJob, onClearUploadJobs, onLogout, onNavigate, onPdfDraftChange, onPdfSubmit, pdfDraft, selectionError, uploadPending }: Props) {
  const isGlossary = mode === "glossary";
  const IntakeContainer = isGlossary ? "details" : "div";
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
  const glossaryQuery = useQuery({
    queryKey: ["abbreviation-glossary"],
    queryFn: abbreviationsApi.get,
    retry: false,
    enabled: isGlossary,
  });
  const currentGlossarySources = glossaryQuery.data?.sources ?? [];
  const currentGlossarySourceIds = useMemo(
    () => currentGlossarySources.map((source) => source.document_id),
    [currentGlossarySources],
  );
  const selectedSpaceIsWritable = Boolean(pdfDraft.groupPath && canUploadToSpace(currentUser, pdfDraft.groupPath));
  const selectedSharedSpacesAreValid = pdfDraft.sharedGroupPaths.every((path) => eligibleSharedSpacePaths.includes(path));
  const completedJobs = batchItems.flatMap((item) => item.job?.status === "complete" ? [item.job] : []);
  const shouldLoadGraphStatus = !isGlossary && completedJobs.length > 0;
  const graphStatusQuery = useQuery({
    queryKey: ["ingest-jobs", "graphrag-status", "upload-batch"],
    queryFn: ingestJobsApi.graphragStatus,
    enabled: shouldLoadGraphStatus,
    refetchInterval: (query) => completedJobs.some((job) => graphEnrichmentTaskForJob(job, query.state.data)) ? 5000 : false,
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
    if (isGlossary) return;
    if (pdfDraft.groupPath && !writableSpacePaths.includes(pdfDraft.groupPath)) {
      onPdfDraftChange({ groupPath: "", sharedGroupPaths: [], supersedesText: "" });
      return;
    }
    const nextShared = pdfDraft.sharedGroupPaths.filter((path) => eligibleSharedSpacePaths.includes(path));
    if (nextShared.length !== pdfDraft.sharedGroupPaths.length) {
      onPdfDraftChange({ sharedGroupPaths: nextShared });
    }
  }, [eligibleSharedSpacePaths, isGlossary, onPdfDraftChange, pdfDraft.groupPath, pdfDraft.sharedGroupPaths, writableSpacePaths]);

  useEffect(() => {
    if (!isGlossary) return;
    const ownerPath = currentDocuments.find((document) => document.id === currentGlossarySourceIds[0])?.group_path
      ?? writableSpacePaths[0]
      ?? "";
    const replacementId = pdfDraft.files.length <= 1 && currentGlossarySourceIds.includes(pdfDraft.supersedesText)
      ? pdfDraft.supersedesText
      : "";
    if (
      pdfDraft.groupPath !== ownerPath
      || pdfDraft.sharedGroupPaths.length > 0
      || pdfDraft.clearanceLevel !== "NATO_UNCLASSIFIED"
      || pdfDraft.effectiveDate
      || pdfDraft.expiryDate
      || pdfDraft.supersedesText !== replacementId
    ) {
      onPdfDraftChange({
        groupPath: ownerPath,
        sharedGroupPaths: [],
        clearanceLevel: "NATO_UNCLASSIFIED",
        effectiveDate: "",
        expiryDate: "",
        supersedesText: replacementId,
      });
    }
  }, [currentDocuments, currentGlossarySourceIds, isGlossary, onPdfDraftChange, pdfDraft, writableSpacePaths]);

  function handleFilesSelected(files: FileList | null) {
    if (!files) return;
    onPdfDraftChange({
      files: mergeDocumentFiles(pdfDraft.files, Array.from(files)),
    });
  }

  return (
    <PrudentiaWorkspace activeRoute={isGlossary ? "abbreviation-glossary" : "upload"} onLogout={onLogout} onNavigate={onNavigate} user={currentUser}>
      <main className="sv-page" id="main-content">
        <div className="sv-page-inner sv-page-inner-workbench max-w-6xl">
          <header className="sv-page-header">
            <div>
              <p className="sv-eyebrow">Document Intake</p>
              <h1 className="sv-page-title">{isGlossary ? "Abbreviation Glossary" : "Add Files"}</h1>
              <p className="sv-page-subtitle">{isGlossary ? "Define the language Prudentia uses to match queries. Add terms directly or manage several governed PDF sources." : "Upload PDF, DOCX, JPG, PNG, and JSON files into governed Knowledge Spaces, then follow each file through indexing."}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => onNavigate("ingestion-jobs")} className="sv-action-secondary">
                <FileClock size={16} />
                {isGlossary ? "All intake activity" : "Activity"}
              </button>
              {!isGlossary ? (
                <button type="button" onClick={() => onNavigate("knowledge-spaces")} className="sv-action-secondary">
                  <FileText size={16} />
                  Knowledge Spaces
                </button>
              ) : null}
            </div>
          </header>

          {isGlossary ? (
            <AbbreviationGlossaryManager
              importStatusKey={batchItems.map((item) => `${item.job?.jobId ?? item.id}:${item.job?.status ?? "queued"}`).join("|")}
            />
          ) : null}

          <IntakeContainer className={isGlossary ? "group mt-4" : undefined}>
            {isGlossary ? (
              <summary className="sv-panel flex min-h-16 cursor-pointer list-none flex-col items-start justify-between gap-3 p-4 text-left sm:flex-row sm:items-center [&::-webkit-details-marker]:hidden">
                <div className="min-w-0">
                  <p className="sv-eyebrow">Governed source</p>
                  <h2 className="sv-section-title mt-1">Manage PDF sources</h2>
                  <p className="mt-1 text-body-md text-on-surface-variant">Add several governed PDFs at once, or replace one active source without affecting the others.</p>
                </div>
                <div className="flex w-full min-w-0 items-center justify-between gap-3 sm:w-auto sm:shrink-0">
                  <span className={`${currentGlossarySources.length > 0 ? "sv-pill sv-pill-success" : "sv-pill"} min-w-0 max-w-full truncate`}>
                    {currentGlossarySources.length > 0 ? `${currentGlossarySources.length} active PDF source${currentGlossarySources.length === 1 ? "" : "s"}` : "No PDF sources"}
                  </span>
                  <ChevronDown aria-hidden="true" className="text-secondary transition-transform group-open:rotate-180" size={18} />
                </div>
              </summary>
            ) : null}

          <div className={isGlossary ? "mt-3" : "grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]"}>
            <form onSubmit={onPdfSubmit} className="sv-panel p-5">
              <div className="mb-5 flex flex-col items-start justify-between gap-3 border-b border-surface-border pb-4 sm:flex-row sm:gap-4">
                <div>
                  <h2 className="sv-section-title">{isGlossary ? "PDF source files" : "Source package"}</h2>
                  <p className="mt-1 text-body-md text-on-surface-variant">{isGlossary ? "Select one or more PDFs containing abbreviation and full-term pairs." : "Select a document batch and attach the metadata used by retrieval filters."}</p>
                </div>
                <span className="sv-pill sv-pill-success shrink-0">{pdfDraft.files.length > 0 ? `${pdfDraft.files.length} selected` : isGlossary ? "PDF only" : "Live pipeline"}</span>
              </div>

              <label className="sv-field">
                <span className="sv-label">{isGlossary ? "Glossary PDF" : "Document Files"}</span>
                <input
                  accept={isGlossary ? "application/pdf,.pdf" : "application/pdf,.pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.docx,image/jpeg,.jpg,.jpeg,image/png,.png,application/json,.json"}
                  type="file"
                  multiple
                  disabled={uploadPending}
                  onChange={(event) => {
                    handleFilesSelected(event.target.files);
                    event.target.value = "";
                  }}
                  className="sv-input file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-sm file:font-bold file:text-on-primary"
                />
                <small className="text-secondary">{isGlossary ? "Select multiple PDFs up to 50 MB each. Tables and lines such as “AD — Assistant Director” are supported." : "Select multiple PDF, DOCX, JPG, PNG, or JSON files, up to 50 MB each. Every file receives its own ingestion job."}</small>
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
                        className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded text-secondary hover:bg-surface hover:text-on-surface disabled:opacity-50"
                        aria-label={`Remove ${file.name}`}
                      >
                        <X size={15} />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
              {selectionError ? <InlineMessage tone="warning">{selectionError}</InlineMessage> : null}
              {!isGlossary ? (
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
              ) : null}
              {isGlossary ? (
                <label className="sv-field mt-4">
                  <span className="sv-label">Import action</span>
                  <select disabled={uploadPending || pdfDraft.files.length > 1} value={pdfDraft.supersedesText} onChange={(event) => onPdfDraftChange({ supersedesText: event.target.value })} className="sv-input">
                    <option value="">Add as new PDF source</option>
                    {currentGlossarySources.map((source) => <option key={source.document_id} value={source.document_id}>Replace {source.document_title}</option>)}
                  </select>
                  <small className="text-secondary">Replacement is available when one PDF is selected. Other active sources remain unchanged.</small>
                </label>
              ) : null}
              <label className="sv-field mt-4">
                <span className="sv-label">Description</span>
                <textarea disabled={uploadPending} value={pdfDraft.description} onChange={(event) => onPdfDraftChange({ description: event.target.value })} placeholder={isGlossary ? "Optional context about the source or terminology standard" : "Optional shared context for library display and reviewer notes"} className="sv-input min-h-24" />
                <small className="text-secondary">{isGlossary ? "Optional context for the imported PDF." : "Shared context appears with the document for reviewers and library users."}</small>
              </label>
              {groupsQuery.isError && canLoadSpaceDirectory ? <InlineMessage tone="error">{errorMessage(groupsQuery.error, isGlossary ? "Unable to prepare PDF storage." : "Unable to load writable Knowledge Spaces.")}</InlineMessage> : null}
              {!groupsQuery.isLoading && writableSpacePaths.length === 0 ? <InlineMessage tone="warning">{isGlossary ? "PDF import is unavailable until document storage is configured. Direct editing remains available below." : "No writable Knowledge Spaces are available for this account."}</InlineMessage> : null}
              <button type="submit" disabled={uploadPending || pdfDraft.files.length === 0 || !selectedSpaceIsWritable || !selectedSharedSpacesAreValid} className="sv-action-primary mt-5 w-full">
                {uploadPending ? <Loader2 className="animate-spin" size={18} /> : <CloudUpload size={18} />}
                {uploadPending
                  ? isGlossary ? "Queueing glossary" : "Queueing selected documents"
                  : pdfDraft.files.length === 0
                    ? isGlossary ? "Select glossary PDFs" : "Select documents to upload"
                    : isGlossary
                      ? pdfDraft.supersedesText ? "Replace PDF source" : `Add ${pdfDraft.files.length} PDF source${pdfDraft.files.length === 1 ? "" : "s"}`
                      : `Upload ${pdfDraft.files.length} document${pdfDraft.files.length === 1 ? "" : "s"}`}
              </button>
              {batchItems.length > 0 ? (
                <BatchUploadStatus
                  cancelingJobId={cancelingJobId}
                  currentUser={currentUser}
                  graphStatus={graphStatusQuery.data}
                  graphStatusError={graphStatusError}
                  hideGovernance={isGlossary}
                  items={batchItems}
                  onCancelIngestJob={onCancelIngestJob}
                  onClearUploadJobs={onClearUploadJobs}
                  onRetryIngestJob={(item) => retryMutation.mutate(item)}
                  onViewActivity={() => onNavigate("ingestion-jobs")}
                  retryingJobId={retryMutation.isPending ? retryMutation.variables?.job?.jobId ?? null : null}
                />
              ) : null}
            </form>

            {!isGlossary ? <aside className="upload-guidance space-y-4">
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
            </aside> : null}
          </div>
          </IntakeContainer>
        </div>
      </main>
    </PrudentiaWorkspace>
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
type Props = {
  batchItems: UploadBatchItemView[]; cancelingJobId: string | null; currentDocuments: Document[]; currentUser: AuthUser;
  mode?: "documents" | "glossary";
  onCancelIngestJob: (jobId: string) => void; onClearUploadJobs: (itemIds: string[]) => void; onLogout: () => void; onNavigate: (route: RouteId) => void; onPdfDraftChange: (patch: Partial<PdfUploadDraft>) => void;
  onPdfSubmit: (event: FormEvent<HTMLFormElement>) => void; pdfDraft: PdfUploadDraft; selectionError: string | null; uploadPending: boolean;
};
