"""Backend interface. A backend turns one package into a Plan for one runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..connections import Connection
from ..manifest import Package
from ..plan import Plan
from ..skills import Skill
from ..util import body_without_frontmatter

# Marker ids written by the retired mission-control materializer, adopted in place.
LEGACY_MARKERS = {"mission-control": ("mission-control:global-agent-instructions",)}


@dataclass
class Context:
    home: Path
    share_dir: Path  # tool-owned materialization area, e.g. ~/.local/share/agentpack
    skills: list[Skill] = field(default_factory=list)


def marker_id(pkg: Package) -> str:
    return f"agentpack:{pkg.name}"


def global_prompt_body(pkg: Package, target: str) -> str:
    """Fragments for this target, frontmatter stripped, joined by one blank line."""
    parts = []
    for frag in pkg.fragments:
        if target in frag.targets:
            body = body_without_frontmatter(frag.path.read_text(encoding="utf-8"))
            if body:
                parts.append(body)
    return "\n".join(parts)


def tools_policy_note(conn: Connection, target: str) -> str | None:
    if conn.tools_include is not None:
        return (
            f"{target}: {conn.name} tool allowlist ({len(conn.tools_include)} tools) is not enforced "
            f"natively by {target}; it is rendered as policy text only"
        )
    return None


class Backend:
    name = "base"

    def plan(self, pkg: Package, ctx: Context) -> Plan:  # pragma: no cover - interface
        raise NotImplementedError
