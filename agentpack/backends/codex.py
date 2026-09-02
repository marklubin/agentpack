"""Codex: ~/.codex/AGENTS.md managed block, skill copies, [mcp_servers.*] TOML block."""

from __future__ import annotations

import re

from ..connections import Connection
from ..manifest import Package
from ..plan import Plan
from .base import LEGACY_MARKERS, Backend, Context, global_prompt_body, marker_id, tools_policy_note

ENV_REF = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def mcp_table(conn: Connection) -> dict:
    if conn.transport == "http":
        t: dict = {"url": conn.url}
        if conn.headers:
            # Codex maps header name -> env var NAME; the value never sits in the file.
            t["env_http_headers"] = {h: ENV_REF.match(v).group(1) for h, v in conn.headers.items()}
    else:
        t = {"command": conn.command, "args": list(conn.args)}
        literal = {k: v for k, v in conn.env.items() if not ENV_REF.match(v)}
        passthrough = [ENV_REF.match(v).group(1) for v in conn.env.values() if ENV_REF.match(v)]
        if literal:
            t["env"] = literal
        if passthrough:
            t["env_vars"] = passthrough
    t.update(conn.runtime_options.get("codex", {}))
    return t


class CodexBackend(Backend):
    name = "codex"

    def plan(self, pkg: Package, ctx: Context) -> Plan:
        p = Plan()
        mid = marker_id(pkg)
        if pkg.is_global:
            body = global_prompt_body(pkg, "codex")
            if body:
                p.block(ctx.home / ".codex" / "AGENTS.md", "html", mid, body, "top", LEGACY_MARKERS.get(pkg.name, ()))
            for s in ctx.skills:
                p.dirs[ctx.home / ".codex" / "skills" / s.name] = s.path
            config = ctx.home / ".codex" / "config.toml"
        else:
            config = pkg.root / ".codex" / "config.toml"
        tables = {}
        for c in pkg.connections:
            if c.wants("codex"):
                tables[f"mcp_servers.{c.name}"] = mcp_table(c)
                n = tools_policy_note(c, "codex")
                if n:
                    p.notes.append(n)
        if tables:
            p.toml_tables[(config, mid)] = tables
        return p
