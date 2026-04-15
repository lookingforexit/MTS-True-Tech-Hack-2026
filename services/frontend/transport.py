"""Helpers for parsing backend transport wrappers."""

from __future__ import annotations


def parse_transport_content(value: str | None) -> tuple[str, str]:
    """Return ``(kind, content)`` for wrapped or plain backend payloads."""
    if value is None:
        return "empty", ""

    stripped = value.strip()
    if stripped.startswith("lua{") and stripped.endswith("}lua"):
        return "lua", stripped[4:-4]
    if stripped.startswith("text{") and stripped.endswith("}text"):
        return "text", stripped[5:-5]
    return "plain", value
