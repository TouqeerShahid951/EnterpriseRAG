import { useEffect, useMemo, useState, type Dispatch, type FormEvent, type SetStateAction } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, Copy, Edit3, Eye, EyeOff, KeyRound, MessageSquareText, Plus, RefreshCw, Search, Trash2, UserCog, Users } from "lucide-react";

import { adminApi } from "../api/contracts";
import {
  accountTypeLabel,
  accountTypeOptions,
  canAssignAccountType,
  clearanceLevelDescription,
  clearanceLevelLabel,
  clearanceLevelsAssignableBy,
  defaultClearanceLevel,
  isGlobalAdmin,
  roleDescription,
} from "../authz";
import { useToast } from "../components/feedback/ToastProvider";
import { EmptyPanel, InlineMessage, Skeleton } from "../components/layout/Common";
import { PrudentiaBasicPage } from "../components/layout/PrudentiaWorkspace";
import { Modal } from "../components/layout/Modal";
import type { RouteId } from "../routes";
import type { AccountType, ClearanceLevel, User as AuthUser, UserAdmin } from "../types/api";
import type { ChatTurn, SavedChatSession, SavedChatSessionSummary } from "../types/chat";
import { errorMessage, formatDateTime } from "../utils/format";
import { flattenGroups, nextSelectedGroups, userSpacesFromPaths, type GroupOption } from "../utils/groups";

