"""HTTP contracts for workspace branding."""

from datetime import datetime

from pydantic import AnyHttpUrl, Field
from typing import Literal

from rag.shared.contracts.http import ContractModel


class BrandingResponse(ContractModel):
    app_name: str
    primary_color: str
    accent_color: str
    background_color: str
    login_message: str
    support_url: str | None = None
    theme_mode: Literal["user", "light", "dark"]
    h1_size: Literal["compact", "standard", "large"]
    h1_weight: Literal["semibold", "bold", "extrabold"]
    h1_color: str | None = None
    h2_size: Literal["compact", "standard", "large"]
    h2_weight: Literal["semibold", "bold", "extrabold"]
    h2_color: str | None = None
    body_size: Literal["compact", "standard", "large"]
    logo_url: str | None = None
    updated_at: datetime | None = None


class BrandingUpdateRequest(ContractModel):
    app_name: str = Field(min_length=1, max_length=80)
    primary_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    background_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    login_message: str = Field(min_length=1, max_length=240)
    support_url: AnyHttpUrl | None = None
    theme_mode: Literal["user", "light", "dark"] = "user"
    h1_size: Literal["compact", "standard", "large"] = "standard"
    h1_weight: Literal["semibold", "bold", "extrabold"] = "bold"
    h1_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    h2_size: Literal["compact", "standard", "large"] = "standard"
    h2_weight: Literal["semibold", "bold", "extrabold"] = "bold"
    h2_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    body_size: Literal["compact", "standard", "large"] = "standard"
