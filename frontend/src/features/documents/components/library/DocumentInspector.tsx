import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArchiveRestore,
  Download,
  Edit3,
  Eye,
  RotateCw,
  ShieldAlert,
  Trash2,
  X,
} from "lucide-react";

import { documentsApi } from "@/lib/api/contracts";
import {
  clearanceLevelDescription,
  clearanceLevelLabel,
  clearanceLevelsAssignableBy,
  defaultClearanceLevel,
  isGlobalAdmin,
} from "@/lib/auth/authz";
import { Fact, InlineMessage } from "@/components/layout/Common";
import {
  ChipList,
  DocumentStatePill,
  IngestStatusPill,
  InspectorSection,
  KeyValueList,
} from "@/features/documents/components/library/DocumentPagePrimitives";
import {
  canModifyDocument,
  canPermanentlyDeleteDocument,
  canTransferDocumentOwner,
  labelize,
  ownershipTransferOptions,
  uniqueTopicValues,
  type DocumentAction,
} from "@/features/documents/utils/documentPageUtils";
import type { ClearanceLevel, Document, User as AuthUser, VersionChainResponse } from "@/types/api";
import { errorMessage, formatDate, formatDateTime } from "@/lib/utils/format";
import type { GroupOption } from "@/lib/utils/groups";
import { OwnerTransferControl, ShareControl, TopicEditor } from "@/features/documents/components/library/DocumentGovernanceControls";


const INSPECTOR_TABS: Array<{ id: InspectorTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "governance", label: "Governance" },
  { id: "extracted", label: "Extracted" },
  { id: "versions", label: "Versions" },
];

type InspectorTab = "overview" | "governance" | "extracted" | "versions";

type DocumentInspectorProps = {
  document: Document | null;
  onClearanceChange: (document: Document, clearanceLevel: ClearanceLevel) => void;
  onClose: () => void;
  onDocumentAction: (action: DocumentAction, document: Document) => void;
  onOwnerChange: (document: Document, groupPath: string) => void;
  onSharesChange: (document: Document, groupPaths: string[]) => void;
  onTopicsChange: (document: Document, topics: string[]) => void;
  onUnshare: (document: Document, groupPath: string) => void;
  pending: boolean;
  spaceOptions: GroupOption[];
  user: AuthUser;
};

