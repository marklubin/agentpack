"""Claude Code: real skill copies, CLAUDE.md managed block, mcpServers JSON."""

from __future__ import annotations

from ..connections import Connection
from ..manifest import Package
from ..plan import Plan
from .base import LEGACY_MARKERS, Backend, Context, global_prompt_body, marker_id, tools_policy_note


def mcp_entry(conn: Connection) -> dict:
    if conn.transport == "http":
        d: dict = {"type": "http", "url": conn.url}
        if conn.headers:
            d["headers"] = dict(conn.headers)
    else:
        d = {"command": conn.command, "args": list(conn.args)}
        if conn.env:
            d["env"] = dict(conn.env)
    d.update(conn.runtime_options.get("claude", {}))
    return d


class ClaudeBackend(Backend):
    name = "claude"

    def plan(self, pkg: Package, ctx: Context) -> Plan:
        p = Plan()
        mid = marker_id(pkg)
        if pkg.is_global:
            body = global_prompt_body(pkg, "claude")
            if body:
                p.block(ctx.home / ".claude" / "CLAUDE.md", "html", mid, body, "top", LEGACY_MARKERS.get(pkg.name, ()))
            for s in ctx.skills:
                p.dirs[ctx.home / ".claude" / "skills" / s.name] = s.path
            for c in pkg.connections:
                if c.wants("claude"):
                    p.json_keys[(ctx.home / ".claude.json", ("mcpServers", c.name))] = mcp_entry(c)
                    if c.headers:
                        p.notes.append(f"claude: {c.name} headers use ${{VAR}}; Claude expands these in .mcp.json, user-scope support is unverified")
                    n = tools_policy_note(c, "claude")
                    if n:
                        p.notes.append(n)
        else:
            claude_md = pkg.root / "CLAUDE.md"
            p.files[claude_md] = "@AGENTS.md\n"
            for s in ctx.skills:
                p.dirs[pkg.root / ".claude" / "skills" / s.name] = s.path
            for c in pkg.connections:
                if c.wants("claude"):
                    p.json_keys[(pkg.root / ".mcp.json", ("mcpServers", c.name))] = mcp_entry(c)
                    n = tools_policy_note(c, "claude")
                    if n:
                        p.notes.append(n)
        return p
