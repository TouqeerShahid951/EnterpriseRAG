import { defaultClearanceLevel } from "../authz";
import type { PdfUploadDraft } from "../types/chat";
export const defaultPdfUploadDraft: PdfUploadDraft = {
  files: [],
  groupPath: "",
  sharedGroupPaths: [],
  clearanceLevel: defaultClearanceLevel,
  effectiveDate: "",
  expiryDate: "",
  description: "",
  supersedesText: "",
};
