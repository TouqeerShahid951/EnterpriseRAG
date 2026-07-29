import type { ClearanceLevel, DocType, ISODateString } from "./common";
import type { DocumentIngestStatus } from "./ingestion";

export interface Document {
  id: string;
  title: string;
  doc_type: DocType | null;
  group_path: string;
  owner_group_path: string;
  shared_group_paths: string[];
  access_group_paths: string[];
  governance_owner: "space" | "system";
  clearance_level: ClearanceLevel;
  effective_date: ISODateString | null;
  expiry_date: ISODateString | null;
  description: string | null;
  summary: string | null;
  language: string | null;
  topics: string[];
  llm_topics: string[];
  auto_doc_type: string | null;
  extracted_dates: Record<string, unknown>;
  metadata_flags: Record<string, unknown>;
  entities: DocumentEntity[];
  cross_references: DocumentCrossReference[];
  claims: DocumentClaim[];
  is_current: boolean;
  ingest_status: DocumentIngestStatus;
  uploaded_by: string;
  superseded_by: string | null;
  deleted_at: ISODateString | null;
  created_at: ISODateString | null;
}

export interface DocumentGroupCount {
  group_path: string;
  count: number;
}

export interface DocumentCatalogSummary {
  groups: DocumentGroupCount[];
  total: number;
}

interface DocumentOverviewAttentionItem {
  id: string;
  title: string;
  group_path: string;
  ingest_status: DocumentIngestStatus;
}

export interface DocumentOverviewSpace {
  group_path: string;
  library_documents: number;
  current_versions: number;
  processing_current: number;
  review_current: number;
  failed_current: number;
  unknown_current: number;
}

export interface DocumentOverview {
  library_documents: number;
  current_versions: number;
  indexed_current: number;
  processing_current: number;
  review_current: number;
  failed_current: number;
  unknown_current: number;
  needs_attention: number;
  superseded_versions: number;
  expiring_soon_current: number;
  trash: number;
  attention_documents: DocumentOverviewAttentionItem[];
  spaces: DocumentOverviewSpace[];
}

interface DocumentEntity {
  text: string;
  type: string;
  start: number | null;
  end: number | null;
}

interface DocumentCrossReference {
  ref_text: string;
  ref_type: string;
  position: number | null;
}

interface DocumentClaim {
  id: string | null;
  chunk_id: string;
  entity: string;
  attribute: string;
  value: string;
}

interface VersionNode {
  id: string;
  effective_date: ISODateString | null;
  is_current: boolean;
  superseded_by: string | null;
}

export interface VersionChainResponse {
  document_id: string;
  chain: VersionNode[];
}

export interface DeleteDocumentResponse {
  id: string;
  status: "soft_deleted" | "permanently_deleted";
}

export interface DocumentReingestResponse {
  document_id: string;
  job_id: string;
  status: "queued";
}

export interface DocumentReingestRequest {
  retry_of_job_id?: string | null;
}

export interface DocumentGraphEnrichmentResponse {
  document_id: string;
  job_id: string;
  status: "queued";
  message: string;
}

export interface DocumentSharesResponse {
  document_id: string;
  owner_group_path: string;
  shared_group_paths: string[];
  access_group_paths: string[];
  governance_owner: "space" | "system";
}

export interface Group {
  path: string;
  name: string;
  children: Group[];
}
