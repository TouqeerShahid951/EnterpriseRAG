import { Edit3, KeyRound, MessageSquareText, Plus, Search, Trash2 } from "lucide-react";

import { EmptyPanel, InlineMessage } from "@/components/layout/Common";
import { SpacePathList, UserTableSkeleton } from "@/features/access/components/AccessPagePrimitives";
import { accountTypeLabel, clearanceLevelLabel, roleDescription } from "@/lib/auth/authz";
import type { User as AuthUser, UserAdmin } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";

type Props = {
  canViewChatActivity: boolean;
  currentUser: AuthUser;
  groupsError: unknown;
  groupsFailed: boolean;
  loading: boolean;
  search: string;
  users: UserAdmin[];
  usersError: unknown;
  usersFailed: boolean;
  onChatActivity: (user: UserAdmin) => void;
  onCreate: () => void;
  onDelete: (user: UserAdmin) => void;
  onEdit: (user: UserAdmin) => void;
  onResetPassword: (user: UserAdmin) => void;
  onSearchChange: (value: string) => void;
};

export function AccessUsersTable({
  canViewChatActivity,
  currentUser,
  groupsError,
  groupsFailed,
  loading,
  search,
  users,
  usersError,
  usersFailed,
  onChatActivity,
  onCreate,
  onDelete,
  onEdit,
  onResetPassword,
  onSearchChange,
}: Props) {
  return (
    <section className="sv-card mt-5 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-surface-border p-4">
        <div>
          <h2 className="sv-section-title">Users</h2>
          <p className="text-body-md text-on-surface-variant">API-backed user inventory and Knowledge Space assignment state.</p>
        </div>
        <button type="button" onClick={onCreate} className="sv-action-primary">
          <Plus size={16} /> Create user
        </button>
      </div>
      <div className="border-b border-surface-border p-4">
        <label className="relative block max-w-xl">
          <span className="sr-only">Search users</span>
          <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant" />
          <input value={search} onChange={(event) => onSearchChange(event.target.value)} placeholder="Search by name, email, or space..." className="sv-input sv-input-with-leading-icon" />
        </label>
      </div>
      {usersFailed ? <InlineMessage tone="error">{errorMessage(usersError, "Unable to load users.")}</InlineMessage> : null}
      {groupsFailed ? <InlineMessage tone="warning">{errorMessage(groupsError, "Unable to load Knowledge Spaces for assignment.")}</InlineMessage> : null}
      <div className="sv-table-wrap">
        <table className="sv-table user-management-table">
          <thead>
            <tr>
              <th>User</th><th>Role</th><th>Clearance</th><th>Status</th><th>Knowledge Spaces</th><th>Permission</th><th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id} className="sv-table-row">
                <td data-label="User">
                  <strong className="text-on-surface">{user.name}</strong>
                  <small className="block text-secondary">{user.email}</small>
                  {user.id === currentUser.user_id ? <small className="mt-1 block font-semibold text-primary">Current session</small> : null}
                </td>
                <td data-label="Role"><strong className="block text-on-surface">{accountTypeLabel(user.account_type)}</strong><small className="text-secondary">{roleDescription(user.account_type)}</small></td>
                <td data-label="Clearance"><span className="sv-pill">{clearanceLevelLabel(user.clearance_level)}</span></td>
                <td data-label="Status">{user.is_active ? <span className="sv-pill sv-pill-success">Active</span> : <span className="sv-pill">Inactive</span>}</td>
                <td data-label="Knowledge Spaces"><SpacePathList paths={user.group_paths} /></td>
                <td data-label="Permission" className="font-semibold text-on-surface">v{user.permission_version}</td>
                <td data-label="Actions">
                  <div className="user-row-actions" aria-label={`Actions for ${user.email}`}>
                    <IconAction label={`Edit ${user.email}`} title="Edit user" icon={<Edit3 size={15} />} onClick={() => onEdit(user)} />
                    {user.id !== currentUser.user_id ? <IconAction label={`Reset password for ${user.email}`} title="Reset password" icon={<KeyRound size={15} />} onClick={() => onResetPassword(user)} /> : null}
                    {canViewChatActivity ? <IconAction label={`View chat activity for ${user.email}`} title="Chat activity" icon={<MessageSquareText size={15} />} onClick={() => onChatActivity(user)} /> : null}
                    {user.id !== currentUser.user_id ? <IconAction danger label={`Delete ${user.email}`} title="Delete user" icon={<Trash2 size={15} />} onClick={() => onDelete(user)} /> : null}
                  </div>
                </td>
              </tr>
            ))}
            {loading ? <UserTableSkeleton /> : null}
          </tbody>
        </table>
      </div>
      {!loading && users.length === 0 ? <div className="p-4"><EmptyPanel>No users match the selected filters.</EmptyPanel></div> : null}
    </section>
  );
}

function IconAction({ danger = false, icon, label, onClick, title }: {
  danger?: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  title: string;
}) {
  return (
    <button type="button" onClick={onClick} className={danger ? "user-row-action user-row-action-danger" : "user-row-action"} aria-label={label} title={title}>
      {icon}<span className="sr-only">{title}</span>
    </button>
  );
}
