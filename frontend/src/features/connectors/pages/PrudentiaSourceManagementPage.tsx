import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Database, Upload } from "lucide-react";

import { InlineMessage } from "@/components/layout/Common";
import { PrudentiaWorkspace } from "@/components/layout/PrudentiaWorkspace";
import { FolderIngestPanel } from "@/features/connectors/components/FolderIngestPanel";
import { adminApi } from "@/lib/api/contracts";
import { canManageSpaces, canUploadToSpace } from "@/lib/auth/authz";
import { errorMessage } from "@/lib/utils/format";
import { flattenGroups } from "@/lib/utils/groups";
import type { RouteId } from "@/routes/routes";
import type { User as AuthUser } from "@/types/api";

export function PrudentiaSourceManagementPage({ onLogout, onNavigate, user, variant }: Props) {
  const databaseConnectors = variant === "database_connectors";
  const groupsQuery = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.listGroups, retry: false, enabled: canManageSpaces(user) });
  const writableSpacePaths = useMemo(
    () => flattenGroups(groupsQuery.data?.items ?? []).filter((space) => canUploadToSpace(user, space.path)).map((space) => space.path),
    [groupsQuery.data?.items, user],
  );

  return (
    <PrudentiaWorkspace activeRoute={databaseConnectors ? "database-connectors" : "document-extraction"} onLogout={onLogout} onNavigate={onNavigate} user={user}>
      <main className="sv-page" id="main-content">
        <div className={`sv-page-inner sv-page-inner-workbench max-w-6xl${databaseConnectors ? " database-connectors-page-inner" : ""}`}>
          <header className="sv-page-header">
            <div>
              <p className="sv-eyebrow">{databaseConnectors ? "Live Database Access" : "Document Intake"}</p>
              <h1 className="sv-page-title">{databaseConnectors ? "Database Connectors" : "Folder Sources"}</h1>
              <p className="sv-page-subtitle">{databaseConnectors ? "Connect read-only databases, review schemas, and approve exactly what Live DB may use." : "Upload local folder snapshots for controlled ingestion."}</p>
            </div>
            <button type="button" onClick={() => onNavigate(databaseConnectors ? "document-extraction" : "upload")} className="sv-action-secondary">
              {databaseConnectors ? <Database size={16} /> : <Upload size={16} />}
              {databaseConnectors ? "Folder Sources" : "Add Files"}
            </button>
          </header>
          {groupsQuery.isError ? <InlineMessage tone="error">{errorMessage(groupsQuery.error, "Unable to load writable Knowledge Spaces.")}</InlineMessage> : null}
          <FolderIngestPanel currentUser={user} groupsLoading={groupsQuery.isLoading} variant={variant} writableSpacePaths={writableSpacePaths} />
        </div>
      </main>
    </PrudentiaWorkspace>
  );
}

type Props = {
  onLogout: () => void;
  onNavigate: (route: RouteId) => void;
  user: AuthUser;
  variant: "database_connectors" | "folder_sources";
};
