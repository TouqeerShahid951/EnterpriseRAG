import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { uploadApi, type UploadDocumentRequest } from "../api/contracts";
import type { PdfUploadDraft, UploadBatchItemView } from "../types/chat";
import { defaultPdfUploadDraft } from "./defaults";
import { createId } from "./ids";
import { toUploadRequests, validateDocumentFiles } from "./pdfUploadBatch";
import { isUploadTerminalStatus, toUploadJobView } from "./uploadJobProgress";

export function usePdfUpload() {
  const queryClient = useQueryClient();
  const [pdfDraft, setPdfDraft] = useState<PdfUploadDraft>(defaultPdfUploadDraft);
  const [submissions, setSubmissions] = useState<UploadSubmission[]>([]);
  const [selectionError, setSelectionError] = useState<string | null>(null);

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
    },
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
    }
  }, [completedJobKey, queryClient]);

  function updatePdfDraft(patch: Partial<PdfUploadDraft>) {
    if (patch.files) {
      const validation = validateDocumentFiles(patch.files);
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
    const requests = toUploadRequests(pdfDraft);
    if (requests.length === 0) return;

    const batch = requests.map((request) => ({ id: createId("upload"), request }));
    setSubmissions((current) => [
      ...batch.map(({ id, request }) => ({
        id,
        file: request.file,
        groupPath: request.group_path,
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

  const batchItems: UploadBatchItemView[] = submissions.map((submission, index) => {
    const query = jobQueries[index];
    return {
      id: submission.id,
      fileName: submission.file.name,
      fileSize: submission.file.size,
      groupPath: submission.groupPath,
      requestState: submission.uploadError ? "failed" : submission.jobId ? "accepted" : "uploading",
      job: submission.jobId ? toUploadJobView(submission.jobId, query?.data) : null,
      uploadError: submission.uploadError,
      jobError: query?.error ?? null,
    };
  });

  return {
    batchItems,
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

interface UploadSubmission {
  id: string;
  file: File;
  groupPath: string;
  jobId: string | null;
  uploadError: Error | null;
}

function normalizeError(error: unknown): Error {
  return error instanceof Error ? error : new Error("Document upload failed.");
}
