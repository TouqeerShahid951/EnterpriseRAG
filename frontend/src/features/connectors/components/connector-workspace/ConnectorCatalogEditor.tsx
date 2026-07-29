import { useEffect, useId, useMemo, useState } from "react";
import { CheckCircle2, Network, Plus, Search, ShieldAlert, Trash2, X } from "lucide-react";

import { InlineMessage } from "@/components/layout/Common";
import type { ClearanceLevel, ConnectorSchemaCatalogStatus } from "@/types/api";
import {
  catalogName,
  catalogOwnerGroupPath,
  catalogSharedGroupPaths,
  emptySchemaJoinDraft,
  normalizeCatalogJson,
  schemaCatalogAiEnrichmentError,
  schemaCatalogAiEnrichmentStatus,
  schemaCatalogAllowedRelationships,
  schemaCatalogApprovalWarnings,
  schemaCatalogColumnsForTable,
  schemaCatalogManualRelationshipName,
  schemaCatalogPendingTableKeys,
  schemaCatalogRelationshipLabel,
  schemaCatalogRelationshipMatchesDraft,
  schemaCatalogRelationshipSource,
  schemaCatalogReviewStats,
  schemaCatalogTableKey,
  schemaCatalogTableMatches,
  schemaCatalogTableNeedsEnrichment,
  splitCommaList,
  uniqueGroupPaths,
  type ConnectorReviewTab,
  type SchemaCatalogColumn,
  type SchemaCatalogFilter,
  type SchemaCatalogJson,
  type SchemaCatalogRelationship,
  type SchemaCatalogTable,
  type SchemaJoinDraft,
} from "@/features/connectors/utils/connectorPanelUtils";
import { ConnectorReviewTabs, SchemaReviewMetric } from "@/features/connectors/components/connector-workspace/ConnectorCatalogPrimitives";
import { CatalogAccessPanel, CatalogReviewActions } from "@/features/connectors/components/connector-workspace/ConnectorCatalogAccess";
import type { ConnectorCatalogEditorProps } from "@/features/connectors/components/connector-workspace/ConnectorCatalogEditor.types";

export type { ConnectorCatalogEditorProps } from "@/features/connectors/components/connector-workspace/ConnectorCatalogEditor.types";

const guidedReviewTabs: ConnectorReviewTab[] = ["summary", "tables", "joins", "access"];