export function PrudentiaAccessPage({ currentUser, onAuthChanged, onLogout, onNavigate }: Props) {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [panel, setPanel] = useState<UserPanelState>(null);
  const [search, setSearch] = useState("");
  const [userDraft, setUserDraft] = useState<UserDraft>(() => createUserDraft(defaultAssignableClearance(currentUser)));
  const [showInitialPassword, setShowInitialPassword] = useState(false);
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const [createdUserEmail, setCreatedUserEmail] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<UserAdmin | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [resetTarget, setResetTarget] = useState<UserAdmin | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [showResetPassword, setShowResetPassword] = useState(false);
  const [resetCopyState, setResetCopyState] = useState<CopyState>("idle");
  const [chatActivityTarget, setChatActivityTarget] = useState<UserAdmin | null>(null);
  const [selectedChatSessionId, setSelectedChatSessionId] = useState<string | null>(null);
  const canViewChatActivity = isGlobalAdmin(currentUser);

  const usersQuery = useQuery({ queryKey: ["admin", "users"], queryFn: adminApi.listUsers, retry: false });
  const groupsQuery = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.listGroups, retry: false });
  const chatActivityQuery = useQuery({
    queryKey: ["admin", "users", chatActivityTarget?.id, "chat-activity"],
    queryFn: () => adminApi.listUserChatActivity(chatActivityTarget?.id ?? "", { limit: 30 }),
    enabled: Boolean(canViewChatActivity && chatActivityTarget),
    retry: false,
  });
  const selectedChatSessionQuery = useQuery({
    queryKey: ["admin", "users", chatActivityTarget?.id, "chat-activity", selectedChatSessionId],
    queryFn: () => adminApi.getUserChatActivitySession(chatActivityTarget?.id ?? "", selectedChatSessionId ?? ""),
    enabled: Boolean(canViewChatActivity && chatActivityTarget && selectedChatSessionId),
    retry: false,
  });

  const users = usersQuery.data?.items ?? [];
  const groupOptions = useMemo(
    () => (groupsQuery.data?.items ? flattenGroups(groupsQuery.data.items) : userSpacesFromPaths(currentUser.group_paths)),
    [currentUser.group_paths, groupsQuery.data?.items],
  );
  const assignableAccountTypes = useMemo(
    () => accountTypeOptions.filter((accountType) => canAssignAccountType(currentUser, accountType)),
    [currentUser],
  );
  const assignableClearanceLevels = useMemo(() => clearanceLevelsAssignableBy(currentUser), [currentUser]);
  const filteredUsers = users.filter((user) => matchesUser(user, search));

  useEffect(() => {
    if (selectedChatSessionId || !chatActivityQuery.data?.items.length) return;
    setSelectedChatSessionId(chatActivityQuery.data.items[0].id);
  }, [chatActivityQuery.data?.items, selectedChatSessionId]);

  const createUserMutation = useMutation({
    mutationFn: (draft: UserDraft) =>
      adminApi.createUser({
        email: draft.email.trim(),
        name: draft.name.trim(),
        account_type: draft.accountType,
        initial_password: draft.initialPassword,
        group_paths: draft.groupPaths,
        clearance_level: draft.clearanceLevel,
        is_active: draft.isActive,
      }),
    onSuccess: (created) => {
      setCreatedUserEmail(created.email);
      void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      notify({ title: "User created", description: `${created.email} is ready for credential handoff.`, tone: "success" });
    },
  });

  const updateUserMutation = useMutation({
    mutationFn: ({ draft, userId }: { draft: UserDraft; userId: string }) =>
      adminApi.updateUser(userId, {
        name: draft.name.trim(),
        account_type: draft.accountType,
        group_paths: draft.groupPaths,
        clearance_level: draft.clearanceLevel,
        is_active: draft.isActive,
      }),
    onSuccess: (updated) => {
      closePanel();
      void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      if (updated.id === currentUser.user_id) onAuthChanged();
      notify({ title: "User updated", description: updated.email, tone: "success" });
    },
    onError: (error) => notify({
      title: "User update failed",
      description: errorMessage(error, "Unable to update user."),
      tone: "error",
    }),
  });

  const deleteUserMutation = useMutation({
    mutationFn: (userId: string) => adminApi.deleteUser(userId),
    onSuccess: () => {
      const deletedEmail = deleteTarget?.email ?? "The selected account";
      setDeleteTarget(null);
      setDeleteConfirmation("");
      void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      notify({ title: "User deleted", description: deletedEmail, tone: "success" });
    },
    onError: (error) => notify({
      title: "User delete failed",
      description: errorMessage(error, "Unable to delete user."),
      tone: "error",
    }),
  });

  const resetPasswordMutation = useMutation({
    mutationFn: ({ userId, temporaryPassword }: { userId: string; temporaryPassword: string }) =>
      adminApi.resetUserPassword(userId, { temporary_password: temporaryPassword }),
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      notify({ title: "Password reset", description: `${updated.email} must change the temporary password at next sign-in.`, tone: "success" });
    },
    onError: (error) => notify({
      title: "Password reset failed",
      description: errorMessage(error, "Unable to reset password."),
      tone: "error",
    }),
  });

  function resetMutationState() {
    createUserMutation.reset();
    updateUserMutation.reset();
  }

  function openCreateUser() {
    resetMutationState();
    setUserDraft(createUserDraft(defaultAssignableClearance(currentUser)));
    setShowInitialPassword(false);
    setCopyState("idle");
    setCreatedUserEmail(null);
    setPanel({ kind: "create-user" });
  }

  function openEditUser(user: UserAdmin) {
    resetMutationState();
    setUserDraft({
      email: user.email,
      accountType: user.account_type,
      clearanceLevel: user.clearance_level,
      groupPaths: user.group_paths,
      initialPassword: "",
      isActive: user.is_active,
      name: user.name,
    });
    setCreatedUserEmail(null);
    setPanel({ kind: "edit-user", user });
  }

  function closePanel() {
    resetMutationState();
    setPanel(null);
    setCreatedUserEmail(null);
    setCopyState("idle");
  }

  function openDeleteUser(user: UserAdmin) {
    deleteUserMutation.reset();
    setDeleteConfirmation("");
    setDeleteTarget(user);
  }

  function closeDeleteUser() {
    if (deleteUserMutation.isPending) return;
    deleteUserMutation.reset();
    setDeleteTarget(null);
    setDeleteConfirmation("");
  }

  function openResetPassword(user: UserAdmin) {
    resetPasswordMutation.reset();
    setResetPassword(generateInitialPassword());
    setShowResetPassword(false);
    setResetCopyState("idle");
    setResetTarget(user);
  }

  function closeResetPassword() {
    if (resetPasswordMutation.isPending) return;
    resetPasswordMutation.reset();
    setResetTarget(null);
    setResetPassword("");
    setShowResetPassword(false);
    setResetCopyState("idle");
  }

  function openChatActivity(user: UserAdmin) {
    setSelectedChatSessionId(null);
    setChatActivityTarget(user);
  }

  function closeChatActivity() {
    setChatActivityTarget(null);
    setSelectedChatSessionId(null);
  }

  function updateUserSpaces(groupPath: string, checked: boolean) {
    setUserDraft((draft) => ({
      ...draft,
      groupPaths: nextSelectedGroups(draft.groupPaths, groupPath, checked, groupOptions),
    }));
  }

  function regeneratePassword() {
    setUserDraft((draft) => ({ ...draft, initialPassword: generateInitialPassword() }));
    setShowInitialPassword(false);
    setCopyState("idle");
  }

  function updateInitialPassword(initialPassword: string) {
    setUserDraft((draft) => ({ ...draft, initialPassword }));
    setCopyState("idle");
  }

  async function copyInitialPassword() {
    try {
      await navigator.clipboard.writeText(userDraft.initialPassword);
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 1800);
    } catch {
      setCopyState("failed");
    }
  }

  async function copyResetPassword() {
    try {
      await navigator.clipboard.writeText(resetPassword);
      setResetCopyState("copied");
      window.setTimeout(() => setResetCopyState("idle"), 1800);
    } catch {
      setResetCopyState("failed");
    }
  }

  function submitUserForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!panel || createdUserEmail) return;
    if (panel.kind === "create-user") {
      createUserMutation.mutate(userDraft);
      return;
    }
    updateUserMutation.mutate({ draft: userDraft, userId: panel.user.id });
  }

  return (
    <PrudentiaBasicPage
      activeRoute="access"
      onLogout={onLogout}
      onNavigate={onNavigate}
      title="User Management"
      subtitle="Create users, control account state, and assign Knowledge Spaces for retrieval access."
      user={currentUser}
    >
      <div className="grid gap-3 md:grid-cols-3">
        <AccessMetric label="Provisioned users" value={String(users.length)} loading={usersQuery.isLoading} />
        <AccessMetric label="Active users" value={String(users.filter((user) => user.is_active).length)} loading={usersQuery.isLoading} />
        <AccessMetric label="Knowledge spaces" value={String(groupOptions.length)} loading={groupsQuery.isLoading} />
      </div>

      <section className="sv-card mt-5 overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-surface-border p-4">
          <div>
            <h2 className="sv-section-title">Users</h2>
            <p className="text-body-md text-on-surface-variant">API-backed user inventory and Knowledge Space assignment state.</p>
          </div>
          <button type="button" onClick={openCreateUser} className="sv-action-primary">
            <Plus size={16} /> Create user
          </button>
        </div>
        <div className="border-b border-surface-border p-4">
          <label className="relative block max-w-xl">
            <span className="sr-only">Search users</span>
            <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant" />
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search by name, email, or space..." className="sv-input sv-input-with-leading-icon" />
          </label>
        </div>
        {usersQuery.isError ? <InlineMessage tone="error">{errorMessage(usersQuery.error, "Unable to load users.")}</InlineMessage> : null}
        {groupsQuery.isError ? <InlineMessage tone="warning">{errorMessage(groupsQuery.error, "Unable to load Knowledge Spaces for assignment.")}</InlineMessage> : null}
        <div className="sv-table-wrap">
          <table className="sv-table user-management-table">
            <thead>
              <tr>
                <th>User</th>
                <th>Role</th>
                <th>Clearance</th>
                <th>Status</th>
                <th>Knowledge Spaces</th>
                <th>Permission</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((user) => (
                <tr key={user.id} className="sv-table-row">
                  <td>
                    <strong className="text-on-surface">{user.name}</strong>
                    <small className="block text-secondary">{user.email}</small>
                    {user.id === currentUser.user_id ? <small className="mt-1 block font-semibold text-primary">Current session</small> : null}
                  </td>
                  <td>
                    <strong className="block text-on-surface">{accountTypeLabel(user.account_type)}</strong>
                    <small className="text-secondary">{roleDescription(user.account_type)}</small>
                  </td>
                  <td>
                    <span className="sv-pill">{clearanceLevelLabel(user.clearance_level)}</span>
                  </td>
                  <td>{user.is_active ? <span className="sv-pill sv-pill-success">Active</span> : <span className="sv-pill">Inactive</span>}</td>
                  <td>
                    <SpacePathList paths={user.group_paths} />
                  </td>
                  <td className="font-semibold text-on-surface">v{user.permission_version}</td>
                  <td>
                    <div className="user-row-actions" aria-label={`Actions for ${user.email}`}>
                      <button type="button" onClick={() => openEditUser(user)} className="user-row-action" aria-label={`Edit ${user.email}`} title="Edit user">
                        <Edit3 size={15} aria-hidden="true" />
                        <span className="sr-only">Edit user</span>
                      </button>
                      {user.id !== currentUser.user_id ? (
                        <button type="button" onClick={() => openResetPassword(user)} className="user-row-action" aria-label={`Reset password for ${user.email}`} title="Reset password">
                          <KeyRound size={15} aria-hidden="true" />
                          <span className="sr-only">Reset password</span>
                        </button>
                      ) : null}
                      {canViewChatActivity ? (
                        <button type="button" onClick={() => openChatActivity(user)} className="user-row-action" aria-label={`View chat activity for ${user.email}`} title="Chat activity">
                          <MessageSquareText size={15} aria-hidden="true" />
                          <span className="sr-only">Chat activity</span>
                        </button>
                      ) : null}
                      {user.id !== currentUser.user_id ? (
                        <button type="button" onClick={() => openDeleteUser(user)} className="user-row-action user-row-action-danger" aria-label={`Delete ${user.email}`} title="Delete user">
                          <Trash2 size={15} aria-hidden="true" />
                          <span className="sr-only">Delete user</span>
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
              {usersQuery.isLoading ? (
                <UserTableSkeleton />
              ) : null}
            </tbody>
          </table>
        </div>
        {!usersQuery.isLoading && filteredUsers.length === 0 ? (
          <div className="p-4">
            <EmptyPanel>No users match the selected filters.</EmptyPanel>
          </div>
        ) : null}
      </section>

      <Modal
        description={panel?.kind === "create-user" ? "Generate credentials and assign the first Knowledge Spaces." : "Update account state and Knowledge Space memberships."}
        icon={<UserCog size={18} />}
        onClose={closePanel}
        open={Boolean(panel)}
        size="lg"
        title={panel?.kind === "create-user" ? "Create user" : "Edit user"}
      >
        {panel ? (
          <UserPanel
            copyState={copyState}
            createdUserEmail={createdUserEmail}
            draft={userDraft}
            accountTypes={assignableAccountTypes}
            clearanceLevels={assignableClearanceLevels}
            groupOptions={groupOptions}
            isCreate={panel.kind === "create-user"}
            isPending={createUserMutation.isPending || updateUserMutation.isPending}
            mutationError={
              panel.kind === "create-user"
                ? createUserMutation.isError
                  ? createUserMutation.error
                  : null
                : updateUserMutation.isError
                  ? updateUserMutation.error
                  : null
            }
            onChange={setUserDraft}
            onClose={closePanel}
            onCopyPassword={() => void copyInitialPassword()}
            onCreateAnother={openCreateUser}
            onInitialPasswordChange={updateInitialPassword}
            onRegeneratePassword={regeneratePassword}
            onSpaceToggle={updateUserSpaces}
            onSubmit={submitUserForm}
            onTogglePassword={() => setShowInitialPassword((value) => !value)}
            showInitialPassword={showInitialPassword}
          />
        ) : null}
      </Modal>

      <Modal
        description={chatActivityTarget ? `Saved sessions for ${chatActivityTarget.email}.` : "Saved chat sessions for the selected user."}
        icon={<MessageSquareText size={18} />}
        onClose={closeChatActivity}
        open={Boolean(chatActivityTarget)}
        size="lg"
        title="Chat activity"
      >
        {chatActivityTarget ? (
          <ChatActivityPanel
            error={chatActivityQuery.isError ? errorMessage(chatActivityQuery.error, "Unable to load chat activity.") : null}
            loading={chatActivityQuery.isLoading}
            onSelectSession={setSelectedChatSessionId}
            selectedSession={selectedChatSessionQuery.data ?? null}
            selectedSessionError={selectedChatSessionQuery.isError ? errorMessage(selectedChatSessionQuery.error, "Unable to load chat session.") : null}
            selectedSessionId={selectedChatSessionId}
            selectedSessionLoading={selectedChatSessionQuery.isLoading}
            sessions={chatActivityQuery.data?.items ?? []}
            target={chatActivityTarget}
            total={chatActivityQuery.data?.total ?? 0}
          />
        ) : null}
      </Modal>

      <Modal
        description={resetTarget ? `Set a temporary password for ${resetTarget.email}. Existing sessions will be signed out.` : "Set a temporary password for the selected account."}
        icon={<KeyRound size={18} />}
        onClose={closeResetPassword}
        open={Boolean(resetTarget)}
        size="sm"
        title="Reset password"
      >
        {resetTarget ? (
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (resetPassword.length >= 8) resetPasswordMutation.mutate({ userId: resetTarget.id, temporaryPassword: resetPassword });
            }}
          >
            <ReadOnlyField label="Account" value={resetTarget.email} />
            <div className="sv-field">
              <span className="sv-label">Temporary password</span>
              <div className="flex gap-2">
                <div className="relative min-w-0 flex-1">
                  <KeyRound size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant" />
                  <input
                    autoComplete="new-password"
                    className="sv-input sv-input-with-leading-icon text-code-sm"
                    disabled={resetPasswordMutation.isPending || resetPasswordMutation.isSuccess}
                    minLength={8}
                    onChange={(event) => {
                      setResetPassword(event.target.value);
                      setResetCopyState("idle");
                      resetPasswordMutation.reset();
                    }}
                    required
                    type={showResetPassword ? "text" : "password"}
                    value={resetPassword}
                  />
                </div>
                <button type="button" onClick={() => setShowResetPassword((value) => !value)} className="sv-action-secondary min-h-11 px-3" aria-label={showResetPassword ? "Hide temporary password" : "Show temporary password"}>
                  {showResetPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => void copyResetPassword()} className="sv-action-secondary min-h-9 px-3">
                  {resetCopyState === "copied" ? <Check size={15} /> : <Copy size={15} />} {resetCopyState === "copied" ? "Copied" : "Copy"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setResetPassword(generateInitialPassword());
                    setShowResetPassword(false);
                    setResetCopyState("idle");
                    resetPasswordMutation.reset();
                  }}
                  disabled={resetPasswordMutation.isPending || resetPasswordMutation.isSuccess}
                  className="sv-action-secondary min-h-9 px-3 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <RefreshCw size={15} /> Regenerate
                </button>
              </div>
              {resetCopyState === "failed" ? <small className="text-error-red">Clipboard access is unavailable. Reveal and copy the password manually.</small> : null}
              <small className="text-secondary">The user will be required to change this after signing in.</small>
            </div>
            {resetPasswordMutation.isError ? <InlineMessage tone="error">{errorMessage(resetPasswordMutation.error, "Unable to reset password.")}</InlineMessage> : null}
            {resetPasswordMutation.isSuccess ? <InlineMessage tone="success">Password reset. Copy the temporary password before closing this dialog.</InlineMessage> : null}
            <div className="flex flex-wrap justify-end gap-2 border-t border-surface-border pt-4">
              <button type="button" onClick={closeResetPassword} disabled={resetPasswordMutation.isPending} className="sv-action-secondary">
                {resetPasswordMutation.isSuccess ? "Done" : "Cancel"}
              </button>
              {!resetPasswordMutation.isSuccess ? (
                <button
                  type="submit"
                  disabled={resetPassword.length < 8 || resetPasswordMutation.isPending}
                  className="sv-action-primary disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <KeyRound size={16} /> {resetPasswordMutation.isPending ? "Resetting" : "Reset password"}
                </button>
              ) : null}
            </div>
          </form>
        ) : null}
      </Modal>

      <Modal
        description="This permanently removes the account, its memberships, chat history, and generated artifacts. Documents and audit history are retained."
        icon={<AlertTriangle size={18} />}
        onClose={closeDeleteUser}
        open={Boolean(deleteTarget)}
        size="sm"
        title="Delete user"
      >
        {deleteTarget ? (
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (deleteConfirmation === deleteTarget.email) deleteUserMutation.mutate(deleteTarget.id);
            }}
          >
            <ReadOnlyField label="Account" value={deleteTarget.email} />
            <label className="sv-field" htmlFor="delete-user-confirmation">
              <span className="sv-label">Type the email address to confirm</span>
              <input
                autoComplete="off"
                className="sv-input"
                disabled={deleteUserMutation.isPending}
                id="delete-user-confirmation"
                onChange={(event) => setDeleteConfirmation(event.target.value)}
                value={deleteConfirmation}
              />
            </label>
            <div className="flex flex-wrap justify-end gap-2 border-t border-surface-border pt-4">
              <button type="button" onClick={closeDeleteUser} disabled={deleteUserMutation.isPending} className="sv-action-secondary">
                Cancel
              </button>
              <button
                type="submit"
                disabled={deleteConfirmation !== deleteTarget.email || deleteUserMutation.isPending}
                className="sv-action-danger disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Trash2 size={16} /> {deleteUserMutation.isPending ? "Deleting" : "Delete user"}
              </button>
            </div>
          </form>
        ) : null}
      </Modal>
    </PrudentiaBasicPage>
  );
}

