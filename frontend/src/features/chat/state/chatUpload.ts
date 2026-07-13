import type { UploadDocumentRequest } from "@/lib/api/contracts";

export function buildChatUploadRequest(file: File, groupPath: string): UploadDocumentRequest {
  return {
    file,
    group_path: groupPath,
  };
}
