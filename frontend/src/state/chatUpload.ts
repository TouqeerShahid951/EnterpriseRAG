import type { UploadDocumentRequest } from "../api/contracts";

export function buildChatUploadRequest(file: File, groupPath: string): UploadDocumentRequest {
  return {
    file,
    group_path: groupPath,
    doc_type: "other",
  };
}
