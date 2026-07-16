import type { ConnectorSchemaCatalog } from "@/types/api";

export type AiDraftProgress = {
  catalogId: string;
  completed: number;
  currentTable: string | null;
  failed: number;
  total: number;
};

export type SchemaCatalogJson = Record<string, unknown> & {
  name?: string;
  tables?: SchemaCatalogTable[];
  relationships?: SchemaCatalogRelationship[];
  business_rules?: string[];
  ai_enrichment?: unknown;
};

export type SchemaCatalogTable = Record<string, unknown> & {
  key?: string;
  schema?: string;
  name?: string;
  allowed?: boolean;
  sensitive?: boolean;
  description?: string;
  synonyms?: string[];
  columns?: SchemaCatalogColumn[];
};

export type SchemaCatalogColumn = Record<string, unknown> & {
  name?: string;
  data_type?: string;
  allowed?: boolean;
  sensitive?: boolean;
  description?: string;
  synonyms?: string[];
};

export type SchemaCatalogRelationship = Record<string, unknown> & {
  name?: string;
  left_table?: string;
  left_columns?: string[];
  right_table?: string;
  right_columns?: string[];
  allowed?: boolean;
  description?: string;
  source?: string;
};

export type SchemaJoinDraft = {
  description: string;
  leftColumn: string;
  leftTable: string;
  rightColumn: string;
  rightTable: string;
};

export type SchemaCatalogFilter = "all" | "included" | "excluded" | "sensitive" | "missing";

export type SchemaCatalogReviewStats = {
  allowedColumns: number;
  allowedTables: number;
  excludedTables: number;
  missingDescriptions: number;
  sensitiveColumns: number;
  totalColumns: number;
  totalTables: number;
};

export function normalizeCatalogJson(value: Record<string, unknown>): SchemaCatalogJson {
  const tables = Array.isArray(value.tables) ? value.tables.filter(isSchemaCatalogTable).map((table) => ({
    ...table,
    columns: Array.isArray(table.columns) ? table.columns.filter(isSchemaCatalogColumn) : [],
    synonyms: Array.isArray(table.synonyms) ? table.synonyms.filter(isString) : [],
  })) : [];
  const relationships = Array.isArray(value.relationships) ? value.relationships.filter(isSchemaCatalogRelationship).map((relationship) => ({
    ...relationship,
    left_columns: Array.isArray(relationship.left_columns) ? relationship.left_columns.filter(isString) : [],
    right_columns: Array.isArray(relationship.right_columns) ? relationship.right_columns.filter(isString) : [],
  })) : [];
  const businessRules = Array.isArray(value.business_rules) ? value.business_rules.filter(isString) : [];
  return {
    ...value,
    name: typeof value.name === "string" ? value.name : "",
    tables,
    relationships,
    business_rules: businessRules,
    ai_enrichment: value.ai_enrichment,
  };
}

export function schemaCatalogAiEnrichmentStatus(value: Record<string, unknown>): string {
  const metadata = isRecord(value.ai_enrichment) ? value.ai_enrichment : {};
  return stringValue(metadata.status);
}

export function schemaCatalogAiEnrichmentError(value: Record<string, unknown>): string {
  const metadata = isRecord(value.ai_enrichment) ? value.ai_enrichment : {};
  return stringValue(metadata.error_message);
}

export function schemaCatalogPendingTableKeys(value: Record<string, unknown>): string[] {
  const metadata = isRecord(value.ai_enrichment) ? value.ai_enrichment : {};
  const statuses = Array.isArray(metadata.table_statuses) ? metadata.table_statuses.filter(isRecord) : [];
  if (statuses.length > 0) {
    return statuses
      .filter((item) => stringValue(item.status) !== "generated")
      .map((item) => stringValue(item.table_key))
      .filter(Boolean);
  }
  const catalog = normalizeCatalogJson(value);
  return (catalog.tables ?? []).filter(schemaCatalogTableNeedsEnrichment).map(schemaCatalogTableKey).filter(Boolean);
}

export function aiDraftProgressFromCatalog(catalog: ConnectorSchemaCatalog, currentTable: string | null): AiDraftProgress {
  const metadata = isRecord(catalog.catalog_json.ai_enrichment) ? catalog.catalog_json.ai_enrichment : {};
  const statuses = Array.isArray(metadata.table_statuses) ? metadata.table_statuses.filter(isRecord) : [];
  const total = statuses.length || (normalizeCatalogJson(catalog.catalog_json).tables ?? []).length;
  const failed = statuses.filter((item) => stringValue(item.status) === "failed").length;
  const completed = statuses.filter((item) => ["generated", "failed"].includes(stringValue(item.status))).length;
  return { catalogId: catalog.id, completed, currentTable, failed, total };
}

