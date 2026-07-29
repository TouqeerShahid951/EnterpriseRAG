import { identityFieldsFromDraft, summarizeFolderFiles, type FolderScheduleDraft } from "@/features/ingestion/state/folderIngest";
import type { ConnectorProfile, ConnectorSchemaCatalog, FolderSchedule } from "@/types/api";
import {
  connectorTypeLabel,
  type ConnectorProfileDraft,
} from "@/features/connectors/utils/connectorProfileUtils";
import { isRecord, numberValue, stringValue } from "@/features/connectors/utils/connectorCatalogUtils";

export type ConnectorWorkspaceTab = "connections" | "schema_reviews" | "live_access" | "diagnostics";
export type ConnectorMetricTone = "neutral" | "success" | "warning" | "danger";
export type ConnectorReviewTab = "summary" | "tables" | "joins" | "access" | "raw_schema";
export type ConnectorNextAction = "test" | "read_schema" | "review" | "live";
export type ConnectorFlowStep = 1 | 2 | 3 | 4;

const connectorFlowStepByAction: Record<ConnectorNextAction, ConnectorFlowStep> = {
  test: 1,
  read_schema: 2,
  review: 3,
  live: 4,
};

export type ConnectorWorkspaceCounts = {
  connections: number;
  diagnostics: number;
  liveAccess: number;
  schemaReviews: number;
};

export type ConnectorProfileEditorState = {
  profile: ConnectorProfile;
  draft: ConnectorProfileDraft;
};

export type ConnectorCatalogEditorState = {
  profile: ConnectorProfile;
  catalog: ConnectorSchemaCatalog;
};

export type ConnectorSchemaSnapshotViewerState = {
  profile: ConnectorProfile | null;
  snapshot: import("@/types/api").ConnectorSchemaSnapshot;
};

export type SchemaSnapshotTableSummary = {
  key: string;
  columns: SchemaSnapshotColumnSummary[];
  primaryKeys: string[];
  foreignKeys: SchemaSnapshotForeignKeySummary[];
  indexes: SchemaSnapshotIndexSummary[];
  estimatedRowCount: number | null;
};

type SchemaSnapshotColumnSummary = {
  name: string;
  type: string;
};

type SchemaSnapshotForeignKeySummary = {
  name: string;
  referencedTable: string;
};

type SchemaSnapshotIndexSummary = {
  name: string;
};

export function nextConnectorAction(profile: ConnectorProfile, catalog: ConnectorSchemaCatalog | null): ConnectorNextAction {
  if (profile.last_test_status !== "ok") return "test";
  if (!catalog) return "read_schema";
  return catalog.status === "approved" ? "live" : "review";
}

export function connectorFlowStep(profile: ConnectorProfile, catalog: ConnectorSchemaCatalog | null): ConnectorFlowStep {
  return connectorFlowStepByAction[nextConnectorAction(profile, catalog)];
}

export function validateDraft(draft: FolderScheduleDraft, selection: ReturnType<typeof summarizeFolderFiles>, writableSpacePaths: string[]): string | null {
  if (!draft.name.trim()) return "Enter a schedule name.";
  if (!draft.groupPath || !writableSpacePaths.includes(draft.groupPath)) return "Select a writable Knowledge Space.";
  if (draft.scheduleType === "one_time" && !draft.scheduledAt) return "Choose the one-time start time.";
  if (draft.scheduleType === "recurring" && draft.recurrenceDays.length === 0) return "Select at least one recurring day.";
  if (draft.sourceMode === "snapshot") {
    if (selection.entries.length === 0) return "Choose a folder snapshot.";
    if (selection.validationMessages.length > 0) return selection.validationMessages[0] ?? "Selected folder is invalid.";
  }
  if (draft.sourceMode === "local_folder" && !draft.folderPath.trim()) {
    return "Enter a watched folder path.";
  }
  if (draft.sourceMode === "connector") {
    if (!draft.connectorProfileId) return "Select a database connection.";
    if (!draft.connectorQuery.trim()) return "Enter a read-only SQL selection.";
    if (identityFieldsFromDraft(draft.connectorIdentityFields).length === 0) return "Enter at least one stable identity field.";
  }
  return null;
}

