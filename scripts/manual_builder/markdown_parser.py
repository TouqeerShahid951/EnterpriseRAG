"""Small Markdown parser for the supported manual authoring subset."""

from __future__ import annotations

from pathlib import Path
import re


def parse_markdown(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks: list[dict] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue

        if stripped.startswith("```"):
            code: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            blocks.append({"type": "code", "text": "\n".join(code)})
            index += 1
            continue

        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            blocks.append({"type": "heading", "level": min(level, 3), "text": stripped[level:].strip()})
            index += 1
            continue

        if stripped.startswith("|") and index + 1 < len(lines) and is_table_divider(lines[index + 1]):
            table_lines = [stripped]
            index += 1
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            blocks.append({"type": "table", "rows": parse_table(table_lines)})
            continue

        bullet_match = re.match(r"^-\s+(.*)", stripped)
        if bullet_match:
            text, index = collect_list_item(lines, index, bullet_match.group(1))
            blocks.append({"type": "bullet", "text": text})
            continue

        number_match = re.match(r"^(\d+)\.\s+(.*)", stripped)
        if number_match:
            text, index = collect_list_item(lines, index, number_match.group(2))
            blocks.append({"type": "number", "number": number_match.group(1), "text": text})
            continue

        parts = [stripped]
        index += 1
        while index < len(lines) and is_paragraph_continuation(lines[index]):
            parts.append(lines[index].strip())
            index += 1
        blocks.append({"type": "paragraph", "text": " ".join(parts)})

    return blocks


def is_paragraph_continuation(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return not (
        stripped.startswith("#")
        or stripped.startswith("```")
        or stripped.startswith("|")
        or stripped.startswith("- ")
        or re.match(r"^\d+\.\s+", stripped)
    )


def collect_list_item(lines: list[str], index: int, first_text: str) -> tuple[str, int]:
    parts = [first_text.strip()]
    index += 1
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if not stripped:
            break
        if raw.startswith("  ") and is_paragraph_continuation(raw):
            parts.append(stripped)
            index += 1
            continue
        break
    return " ".join(parts), index


def is_table_divider(line: str) -> bool:
    stripped = line.strip()
    return bool(re.match(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$", stripped))


def parse_table(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines:
        if is_table_divider(line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows.append(cells)
    return rows
