import type { UploadDocumentRequest } from "../api/contracts";
import type { PdfUploadDraft } from "../types/chat";

export const DOCUMENT_UPLOAD_MAX_BYTES = 50 * 1024 * 1024;

export interface DocumentFileValidation {
  accepted: File[];
  rejectedMessages: string[];
}

export function mergeDocumentFiles(current: File[], incoming: File[]): File[] {
  const merged = new Map<string, File>();
  for (const file of [...current, ...incoming]) {
    merged.set(fileKey(file), file);
  }
  return Array.from(merged.values());
}

export function validateDocumentFiles(files: File[]): DocumentFileValidation {
  const accepted: File[] = [];
  const rejectedMessages: string[] = [];

  for (const file of files) {
    if (!isSupportedDocumentFile(file)) {
      rejectedMessages.push(`${file.name} is not a PDF, DOCX, JPG, or PNG file.`);
      continue;
    }
    if (file.size === 0) {
      rejectedMessages.push(`${file.name} is empty.`);
      continue;
    }
    if (file.size > DOCUMENT_UPLOAD_MAX_BYTES) {
      rejectedMessages.push(`${file.name} exceeds the 50 MB upload limit.`);
      continue;
    }
    accepted.push(file);
  }

  return { accepted, rejectedMessages };
}

export function toUploadRequests(draft: PdfUploadDraft): UploadDocumentRequest[] {
  const supersedes = draft.files.length === 1
    ? draft.supersedesText
        .split(/[,\n]/)
        .map((value) => value.trim())
        .filter(Boolean)
    : [];

  return draft.files.map((file) => ({
    file,
    group_path: draft.groupPath.trim(),
    effective_date: draft.effectiveDate || null,
    expiry_date: draft.expiryDate || null,
    doc_type: draft.docType,
    description: draft.description.trim() || null,
    supersedes,
  }));
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isSupportedDocumentFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return (
    file.type === "application/pdf"
    || file.type === "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    || file.type === "image/jpeg"
    || file.type === "image/png"
    || name.endsWith(".pdf")
    || name.endsWith(".docx")
    || name.endsWith(".jpg")
    || name.endsWith(".jpeg")
    || name.endsWith(".png")
  );
}

function fileKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}
