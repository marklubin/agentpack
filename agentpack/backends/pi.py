"""Pi: native AGENTS.md and .agents/skills; global marker block + skill copies; no MCP."""

from __future__ import annotations

from ..manifest import Package
from ..plan import Plan
from .base import LEGACY_MARKERS, Backend, Context, global_prompt_body, marker_id


class PiBackend(Backend):
    name = "pi"

    def plan(self, pkg: Package, ctx: Context) -> Plan:
        p = Plan()
        mid = marker_id(pkg)
        if pkg.is_global:
            body = global_prompt_body(pkg, "pi")
            if body:
                p.block(ctx.home / ".pi" / "agent" / "AGENTS.md", "html", mid, body, "top", LEGACY_MARKERS.get(pkg.name, ()))
            for s in ctx.skills:
                p.dirs[ctx.home / ".pi" / "agent" / "skills" / s.name] = s.path
        for c in pkg.connections:
            if c.wants("pi"):
                p.notes.append(f"pi: {c.name} connection skipped; pi has no MCP runtime")
        return p
