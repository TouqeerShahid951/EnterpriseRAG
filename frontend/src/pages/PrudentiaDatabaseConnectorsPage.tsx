import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Database } from "lucide-react";

import { adminApi } from "../api/contracts";
import { canManageSpaces, canUploadToSpace } from "../authz";
import { InlineMessage } from "../components/layout/Common";
import { PrudentiaWorkspace } from "../components/layout/PrudentiaWorkspace";
import { FolderIngestPanel } from "../components/upload/FolderIngestPanel";
import type { RouteId } from "../routes";
import type { User as AuthUser } from "../types/api";
import { errorMessage } from "../utils/format";
import { flattenGroups } from "../utils/groups";

export function PrudentiaDatabaseConnectorsPage({ onLogout, onNavigate, user }: Props) {
  const groupsQuery = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.listGroups, retry: false, enabled: canManageSpaces(user) });
  const writableSpacePaths = useMemo(
    () => flattenGroups(groupsQuery.data?.items ?? []).filter((space) => canUploadToSpace(user, space.path)).map((space) => space.path),
    [groupsQuery.data?.items, user],
  );

  return (
    <PrudentiaWorkspace activeRoute="database-connectors" onLogout={onLogout} onNavigate={onNavigate} user={user}>
      <main className="sv-page" id="main-content">
        <div className="sv-page-inner max-w-6xl">
          <header className="sv-page-header">
            <div>
              <p className="sv-eyebrow">Live Database Access</p>
              <h1 className="sv-page-title">Database Connectors</h1>
              <p className="sv-page-subtitle">Create SQL Server and PostgreSQL connections, inspect schemas, and choose the tables, columns, and joins Live DB may use.</p>
            </div>
            <button type="button" onClick={() => onNavigate("document-extraction")} className="sv-action-secondary">
              <Database size={16} /> Folder Sources
            </button>
          </header>
          {groupsQuery.isError ? <InlineMessage tone="error">{errorMessage(groupsQuery.error, "Unable to load writable Knowledge Spaces.")}</InlineMessage> : null}
          <FolderIngestPanel currentUser={user} groupsLoading={groupsQuery.isLoading} variant="database_connectors" writableSpacePaths={writableSpacePaths} />
        </div>
      </main>
    </PrudentiaWorkspace>
  );
}

type Props = { onLogout: () => void; onNavigate: (route: RouteId) => void; user: AuthUser };