function UserPanel({
  clearanceLevels,
  copyState,
  createdUserEmail,
  draft,
  accountTypes,
  groupOptions,
  isCreate,
  isPending,
  mutationError,
  onChange,
  onClose,
  onCopyPassword,
  onCreateAnother,
  onInitialPasswordChange,
  onRegeneratePassword,
  onSpaceToggle,
  onSubmit,
  onTogglePassword,
  showInitialPassword,
}: UserPanelProps) {
  const createComplete = isCreate && Boolean(createdUserEmail);
  const canSubmit = draft.name.trim().length > 0 && (!isCreate || (draft.email.trim().length > 0 && draft.initialPassword.length >= 8));

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {isCreate ? (
        <TextField
          autoComplete="off"
          disabled={createComplete || isPending}
          helper="Used for sign-in and audit attribution."
          label="Email"
          onChange={(value) => onChange((current) => ({ ...current, email: value }))}
          required
          type="email"
          value={draft.email}
        />
      ) : (
        <ReadOnlyField label="Email" value={draft.email} />
      )}

      <TextField
        autoComplete="off"
        disabled={createComplete || isPending}
        helper="Shown in admin lists and account dialogs."
        label="Name"
        onChange={(value) => onChange((current) => ({ ...current, name: value }))}
        required
        value={draft.name}
      />

      <AccountTypePicker
        accountTypes={accountTypes}
        disabled={createComplete || isPending}
        value={draft.accountType}
        onChange={(accountType) => onChange((current) => ({
          ...current,
          accountType,
          clearanceLevel: isGlobalAccountType(accountType) ? "COSMIC_TOP_SECRET" : current.clearanceLevel,
        }))}
      />

      <ClearanceLevelPicker
        clearanceLevels={clearanceLevels}
        disabled={createComplete || isPending || isGlobalAccountType(draft.accountType)}
        lockedByGlobalRole={isGlobalAccountType(draft.accountType)}
        value={draft.clearanceLevel}
        onChange={(clearanceLevel) => onChange((current) => ({ ...current, clearanceLevel }))}
      />

      {isCreate ? (
        <div className="sv-field">
          <span className="sv-label">Initial password</span>
          <div className="flex gap-2">
            <div className="relative min-w-0 flex-1">
              <KeyRound size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant" />
              <input
                autoComplete="new-password"
                className="sv-input sv-input-with-leading-icon text-code-sm"
                disabled={createComplete || isPending}
                minLength={8}
                onChange={(event) => onInitialPasswordChange(event.target.value)}
                required
                type={showInitialPassword ? "text" : "password"}
                value={draft.initialPassword}
              />
            </div>
            <button type="button" onClick={onTogglePassword} className="sv-action-secondary min-h-11 px-3" aria-label={showInitialPassword ? "Hide initial password" : "Show initial password"}>
              {showInitialPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={onCopyPassword} className="sv-action-secondary min-h-9 px-3">
              {copyState === "copied" ? <Check size={15} /> : <Copy size={15} />} {copyState === "copied" ? "Copied" : "Copy"}
            </button>
            <button type="button" onClick={onRegeneratePassword} disabled={createComplete || isPending} className="sv-action-secondary min-h-9 px-3 disabled:cursor-not-allowed disabled:opacity-60">
              <RefreshCw size={15} /> Regenerate
            </button>
          </div>
          {copyState === "failed" ? <small className="text-error-red">Clipboard access is unavailable. Reveal and copy the password manually.</small> : null}
          <small className="text-secondary">Share once with the new user; they can change it after sign-in.</small>
        </div>
      ) : null}

      <label className="flex items-center gap-3 rounded-lg border border-surface-border bg-surface-container-low p-3 text-body-md text-on-surface">
        <input
          type="checkbox"
          checked={draft.isActive}
          disabled={createComplete || isPending}
          onChange={(event) => onChange((current) => ({ ...current, isActive: event.target.checked }))}
        />
        Active account
      </label>
      <small className="block text-secondary">Disable to block sign-in without removing memberships.</small>

      <SpacePicker disabled={createComplete || isPending} groupOptions={groupOptions} onToggle={onSpaceToggle} selectedPaths={draft.groupPaths} />

      {mutationError ? <InlineMessage tone="error">{errorMessage(mutationError, isCreate ? "Unable to create user." : "Unable to update user.")}</InlineMessage> : null}
      {createdUserEmail ? <InlineMessage tone="success">User {createdUserEmail} was created. Copy the initial password before leaving this dialog.</InlineMessage> : null}

      <div className="flex flex-wrap justify-end gap-2 border-t border-surface-border pt-4">
        {createdUserEmail ? (
          <>
            <button type="button" onClick={onCreateAnother} className="sv-action-secondary">
              <Plus size={16} /> Create another
            </button>
            <button type="button" onClick={onClose} className="sv-action-primary">
              Done
            </button>
          </>
        ) : (
          <>
            <button type="button" onClick={onClose} className="sv-action-secondary" disabled={isPending}>
              Cancel
            </button>
            <button type="submit" disabled={!canSubmit || isPending} className="sv-action-primary disabled:cursor-not-allowed disabled:opacity-60">
              {isPending ? "Saving" : isCreate ? "Create user" : "Save user"}
            </button>
          </>
        )}
      </div>
    </form>
  );
}