export function ConnectorCatalogEditor({ catalog, clearanceOptions, isSaving, mutationError, onClose, onContinueAiEnrichment, onSave, profile, writableSpacePaths }: ConnectorCatalogEditorProps) {
  const reviewTabsId = useId();
  const [draftJson, setDraftJson] = useState<SchemaCatalogJson>(() => normalizeCatalogJson(catalog.catalog_json));
  const [ownerGroupPath, setOwnerGroupPath] = useState(catalogOwnerGroupPath(catalog));
  const [sharedGroupPaths, setSharedGroupPaths] = useState<string[]>(() => catalogSharedGroupPaths(catalog));
  const [shareCandidate, setShareCandidate] = useState("");
  const [clearanceLevel, setClearanceLevel] = useState<ClearanceLevel>(catalog.clearance_level as ClearanceLevel);
  const [tableSearch, setTableSearch] = useState("");
  const [tableFilter, setTableFilter] = useState<SchemaCatalogFilter>("all");
  const [joinDraft, setJoinDraft] = useState<SchemaJoinDraft>(() => emptySchemaJoinDraft());
  const [reviewTab, setReviewTab] = useState<ConnectorReviewTab>("summary");

  useEffect(() => {
    setDraftJson(normalizeCatalogJson(catalog.catalog_json));
    setOwnerGroupPath(catalogOwnerGroupPath(catalog));
    setSharedGroupPaths(catalogSharedGroupPaths(catalog));
    setShareCandidate("");
    setClearanceLevel(catalog.clearance_level as ClearanceLevel);
    setTableSearch("");
    setTableFilter("all");
    setJoinDraft(emptySchemaJoinDraft());
    setReviewTab("summary");
  }, [catalog]);

  const tables = draftJson.tables ?? [];
  const relationships = draftJson.relationships ?? [];
  const tableOptions = useMemo(() => tables.map(schemaCatalogTableKey).filter(Boolean), [tables]);
  const leftJoinColumns = useMemo(() => schemaCatalogColumnsForTable(tables, joinDraft.leftTable), [joinDraft.leftTable, tables]);
  const rightJoinColumns = useMemo(() => schemaCatalogColumnsForTable(tables, joinDraft.rightTable), [joinDraft.rightTable, tables]);
  const reviewStats = schemaCatalogReviewStats(draftJson);
  const accessGroupPaths = useMemo(() => uniqueGroupPaths([ownerGroupPath, ...sharedGroupPaths]), [ownerGroupPath, sharedGroupPaths]);
  const approvalWarnings = schemaCatalogApprovalWarnings(reviewStats, ownerGroupPath);
  const visibleTables = useMemo(
    () => tables
      .map((table, tableIndex) => ({ table, tableIndex }))
      .filter(({ table }) => schemaCatalogTableMatches(table, tableSearch, tableFilter)),
    [tableFilter, tableSearch, tables],
  );
  const enrichmentStatus = schemaCatalogAiEnrichmentStatus(draftJson);
  const enrichmentError = schemaCatalogAiEnrichmentError(draftJson);
  const aiGenerated = enrichmentStatus === "generated";
  const aiFailed = enrichmentStatus === "failed";
  const missingAiTableCount = schemaCatalogPendingTableKeys(draftJson).length;
  const aiIncomplete = enrichmentStatus === "pending" || enrichmentStatus === "in_progress" || enrichmentStatus === "partial" || aiFailed || missingAiTableCount > 0;
  const canContinueAiEnrichment = aiIncomplete && (catalog.status === "draft" || catalog.status === "reviewed");
  const groupOptions = Array.from(new Set(["", ownerGroupPath, ...writableSpacePaths].filter((value, index) => index === 0 || Boolean(value))));
  const shareOptions = writableSpacePaths.filter((path) => path !== ownerGroupPath && !sharedGroupPaths.includes(path));
  const joinDraftReady = Boolean(joinDraft.leftTable && joinDraft.leftColumn && joinDraft.rightTable && joinDraft.rightColumn);
  const joinDraftDuplicate = joinDraftReady && relationships.some((relationship) => schemaCatalogRelationshipMatchesDraft(relationship, joinDraft));
  const guidedReviewIndex = guidedReviewTabs.indexOf(reviewTab);
  const previousReviewTab = guidedReviewIndex > 0 ? guidedReviewTabs[guidedReviewIndex - 1] : null;
  const nextReviewTab = guidedReviewIndex >= 0 && guidedReviewIndex < guidedReviewTabs.length - 1 ? guidedReviewTabs[guidedReviewIndex + 1] : null;

  function updateTable(index: number, patch: Partial<SchemaCatalogTable>) {
    setDraftJson((current) => {
      const next = normalizeCatalogJson(current);
      const nextTables = [...(next.tables ?? [])];
      nextTables[index] = { ...nextTables[index], ...patch };
      return { ...next, tables: nextTables };
    });
  }

  function updateColumn(tableIndex: number, columnIndex: number, patch: Partial<SchemaCatalogColumn>) {
    setDraftJson((current) => {
      const next = normalizeCatalogJson(current);
      const nextTables = [...(next.tables ?? [])];
      const table = { ...nextTables[tableIndex] };
      const columns = [...(table.columns ?? [])];
      columns[columnIndex] = { ...columns[columnIndex], ...patch };
      table.columns = columns;
      nextTables[tableIndex] = table;
      return { ...next, tables: nextTables };
    });
  }

  function updateRelationship(index: number, patch: Partial<SchemaCatalogRelationship>) {
    setDraftJson((current) => {
      const next = normalizeCatalogJson(current);
      const nextRelationships = [...(next.relationships ?? [])];
      nextRelationships[index] = { ...nextRelationships[index], ...patch };
      return { ...next, relationships: nextRelationships };
    });
  }

  function removeRelationship(index: number) {
    setDraftJson((current) => {
      const next = normalizeCatalogJson(current);
      return { ...next, relationships: (next.relationships ?? []).filter((_relationship, relationshipIndex) => relationshipIndex !== index) };
    });
  }

  function updateJoinDraft(patch: Partial<SchemaJoinDraft>) {
    setJoinDraft((current) => ({ ...current, ...patch }));
  }

  function addJoinDraft() {
    if (!joinDraftReady || joinDraftDuplicate) return;
    setDraftJson((current) => {
      const next = normalizeCatalogJson(current);
      const relationship: SchemaCatalogRelationship = {
        name: schemaCatalogManualRelationshipName(joinDraft),
        left_table: joinDraft.leftTable,
        left_columns: [joinDraft.leftColumn],
        right_table: joinDraft.rightTable,
        right_columns: [joinDraft.rightColumn],
        allowed: true,
        description: joinDraft.description,
        source: "manual",
      };
      return { ...next, relationships: [...(next.relationships ?? []), relationship] };
    });
    setJoinDraft(emptySchemaJoinDraft());
  }

  function addSharedGroupPath(path: string) {
    const groupPath = path.trim();
    if (!groupPath || groupPath === ownerGroupPath || sharedGroupPaths.includes(groupPath)) return;
    setSharedGroupPaths(uniqueGroupPaths([...sharedGroupPaths, groupPath]));
    setShareCandidate("");
  }

  function updateOwnerGroupPath(groupPath: string) {
    setOwnerGroupPath(groupPath);
    setSharedGroupPaths((current) => current.filter((path) => path !== groupPath));
    if (shareCandidate === groupPath) setShareCandidate("");
  }

  function bulkUpdateVisibleTables(patch: Partial<SchemaCatalogTable>) {
    const visibleIndexes = new Set(visibleTables.map((item) => item.tableIndex));
    setDraftJson((current) => {
      const next = normalizeCatalogJson(current);
      const nextTables = (next.tables ?? []).map((table, index) => visibleIndexes.has(index) ? { ...table, ...patch } : table);
      return { ...next, tables: nextTables };
    });
  }

  function bulkUpdateVisibleColumns(patch: Partial<SchemaCatalogColumn>) {
    const visibleIndexes = new Set(visibleTables.map((item) => item.tableIndex));
    setDraftJson((current) => {
      const next = normalizeCatalogJson(current);
      const nextTables = (next.tables ?? []).map((table, index) => {
        if (!visibleIndexes.has(index)) return table;
        return {
          ...table,
          columns: (table.columns ?? []).map((column) => ({ ...column, ...patch })),
        };
      });
      return { ...next, tables: nextTables };
    });
  }

  function handleSave(nextStatus: ConnectorSchemaCatalogStatus = "draft") {
    onSave({
      catalog_json: { ...(draftJson as Record<string, unknown>), shared_group_paths: sharedGroupPaths },
      status: nextStatus,
      group_path: ownerGroupPath,
      group_paths: accessGroupPaths,
      clearance_level: clearanceLevel,
    });
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-surface-border pb-4">
        <div>
          <p className="sv-label">Database access review</p>
          <h3 className="mt-1 text-body-lg font-extrabold text-on-surface">{catalogName(catalog, profile)}</h3>
          <p className="mt-1 max-w-3xl text-body-md text-on-surface-variant">
            Approving this review tells Live DB exactly which tables, columns, and joins it may use.
          </p>
        </div>
      </div>

      <ConnectorReviewTabs idPrefix={reviewTabsId} onChange={setReviewTab} value={reviewTab} />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="space-y-4">
          <div
            aria-labelledby={`${reviewTabsId}-tab-summary`}
            className="space-y-4"
            hidden={reviewTab !== "summary"}
            id={`${reviewTabsId}-panel-summary`}
            role="tabpanel"
            tabIndex={0}
          >
            {reviewTab === "summary" ? (
              <>
          <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <SchemaReviewMetric label="Included tables" value={`${reviewStats.allowedTables}/${reviewStats.totalTables}`} />
            <SchemaReviewMetric label="Included columns" value={`${reviewStats.allowedColumns}/${reviewStats.totalColumns}`} />
            <SchemaReviewMetric label="Sensitive fields" value={reviewStats.sensitiveColumns.toString()} />
            <SchemaReviewMetric label="Missing text" value={reviewStats.missingDescriptions.toString()} />
          </dl>

          {aiFailed ? (
            <InlineMessage tone="warning">
              AI enrichment failed, so this review contains raw schema metadata only. You can still edit descriptions, mark sensitive fields, and approve access after review.
              {enrichmentError ? ` Detail: ${enrichmentError}` : ""}
            </InlineMessage>
          ) : null}
          {!aiFailed && aiIncomplete ? (
            <InlineMessage tone="warning">
              AI enrichment is incomplete. Completed table descriptions are saved, and remaining tables can be retried.
              {enrichmentError ? ` Detail: ${enrichmentError}` : ""}
            </InlineMessage>
          ) : null}
          {aiGenerated && !aiIncomplete ? (
            <p className="rounded-md border border-surface-border bg-surface px-3 py-2 text-label-md text-on-surface-variant">
              AI-generated metadata is editable. Live DB cannot use it until this review is approved.
            </p>
          ) : null}
          <label className="sv-field">
            <span className="sv-label">Review Name</span>
            <input value={draftJson.name ?? ""} onChange={(event) => setDraftJson((current) => ({ ...normalizeCatalogJson(current), name: event.target.value }))} placeholder={`${profile.name} Live DB access`} className="sv-input" />
          </label>
          <label className="sv-field">
            <span className="sv-label">Business Rules</span>
            <textarea
              value={(draftJson.business_rules ?? []).join("\n")}
              onChange={(event) => setDraftJson((current) => ({ ...normalizeCatalogJson(current), business_rules: event.target.value.split("\n").map((line) => line.trim()).filter(Boolean) }))}
              placeholder="One rule per line"
              className="sv-input min-h-24"
            />
          </label>
              </>
            ) : null}
          </div>

          <div
            aria-labelledby={`${reviewTabsId}-tab-tables`}
            className="space-y-4"
            hidden={reviewTab !== "tables"}
            id={`${reviewTabsId}-panel-tables`}
            role="tabpanel"
            tabIndex={0}
          >
            {reviewTab === "tables" ? (
              <>
          <section className="rounded-md border border-surface-border bg-surface p-3">
            <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_12rem]">
              <label className="sv-field">
                <span className="sv-label">Find schema objects</span>
                <span className="relative block">
                  <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-secondary" size={15} />
                  <input value={tableSearch} onChange={(event) => setTableSearch(event.target.value)} placeholder="Table, column, synonym, or description" className="sv-input pl-9" />
                </span>
              </label>
              <label className="sv-field">
                <span className="sv-label">Filter</span>
                <select value={tableFilter} onChange={(event) => setTableFilter(event.target.value as SchemaCatalogFilter)} className="sv-select">
                  <option value="all">All tables</option>
                  <option value="included">Included</option>
                  <option value="excluded">Excluded</option>
                  <option value="sensitive">Sensitive</option>
                  <option value="missing">Needs descriptions</option>
                </select>
              </label>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="text-label-md text-secondary">{visibleTables.length} visible</span>
              <button type="button" disabled={visibleTables.length === 0} onClick={() => bulkUpdateVisibleTables({ allowed: true, sensitive: false })} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
                <span className="inline-flex items-center gap-1"><CheckCircle2 size={14} />Include visible</span>
              </button>
              <button type="button" disabled={visibleTables.length === 0} onClick={() => bulkUpdateVisibleTables({ allowed: false })} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
                <span className="inline-flex items-center gap-1"><X size={14} />Exclude visible</span>
              </button>
              <button type="button" disabled={visibleTables.length === 0} onClick={() => bulkUpdateVisibleColumns({ allowed: false, sensitive: true })} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
                <span className="inline-flex items-center gap-1"><ShieldAlert size={14} />Mark visible columns sensitive</span>
              </button>
              <button type="button" disabled={visibleTables.length === 0} onClick={() => bulkUpdateVisibleColumns({ sensitive: false })} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-on-surface hover:border-primary disabled:opacity-50">
                Clear column sensitivity
              </button>
            </div>
          </section>

          <div className="space-y-3">
            {tables.length === 0 ? <p className="rounded-md border border-surface-border bg-surface p-3 text-body-md text-secondary">This catalog has no tables to review.</p> : null}
            {tables.length > 0 && visibleTables.length === 0 ? <p className="rounded-md border border-surface-border bg-surface p-3 text-body-md text-secondary">No tables match the current filter.</p> : null}
            {visibleTables.map(({ table, tableIndex }) => (
              <details key={table.key ?? `${table.schema}.${table.name}.${tableIndex}`} className="rounded-md border border-surface-border bg-surface p-3" open={tableIndex < 3}>
                <summary className="cursor-pointer text-body-md font-extrabold text-on-surface">
                  <span>{table.key ?? table.name ?? "Unnamed table"}</span>
                  <span className="ml-2 text-label-md font-normal text-secondary">{table.columns?.length ?? 0} columns</span>
                  <span className="ml-2 inline-flex flex-wrap gap-1 align-middle">
                    <span className={table.allowed !== false && table.sensitive !== true ? "sv-pill sv-pill-success" : "sv-pill"}>{table.allowed !== false && table.sensitive !== true ? "included" : "excluded"}</span>
                    {table.sensitive === true ? <span className="sv-pill">sensitive</span> : null}
                    {schemaCatalogTableNeedsEnrichment(table) ? <span className="sv-pill">needs text</span> : null}
                  </span>
                </summary>
                <div className="mt-3 grid gap-3">
                  <div className="flex flex-wrap gap-3">
                    <label className="inline-flex items-center gap-2 text-label-md font-bold text-on-surface">
                      <input type="checkbox" checked={table.allowed !== false} onChange={(event) => updateTable(tableIndex, { allowed: event.target.checked })} />
                      Allowed
                    </label>
                    <label className="inline-flex items-center gap-2 text-label-md font-bold text-on-surface">
                      <input type="checkbox" checked={table.sensitive === true} onChange={(event) => updateTable(tableIndex, { sensitive: event.target.checked })} />
                      Sensitive
                    </label>
                  </div>
                  <label className="sv-field">
                    <span className="sv-label">Table Description</span>
                    <textarea value={table.description ?? ""} onChange={(event) => updateTable(tableIndex, { description: event.target.value })} className="sv-input min-h-20" />
                  </label>
                  <label className="sv-field">
                    <span className="sv-label">Table Synonyms</span>
                    <input value={(table.synonyms ?? []).join(", ")} onChange={(event) => updateTable(tableIndex, { synonyms: splitCommaList(event.target.value) })} className="sv-input" />
                  </label>
                  <div className="rounded-md border border-surface-border">
                    {(table.columns ?? []).map((column, columnIndex) => (
                      <div key={`${column.name ?? columnIndex}`} className="grid gap-3 border-b border-surface-border p-3 last:border-b-0 lg:grid-cols-[minmax(10rem,12rem)_minmax(0,1fr)]">
                        <div>
                          <strong className="block text-body-md text-on-surface">{column.name}</strong>
                          <small className="text-secondary">{column.data_type ?? "unknown"}</small>
                          <div className="mt-2 flex flex-wrap gap-3">
                            <label className="inline-flex items-center gap-2 text-label-md font-bold text-on-surface">
                              <input type="checkbox" checked={column.allowed !== false} onChange={(event) => updateColumn(tableIndex, columnIndex, { allowed: event.target.checked })} />
                              Allowed
                            </label>
                            <label className="inline-flex items-center gap-2 text-label-md font-bold text-on-surface">
                              <input type="checkbox" checked={column.sensitive === true} onChange={(event) => updateColumn(tableIndex, columnIndex, { sensitive: event.target.checked })} />
                              Sensitive
                            </label>
                          </div>
                          {column.sensitive === true || column.allowed === false ? <small className="mt-2 block text-secondary">Excluded from Live DB SQL prompts.</small> : null}
                        </div>
                        <div className="grid gap-2">
                          <textarea aria-label={`${column.name ?? "Column"} description`} value={column.description ?? ""} onChange={(event) => updateColumn(tableIndex, columnIndex, { description: event.target.value })} placeholder="Column meaning" className="sv-input min-h-16" />
                          <input aria-label={`${column.name ?? "Column"} synonyms`} value={(column.synonyms ?? []).join(", ")} onChange={(event) => updateColumn(tableIndex, columnIndex, { synonyms: splitCommaList(event.target.value) })} placeholder="Synonyms, comma separated" className="sv-input" />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </details>
            ))}
          </div>
              </>
            ) : null}
          </div>

          <div
            aria-labelledby={`${reviewTabsId}-tab-joins`}
            hidden={reviewTab !== "joins"}
            id={`${reviewTabsId}-panel-joins`}
            role="tabpanel"
            tabIndex={0}
          >
            {reviewTab === "joins" ? (
              <details className="rounded-md border border-surface-border bg-surface p-3" open>
            <summary className="cursor-pointer text-body-md font-extrabold text-on-surface">
              <span className="inline-flex items-center gap-2"><Network size={16} />Joins</span>
              <span className="ml-2 text-label-md font-normal text-secondary">{schemaCatalogAllowedRelationships(relationships)} of {relationships.length} joins approved</span>
            </summary>
            <div className="mt-3 rounded-md border border-surface-border bg-surface-container-low p-3">
              <div className="mb-3">
                <p className="text-label-md font-extrabold text-on-surface">Add inferred join</p>
                <p className="mt-1 text-label-md text-secondary">Use this when the database does not declare a foreign key, but reviewers know the columns should join.</p>
              </div>
              <div className="grid gap-3 xl:grid-cols-4">
                <label className="sv-field">
                  <span className="sv-label">Left Table</span>
                  <select value={joinDraft.leftTable} onChange={(event) => updateJoinDraft({ leftTable: event.target.value, leftColumn: "" })} className="sv-select">
                    <option value="">Select table</option>
                    {tableOptions.map((tableKey) => <option key={`left.${tableKey}`} value={tableKey}>{tableKey}</option>)}
                  </select>
                </label>
                <label className="sv-field">
                  <span className="sv-label">Left Column</span>
                  <select value={joinDraft.leftColumn} onChange={(event) => updateJoinDraft({ leftColumn: event.target.value })} disabled={!joinDraft.leftTable} className="sv-select disabled:opacity-50">
                    <option value="">Select column</option>
                    {leftJoinColumns.map((column) => <option key={`left.${joinDraft.leftTable}.${column}`} value={column}>{column}</option>)}
                  </select>
                </label>
                <label className="sv-field">
                  <span className="sv-label">Right Table</span>
                  <select value={joinDraft.rightTable} onChange={(event) => updateJoinDraft({ rightTable: event.target.value, rightColumn: "" })} className="sv-select">
                    <option value="">Select table</option>
                    {tableOptions.map((tableKey) => <option key={`right.${tableKey}`} value={tableKey}>{tableKey}</option>)}
                  </select>
                </label>
                <label className="sv-field">
                  <span className="sv-label">Right Column</span>
                  <select value={joinDraft.rightColumn} onChange={(event) => updateJoinDraft({ rightColumn: event.target.value })} disabled={!joinDraft.rightTable} className="sv-select disabled:opacity-50">
                    <option value="">Select column</option>
                    {rightJoinColumns.map((column) => <option key={`right.${joinDraft.rightTable}.${column}`} value={column}>{column}</option>)}
                  </select>
                </label>
              </div>
              <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_9rem]">
                <input aria-label="Join description" value={joinDraft.description} onChange={(event) => updateJoinDraft({ description: event.target.value })} placeholder="Join meaning, optional" className="sv-input" />
                <button type="button" disabled={!joinDraftReady || Boolean(joinDraftDuplicate)} onClick={addJoinDraft} className="sv-action-secondary justify-center disabled:opacity-50">
                  <Plus size={16} />
                  Add Join
                </button>
              </div>
              {joinDraftDuplicate ? <p className="mt-2 text-label-md text-secondary">That join is already in the review.</p> : null}
            </div>
            {relationships.length === 0 ? (
              <p className="mt-3 text-body-md text-secondary">No joins are in this review yet. Add one above or rerun Schema after foreign keys are added to the database.</p>
            ) : (
              <div className="mt-3 grid gap-2">
                {relationships.map((relationship, relationshipIndex) => (
                  <div key={`${schemaCatalogRelationshipLabel(relationship)}.${relationshipIndex}`} className="grid gap-3 rounded-md border border-surface-border bg-surface-container-low p-3 lg:grid-cols-[minmax(0,1fr)_9rem]">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <strong className="block text-body-md text-on-surface" style={{ overflowWrap: "anywhere" }}>{schemaCatalogRelationshipLabel(relationship)}</strong>
                        {schemaCatalogRelationshipSource(relationship) === "manual" ? <span className="sv-pill">manual</span> : <span className="sv-pill">detected</span>}
                      </div>
                      <textarea
                        aria-label={`Description for ${schemaCatalogRelationshipLabel(relationship)}`}
                        value={relationship.description ?? ""}
                        onChange={(event) => updateRelationship(relationshipIndex, { description: event.target.value })}
                        placeholder="Join meaning"
                        className="sv-input mt-2 min-h-16"
                      />
                    </div>
                    <div className="grid content-start gap-2">
                      <label className="inline-flex items-start gap-2 text-label-md font-bold text-on-surface">
                        <input type="checkbox" checked={relationship.allowed !== false} onChange={(event) => updateRelationship(relationshipIndex, { allowed: event.target.checked })} />
                        Approved join
                      </label>
                      <button type="button" onClick={() => removeRelationship(relationshipIndex)} className="rounded-md border border-surface-border px-2 py-1 text-label-md font-bold text-error-red hover:border-error-red">
                        <span className="inline-flex items-center gap-1"><Trash2 size={14} />Remove</span>
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
              </details>
            ) : null}
          </div>

          <div
            aria-labelledby={`${reviewTabsId}-tab-access`}
            hidden={reviewTab !== "access"}
            id={`${reviewTabsId}-panel-access`}
            role="tabpanel"
            tabIndex={0}
          >
            {reviewTab === "access" ? (
              <CatalogAccessPanel
                catalogStatus={catalog.status}
                clearanceLevel={clearanceLevel}
                clearanceOptions={clearanceOptions}
                groupOptions={groupOptions}
                ownerGroupPath={ownerGroupPath}
                shareCandidate={shareCandidate}
                shareOptions={shareOptions}
                sharedGroupPaths={sharedGroupPaths}
                onAddSharedGroupPath={addSharedGroupPath}
                onClearanceChange={setClearanceLevel}
                onOwnerGroupPathChange={updateOwnerGroupPath}
                onShareCandidateChange={setShareCandidate}
                onSharedGroupPathsChange={setSharedGroupPaths}
              />
            ) : null}
          </div>

          <div
            aria-labelledby={`${reviewTabsId}-tab-raw_schema`}
            hidden={reviewTab !== "raw_schema"}
            id={`${reviewTabsId}-panel-raw_schema`}
            role="tabpanel"
            tabIndex={0}
          >
            {reviewTab === "raw_schema" ? (
              <details className="rounded-md border border-surface-border bg-surface p-3" open>
                <summary className="cursor-pointer text-body-md font-extrabold text-on-surface">Raw schema catalog JSON</summary>
                <pre className="mt-3 max-h-[32rem] overflow-auto rounded-md bg-surface-container-low p-3 text-xs text-on-surface">
                  {JSON.stringify(draftJson, null, 2)}
                </pre>
              </details>
            ) : null}
          </div>

          {previousReviewTab || nextReviewTab ? (
            <div className="flex flex-wrap items-center gap-2 border-t border-surface-border pt-3">
              {previousReviewTab ? (
                <button type="button" onClick={() => setReviewTab(previousReviewTab)} className="sv-action-secondary">
                  Back
                </button>
              ) : null}
              {nextReviewTab ? (
                <button type="button" onClick={() => setReviewTab(nextReviewTab)} className="sv-action-primary ml-auto">
                  Next
                </button>
              ) : null}
            </div>
          ) : null}
        </div>

        <CatalogReviewActions
          approvalWarnings={approvalWarnings}
          canContinueAiEnrichment={canContinueAiEnrichment}
          catalogStatus={catalog.status}
          isSaving={isSaving}
          mutationError={mutationError}
          ownerGroupPath={ownerGroupPath}
          relationships={relationships}
          reviewStats={reviewStats}
          onClose={onClose}
          onContinueAiEnrichment={onContinueAiEnrichment}
          onEditAccess={() => setReviewTab("access")}
          onSave={handleSave}
        />
      </div>
    </section>
  );
}
