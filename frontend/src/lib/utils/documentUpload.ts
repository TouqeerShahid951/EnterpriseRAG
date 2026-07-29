export const DOCUMENT_UPLOAD_MAX_BYTES = 50 * 1024 * 1024;

export function isSupportedDocumentFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return (
    file.type === "application/pdf"
    || file.type === "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    || file.type === "image/jpeg"
    || file.type === "image/png"
    || file.type === "application/json"
    || name.endsWith(".pdf")
    || name.endsWith(".docx")
    || name.endsWith(".jpg")
    || name.endsWith(".jpeg")
    || name.endsWith(".png")
    || name.endsWith(".json")
  );
}