function ChatActivityPanel({
  error,
  loading,
  onSelectSession,
  selectedSession,
  selectedSessionError,
  selectedSessionId,
  selectedSessionLoading,
  sessions,
  target,
  total,
}: ChatActivityPanelProps) {
  return (
    <div className="admin-chat-activity">
      <div className="admin-chat-activity-header">
        <div>
          <span className="sv-metadata">Account</span>
          <h3>{target.name}</h3>
          <p>{target.email}</p>
        </div>
        <div>
          <span className="sv-metadata">Current permission</span>
          <strong>v{target.permission_version}</strong>
          <small>{total} saved session{total === 1 ? "" : "s"}</small>
        </div>
      </div>

      <div className="admin-chat-activity-grid">
        <section className="admin-chat-session-panel" aria-label="Saved chat sessions">
          <div className="admin-chat-panel-heading">
            <h3>Saved sessions</h3>
            <p>{loading ? "Loading" : `${sessions.length} shown`}</p>
          </div>
          {error ? <InlineMessage tone="error">{error}</InlineMessage> : null}
          {loading ? <ChatActivitySkeleton /> : null}
          {!loading && !error && sessions.length === 0 ? <EmptyPanel>No saved chat sessions for this permission version.</EmptyPanel> : null}
          {!loading && sessions.length > 0 ? (
            <div className="admin-chat-session-list">
              {sessions.map((session) => (
                <button
                  aria-pressed={selectedSessionId === session.id}
                  className={selectedSessionId === session.id ? "admin-chat-session-item is-active" : "admin-chat-session-item"}
                  key={session.id}
                  onClick={() => onSelectSession(session.id)}
                  type="button"
                >
                  <strong>{session.title}</strong>
                  <small>{session.questionCount} question{session.questionCount === 1 ? "" : "s"} | Updated {formatDateTime(session.updatedAt)}</small>
                </button>
              ))}
            </div>
          ) : null}
        </section>

        <section className="admin-chat-transcript-panel" aria-label="Selected chat transcript">
          {!selectedSessionId ? (
            <EmptyPanel>Select a saved session to inspect the transcript.</EmptyPanel>
          ) : selectedSessionLoading ? (
            <ChatActivitySkeleton />
          ) : selectedSessionError ? (
            <InlineMessage tone="error">{selectedSessionError}</InlineMessage>
          ) : selectedSession ? (
            <ChatTranscript session={selectedSession} />
          ) : null}
        </section>
      </div>
    </div>
  );
}

