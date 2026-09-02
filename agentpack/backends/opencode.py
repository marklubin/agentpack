"""OpenCode: inherits Claude's skills and CLAUDE.md natively; only MCP config is written."""

from __future__ import annotations

import re

from ..connections import Connection
from ..manifest import Package
from ..plan import Plan
from .base import Backend, Context, marker_id, tools_policy_note

ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
SCHEMA = "https://opencode.ai/config.json"


def _env(v: str) -> str:
    return ENV_REF.sub(lambda m: "{env:" + m.group(1) + "}", v)


def mcp_entry(conn: Connection) -> dict:
    if conn.transport == "http":
        d: dict = {"type": "remote", "url": conn.url}
        if conn.headers:
            d["headers"] = {k: _env(v) for k, v in conn.headers.items()}
    else:
        d = {"type": "local", "command": [conn.command, *conn.args]}
        if conn.env:
            d["environment"] = {k: _env(v) for k, v in conn.env.items()}
    d["enabled"] = True
    d.update(conn.runtime_options.get("opencode", {}))
    return d


class OpenCodeBackend(Backend):
    name = "opencode"

    def plan(self, pkg: Package, ctx: Context) -> Plan:
        p = Plan()
        marker_id(pkg)
        if pkg.is_global:
            config = ctx.home / ".config" / "opencode" / "opencode.json"
            if ctx.skills or pkg.fragments:
                p.notes.append("opencode: reads ~/.claude/skills and ~/.claude/CLAUDE.md natively; nothing written for prompts or skills")
        else:
            config = pkg.root / ".opencode" / "opencode.json"
        p.json_defaults[config] = {"$schema": SCHEMA}
        for c in pkg.connections:
            if c.wants("opencode"):
                p.json_keys[(config, ("mcp", c.name))] = mcp_entry(c)
                n = tools_policy_note(c, "opencode")
                if n:
                    p.notes.append(n)
        return p
