export const DOCUMENT_UPLOAD_MAX_BYTES = 50 * 1024 * 1024;

export function isSupportedDocumentFile(file: File): boolean {
  return (
    file.type === "application/pdf"
    || file.type === "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    || file.type === "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    || file.type === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    || file.type === "text/csv"
    || file.type === "image/jpeg"
    || file.type === "image/png"
    || file.type === "application/json"
    || isSupportedDocumentName(file.name)
  );
}

export function isSupportedDocumentName(value: string): boolean {
  const name = value.toLowerCase();
  return [".pdf", ".docx", ".pptx", ".csv", ".xlsx", ".jpg", ".jpeg", ".png", ".json"]
    .some((extension) => name.endsWith(extension));
}
