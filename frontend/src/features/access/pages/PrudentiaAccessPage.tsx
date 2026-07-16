import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Eye, EyeOff, KeyRound, MessageSquareText, RefreshCw, UserCog } from "lucide-react";

import { adminApi } from "@/lib/api/contracts";
import {
  accountTypeOptions,
  canAssignAccountType,
  clearanceLevelsAssignableBy,
  isGlobalAdmin,
} from "@/lib/auth/authz";
import { useToast } from "@/components/feedback/ToastProvider";
import { InlineMessage } from "@/components/layout/Common";
import { PrudentiaBasicPage } from "@/components/layout/PrudentiaWorkspace";
import { Modal } from "@/components/layout/Modal";
import type { RouteId } from "@/routes/routes";
import type { User as AuthUser, UserAdmin } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";
import { flattenGroups, nextSelectedGroups, userSpacesFromPaths } from "@/lib/utils/groups";
import {
  type CopyState,
  type UserDraft,
  type UserPanelState,
  createUserDraft,
  defaultAssignableClearance,
  generateInitialPassword,
  matchesUser,
} from "@/features/access/utils/accessUserUtils";
import { ReadOnlyField, UserPanel } from "@/features/access/components/AccessUserPanel";
import { ChatActivityPanel } from "@/features/access/components/ChatActivityPanel";
import { AccessMetric } from "@/features/access/components/AccessPagePrimitives";
import { AccessUsersTable } from "@/features/access/components/AccessUsersTable";
import { DeleteUserDialog } from "@/features/access/components/DeleteUserDialog";


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

      <AccessUsersTable
        canViewChatActivity={canViewChatActivity}
        currentUser={currentUser}
        groupsError={groupsQuery.error}
        groupsFailed={groupsQuery.isError}
        loading={usersQuery.isLoading}
        search={search}
        users={filteredUsers}
        usersError={usersQuery.error}
        usersFailed={usersQuery.isError}
        onChatActivity={openChatActivity}
        onCreate={openCreateUser}
        onDelete={openDeleteUser}
        onEdit={openEditUser}
        onResetPassword={openResetPassword}
        onSearchChange={setSearch}
      />

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

      <DeleteUserDialog
        confirmation={deleteConfirmation}
        isPending={deleteUserMutation.isPending}
        onClose={closeDeleteUser}
        onConfirmationChange={setDeleteConfirmation}
        onDelete={(userId) => deleteUserMutation.mutate(userId)}
        target={deleteTarget}
      />
    </PrudentiaBasicPage>
  );
}

type Props = {
  currentUser: AuthUser;
  onAuthChanged: () => void;
  onLogout: () => void;
  onNavigate: (route: RouteId) => void;
};
