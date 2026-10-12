"""Workspace branding contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


DEFAULT_APP_NAME = "Prudentia AI"
DEFAULT_PRIMARY_COLOR = "#b8a77a"
DEFAULT_ACCENT_COLOR = "#b8a77a"
DEFAULT_BACKGROUND_COLOR = "#101016"
DEFAULT_LOGIN_MESSAGE = "Use your organization credentials to continue."
DEFAULT_THEME_MODE = "user"
DEFAULT_H1_SIZE = "standard"
DEFAULT_H1_WEIGHT = "bold"
DEFAULT_H2_SIZE = "standard"
DEFAULT_H2_WEIGHT = "bold"
DEFAULT_BODY_SIZE = "standard"


@dataclass(frozen=True)
class BrandingRecord:
    app_name: str = DEFAULT_APP_NAME
    primary_color: str = DEFAULT_PRIMARY_COLOR
    accent_color: str = DEFAULT_ACCENT_COLOR
    background_color: str = DEFAULT_BACKGROUND_COLOR
    login_message: str = DEFAULT_LOGIN_MESSAGE
    support_url: str | None = None
    theme_mode: str = DEFAULT_THEME_MODE
    h1_size: str = DEFAULT_H1_SIZE
    h1_weight: str = DEFAULT_H1_WEIGHT
    h1_color: str | None = None
    h2_size: str = DEFAULT_H2_SIZE
    h2_weight: str = DEFAULT_H2_WEIGHT
    h2_color: str | None = None
    body_size: str = DEFAULT_BODY_SIZE
    logo_content: bytes | None = None
    logo_content_type: str | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None


class BrandingRepository(Protocol):
    def get_active(self) -> BrandingRecord | None: ...
    def save_active(self, record: BrandingRecord) -> BrandingRecord: ...
    def delete_active(self) -> None: ...