export function schemaCatalogTableKey(table: SchemaCatalogTable): string {
  if (typeof table.key === "string" && table.key.trim()) return table.key.trim().toLowerCase();
  const schema = typeof table.schema === "string" ? table.schema.trim() : "";
  const name = typeof table.name === "string" ? table.name.trim() : "";
  return `${schema ? `${schema}.` : ""}${name}`.toLowerCase();
}

export function schemaCatalogTableNeedsEnrichment(table: SchemaCatalogTable): boolean {
  if (!stringValue(table.description).trim()) return true;
  return (table.columns ?? []).some((column) => !stringValue(column.description).trim());
}

export function schemaCatalogReviewStats(catalog: SchemaCatalogJson): SchemaCatalogReviewStats {
  const stats: SchemaCatalogReviewStats = {
    allowedColumns: 0,
    allowedTables: 0,
    excludedTables: 0,
    missingDescriptions: 0,
    sensitiveColumns: 0,
    totalColumns: 0,
    totalTables: catalog.tables?.length ?? 0,
  };
  for (const table of catalog.tables ?? []) {
    const tableIncluded = table.allowed !== false && table.sensitive !== true;
    if (tableIncluded) stats.allowedTables += 1;
    else stats.excludedTables += 1;
    if (tableIncluded && !stringValue(table.description).trim()) stats.missingDescriptions += 1;
    for (const column of table.columns ?? []) {
      stats.totalColumns += 1;
      const columnIncluded = tableIncluded && column.allowed !== false && column.sensitive !== true;
      if (column.sensitive === true) stats.sensitiveColumns += 1;
      if (columnIncluded) stats.allowedColumns += 1;
      if (columnIncluded && !stringValue(column.description).trim()) stats.missingDescriptions += 1;
    }
  }
  return stats;
}

export function schemaCatalogApprovalWarnings(stats: SchemaCatalogReviewStats, ownerGroupPath: string): string[] {
  const warnings: string[] = [];
  if (!ownerGroupPath) warnings.push("Select an owner Knowledge Space before enabling Live DB access.");
  if (stats.allowedTables === 0) warnings.push("Include at least one table before enabling Live DB access.");
  if (stats.allowedColumns === 0) warnings.push("Include at least one column before enabling Live DB access.");
  if (stats.missingDescriptions > 0) warnings.push(`${stats.missingDescriptions} included schema item${stats.missingDescriptions === 1 ? "" : "s"} still need descriptions.`);
  return warnings;
}

export function schemaCatalogTableMatches(table: SchemaCatalogTable, search: string, filter: SchemaCatalogFilter): boolean {
  const tableIncluded = table.allowed !== false && table.sensitive !== true;
  const hasSensitive = table.sensitive === true || (table.columns ?? []).some((column) => column.sensitive === true);
  const matchesFilter =
    filter === "all" ||
    (filter === "included" && tableIncluded) ||
    (filter === "excluded" && !tableIncluded) ||
    (filter === "sensitive" && hasSensitive) ||
    (filter === "missing" && schemaCatalogTableNeedsEnrichment(table));
  if (!matchesFilter) return false;
  const query = search.trim().toLowerCase();
  if (!query) return true;
  return schemaCatalogTableSearchText(table).includes(query);
}

function schemaCatalogTableSearchText(table: SchemaCatalogTable): string {
  const parts = [
    table.key,
    table.schema,
    table.name,
    table.description,
    ...(table.synonyms ?? []),
  ];
  for (const column of table.columns ?? []) {
    parts.push(column.name, column.data_type, column.description, ...(column.synonyms ?? []));
  }
  return parts.map(stringValue).join(" ").toLowerCase();
}

export function schemaCatalogAllowedRelationships(relationships: SchemaCatalogRelationship[]): number {
  return relationships.filter((relationship) => relationship.allowed !== false).length;
}

export function schemaCatalogRelationshipLabel(relationship: SchemaCatalogRelationship): string {
  const leftColumns = (relationship.left_columns ?? []).join(", ");
  const rightColumns = (relationship.right_columns ?? []).join(", ");
  return `${relationship.left_table || "left table"}(${leftColumns || "columns"}) = ${relationship.right_table || "right table"}(${rightColumns || "columns"})`;
}

export function schemaCatalogRelationshipSource(relationship: SchemaCatalogRelationship): string {
  return stringValue(relationship.source);
}

export function schemaCatalogColumnsForTable(tables: SchemaCatalogTable[], tableKey: string): string[] {
  const table = tables.find((item) => schemaCatalogTableKey(item) === tableKey);
  return (table?.columns ?? []).map((column) => stringValue(column.name)).filter(Boolean);
}

