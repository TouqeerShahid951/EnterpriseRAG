import type { LoginResponse, User } from "@/types/api";
import { apiClient } from "./apiClient";

export interface LoginRequest {
  email: string;
  password: string;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export const authApi = {
  login: async (request: LoginRequest) => {
    const response = await apiClient.postJson<LoginResponse>("/api/v1/auth/login", request);
    return { ...response, user: normalizeUser(response.user) };
  },
  currentUser: async () => normalizeUser(await apiClient.get<User>("/api/v1/auth/me", { timeoutMs: 8000 })),
  refresh: async () => {
    const response = await apiClient.postJson<LoginResponse>("/api/v1/auth/refresh", null);
    return { ...response, user: normalizeUser(response.user) };
  },
  logout: () => apiClient.postJson<void>("/api/v1/auth/logout", null),
  changePassword: async (request: ChangePasswordRequest) => normalizeUser(await apiClient.postJson<User>("/api/v1/auth/change-password", request)),
};

function normalizeUser(user: User): User {
  const legacyUser = user as User & { id?: string };
  return {
    ...user,
    user_id: user.user_id ?? legacyUser.id ?? "",
    email: user.email ?? "",
    account_type: user.account_type ?? "member",
    group_paths: Array.isArray(user.group_paths) ? user.group_paths : [],
    clearance_level: user.clearance_level ?? "NATO_RESTRICTED",
    permission_version: user.permission_version ?? 0,
    must_change_password: Boolean(user.must_change_password),
  };
}
