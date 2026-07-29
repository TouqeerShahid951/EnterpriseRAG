import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { ingestJobsApi, uploadApi, type UploadDocumentRequest } from "@/lib/api/contracts";
import type { IngestJob, User as AuthUser } from "@/types/api";
import type { PdfUploadDraft, UploadBatchItemView } from "@/types/chat";
import { defaultPdfUploadDraft } from "./defaults";
import { createId } from "@/lib/utils/ids";
import { ABBREVIATION_GLOSSARY_DOC_TYPE, toUploadRequests, validateDocumentFiles, validateGlossaryPdfFiles } from "./pdfUploadBatch";
import { isUploadTerminalStatus, toUploadJobView, uploadItemNeedsAttention } from "./uploadJobProgress";

const RECENT_UPLOAD_JOB_LIMIT = 100;
const DISMISSED_UPLOAD_JOB_LIMIT = 100;

export function usePdfUpload(currentUser: AuthUser | null, enabled = true, docType: string | null = null) {
  const queryClient = useQueryClient();
  const [pdfDraft, setPdfDraft] = useState<PdfUploadDraft>(defaultPdfUploadDraft);
  const [submissions, setSubmissions] = useState<UploadSubmission[]>([]);
  const [hiddenItemIds, setHiddenItemIds] = useState<Set<string>>(() => new Set());
  const [selectionError, setSelectionError] = useState<string | null>(null);

  useEffect(() => {
    setSubmissions([]);
    setHiddenItemIds(readDismissedUploadJobIds(currentUser?.user_id));
  }, [currentUser?.user_id]);

  useEffect(() => {
    setPdfDraft(defaultPdfUploadDraft);
    setSelectionError(null);
  }, [docType]);

  const uploadMutation = useMutation({
    mutationFn: async (batch: PreparedUpload[]) => {
      await Promise.all(
        batch.map(async ({ id, request }) => {
          try {
            const response = await uploadApi.document(request);
            setSubmissions((current) => current.map((item) => (
              item.id === id ? { ...item, jobId: response.job_id, uploadError: null } : item
            )));
          } catch (error) {
            setSubmissions((current) => current.map((item) => (
              item.id === id ? { ...item, uploadError: normalizeError(error) } : item
            )));
          }
        }),
      );
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["ingest-jobs"] });
    },
  });

  const cancelJobMutation = useMutation({
    mutationFn: (jobId: string) => ingestJobsApi.cancel(jobId),
    onSettled: (_data, _error, jobId) => {
      void queryClient.invalidateQueries({ queryKey: ["upload", "status", jobId] });
      void queryClient.invalidateQueries({ queryKey: ["ingest-jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["review-queue"] });
    },
  });

  const recentUploadJobsQuery = useQuery({
    queryKey: ["ingest-jobs", "recent-uploads", "mine", currentUser?.user_id],
    queryFn: () => ingestJobsApi.list({ uploaded_by_me: true, limit: RECENT_UPLOAD_JOB_LIMIT, offset: 0 }),
    enabled: Boolean(currentUser) && enabled && uploadHistoryBelongsOnPage(docType),
    refetchInterval: (query) => query.state.data?.items?.some((job) => !isUploadTerminalStatus(job.status)) ? 2500 : false,
    retry: false,
    staleTime: 1000,
  });

  const jobQueries = useQueries({
    queries: submissions.map((submission) => ({
      queryKey: ["upload", "status", submission.jobId],
      queryFn: () => uploadApi.status(submission.jobId ?? ""),
      enabled: Boolean(submission.jobId),
      refetchInterval: (query: { state: { data?: { status?: Parameters<typeof isUploadTerminalStatus>[0] } } }) => (
        isUploadTerminalStatus(query.state.data?.status) ? false : 2000
      ),
      retry: false,
    })),
  });

  const completedJobKey = jobQueries
    .map((query, index) => query.data?.status === "complete" ? submissions[index]?.jobId : null)
    .filter(Boolean)
    .join(",");

  useEffect(() => {
    if (completedJobKey) {
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["ingest-jobs"] });
    }
  }, [completedJobKey, queryClient]);

  function updatePdfDraft(patch: Partial<PdfUploadDraft>) {
    if (patch.files) {
      const validation = docType === ABBREVIATION_GLOSSARY_DOC_TYPE
        ? validateGlossaryPdfFiles(patch.files)
        : validateDocumentFiles(patch.files);
      setSelectionError(validation.rejectedMessages.join(" ") || null);
      setPdfDraft((current) => ({
        ...current,
        ...patch,
        files: validation.accepted,
        supersedesText: validation.accepted.length === 1 ? current.supersedesText : "",
      }));
      return;
    }
    setPdfDraft((current) => ({ ...current, ...patch }));
  }

  function handlePdfSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const requests = toUploadRequests(pdfDraft, docType);
    if (requests.length === 0) return;

    const batch = requests.map((request) => ({ id: createId("upload"), request }));
    setSubmissions((current) => [
      ...batch.map(({ id, request }) => ({
        id,
        fileName: request.file.name,
        fileSize: request.file.size,
        groupPath: request.group_path,
        clearanceLevel: request.clearance_level ?? pdfDraft.clearanceLevel,
        docType,
        jobId: null,
        uploadError: null,
      })),
      ...current,
    ]);
    setPdfDraft((current) => ({ ...current, files: [], supersedesText: "" }));
    setSelectionError(null);
    event.currentTarget.reset();
    uploadMutation.mutate(batch);
  }

  const submissionItems: UploadBatchItemView[] = submissions.flatMap((submission, index) => {
    if (submission.docType !== docType) return [];
    const query = jobQueries[index];
    return [{
      id: submission.id,
      fileName: submission.fileName,
      fileSize: submission.fileSize,
      groupPath: submission.groupPath,
      clearanceLevel: submission.clearanceLevel,
      isCurrentSession: true,
      requestState: submission.uploadError ? "failed" : submission.jobId ? "accepted" : "uploading",
      job: submission.jobId ? toUploadJobView(submission.jobId, query?.data) : null,
      uploadError: submission.uploadError,
      jobError: query?.error ?? null,
    }];
  });
  const submissionJobIds = new Set(submissions.map((submission) => submission.jobId).filter(Boolean));
  const recentJobs = (recentUploadJobsQuery.data?.items ?? [])
    .filter((job) => job.origin === "upload" || job.retry_of_job_id);
  const retriedJobIds = new Set(recentJobs.map((job) => job.retry_of_job_id).filter(Boolean));
  const backendItems = recentJobs
    .filter((job) => !submissionJobIds.has(job.job_id) && !retriedJobIds.has(job.job_id))
    .map(ingestJobToUploadBatchItem);
  const batchItems = [...submissionItems, ...backendItems].filter((item) => !hiddenItemIds.has(item.id));

  function clearUploadJobs(itemIds: string[]) {
    setHiddenItemIds((current) => new Set([...current, ...itemIds]));
    if (!currentUser) return;
    const selectedIds = new Set(itemIds);
    const attentionIds = batchItems
      .filter((item) => selectedIds.has(item.id) && uploadItemNeedsAttention(item))
      .map((item) => item.id);
    if (attentionIds.length > 0) {
      writeDismissedUploadJobIds(currentUser.user_id, [
        ...readDismissedUploadJobIds(currentUser.user_id),
        ...attentionIds,
      ]);
    }
  }

  return {
    batchItems,
    cancelingJobId: cancelJobMutation.isPending ? cancelJobMutation.variables ?? null : null,
    cancelJob: (jobId: string) => cancelJobMutation.mutate(jobId),
    clearUploadJobs,
    onPdfSubmit: handlePdfSubmit,
    pdfDraft,
    selectionError,
    updatePdfDraft,
    uploadMutation,
  };
}

