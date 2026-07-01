"""PostgreSQL identity repository."""

from __future__ import annotations

from ..auth.abac import normalize_group_path
from ..auth.permissions import AccountType, effective_clearance_level, normalize_account_type
from ..shared.contracts.clearance import ClearanceLevel, normalize_clearance_level
from ..shared.contracts.group_paths import require_flat_group_path
from .identity_models import GroupRecord, UserRecord
from .postgres import PostgresConnectionMixin


class PostgresIdentityRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def count_users(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
            return int(row["count"])

    def create_initial_admin_if_empty(
        self,
        *,
        email: str,
        name: str,
        password_hash: str,
    ) -> UserRecord | None:
        with self._connect() as conn:
            with conn.transaction():
                conn.execute("LOCK TABLE users IN EXCLUSIVE MODE")
                if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                    return None
                row = conn.execute(
                    """
                    INSERT INTO users (email, name, password_hash, is_active, account_type, clearance_level)
                    VALUES (%s, %s, %s, TRUE, 'platform_admin', 'COSMIC_TOP_SECRET')
                    RETURNING id::text, email, name, password_hash, is_active, account_type, clearance_level,
                              must_change_password, permission_version, last_login_at
                    """,
                    (email.strip().lower(), name.strip(), password_hash),
                ).fetchone()
                return self._user_from_row(conn, row)

    def get_user_by_email(self, email: str) -> UserRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id::text, email, name, password_hash, is_active, account_type, clearance_level,
                       must_change_password, permission_version, last_login_at
                FROM users
                WHERE lower(email) = lower(%s)
                """,
                (email.strip(),),
            ).fetchone()
            return self._user_from_row(conn, row)

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id::text, email, name, password_hash, is_active, account_type, clearance_level,
                       must_change_password, permission_version, last_login_at
                FROM users
                WHERE id = %s
                """,
                (user_id,),
            ).fetchone()
            return self._user_from_row(conn, row)

    def list_users(self) -> list[UserRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id::text, email, name, password_hash, is_active, account_type, clearance_level,
                       must_change_password, permission_version, last_login_at
                FROM users
                ORDER BY lower(email)
                """
            ).fetchall()
            return [user for row in rows if (user := self._user_from_row(conn, row))]

    def create_user(
        self,
        *,
        email: str,
        name: str,
        password_hash: str,
        group_paths: list[str],
        is_active: bool,
        account_type: AccountType | None = None,
        clearance_level: ClearanceLevel | None = None,
    ) -> UserRecord:
        if self.get_user_by_email(email):
            raise ValueError("email already exists")
        groups = self._normalize_existing_groups(group_paths)
        normalized_account_type = normalize_account_type(account_type, groups)
        normalized_clearance = effective_clearance_level(normalized_account_type, clearance_level)
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    """
                    INSERT INTO users (email, name, password_hash, is_active, account_type, clearance_level)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id::text, email, name, password_hash, is_active, account_type, clearance_level,
                              must_change_password, permission_version, last_login_at
                    """,
                    (email.strip().lower(), name.strip(), password_hash, is_active, normalized_account_type, normalized_clearance),
                ).fetchone()
                for group_path in groups:
                    conn.execute(
                        "INSERT INTO user_groups (user_id, group_path) VALUES (%s, %s)",
                        (row["id"], group_path),
                    )
            return self.get_user_by_id(row["id"])  # type: ignore[return-value]

    def update_user(
        self,
        user_id: str,
        *,
        name: str | None = None,
        group_paths: list[str] | None = None,
        is_active: bool | None = None,
        account_type: AccountType | None = None,
        clearance_level: ClearanceLevel | None = None,
    ) -> UserRecord | None:
        current = self.get_user_by_id(user_id)
        if current is None:
            return None
        groups = None if group_paths is None else self._normalize_existing_groups(group_paths)
        next_groups = current.group_paths if groups is None else tuple(groups)
        next_account_type = current.account_type if account_type is None else normalize_account_type(account_type, next_groups)
        next_clearance = (
            effective_clearance_level(next_account_type, current.clearance_level)
            if clearance_level is None
            else effective_clearance_level(next_account_type, normalize_clearance_level(clearance_level))
        )
        permission_changed = (groups is not None and tuple(groups) != current.group_paths) or (
            is_active is not None and is_active != current.is_active
        ) or next_account_type != current.account_type or next_clearance != current.clearance_level
        with self._connect() as conn:
            with conn.transaction():
                conn.execute(
                    """
                    UPDATE users
                    SET name = COALESCE(%s, name),
                        is_active = COALESCE(%s, is_active),
                        account_type = %s,
                        clearance_level = %s,
                        permission_version = permission_version + %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (name.strip() if name is not None else None, is_active, next_account_type, next_clearance, 1 if permission_changed else 0, user_id),
                )
                if groups is not None:
                    conn.execute("DELETE FROM user_groups WHERE user_id = %s", (user_id,))
                    for group_path in groups:
                        conn.execute(
                            "INSERT INTO user_groups (user_id, group_path) VALUES (%s, %s)",
                            (user_id, group_path),
                        )
        return self.get_user_by_id(user_id)

    def delete_user(self, user_id: str) -> bool:
        with self._connect() as conn:
            result = conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
            return result.rowcount > 0

    def set_user_password(self, user_id: str, password_hash: str, *, must_change_password: bool = False) -> UserRecord | None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET password_hash = %s, must_change_password = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (password_hash, must_change_password, user_id),
            )
        return self.get_user_by_id(user_id)

    def set_last_login(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE users SET last_login_at = NOW() WHERE id = %s", (user_id,))

    def list_groups(self) -> list[GroupRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT path, name FROM groups ORDER BY path").fetchall()
            return [GroupRecord(**row) for row in rows]

    def create_group(self, *, path: str, name: str) -> GroupRecord:
        normalized = require_flat_group_path(path)
        if normalized in {group.path for group in self.list_groups()}:
            raise ValueError("group already exists")
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO groups (path, name)
                VALUES (%s, %s)
                RETURNING path, name
                """,
                (normalized, name.strip()),
            ).fetchone()
            return GroupRecord(**row)

    def update_group(self, *, path: str, name: str) -> GroupRecord | None:
        normalized = require_flat_group_path(path)
        known = {group.path for group in self.list_groups()}
        if normalized not in known:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE groups
                SET name = %s, updated_at = NOW()
                WHERE path = %s
                RETURNING path, name
                """,
                (name.strip(), normalized),
            ).fetchone()
            return GroupRecord(**row) if row else None

    def delete_group(self, path: str) -> bool:
        normalized = normalize_group_path(path)
        with self._connect() as conn:
            exists = conn.execute("SELECT 1 FROM groups WHERE path = %s", (normalized,)).fetchone()
            if not exists:
                return False
            assigned = conn.execute(
                "SELECT 1 FROM user_groups WHERE group_path = %s LIMIT 1",
                (normalized,),
            ).fetchone()
            if assigned:
                raise ValueError("group has assigned users")
            result = conn.execute("DELETE FROM groups WHERE path = %s", (normalized,))
            return result.rowcount > 0

    def add_user_group(self, user_id: str, group_path: str) -> UserRecord | None:
        user = self.get_user_by_id(user_id)
        if user is None:
            return None
        normalized = self._normalize_existing_groups([group_path])[0]
        return self.update_user(user_id, group_paths=sorted({*user.group_paths, normalized}))

    def remove_user_group(self, user_id: str, group_path: str) -> UserRecord | None:
        user = self.get_user_by_id(user_id)
        if user is None:
            return None
        normalized = normalize_group_path(group_path)
        return self.update_user(user_id, group_paths=[path for path in user.group_paths if path != normalized])

    def _user_from_row(self, conn, row) -> UserRecord | None:
        if not row:
            return None
        groups = conn.execute(
            "SELECT group_path FROM user_groups WHERE user_id = %s ORDER BY group_path",
            (row["id"],),
        ).fetchall()
        group_paths = tuple(group["group_path"] for group in groups)
        account_type = normalize_account_type(row.get("account_type"), group_paths)
        return UserRecord(
            id=row["id"],
            email=row["email"],
            name=row["name"],
            password_hash=row["password_hash"],
            is_active=bool(row["is_active"]),
            account_type=account_type,
            clearance_level=effective_clearance_level(account_type, row.get("clearance_level")),
            must_change_password=bool(row["must_change_password"]),
            permission_version=int(row["permission_version"]),
            group_paths=group_paths,
            last_login_at=row["last_login_at"],
        )

    def _normalize_existing_groups(self, group_paths: list[str]) -> list[str]:
        normalized = sorted({require_flat_group_path(path) for path in group_paths})
        known = {group.path for group in self.list_groups()}
        missing = [path for path in normalized if path not in known]
        if missing:
            raise ValueError(f"group does not exist: {missing[0]}")
        return normalized
