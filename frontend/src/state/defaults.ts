import { defaultClearanceLevel } from "../authz";
import type { PdfUploadDraft } from "../types/chat";
export const defaultPdfUploadDraft: PdfUploadDraft = {
  files: [],
  groupPath: "",
  clearanceLevel: defaultClearanceLevel,
  effectiveDate: "",
  expiryDate: "",
  description: "",
  supersedesText: "",
};
