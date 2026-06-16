"""OpenAI-compatible vision adapter for image OCR and captions."""

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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.provider = _vision_provider(provider)

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
                    "content": no_thinking_system("You extract image text and captions for document ingestion."),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Extract all visible text from this image and write a concise caption. "
                                "Return JSON with keys extracted_text, caption, and confidence between 0 and 1."
                            ),
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
            "options": {"temperature": 0.0},
            "messages": [
                {
                    "role": "system",
                    "content": no_thinking_system("You extract image text and captions for document ingestion."),
                },
                {
                    "role": "user",
                    "content": (
                        "Extract all visible text from this image and write a concise caption. "
                        "Return JSON with keys extracted_text, caption, and confidence between 0 and 1."
                    ),
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
