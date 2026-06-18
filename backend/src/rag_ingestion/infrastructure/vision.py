"""OpenAI-compatible vision adapter for image OCR and visual descriptions."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from json import JSONDecodeError
from typing import Any

from rag.shared.thinking import no_thinking_payload_fields, no_thinking_system, strip_thinking_content

from .http import ServiceRequestError, request_json

OPENAI_COMPATIBLE_PROVIDER = "openai_compatible"
OLLAMA_PROVIDER = "ollama"
VISION_SYSTEM_PROMPT = (
    "You extract visible text and highly detailed visual descriptions for enterprise document ingestion. "
    "Your output will be embedded for RAG retrieval, so preserve concrete, searchable details and "
    "fine-grained visual identifiers."
)
VISION_USER_PROMPT = (
    "Analyze this image for RAG indexing, not for a generic caption.\n"
    "Return only valid JSON with keys extracted_text, caption, and confidence.\n"
    "extracted_text: transcribe every readable word, number, label, title, table cell, chart axis/legend, "
    "stamp, signature text, handwriting, watermark, logo text, and document identifier. Preserve reading "
    "order and line breaks where useful. Use an empty string if no text is readable.\n"
    "caption: write the most detailed useful visual description you can. Start with the main subject or "
    "most important visible entity, then describe fine-grained attributes and identifiers: object category, "
    "brand/make, model, variant or trim, body style, color, size, shape, material, logos, badges, labels, "
    "serial numbers, license plates, uniforms, distinctive markings, damage, accessories, orientation, "
    "position, background, surrounding objects, people, actions, relationships, layout, diagrams, "
    "tables/charts, quantities, dates, locations, and anything else visible that could help retrieval. "
    "For vehicles, be especially specific: identify the visible make, model, generation/body shape, trim "
    "or variant, vehicle type, color, plate number, decals, cargo, damage, wheel/body features, and camera "
    "angle when visible. If an exact model or identity is uncertain, write what it appears to be and name "
    "the visible cues; do not present guesses as facts. For charts or tables, describe apparent trends, "
    "categories, and notable values. For document scans, describe the form type, fields, stamps, "
    "signatures, and image quality. Do not invent identities, locations, values, or events that are not "
    "visible; say when a detail is unclear.\n"
    "confidence: number from 0 to 1 for the combined OCR and visual description accuracy."
)
OLLAMA_VISION_FORMAT = {
    "type": "object",
    "properties": {
        "extracted_text": {"type": "string"},
        "caption": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["extracted_text", "caption", "confidence"],
}


@dataclass(frozen=True)
class ImageAnalysis:
    extracted_text: str = ""
    caption: str = ""
    confidence: float | None = None
    quality_flags: list[str] = field(default_factory=list)


class VisionClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        provider: str = OPENAI_COMPATIBLE_PROVIDER,
        num_ctx: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.provider = _vision_provider(provider)
        self.num_ctx = num_ctx

    def analyze_image(self, *, content: bytes, content_type: str) -> ImageAnalysis:
        if not self.base_url:
            return ImageAnalysis(quality_flags=["vision_unconfigured"])
        if self.provider == OLLAMA_PROVIDER:
            return self._analyze_ollama(content=content, content_type=content_type)
        return self._analyze_openai_compatible(content=content, content_type=content_type)

    def _analyze_openai_compatible(self, *, content: bytes, content_type: str) -> ImageAnalysis:
        payload = {
            "model": self.model,
            **no_thinking_payload_fields(),
            "messages": [
                {
                    "role": "system",
                    "content": no_thinking_system(VISION_SYSTEM_PROMPT),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": VISION_USER_PROMPT,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{content_type};base64,{base64.b64encode(content).decode('ascii')}"
                            },
                        },
                    ],
                }
            ],
            "temperature": 0,
        }
        try:
            response = request_json(
                self._api_base_url(),
                "/chat/completions",
                service="vision",
                method="POST",
                payload=payload,
                timeout_seconds=self.timeout_seconds,
            )
        except ServiceRequestError as exc:
            return ImageAnalysis(quality_flags=[f"vision_failed:{exc.status_code or 'request'}"])
        content_text = _message_content(response)
        if not content_text:
            return ImageAnalysis(quality_flags=["vision_empty_response"])
        return _analysis_from_text(content_text)

    def _analyze_ollama(self, *, content: bytes, content_type: str) -> ImageAnalysis:
        payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "format": OLLAMA_VISION_FORMAT,
            "keep_alive": "5m",
            "options": _ollama_options(temperature=0.0, num_ctx=self.num_ctx),
            "messages": [
                {
                    "role": "system",
                    "content": no_thinking_system(VISION_SYSTEM_PROMPT),
                },
                {
                    "role": "user",
                    "content": VISION_USER_PROMPT,
                    "images": [base64.b64encode(content).decode("ascii")],
                },
            ],
        }
        try:
            response = request_json(
                self.base_url,
                "/api/chat",
                service="ollama-vision",
                method="POST",
                payload=payload,
                timeout_seconds=self.timeout_seconds,
            )
        except ServiceRequestError as exc:
            return ImageAnalysis(quality_flags=[f"vision_failed:{exc.status_code or 'request'}"])
        content_text = _ollama_message_content(response)
        if not content_text:
            return ImageAnalysis(quality_flags=["vision_empty_response"])
        return _analysis_from_text(content_text)

    def _api_base_url(self) -> str:
        return self.base_url if self.base_url.endswith("/v1") else f"{self.base_url}/v1"


def _message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return strip_thinking_content(content) if isinstance(content, str) else ""


def _ollama_message_content(response: dict[str, Any]) -> str:
    message = response.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return strip_thinking_content(content) if isinstance(content, str) else ""


def _ollama_options(*, temperature: float, num_ctx: int | None) -> dict[str, int | float]:
    options: dict[str, int | float] = {"temperature": temperature}
    if num_ctx is not None:
        options["num_ctx"] = num_ctx
    return options


def _vision_provider(value: str) -> str:
    normalized = value.strip().lower()
    return OLLAMA_PROVIDER if normalized == OLLAMA_PROVIDER else OPENAI_COMPATIBLE_PROVIDER


def _analysis_from_text(value: str) -> ImageAnalysis:
    candidate = value.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`").strip()
        if candidate.lower().startswith("json"):
            candidate = candidate[4:].strip()
    try:
        parsed = json.loads(candidate)
    except JSONDecodeError:
        return ImageAnalysis(
            caption=value.strip(),
            confidence=None,
            quality_flags=["vision_plain_text_response"],
        )
    if not isinstance(parsed, dict):
        return ImageAnalysis(
            caption=value.strip(),
            confidence=None,
            quality_flags=["vision_non_object_response"],
        )
    extracted_text = str(parsed.get("extracted_text") or parsed.get("text") or "").strip()
    caption = str(parsed.get("caption") or parsed.get("description") or "").strip()
    confidence = parsed.get("confidence")
    flags = parsed.get("quality_flags")
    return ImageAnalysis(
        extracted_text=extracted_text,
        caption=caption,
        confidence=max(0.0, min(1.0, float(confidence))) if isinstance(confidence, (int, float)) else None,
        quality_flags=[str(flag) for flag in flags] if isinstance(flags, list) else [],
    )