interface PreparedUpload {
  id: string;
  request: UploadDocumentRequest;
}

export interface UploadSubmission {
  id: string;
  fileName: string;
  fileSize: number;
  groupPath: string;
  clearanceLevel: UploadSubmissionClearanceLevel;
  docType: string | null;
  jobId: string | null;
  uploadError: Error | null;
}

type UploadSubmissionClearanceLevel = PdfUploadDraft["clearanceLevel"];

export function uploadHistoryBelongsOnPage(docType: string | null): boolean {
  return docType !== ABBREVIATION_GLOSSARY_DOC_TYPE;
}

function normalizeError(error: unknown): Error {
  return error instanceof Error ? error : new Error("Document upload failed.");
}

export function ingestJobToUploadBatchItem(job: IngestJob): UploadBatchItemView {
  return {
    id: job.job_id,
    fileName: job.document_title,
    fileSize: null,
    groupPath: job.group_path,
    clearanceLevel: job.clearance_level,
    isCurrentSession: false,
    requestState: "accepted",
    job: toUploadJobView(job.job_id, job),
    uploadError: null,
    jobError: null,
  };
}

export function parseDismissedUploadJobIds(value: string | null): Set<string> {
  if (!value) return new Set();
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((item): item is string => typeof item === "string").slice(-DISMISSED_UPLOAD_JOB_LIMIT));
  } catch {
    return new Set();
  }
}

function readDismissedUploadJobIds(userId: string | undefined): Set<string> {
  if (!userId || typeof window === "undefined") return new Set();
  try {
    return parseDismissedUploadJobIds(window.localStorage.getItem(dismissedUploadJobStorageKey(userId)));
  } catch {
    return new Set();
  }
}

function writeDismissedUploadJobIds(userId: string, itemIds: string[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      dismissedUploadJobStorageKey(userId),
      JSON.stringify(Array.from(new Set(itemIds)).slice(-DISMISSED_UPLOAD_JOB_LIMIT)),
    );
  } catch {
    // Dismissal persistence is optional; the current page still updates.
  }
}

function dismissedUploadJobStorageKey(userId: string): string {
  return `Prudentia-dismissed-upload-jobs:${userId}`;
}