function ChatTranscript({ session }: { session: SavedChatSession }) {
  return (
    <div className="admin-chat-transcript">
      <header>
        <h3>{session.title}</h3>
        <p>{session.questionCount} question{session.questionCount === 1 ? "" : "s"} | {formatDateTime(session.createdAt)} to {formatDateTime(session.updatedAt)}</p>
      </header>
      <div className="admin-chat-turn-list">
        {session.turns.map((turn) => (
          <ChatTurnItem key={turn.id} turn={turn} />
        ))}
      </div>
      {session.turns.length === 0 ? <EmptyPanel>This saved session does not contain transcript turns.</EmptyPanel> : null}
    </div>
  );
}

function ChatTurnItem({ turn }: { turn: ChatTurn }) {
  const isAssistant = turn.role === "assistant";
  return (
    <article className={isAssistant ? "admin-chat-turn admin-chat-turn-assistant" : "admin-chat-turn admin-chat-turn-user"}>
      <div>
        <strong>{isAssistant ? "Assistant" : "User"}</strong>
        <small>{formatDateTime(turn.createdAt)}</small>
      </div>
      <p>{chatTurnContent(turn)}</p>
      {isAssistant && turn.response ? (
        <footer>
          <span>{turn.response.intent.replace(/_/g, " ")}</span>
          <span>{turn.response.sources.length} source{turn.response.sources.length === 1 ? "" : "s"}</span>
          {turn.groupPath ? <span>{turn.groupPath}</span> : null}
        </footer>
      ) : null}
    </article>
  );
}

