import { FileText } from "lucide-react";

import { InlineMessage } from "@/components/layout/Common";
import { Modal } from "@/components/layout/Modal";
import {
  connectorTypeLabel,
  formatDateTime,
  schemaSnapshotTables,
  type ConnectorSchemaSnapshotViewerState,
} from "@/features/connectors/utils/connectorPanelUtils";

export function SchemaSnapshotModal({ onClose, viewer }: SchemaSnapshotModalProps) {
  const snapshot = viewer?.snapshot ?? null;
  const profile = viewer?.profile ?? null;
  const tables = snapshot ? schemaSnapshotTables(snapshot.schema_json) : [];
  const columnCount = tables.reduce((total, table) => total + table.columns.length, 0);
  const relationshipCount = tables.reduce((total, table) => total + table.foreignKeys.length, 0);
  const indexCount = tables.reduce((total, table) => total + table.indexes.length, 0);
  const visibleTables = tables.slice(0, 12);

  return (
    <Modal
      description="Review the latest raw schema captured from the connector before preparing a database access review."
      icon={<FileText size={18} />}
      onClose={onClose}
      open={Boolean(viewer)}
      size="lg"
      title="Schema Snapshot"
    >
      {snapshot ? (
        <section className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="sv-label">{profile?.name ?? connectorTypeLabel(snapshot.connector_type)}</p>
              <p className="mt-1 text-body-md text-on-surface-variant">
                {connectorTypeLabel(snapshot.connector_type)} introspection {snapshot.created_at ? `captured ${formatDateTime(snapshot.created_at)}` : "captured now"}.
              </p>
            </div>
            <span className={snapshot.status === "ok" ? "sv-pill sv-pill-success" : "sv-pill"}>
              {snapshot.status}
            </span>
          </div>

          {snapshot.status !== "ok" ? (
            <InlineMessage tone="error">{snapshot.error_message ?? "Schema introspection failed."}</InlineMessage>
          ) : (
            <>
              <dl className="grid gap-3 md:grid-cols-4">
                <SchemaSnapshotMetric label="Tables" value={tables.length.toString()} />
                <SchemaSnapshotMetric label="Columns" value={columnCount.toString()} />
                <SchemaSnapshotMetric label="Relationships" value={relationshipCount.toString()} />
                <SchemaSnapshotMetric label="Indexes" value={indexCount.toString()} />
              </dl>

              {tables.length === 0 ? (
                <InlineMessage tone="warning">The connector returned no tables in this schema snapshot.</InlineMessage>
              ) : (
                <div className="space-y-2">
                  {visibleTables.map((table) => (
                    <details key={table.key} className="rounded-md border border-surface-border bg-surface px-3 py-2">
                      <summary className="cursor-pointer text-body-md font-bold text-on-surface">
                        {table.key}
                        <span className="ml-2 text-label-md font-normal text-secondary">
                          {table.columns.length} column{table.columns.length === 1 ? "" : "s"}
                          {table.estimatedRowCount !== null ? `, ${table.estimatedRowCount} estimated rows` : ""}
                        </span>
                      </summary>
                      <div className="mt-3 space-y-3">
                        {table.columns.length > 0 ? (
                          <div className="grid gap-2 md:grid-cols-2">
                            {table.columns.slice(0, 16).map((column) => (
                              <span key={`${table.key}.${column.name}`} className="rounded-md border border-surface-border bg-surface-container-low px-2 py-1 text-label-md text-on-surface">
                                <strong>{column.name}</strong>
                                <span className="text-secondary"> {column.type}</span>
                              </span>
                            ))}
                          </div>
                        ) : (
                          <p className="text-body-md text-secondary">No columns were returned for this table.</p>
                        )}
                        {table.columns.length > 16 ? <p className="text-label-md text-secondary">Showing 16 of {table.columns.length} columns.</p> : null}
                        {table.primaryKeys.length > 0 ? <p className="text-label-md text-secondary">Primary key: {table.primaryKeys.join(", ")}</p> : null}
                        {table.foreignKeys.length > 0 ? <p className="text-label-md text-secondary">Foreign keys: {table.foreignKeys.map((key) => key.name || key.referencedTable).join(", ")}</p> : null}
                        {table.indexes.length > 0 ? <p className="text-label-md text-secondary">Indexes: {table.indexes.map((index) => index.name).filter(Boolean).join(", ")}</p> : null}
                      </div>
                    </details>
                  ))}
                  {tables.length > visibleTables.length ? (
                    <p className="text-label-md text-secondary">Showing {visibleTables.length} of {tables.length} tables. Prepare a review to choose the tables, columns, and joins Live DB may use.</p>
                  ) : null}
                </div>
              )}

              <details className="rounded-md border border-surface-border bg-surface px-3 py-2">
                <summary className="cursor-pointer text-label-md font-bold text-on-surface">Raw schema JSON</summary>
                <pre className="mt-3 max-h-80 overflow-auto rounded-md bg-surface-container-low p-3 text-xs text-on-surface">
                  {JSON.stringify(snapshot.schema_json, null, 2)}
                </pre>
              </details>
            </>
          )}
        </section>
      ) : null}
    </Modal>
  );
}

function SchemaSnapshotMetric({ label, value }: SchemaSnapshotMetricProps) {
  return (
    <div className="rounded-md border border-surface-border bg-surface px-3 py-2">
      <dt className="text-label-md font-bold uppercase tracking-wide text-secondary">{label}</dt>
      <dd className="mt-1 text-body-lg font-extrabold text-on-surface">{value}</dd>
    </div>
  );
}

export type SchemaSnapshotModalProps = {
  onClose: () => void;
  viewer: ConnectorSchemaSnapshotViewerState | null;
};

type SchemaSnapshotMetricProps = {
  label: string;
  value: string;
};