export function DocumentInspector({ document, onClearanceChange, onClose, onDocumentAction, onOwnerChange, onSharesChange, onTopicsChange, onUnshare, pending, spaceOptions, user }: DocumentInspectorProps) {
  const inspectorRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const [modalLayout, setModalLayout] = useState(() => typeof window !== "undefined" && window.matchMedia("(max-width: 1319px)").matches);
  const detailQuery = useQuery({
    queryKey: ["documents", "detail", document?.id],
    queryFn: () => documentsApi.get(document?.id ?? ""),
    enabled: Boolean(document?.id),
    retry: false,
  });
  const versionsQuery = useQuery<VersionChainResponse, Error>({
    queryKey: ["documents", "versions", document?.id],
    queryFn: () => documentsApi.versions(document?.id ?? ""),
    enabled: Boolean(document?.id),
    retry: false,
  });
  const selected = detailQuery.data ?? document;
  const [clearanceDraft, setClearanceDraft] = useState<ClearanceLevel>(document?.clearance_level ?? defaultClearanceLevel);
  const [topicDraft, setTopicDraft] = useState<string[]>([]);
  const [topicInput, setTopicInput] = useState("");
  const [shareDraft, setShareDraft] = useState<string[]>([]);
  const [shareCandidate, setShareCandidate] = useState("");
  const [ownerCandidate, setOwnerCandidate] = useState("");
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("overview");
  const clearanceOptions = useMemo(() => clearanceLevelsAssignableBy(user), [user]);
  const selectedTopics = useMemo(() => uniqueTopicValues([...(selected?.topics ?? []), ...(selected?.llm_topics ?? [])]), [selected?.topics, selected?.llm_topics]);
  const selectedTopicKey = selectedTopics.join("\u001f");
  const selectedShareKey = (selected?.shared_group_paths ?? []).join("\u001f");
  const shareDraftKey = shareDraft.join("\u001f");
  const ownerGroupPath = selected?.owner_group_path ?? selected?.group_path ?? "";
  const shareOptions = useMemo(
    () => spaceOptions
      .filter((space) => space.path !== ownerGroupPath)
      .filter((space) => !shareDraft.includes(space.path)),
    [ownerGroupPath, shareDraft, spaceOptions],
  );
  const ownerOptions = useMemo(() => ownershipTransferOptions(user, ownerGroupPath, spaceOptions), [ownerGroupPath, spaceOptions, user]);
  useEffect(() => {
    if (selected) setClearanceDraft(selected.clearance_level);
  }, [selected?.id, selected?.clearance_level]);
  useEffect(() => {
    setShareDraft(selected?.shared_group_paths ?? []);
    setShareCandidate("");
  }, [selected?.id, selectedShareKey]);
  useEffect(() => {
    setOwnerCandidate("");
  }, [selected?.id, ownerGroupPath]);
  useEffect(() => {
    setTopicDraft(selectedTopics);
    setTopicInput("");
  }, [selected?.id, selectedTopicKey]);
  useEffect(() => {
    setInspectorTab("overview");
  }, [selected?.id]);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(max-width: 1319px)");
    const updateLayout = () => setModalLayout(mediaQuery.matches);
    updateLayout();
    mediaQuery.addEventListener("change", updateLayout);
    return () => mediaQuery.removeEventListener("change", updateLayout);
  }, []);

  useEffect(() => {
    if (!modalLayout || !selected) return;
    returnFocusRef.current = window.document.activeElement instanceof HTMLElement ? window.document.activeElement : null;
    window.document.body.classList.add("knowledge-inspector-modal-open");
    const frame = window.requestAnimationFrame(() => closeRef.current?.focus({ preventScroll: true }));
    return () => {
      window.cancelAnimationFrame(frame);
      window.document.body.classList.remove("knowledge-inspector-modal-open");
      returnFocusRef.current?.focus({ preventScroll: true });
    };
  }, [modalLayout, selected?.id]);

  if (!selected) return null;
  const writable = canModifyDocument(user, selected);
  const canPermanent = canPermanentlyDeleteDocument(user, selected);
  const isDeleted = Boolean(selected.deleted_at);
  const canTransferOwner = canTransferDocumentOwner(user, selected) && !isDeleted;
  const canEditClearance = writable && !isDeleted;
  const clearanceChanged = clearanceDraft !== selected.clearance_level;
  const canEditTopics = writable && !isDeleted;
  const topicDraftKey = uniqueTopicValues(topicDraft).join("\u001f");
  const topicsChanged = topicDraftKey !== selectedTopicKey;
  const canEditShares = isGlobalAdmin(user) && !isDeleted;
  const sharesChanged = shareDraftKey !== selectedShareKey;
  const flagEntries = Object.entries(selected.metadata_flags ?? {}).filter(([, value]) => Boolean(value));

  function addTopic(value: string) {
    const topic = value.trim();
    if (!topic || topic.length > 80 || topicDraft.length >= 32) return;
    setTopicDraft(uniqueTopicValues([...topicDraft, topic]).slice(0, 32));
    setTopicInput("");
  }

  function addShare(path: string) {
    const normalized = path.trim();
    if (!normalized || shareDraft.includes(normalized)) return;
    setShareDraft([...shareDraft, normalized].sort((a, b) => a.localeCompare(b)));
    setShareCandidate("");
  }

  function handleInspectorKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (!modalLayout) return;
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      inspectorRef.current?.querySelectorAll<HTMLElement>(
        "button:not([disabled]), a[href], select:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
      ) ?? [],
    ).filter((element) => element.offsetParent !== null);
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && window.document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && window.document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <>
      {modalLayout ? <button type="button" className="knowledge-inspector-backdrop" onClick={onClose} aria-label="Close document inspector" /> : null}
      <aside
        ref={inspectorRef}
        className="knowledge-inspector"
        aria-labelledby={titleId}
        aria-modal={modalLayout ? true : undefined}
        onKeyDown={handleInspectorKeyDown}
        role={modalLayout ? "dialog" : undefined}
      >
      <div className="knowledge-inspector-header">
        <div>
          <p className="sv-eyebrow">{isDeleted ? "Trash Inspector" : "Document Inspector"}</p>
          <h2 id={titleId}>{selected.title}</h2>
        </div>
        <button ref={closeRef} type="button" onClick={onClose} className="knowledge-icon-button" aria-label="Close inspector">
          <X size={16} />
        </button>
      </div>
      {detailQuery.isError ? <InlineMessage tone="warning">{errorMessage(detailQuery.error, "Full document metadata could not be loaded.")}</InlineMessage> : null}
      <div className="knowledge-inspector-actions">
        {!isDeleted ? (
          <>
            <a href={documentsApi.contentUrl(selected.id)} target="_blank" rel="noreferrer" className="sv-action-secondary">
              <Eye size={15} /> View
            </a>
            <a href={documentsApi.contentUrl(selected.id)} download className="sv-action-secondary">
              <Download size={15} /> Download
            </a>
            {writable ? (
              <>
                <button type="button" onClick={() => onDocumentAction("reingest", selected)} disabled={pending} className="sv-action-secondary">
                  <RotateCw size={15} /> Reingest
                </button>
                <button type="button" onClick={() => onDocumentAction("trash", selected)} disabled={pending} className="sv-action-danger">
                  <Trash2 size={15} /> Move to Trash
                </button>
              </>
            ) : null}
          </>
        ) : (
          <>
            {writable ? (
              <button type="button" onClick={() => onDocumentAction("restore", selected)} disabled={pending} className="sv-action-secondary">
                <ArchiveRestore size={15} /> Restore
              </button>
            ) : null}
            {canPermanent ? (
              <button type="button" onClick={() => onDocumentAction("permanent", selected)} disabled={pending} className="sv-action-danger">
                <ShieldAlert size={15} /> Permanently Delete
              </button>
            ) : null}
          </>
        )}
      </div>
      <div className="knowledge-inspector-statusbar">
        <DocumentStatePill document={selected} />
        <IngestStatusPill status={selected.ingest_status} />
        <span className="sv-pill">{clearanceLevelLabel(selected.clearance_level)}</span>
      </div>
      <div className="knowledge-inspector-tabs" role="tablist" aria-label="Document inspector sections">
        {INSPECTOR_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={inspectorTab === tab.id}
            className={inspectorTab === tab.id ? "knowledge-inspector-tab-active" : "knowledge-inspector-tab"}
            onClick={() => setInspectorTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {inspectorTab === "overview" ? (
        <div className="knowledge-inspector-panel" role="tabpanel">
          <dl className="knowledge-detail-grid">
            <Fact label="Document ID" value={selected.id} />
            <Fact label="Owner Space" value={selected.owner_group_path ?? selected.group_path} />
            <Fact label="Shared Spaces" value={selected.shared_group_paths.length ? selected.shared_group_paths.join(", ") : "None"} />
            <Fact label="Uploaded by" value={selected.uploaded_by} />
            <Fact label="Created" value={formatDateTime(selected.created_at)} />
            <Fact label="Effective" value={formatDate(selected.effective_date)} />
            <Fact label="Language" value={selected.language || "Unknown"} />
          </dl>
          <InspectorSection title="Summary">
            <p>{selected.summary || selected.description || "No summary or description available."}</p>
          </InspectorSection>
        </div>
      ) : null}

      {inspectorTab === "governance" ? (
        <div className="knowledge-inspector-panel" role="tabpanel">
          <dl className="knowledge-detail-grid">
            <Fact label="Clearance" value={clearanceLevelLabel(selected.clearance_level)} />
            <Fact label="Governance" value={selected.governance_owner === "system" ? "System governed" : "Owner space"} />
            <Fact label="Ingestion Status" value={labelize(selected.ingest_status)} />
            <Fact label="Lifecycle" value={isDeleted ? "In Trash" : selected.is_current ? "Current" : "Superseded"} />
            <Fact label="Deleted" value={selected.deleted_at ? formatDateTime(selected.deleted_at) : "Not deleted"} />
            <Fact label="Expires" value={selected.expiry_date ? formatDate(selected.expiry_date) : "No expiry"} />
          </dl>
          <InspectorSection title="Owner Knowledge Space">
            <OwnerTransferControl
              canTransfer={canTransferOwner}
              currentGroupPath={ownerGroupPath}
              disabled={pending}
              onTransfer={() => onOwnerChange(selected, ownerCandidate)}
              options={ownerOptions}
              selectedCandidate={ownerCandidate}
              setSelectedCandidate={setOwnerCandidate}
            />
          </InspectorSection>
          <InspectorSection title="Shared Knowledge Spaces">
            <ShareControl
              canEdit={canEditShares}
              disabled={pending}
              draft={shareDraft}
              onAdd={addShare}
              onRemove={(path) => setShareDraft(shareDraft.filter((value) => value !== path))}
              onRevert={() => {
                setShareDraft(selected.shared_group_paths);
                setShareCandidate("");
              }}
              onSave={() => onSharesChange(selected, shareDraft)}
              onUnshare={(path) => onUnshare(selected, path)}
              options={shareOptions}
              ownerGroupPath={selected.owner_group_path ?? selected.group_path}
              selectedCandidate={shareCandidate}
              setSelectedCandidate={setShareCandidate}
              sharesChanged={sharesChanged}
              user={user}
            />
          </InspectorSection>
          {canEditClearance ? (
            <InspectorSection title="Access Control">
              <label className="sv-field" htmlFor="document-clearance-level">
                <span className="sv-label">Clearance Level</span>
                <select
                  id="document-clearance-level"
                  className="sv-select"
                  disabled={pending}
                  onChange={(event) => setClearanceDraft(event.target.value as ClearanceLevel)}
                  value={clearanceDraft}
                >
                  {clearanceOptions.map((level) => (
                    <option key={level} value={level}>
                      {clearanceLevelLabel(level)}
                    </option>
                  ))}
                </select>
                <small className="text-secondary">{clearanceLevelDescription(clearanceDraft)}</small>
              </label>
              <button
                type="button"
                className="sv-action-primary"
                disabled={!clearanceChanged || pending}
                onClick={() => onClearanceChange(selected, clearanceDraft)}
              >
                <Edit3 size={15} /> Save Clearance
              </button>
            </InspectorSection>
          ) : null}
        </div>
      ) : null}

      {inspectorTab === "extracted" ? (
        <div className="knowledge-inspector-panel" role="tabpanel">
          {flagEntries.length > 0 ? (
            <InspectorSection title="Metadata Review Flags" defaultCollapsed resetKey={selected.id}>
              {flagEntries.map(([key, value]) => (
                <div key={key} className="knowledge-inspector-warning">
                  <strong>{labelize(key)}</strong>
                  <pre>{JSON.stringify(value, null, 2)}</pre>
                </div>
              ))}
            </InspectorSection>
          ) : null}
          <InspectorSection title="Topics">
            {canEditTopics ? (
              <TopicEditor
                changed={topicsChanged}
                disabled={pending}
                inputValue={topicInput}
                onAdd={addTopic}
                onInputChange={setTopicInput}
                onRemove={(topic) => setTopicDraft(topicDraft.filter((value) => value !== topic))}
                onRevert={() => {
                  setTopicDraft(selectedTopics);
                  setTopicInput("");
                }}
                onSave={() => onTopicsChange(selected, uniqueTopicValues(topicDraft))}
                values={topicDraft}
              />
            ) : (
              <ChipList values={selectedTopics} empty="No topics extracted yet." />
            )}
          </InspectorSection>
          <InspectorSection title="Entities">
            <KeyValueList
              empty="No entities extracted yet."
              items={selected.entities.slice(0, 12).map((entity) => ({ key: entity.type, value: entity.text }))}
            />
          </InspectorSection>
          <InspectorSection title="Cross References">
            <KeyValueList
              empty="No cross-references extracted yet."
              items={selected.cross_references.slice(0, 12).map((ref) => ({ key: ref.ref_type, value: ref.ref_text }))}
            />
          </InspectorSection>
          <InspectorSection title="Claims">
            <KeyValueList
              empty="No claims extracted yet."
              items={selected.claims.slice(0, 12).map((claim) => ({ key: `${claim.entity}.${claim.attribute}`, value: claim.value }))}
            />
          </InspectorSection>
        </div>
      ) : null}

      {inspectorTab === "versions" ? (
        <div className="knowledge-inspector-panel" role="tabpanel">
          <InspectorSection title="Version History">
            {versionsQuery.isLoading ? <p className="text-secondary">Loading versions.</p> : null}
            {versionsQuery.isError ? <InlineMessage tone="warning">Version history could not be loaded.</InlineMessage> : null}
            {versionsQuery.data?.chain.length ? (
              <div className="knowledge-version-list">
                {versionsQuery.data.chain.map((version) => (
                  <div key={version.id}>
                    <strong>{version.id}</strong>
                    <span className={version.is_current ? "sv-pill sv-pill-success" : "sv-pill"}>{version.is_current ? "Current" : "Superseded"}</span>
                  </div>
                ))}
              </div>
            ) : !versionsQuery.isLoading ? (
              <p className="text-secondary">No version history recorded.</p>
            ) : null}
          </InspectorSection>
        </div>
      ) : null}
      </aside>
    </>
  );
}
