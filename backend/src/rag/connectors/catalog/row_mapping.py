"""Database-driver result mapping for connector responses."""

from __future__ import annotations

from typing import Any


def column_names(cursor) -> list[str]:
    names: list[str] = []
    for column in cursor.description or []:
        name = getattr(column, "name", None)
        if name is None:
            try:
                name = column[0]
            except Exception:
                name = None
        if name is not None:
            names.append(str(name))
    return names


def json_safe(value: dict[str, Any]) -> dict[str, Any]:
    return {str(key): json_safe_value(item) for key, item in value.items()}


def json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def row_dict(cursor, row) -> dict[str, Any]:
    names = [column[0] for column in cursor.description]
    return {name: json_safe_value(value) for name, value in zip(names, row)}
