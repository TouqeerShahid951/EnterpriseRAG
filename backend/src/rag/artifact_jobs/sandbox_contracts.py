"""Contracts for sandboxed artifact rendering."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..schemas.common import ContractModel
from ..schemas.query import ArtifactFormat
from .contracts import ArtifactContentBundle


class ArtifactExpectedOutput(ContractModel):
    format: ArtifactFormat
    filename: str = Field(..., min_length=5, max_length=120)

    @field_validator("filename")
    @classmethod
    def filename_is_safe(cls, value: str) -> str:
        if "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError("filename must not contain path separators")
        if value.strip() != value:
            raise ValueError("filename must not contain leading or trailing whitespace")
        return value

    @model_validator(mode="after")
    def extension_matches_format(self) -> "ArtifactExpectedOutput":
        if not self.filename.lower().endswith(f".{self.format}"):
            raise ValueError("filename extension must match format")
        return self


class ArtifactBuildProgram(ContractModel):
    sdk_version: Literal["artifact_sdk_v1"] = "artifact_sdk_v1"
    layout_profile: str = Field(default="professional", min_length=1, max_length=80)
    expected_outputs: list[ArtifactExpectedOutput] = Field(..., min_length=1, max_length=3)
    python_code: str = Field(..., min_length=1, max_length=24000)

    @model_validator(mode="after")
    def unique_formats_and_outputs(self) -> "ArtifactBuildProgram":
        formats = [item.format for item in self.expected_outputs]
        filenames = [item.filename for item in self.expected_outputs]
        if len(set(formats)) != len(formats):
            raise ValueError("expected output formats must be unique")
        if len(set(filenames)) != len(filenames):
            raise ValueError("expected output filenames must be unique")
        return self


class ArtifactRenderPolicy(ContractModel):
    timeout_seconds: float = Field(default=120.0, ge=1.0, le=600.0)
    max_file_mb: int = Field(default=30, ge=1, le=100)
    require_libreoffice: bool = False


class ArtifactSandboxRenderRequest(ContractModel):
    job_id: str = Field(..., min_length=1, max_length=120)
    formats: list[ArtifactFormat] = Field(..., min_length=1, max_length=3)
    generated_at: str = Field(..., min_length=1)
    bundle: ArtifactContentBundle
    program: ArtifactBuildProgram
    policy: ArtifactRenderPolicy = Field(default_factory=ArtifactRenderPolicy)


class RenderedSandboxFile(ContractModel):
    filename: str
    format: ArtifactFormat
    content_type: str
    content_base64: str
    size_bytes: int = Field(..., ge=0)
    warnings: list[str] = Field(default_factory=list)


class ArtifactSandboxRenderResult(ContractModel):
    files: list[RenderedSandboxFile] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
