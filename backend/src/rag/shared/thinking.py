"""Helpers for disabling and hiding model thinking output."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

NO_THINKING_INSTRUCTION = (
    "Do not include hidden reasoning, chain-of-thought, analysis, or <think> tags. "
    "Return only the final answer."
)


def no_thinking_payload_fields() -> dict[str, Any]:
    return {
        "reasoning_effort": "none",
        "include_reasoning": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }


def no_thinking_system(system: str) -> str:
    if NO_THINKING_INSTRUCTION in system:
        return system
    return f"{system.rstrip()} {NO_THINKING_INSTRUCTION}"


def no_thinking_prompt(prompt: str, model: str) -> str:
    text = prompt.rstrip()
    if "qwen3" in model.lower() and not text.endswith("/no_think"):
        text = f"{text}\n\n/no_think"
    return text


def strip_thinking_content(content: str) -> str:
    text = content.strip()
    while text.lower().startswith("<think>"):
        end = text.lower().find("</think>")
        if end < 0:
            return ""
        text = text[end + len("</think>") :].strip()
    return text


def strip_thinking_chunks(chunks: Iterator[str]) -> Iterator[str]:
    buffer = ""
    inside_thinking = False
    for chunk in chunks:
        if not chunk:
            continue
        buffer += chunk
        while buffer:
            lower_buffer = buffer.lower()
            if inside_thinking:
                end = lower_buffer.find("</think>")
                if end < 0:
                    buffer = buffer[-(len("</think>") - 1) :]
                    break
                buffer = buffer[end + len("</think>") :]
                inside_thinking = False
                continue

            start = lower_buffer.find("<think>")
            if start < 0:
                hold = _tag_prefix_hold(buffer, "<think>")
                emit = buffer[:-hold] if hold else buffer
                buffer = buffer[-hold:] if hold else ""
                if emit:
                    yield emit
                break

            if start:
                yield buffer[:start]
            buffer = buffer[start + len("<think>") :]
            inside_thinking = True


def _tag_prefix_hold(text: str, tag: str) -> int:
    lower_text = text.lower()
    lower_tag = tag.lower()
    max_size = min(len(lower_text), len(lower_tag) - 1)
    for size in range(max_size, 0, -1):
        if lower_tag.startswith(lower_text[-size:]):
            return size
    return 0