export function schemaCatalogRelationshipMatchesDraft(relationship: SchemaCatalogRelationship, draft: SchemaJoinDraft): boolean {
  const leftTable = stringValue(relationship.left_table).toLowerCase();
  const rightTable = stringValue(relationship.right_table).toLowerCase();
  const leftColumns = (relationship.left_columns ?? []).map((column) => column.toLowerCase()).join(",");
  const rightColumns = (relationship.right_columns ?? []).map((column) => column.toLowerCase()).join(",");
  const draftLeftColumn = draft.leftColumn.toLowerCase();
  const draftRightColumn = draft.rightColumn.toLowerCase();
  return (
    leftTable === draft.leftTable &&
    rightTable === draft.rightTable &&
    leftColumns === draftLeftColumn &&
    rightColumns === draftRightColumn
  ) || (
    leftTable === draft.rightTable &&
    rightTable === draft.leftTable &&
    leftColumns === draftRightColumn &&
    rightColumns === draftLeftColumn
  );
}

export function schemaCatalogManualRelationshipName(draft: SchemaJoinDraft): string {
  return `manual_${draft.leftTable}_${draft.leftColumn}_${draft.rightTable}_${draft.rightColumn}`.replace(/[^a-zA-Z0-9_]+/g, "_");
}

export function emptySchemaJoinDraft(): SchemaJoinDraft {
  return { description: "", leftColumn: "", leftTable: "", rightColumn: "", rightTable: "" };
}

export function splitCommaList(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

export function uniqueGroupPaths(paths: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  paths.map((path) => path.trim()).filter(Boolean).forEach((path) => {
    if (seen.has(path)) return;
    seen.add(path);
    result.push(path);
  });
  return result;
}

export function catalogOwnerGroupPath(catalog: ConnectorSchemaCatalog): string {
  return catalog.owner_group_path || catalog.group_path;
}

export function catalogSharedGroupPaths(catalog: ConnectorSchemaCatalog): string[] {
  if (Array.isArray(catalog.shared_group_paths)) return uniqueGroupPaths(catalog.shared_group_paths);
  const raw = catalog.catalog_json.shared_group_paths;
  return Array.isArray(raw) ? uniqueGroupPaths(raw.filter(isString)) : [];
}

export function catalogScopeSummary(catalog: ConnectorSchemaCatalog): string {
  const owner = catalogOwnerGroupPath(catalog);
  const shared = catalogSharedGroupPaths(catalog);
  if (!shared.length) return owner;
  return `${owner} + ${shared.length} shared`;
}

export function latestConnectorCatalog(catalogs: ConnectorSchemaCatalog[]): ConnectorSchemaCatalog | null {
  return [...catalogs].sort((left, right) => catalogTimestamp(right).localeCompare(catalogTimestamp(left)))[0] ?? null;
}

function catalogTimestamp(catalog: ConnectorSchemaCatalog): string {
  return catalog.updated_at ?? catalog.created_at ?? "";
}

export function catalogAccessStateLabel(value: string): string {
  if (value === "approved") return "Enabled";
  if (value === "disabled") return "Disabled";
  return "Not enabled";
}

export function catalogAccessStateDescription(value: string): string {
  if (value === "approved") return "Live DB can answer from this approved review.";
  if (value === "disabled") return "Live DB will not use this review.";
  return "Save changes as a draft, then enable access when the review is ready.";
}

export function catalogAccessStateHint(value: string): string {
  if (value === "approved") return "Available to Live DB";
  if (value === "disabled") return "Disabled for Live DB";
  return "Review required";
}

export function catalogReviewLabel(value: string): string {
  if (value === "approved") return "Live access enabled";
  if (value === "reviewed") return "Reviewed";
  if (value === "disabled") return "Disabled";
  return "Needs review";
}

export function catalogReviewPillClass(value: string): string {
  if (value === "approved") return "sv-pill sv-pill-success";
  if (value === "disabled") return "sv-pill sv-pill-warning";
  if (value === "reviewed") return "sv-pill";
  return "sv-pill sv-pill-warning";
}

export function catalogAccessPillClass(value: string): string {
  if (value === "approved") return "sv-pill sv-pill-success";
  if (value === "disabled") return "sv-pill sv-pill-warning";
  return "sv-pill";
}

export function connectorSchemaAccessSummary(catalog: ConnectorSchemaCatalog): string {
  const catalogJson = normalizeCatalogJson(catalog.catalog_json);
  const stats = schemaCatalogReviewStats(catalogJson);
  const relationships = catalogJson.relationships ?? [];
  return `${stats.allowedTables}/${stats.totalTables} tables, ${stats.allowedColumns}/${stats.totalColumns} columns, ${schemaCatalogAllowedRelationships(relationships)}/${relationships.length} joins`;
}

function isSchemaCatalogTable(value: unknown): value is SchemaCatalogTable {
  return typeof value === "object" && value !== null;
}

function isSchemaCatalogColumn(value: unknown): value is SchemaCatalogColumn {
  return typeof value === "object" && value !== null;
}

function isSchemaCatalogRelationship(value: unknown): value is SchemaCatalogRelationship {
  return typeof value === "object" && value !== null;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function stringValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(stringValue).filter(Boolean).join(", ");
  return "";
}

export function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}