export function formatLatestRun(schedule: FolderSchedule): string {
  if (!schedule.latest_run) return "No runs";
  const run = schedule.latest_run;
  return `${run.status}: ${run.queued_count} queued, ${run.skipped_count} skipped`;
}

export function schemaSnapshotSummary(schemaJson: Record<string, unknown>): string {
  const tables = schemaSnapshotTables(schemaJson);
  const columnCount = tables.reduce((total, table) => total + table.columns.length, 0);
  return `${tables.length} table${tables.length === 1 ? "" : "s"} and ${columnCount} column${columnCount === 1 ? "" : "s"} found.`;
}

export function schemaSnapshotTables(schemaJson: Record<string, unknown>): SchemaSnapshotTableSummary[] {
  const rawTables = Array.isArray(schemaJson.tables) ? schemaJson.tables : Array.isArray(schemaJson.collections) ? schemaJson.collections : [];
  return rawTables.filter(isRecord).map((table, index) => {
    const schema = stringValue(table.schema);
    const name = stringValue(table.name) || stringValue(table.collection) || `table_${index + 1}`;
    const key = stringValue(table.key) || [schema, name].filter(Boolean).join(".") || name;
    const sampleMetadata = isRecord(table.sample_metadata) ? table.sample_metadata : {};
    const columns = Array.isArray(table.columns) ? table.columns.filter(isRecord).map((column, columnIndex) => ({
      name: stringValue(column.name) || `column_${columnIndex + 1}`,
      type: stringValue(column.type) || stringValue(column.data_type) || "unknown",
    })) : [];
    const primaryKeys = Array.isArray(table.primary_keys)
      ? table.primary_keys.map((item) => isRecord(item) ? stringValue(item.name) || stringValue(item.column) || stringValue(item.columns) : stringValue(item)).filter(Boolean)
      : [];
    const foreignKeys = Array.isArray(table.foreign_keys) ? table.foreign_keys.filter(isRecord).map((item) => ({
      name: stringValue(item.name),
      referencedTable: stringValue(item.referenced_table),
    })) : [];
    const indexes = Array.isArray(table.indexes) ? table.indexes.filter(isRecord).map((item) => ({
      name: stringValue(item.name),
    })) : [];

    return {
      key,
      columns,
      primaryKeys,
      foreignKeys,
      indexes,
      estimatedRowCount: numberValue(sampleMetadata.estimated_row_count ?? table.estimated_row_count),
    };
  });
}

export function sourceTypeLabel(schedule: FolderSchedule): string {
  if (schedule.source_type === "snapshot") return "Browser snapshot";
  if (schedule.source_type === "local_folder") return "Watched folder";
  if (schedule.source_type === "minio_prefix") return "S3/MinIO prefix";
  if (schedule.source_type === "connector") {
    const connectorType = typeof schedule.source_config.connector_type === "string" ? schedule.source_config.connector_type : "database";
    return connectorTypeLabel(connectorType);
  }
  return connectorTypeLabel(schedule.source_type);
}

export function connectorWorkspaceTabDetail(tab: ConnectorWorkspaceTab, counts: ConnectorWorkspaceCounts): string {
  if (tab === "connections") return `${counts.connections} saved`;
  if (tab === "schema_reviews") return `${counts.schemaReviews} prepared`;
  if (tab === "live_access") return `${counts.liveAccess} enabled`;
  return counts.diagnostics > 0 ? `${counts.diagnostics} issue${counts.diagnostics === 1 ? "" : "s"}` : "clear";
}

export function connectorWorkspaceTabCount(tab: ConnectorWorkspaceTab, counts: ConnectorWorkspaceCounts): string {
  if (tab === "connections") return counts.connections.toString();
  if (tab === "schema_reviews") return counts.schemaReviews.toString();
  if (tab === "live_access") return counts.liveAccess.toString();
  return counts.diagnostics.toString();
}

export * from "@/features/connectors/utils/connectorCatalogUtils";

export * from "@/features/connectors/utils/connectorProfileUtils";
