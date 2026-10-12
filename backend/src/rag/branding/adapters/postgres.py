"""PostgreSQL workspace branding repository."""

from __future__ import annotations

from rag.shared.persistence import PostgresConnectionMixin

from ..models import BrandingRecord


class PostgresBrandingRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def get_active(self) -> BrandingRecord | None:
        self._ensure_table()
        row = self._execute_optional("SELECT * FROM workspace_branding WHERE config_key = 'active'", ())
        return _record_from_row(row) if row else None

    def save_active(self, record: BrandingRecord) -> BrandingRecord:
        self._ensure_table()
        row = self._execute_one(
            """
            INSERT INTO workspace_branding (config_key, app_name, primary_color, accent_color, background_color, login_message, support_url, theme_mode, h1_size, h1_weight, h1_color, h2_size, h2_weight, h2_color, body_size, logo_content, logo_content_type, updated_by)
            VALUES ('active', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::uuid)
            ON CONFLICT (config_key) DO UPDATE SET
                app_name = EXCLUDED.app_name,
                primary_color = EXCLUDED.primary_color,
                accent_color = EXCLUDED.accent_color,
                background_color = EXCLUDED.background_color,
                login_message = EXCLUDED.login_message,
                support_url = EXCLUDED.support_url,
                theme_mode = EXCLUDED.theme_mode,
                h1_size = EXCLUDED.h1_size,
                h1_weight = EXCLUDED.h1_weight,
                h1_color = EXCLUDED.h1_color,
                h2_size = EXCLUDED.h2_size,
                h2_weight = EXCLUDED.h2_weight,
                h2_color = EXCLUDED.h2_color,
                body_size = EXCLUDED.body_size,
                logo_content = EXCLUDED.logo_content,
                logo_content_type = EXCLUDED.logo_content_type,
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            RETURNING *
            """,
            (record.app_name, record.primary_color, record.accent_color, record.background_color, record.login_message, record.support_url, record.theme_mode, record.h1_size, record.h1_weight, record.h1_color, record.h2_size, record.h2_weight, record.h2_color, record.body_size, record.logo_content, record.logo_content_type, record.updated_by),
        )
        return _record_from_row(row)

    def delete_active(self) -> None:
        self._ensure_table()
        self._execute_optional("DELETE FROM workspace_branding WHERE config_key = 'active' RETURNING config_key", ())

    def _ensure_table(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_branding (
                    config_key TEXT PRIMARY KEY DEFAULT 'active' CHECK (config_key = 'active'),
                    app_name TEXT NOT NULL CHECK (length(btrim(app_name)) BETWEEN 1 AND 80),
                    primary_color TEXT NOT NULL CHECK (primary_color ~ '^#[0-9A-Fa-f]{6}$'),
                    accent_color TEXT NOT NULL DEFAULT '#b8a77a' CHECK (accent_color ~ '^#[0-9A-Fa-f]{6}$'),
                    background_color TEXT NOT NULL DEFAULT '#101016' CHECK (background_color ~ '^#[0-9A-Fa-f]{6}$'),
                    login_message TEXT NOT NULL DEFAULT 'Use your organization credentials to continue.' CHECK (length(btrim(login_message)) BETWEEN 1 AND 240),
                    support_url TEXT NULL,
                    theme_mode TEXT NOT NULL DEFAULT 'user' CHECK (theme_mode IN ('user', 'light', 'dark')),
                    h1_size TEXT NOT NULL DEFAULT 'standard' CHECK (h1_size IN ('compact', 'standard', 'large')),
                    h1_weight TEXT NOT NULL DEFAULT 'bold' CHECK (h1_weight IN ('semibold', 'bold', 'extrabold')),
                    h1_color TEXT NULL CHECK (h1_color ~ '^#[0-9A-Fa-f]{6}$'),
                    h2_size TEXT NOT NULL DEFAULT 'standard' CHECK (h2_size IN ('compact', 'standard', 'large')),
                    h2_weight TEXT NOT NULL DEFAULT 'bold' CHECK (h2_weight IN ('semibold', 'bold', 'extrabold')),
                    h2_color TEXT NULL CHECK (h2_color ~ '^#[0-9A-Fa-f]{6}$'),
                    body_size TEXT NOT NULL DEFAULT 'standard' CHECK (body_size IN ('compact', 'standard', 'large')),
                    logo_content BYTEA NULL,
                    logo_content_type TEXT NULL CHECK (logo_content_type IN ('image/png', 'image/jpeg') OR logo_content_type IS NULL),
                    updated_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT workspace_branding_logo_complete CHECK ((logo_content IS NULL) = (logo_content_type IS NULL))
                )
                """
            )
            conn.execute("ALTER TABLE workspace_branding ADD COLUMN IF NOT EXISTS accent_color TEXT NOT NULL DEFAULT '#b8a77a'")
            conn.execute("ALTER TABLE workspace_branding ADD COLUMN IF NOT EXISTS background_color TEXT NOT NULL DEFAULT '#101016'")
            conn.execute("ALTER TABLE workspace_branding ADD COLUMN IF NOT EXISTS login_message TEXT NOT NULL DEFAULT 'Use your organization credentials to continue.'")
            conn.execute("ALTER TABLE workspace_branding ADD COLUMN IF NOT EXISTS support_url TEXT NULL")
            conn.execute("ALTER TABLE workspace_branding ADD COLUMN IF NOT EXISTS theme_mode TEXT NOT NULL DEFAULT 'user'")
            conn.execute("ALTER TABLE workspace_branding ADD COLUMN IF NOT EXISTS h1_size TEXT NOT NULL DEFAULT 'standard'")
            conn.execute("ALTER TABLE workspace_branding ADD COLUMN IF NOT EXISTS h1_weight TEXT NOT NULL DEFAULT 'bold'")
            conn.execute("ALTER TABLE workspace_branding ADD COLUMN IF NOT EXISTS h1_color TEXT NULL")
            conn.execute("ALTER TABLE workspace_branding ADD COLUMN IF NOT EXISTS h2_size TEXT NOT NULL DEFAULT 'standard'")
            conn.execute("ALTER TABLE workspace_branding ADD COLUMN IF NOT EXISTS h2_weight TEXT NOT NULL DEFAULT 'bold'")
            conn.execute("ALTER TABLE workspace_branding ADD COLUMN IF NOT EXISTS h2_color TEXT NULL")
            conn.execute("ALTER TABLE workspace_branding ADD COLUMN IF NOT EXISTS body_size TEXT NOT NULL DEFAULT 'standard'")


def _record_from_row(row: dict[str, object]) -> BrandingRecord:
    return BrandingRecord(
        app_name=str(row["app_name"]),
        primary_color=str(row["primary_color"]),
        accent_color=str(row.get("accent_color") or "#b8a77a"),
        background_color=str(row.get("background_color") or "#101016"),
        login_message=str(row.get("login_message") or "Use your organization credentials to continue."),
        support_url=str(row["support_url"]) if row.get("support_url") else None,
        theme_mode=str(row.get("theme_mode") or "user"),
        h1_size=str(row.get("h1_size") or "standard"),
        h1_weight=str(row.get("h1_weight") or "bold"),
        h1_color=str(row["h1_color"]) if row.get("h1_color") else None,
        h2_size=str(row.get("h2_size") or "standard"),
        h2_weight=str(row.get("h2_weight") or "bold"),
        h2_color=str(row["h2_color"]) if row.get("h2_color") else None,
        body_size=str(row.get("body_size") or "standard"),
        logo_content=bytes(row["logo_content"]) if row.get("logo_content") is not None else None,
        logo_content_type=str(row["logo_content_type"]) if row.get("logo_content_type") else None,
        updated_at=row.get("updated_at"),  # type: ignore[arg-type]
        updated_by=str(row["updated_by"]) if row.get("updated_by") else None,
    )
