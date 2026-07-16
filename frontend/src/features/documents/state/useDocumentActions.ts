import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/feedback/ToastProvider";
import {
  confirmDocumentAction,
  runBounded,
  type DocumentAction,
} from "@/features/documents/utils/documentPageUtils";
import { documentsApi, ingestJobsApi } from "@/lib/api/contracts";
import { clearanceLevelLabel } from "@/lib/auth/authz";
import { errorMessage } from "@/lib/utils/format";
import type { GraphEnrichmentTask } from "@/features/upload/state/uploadJobProgress";
import type { ClearanceLevel, Document } from "@/types/api";

type UseDocumentActionsOptions = {
  onDocumentRemoved: () => void;
  onSelectionCleared: () => void;
};

export function useDocumentActions({ onDocumentRemoved, onSelectionCleared }: UseDocumentActionsOptions) {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [pendingIds, setPendingIds] = useState<Set<string>>(() => new Set());

  function markPending(document: Document) {
    setPendingIds((current) => new Set([...current, document.id]));
  }

  function clearPending(document: Document) {
    setPendingIds((current) => {
      const next = new Set(current);
      next.delete(document.id);
      return next;
    });
  }

  async function refreshDocuments() {
    await queryClient.invalidateQueries({ queryKey: ["documents"] });
  }

  function refreshDocumentGovernance(documentId: string) {
    void refreshDocuments();
    void queryClient.invalidateQueries({ queryKey: ["documents", "detail", documentId] });
    void queryClient.invalidateQueries({ queryKey: ["documents", "shares", documentId] });
  }

  const updateDocumentClearanceMutation = useMutation({
    mutationFn: ({ clearanceLevel, document }: DocumentClearanceMutation) =>
      documentsApi.updateClearance(document.id, { clearance_level: clearanceLevel }),
    onMutate: ({ document }) => markPending(document),
    onSuccess: (updated) => {
      notify({
        title: "Document clearance updated",
        description: `${updated.title} is now ${clearanceLevelLabel(updated.clearance_level)}.`,
        tone: "success",
      });
      void refreshDocuments();
    },
    onError: (error) => notify({
      title: "Clearance update failed",
      description: errorMessage(error, "Unable to update document clearance."),
      tone: "error",
    }),
    onSettled: (_data, _error, variables) => {
      if (variables) clearPending(variables.document);
    },
  });

  const updateDocumentTopicsMutation = useMutation({
    mutationFn: ({ document, topics }: DocumentTopicsMutation) =>
      documentsApi.updateTopics(document.id, { topics, llm_topics: [] }),
    onMutate: ({ document }) => markPending(document),
    onSuccess: (updated) => {
      notify({
        title: "Document topics updated",
        description: `${updated.title} now has ${updated.topics.length} topic${updated.topics.length === 1 ? "" : "s"}.`,
        tone: "success",
      });
      void refreshDocuments();
    },
    onError: (error) => notify({
      title: "Topic update failed",
      description: errorMessage(error, "Unable to update document topics."),
      tone: "error",
    }),
    onSettled: (_data, _error, variables) => {
      if (variables) clearPending(variables.document);
    },
  });

  const updateDocumentSharesMutation = useMutation({
    mutationFn: ({ document, groupPaths }: DocumentSharesMutation) =>
      documentsApi.updateShares(document.id, { group_paths: groupPaths }),
    onMutate: ({ document }) => markPending(document),
    onSuccess: (shares, { document }) => {
      notify({
        title: "Document sharing updated",
        description: `${document.title} is shared with ${shares.shared_group_paths.length} Knowledge Space${shares.shared_group_paths.length === 1 ? "" : "s"}.`,
        tone: "success",
      });
      refreshDocumentGovernance(document.id);
    },
    onError: (error) => notify({
      title: "Sharing update failed",
      description: errorMessage(error, "Unable to update document sharing."),
      tone: "error",
    }),
    onSettled: (_data, _error, variables) => {
      if (variables) clearPending(variables.document);
    },
  });

  const transferDocumentOwnerMutation = useMutation({
    mutationFn: ({ document, groupPath }: DocumentOwnerTransferMutation) =>
      documentsApi.transferOwnership(document.id, { group_path: groupPath }),
    onMutate: ({ document }) => markPending(document),
    onSuccess: (updated, { document }) => {
      notify({
        title: "Document ownership transferred",
        description: `${updated.title} now belongs to ${updated.owner_group_path}.`,
        tone: "success",
      });
      refreshDocumentGovernance(document.id);
      void queryClient.invalidateQueries({ queryKey: ["ingest-jobs"] });
    },
    onError: (error) => notify({
      title: "Ownership transfer failed",
      description: errorMessage(error, "Unable to transfer document ownership."),
      tone: "error",
    }),
    onSettled: (_data, _error, variables) => {
      if (variables) clearPending(variables.document);
    },
  });

  const unshareDocumentMutation = useMutation({
    mutationFn: ({ document, groupPath }: DocumentUnshareMutation) =>
      documentsApi.unshare(document.id, { group_path: groupPath }),
    onMutate: ({ document }) => markPending(document),
    onSuccess: (_shares, { document, groupPath }) => {
      notify({
        title: "Knowledge Space removed",
        description: `${groupPath} no longer has shared access.`,
        tone: "success",
      });
      refreshDocumentGovernance(document.id);
    },
    onError: (error) => notify({
      title: "Unshare failed",
      description: errorMessage(error, "Unable to remove document sharing."),
      tone: "error",
    }),
    onSettled: (_data, _error, variables) => {
      if (variables) clearPending(variables.document);
    },
  });

  const graphEnrichmentMutation = useMutation({
    mutationFn: (document: Document) => documentsApi.enrichGraph(document.id),
    onSuccess: async (response, document) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ingest-jobs", "graphrag-status"] }),
        queryClient.invalidateQueries({ queryKey: ["audit-log"] }),
      ]);
      notify({
        title: "Graph enrichment queued",
        description: `${document.title} queued as graph task for job ${response.job_id}.`,
        tone: "success",
      });
    },
    onError: (error) => notify({
      title: "Graph enrichment not queued",
      description: errorMessage(error, "Unable to queue graph enrichment."),
      tone: "error",
    }),
  });

  const graphCancelMutation = useMutation({
    mutationFn: ({ task }: GraphCancelMutation) => {
      if (!task.jobId) throw new Error("Graph task is missing its ingestion job ID.");
      return ingestJobsApi.cancelGraphEnrichment(task.jobId, task.taskId);
    },
    onSuccess: async (response, { document }) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ingest-jobs", "graphrag-status"] }),
        queryClient.invalidateQueries({ queryKey: ["audit-log"] }),
      ]);
      notify({
        title: "Graph enrichment cancelled",
        description: `${document.title}: ${response.message}`,
        tone: "success",
      });
    },
    onError: (error) => notify({
      title: "Graph enrichment not cancelled",
      description: errorMessage(error, "Unable to cancel graph enrichment."),
      tone: "error",
    }),
  });

  async function performDocumentAction(action: DocumentAction, document: Document) {
    if (!confirmDocumentAction(action, [document])) return;
    await runDocumentActions(action, [document]);
  }

  async function performBulkAction(action: DocumentAction, documents: Document[]) {
    if (documents.length === 0 || !confirmDocumentAction(action, documents)) return;
    await runDocumentActions(action, documents);
  }

  async function runDocumentActions(action: DocumentAction, documents: Document[]) {
    setPendingIds((current) => new Set([...current, ...documents.map((document) => document.id)]));
    const results = await runBounded(documents, 4, async (document) => {
      await executeDocumentAction(action, document);
      return document;
    });
    setPendingIds((current) => {
      const next = new Set(current);
      documents.forEach((document) => next.delete(document.id));
      return next;
    });

    const failures = results.filter((result) => !result.ok);
    const successCount = results.length - failures.length;
    notify({
      title: failures.length ? "Document action partially failed" : "Documents updated",
      description: failures.length
        ? `${successCount} succeeded, ${failures.length} failed. ${failures[0]?.message ?? ""}`.trim()
        : `${successCount} document${successCount === 1 ? "" : "s"} updated.`,
      tone: failures.length ? "warning" : "success",
    });
    onSelectionCleared();
    if (action === "trash" || action === "permanent") onDocumentRemoved();
    await refreshDocuments();
  }

  return {
    cancelGraphEnrichment: (document: Document, task: GraphEnrichmentTask) =>
      graphCancelMutation.mutate({ document, task }),
    cancellingGraphTaskId: graphCancelMutation.isPending
      ? graphCancelMutation.variables?.task.taskId ?? null
      : null,
    enrichGraph: (document: Document) => graphEnrichmentMutation.mutate(document),
    enrichingDocumentId: graphEnrichmentMutation.isPending
      ? graphEnrichmentMutation.variables?.id ?? null
      : null,
    pendingIds,
    performBulkAction,
    performDocumentAction,
    transferDocumentOwner: (document: Document, groupPath: string) =>
      transferDocumentOwnerMutation.mutate({ document, groupPath }),
    unshareDocument: (document: Document, groupPath: string) =>
      unshareDocumentMutation.mutate({ document, groupPath }),
    updateDocumentClearance: (document: Document, clearanceLevel: ClearanceLevel) =>
      updateDocumentClearanceMutation.mutate({ document, clearanceLevel }),
    updateDocumentShares: (document: Document, groupPaths: string[]) =>
      updateDocumentSharesMutation.mutate({ document, groupPaths }),
    updateDocumentTopics: (document: Document, topics: string[]) =>
      updateDocumentTopicsMutation.mutate({ document, topics }),
  };
}

async function executeDocumentAction(action: DocumentAction, document: Document) {
  if (action === "reingest") return documentsApi.reingest(document.id);
  if (action === "trash") return documentsApi.remove(document.id);
  if (action === "restore") return documentsApi.restore(document.id);
  return documentsApi.permanentlyRemove(document.id);
}

type DocumentClearanceMutation = {
  clearanceLevel: ClearanceLevel;
  document: Document;
};

type DocumentTopicsMutation = {
  document: Document;
  topics: string[];
};

type DocumentSharesMutation = {
  document: Document;
  groupPaths: string[];
};

type DocumentOwnerTransferMutation = {
  document: Document;
  groupPath: string;
};

type DocumentUnshareMutation = {
  document: Document;
  groupPath: string;
};

type GraphCancelMutation = {
  document: Document;
  task: GraphEnrichmentTask;
};