function chatTurnContent(turn: ChatTurn): string {
  if (turn.role === "user") return turn.content;
  if (turn.response?.answer) return turn.response.answer;
  if (turn.streamText) return turn.streamText;
  if (turn.errorMessage) return turn.errorMessage;
  return "Assistant response unavailable.";
}

function ChatActivitySkeleton() {
  return (
    <div className="grid gap-2">
      {Array.from({ length: 3 }, (_, index) => (
        <Skeleton className="h-14 w-full" key={index} />
      ))}
    </div>
  );
}

function SpacePicker({ disabled, groupOptions, onToggle, selectedPaths }: SpacePickerProps) {
  if (groupOptions.length === 0) return <EmptyPanel>No Knowledge Spaces are available for assignment.</EmptyPanel>;

  return (
    <fieldset className="space-y-2">
      <legend className="sv-label">Knowledge Space memberships</legend>
      <p className="text-body-md text-secondary">Selected spaces control retrieval scope and upload access.</p>
      <div className="max-h-72 overflow-auto rounded-lg border border-surface-border bg-surface-container-low p-2">
        {groupOptions.map((group) => (
          <label key={group.path} className="flex items-start gap-3 rounded-md p-2 text-body-md text-on-surface hover:bg-surface-container-high" style={{ paddingLeft: `${0.5 + group.depth * 1}rem` }}>
            <input type="checkbox" checked={selectedPaths.includes(group.path)} disabled={disabled} onChange={(event) => onToggle(group.path, event.target.checked)} />
            <span className="min-w-0">
              <span className="block font-semibold">{group.name}</span>
              <small className="block break-all text-secondary">{group.path}</small>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function AccountTypePicker({ accountTypes, disabled, onChange, value }: AccountTypePickerProps) {
  return (
    <label className="sv-field" htmlFor="account-type">
      <span className="sv-label">Account type</span>
      <select
        className="sv-select"
        disabled={disabled}
        id="account-type"
        onChange={(event) => onChange(event.target.value as AccountType)}
        value={value}
      >
        {accountTypes.map((accountType) => (
          <option key={accountType} value={accountType}>
            {accountTypeLabel(accountType)}
          </option>
        ))}
      </select>
      <small className="text-secondary">{roleDescription(value)}</small>
    </label>
  );
}

function ClearanceLevelPicker({ clearanceLevels, disabled, lockedByGlobalRole, onChange, value }: ClearanceLevelPickerProps) {
  return (
    <label className="sv-field" htmlFor="clearance-level">
      <span className="sv-label">Clearance level</span>
      <select
        className="sv-select"
        disabled={disabled}
        id="clearance-level"
        onChange={(event) => onChange(event.target.value as ClearanceLevel)}
        value={value}
      >
        {clearanceLevels.map((clearanceLevel) => (
          <option key={clearanceLevel} value={clearanceLevel}>
            {clearanceLevelLabel(clearanceLevel)}
          </option>
        ))}
      </select>
      <small className="text-secondary">
        {lockedByGlobalRole
          ? "Global administrator accounts are always Top Secret."
          : clearanceLevelDescription(value)}
      </small>
    </label>
  );
}

function SpacePathList({ paths }: { paths: string[] }) {
  if (paths.length === 0) return <span className="text-secondary">No spaces</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {paths.map((path) => (
        <span key={path} className="sv-pill">
          {path}
        </span>
      ))}
    </div>
  );
}

function AccessMetric({ label, loading, value }: { label: string; loading: boolean; value: string }) {
  return (
    <div className="sv-metric" aria-busy={loading} data-cursor-glow>
      <div className="flex items-center gap-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Users size={17} />
        </span>
        <span>
          <span className="block text-label-md text-secondary">{label}</span>
          {loading ? (
            <>
              <span className="sr-only">Loading {label.toLowerCase()}</span>
              <Skeleton className="mt-1 h-5 w-12" />
            </>
          ) : <strong className="text-body-lg text-on-surface">{value}</strong>}
        </span>
      </div>
    </div>
  );
}

function UserTableSkeleton() {
  return (
    <>
      {Array.from({ length: 4 }, (_, index) => (
        <tr key={index}>
          <td colSpan={7}>
            <div className="grid gap-2 py-1">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-64 max-w-full" />
            </div>
          </td>
        </tr>
      ))}
    </>
  );
}

function TextField({ autoComplete, disabled, helper, label, onChange, required, type = "text", value }: TextFieldProps) {
  const id = label.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return (
    <label className="sv-field" htmlFor={id}>
      <span className="sv-label">{label}</span>
      <input autoComplete={autoComplete} className="sv-input" disabled={disabled} id={id} onChange={(event) => onChange(event.target.value)} required={required} type={type} value={value} />
      {helper ? <small className="text-secondary">{helper}</small> : null}
    </label>
  );
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="sv-metadata">{label}</span>
      <p className="mt-1 break-all rounded-lg border border-surface-border bg-surface-container-low p-3 text-body-md font-semibold text-on-surface">{value}</p>
    </div>
  );
}

function matchesUser(user: UserAdmin, search: string): boolean {
  const query = search.toLowerCase().trim();
  if (!query) return true;
  return (
    user.name.toLowerCase().includes(query) ||
    user.email.toLowerCase().includes(query) ||
    accountTypeLabel(user.account_type).toLowerCase().includes(query) ||
    clearanceLevelLabel(user.clearance_level).toLowerCase().includes(query) ||
    user.group_paths.some((path) => path.toLowerCase().includes(query))
  );
}

function createUserDraft(clearanceLevel: ClearanceLevel): UserDraft {
  return {
    accountType: "member",
    clearanceLevel,
    email: "",
    groupPaths: [],
    initialPassword: generateInitialPassword(),
    isActive: true,
    name: "",
  };
}

function defaultAssignableClearance(user: AuthUser): ClearanceLevel {
  const assignable = clearanceLevelsAssignableBy(user);
  if (assignable.includes(defaultClearanceLevel)) return defaultClearanceLevel;
  return assignable.at(-1) ?? defaultClearanceLevel;
}

function isGlobalAccountType(accountType: AccountType): boolean {
  return accountType === "platform_admin" || accountType === "system_admin";
}

function generateInitialPassword(length = 16): string {
  const requiredSets = ["ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnopqrstuvwxyz", "23456789", "!@#$%"];
  const allCharacters = requiredSets.join("");
  const characters = [
    ...requiredSets.map((set) => pickCharacter(set)),
    ...Array.from({ length: Math.max(0, length - requiredSets.length) }, () => pickCharacter(allCharacters)),
  ];

  for (let index = characters.length - 1; index > 0; index -= 1) {
    const swapIndex = randomIndex(index + 1);
    [characters[index], characters[swapIndex]] = [characters[swapIndex], characters[index]];
  }

  return characters.join("");
}

function pickCharacter(characters: string): string {
  return characters[randomIndex(characters.length)];
}

function randomIndex(max: number): number {
  if (typeof crypto !== "undefined" && crypto.getRandomValues) {
    const values = new Uint32Array(1);
    crypto.getRandomValues(values);
    return values[0] % max;
  }
  return Math.floor(Math.random() * max);
}

type Props = {
  currentUser: AuthUser;
  onAuthChanged: () => void;
  onLogout: () => void;
  onNavigate: (route: RouteId) => void;
};

type CopyState = "idle" | "copied" | "failed";
type UserPanelState = { kind: "create-user" } | { kind: "edit-user"; user: UserAdmin } | null;

type UserDraft = {
  accountType: AccountType;
  clearanceLevel: ClearanceLevel;
  email: string;
  groupPaths: string[];
  initialPassword: string;
  isActive: boolean;
  name: string;
};

type UserPanelProps = {
  accountTypes: AccountType[];
  clearanceLevels: ClearanceLevel[];
  copyState: CopyState;
  createdUserEmail: string | null;
  draft: UserDraft;
  groupOptions: GroupOption[];
  isCreate: boolean;
  isPending: boolean;
  mutationError: unknown;
  onChange: Dispatch<SetStateAction<UserDraft>>;
  onClose: () => void;
  onCopyPassword: () => void;
  onCreateAnother: () => void;
  onInitialPasswordChange: (initialPassword: string) => void;
  onRegeneratePassword: () => void;
  onSpaceToggle: (groupPath: string, checked: boolean) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onTogglePassword: () => void;
  showInitialPassword: boolean;
};

type ChatActivityPanelProps = {
  error: string | null;
  loading: boolean;
  onSelectSession: (sessionId: string) => void;
  selectedSession: SavedChatSession | null;
  selectedSessionError: string | null;
  selectedSessionId: string | null;
  selectedSessionLoading: boolean;
  sessions: SavedChatSessionSummary[];
  target: UserAdmin;
  total: number;
};

type TextFieldProps = {
  autoComplete?: string;
  disabled?: boolean;
  helper?: string;
  label: string;
  onChange: (value: string) => void;
  required?: boolean;
  type?: string;
  value: string;
};

type SpacePickerProps = {
  disabled?: boolean;
  groupOptions: GroupOption[];
  onToggle: (groupPath: string, checked: boolean) => void;
  selectedPaths: string[];
};

type AccountTypePickerProps = {
  accountTypes: AccountType[];
  disabled?: boolean;
  onChange: (accountType: AccountType) => void;
  value: AccountType;
};

type ClearanceLevelPickerProps = {
  clearanceLevels: ClearanceLevel[];
  disabled?: boolean;
  lockedByGlobalRole: boolean;
  onChange: (clearanceLevel: ClearanceLevel) => void;
  value: ClearanceLevel;
};
