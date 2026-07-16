import type { AccountType, ClearanceLevel, ISODateString } from "./common";

export interface User {
  user_id: string;
  email: string;
  account_type: AccountType;
  group_paths: string[];
  clearance_level: ClearanceLevel;
  permission_version: number;
  must_change_password?: boolean;
}

export interface UserAdmin {
  id: string;
  email: string;
  name: string;
  account_type: AccountType;
  group_paths: string[];
  clearance_level: ClearanceLevel;
  last_login_at: ISODateString | null;
  is_active: boolean;
  permission_version: number;
}

export interface LoginResponse {
  user: User;
  csrf_token: string;
}
