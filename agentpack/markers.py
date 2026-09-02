"""Managed marker blocks inside files the runtime owns.

Two comment styles: ``html`` for Markdown (``<!-- agentpack:x:begin -->``) and ``hash`` for
TOML/YAML-like files (``# agentpack:x:begin``). Content outside the markers is preserved.
Legacy marker ids (the retired mission-control materializer) are adopted in place.
"""

from __future__ import annotations

import re

from . import AgentpackError

STYLES = {
    "html": ("<!-- {id}:begin -->", "<!-- {id}:end -->"),
    "hash": ("# {id}:begin", "# {id}:end"),
}


def _pair(style: str, marker_id: str) -> tuple[str, str]:
    b, e = STYLES[style]
    return b.format(id=marker_id), e.format(id=marker_id)


def render_block(style: str, marker_id: str, body: str) -> str:
    begin, end = _pair(style, marker_id)
    body = body if body.endswith("\n") or not body else body + "\n"
    return f"{begin}\n{body}{end}\n"


def _find(lines: list[str], begin: str, end: str) -> tuple[int, int] | None:
    starts = [i for i, l in enumerate(lines) if l == begin]
    ends = [i for i, l in enumerate(lines) if l == end]
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise AgentpackError(f"malformed managed markers for {begin!r}")
    return starts[0], ends[0]


def apply_block(
    text: str,
    style: str,
    marker_id: str,
    body: str,
    placement: str = "top",
    legacy_ids: tuple[str, ...] = (),
) -> str:
    """Replace the block in place, adopting a legacy block if present; otherwise insert."""
    block = render_block(style, marker_id, body)
    lines = text.split("\n")
    if text.endswith("\n"):
        lines = lines[:-1]
    for mid in (marker_id, *legacy_ids):
        begin, end = _pair(style, mid)
        pos = _find(lines, begin, end)
        if pos:
            s, e = pos
            new = lines[:s] + block.rstrip("\n").split("\n") + lines[e + 1 :]
            return "\n".join(new) + "\n"
    existing = text
    if not existing.strip():
        return block
    if placement == "top":
        return block + "\n" + existing.rstrip("\n") + "\n"
    return existing.rstrip("\n") + "\n\n" + block


def remove_block(text: str, style: str, marker_id: str, legacy_ids: tuple[str, ...] = ()) -> str:
    lines = text.split("\n")
    trailing_nl = text.endswith("\n")
    if trailing_nl:
        lines = lines[:-1]
    for mid in (marker_id, *legacy_ids):
        begin, end = _pair(style, mid)
        pos = _find(lines, begin, end)
        if pos:
            s, e = pos
            new = lines[:s] + lines[e + 1 :]
            # collapse the blank line that separated the block from neighbours
            while new and new[0] == "":
                new.pop(0)
            joined = "\n".join(new)
            joined = re.sub(r"\n{3,}", "\n\n", joined)
            return (joined.rstrip("\n") + "\n") if joined.strip() else ""
    return text


def has_block(text: str, style: str, marker_id: str) -> bool:
    begin, end = _pair(style, marker_id)
    return begin in text.split("\n") and end in text.split("\n")
