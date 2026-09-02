"""Hermes: ~/AGENTS.md managed block, skills.external_dirs, mcp_servers in config.yaml."""

from __future__ import annotations

from ..connections import Connection
from ..manifest import Package
from ..plan import Plan
from .base import LEGACY_MARKERS, Backend, Context, global_prompt_body, marker_id


def mcp_entry(conn: Connection) -> dict:
    # Key order mirrors what `hermes mcp add` writes, so adopting a live entry is a no-op.
    if conn.transport == "http":
        d: dict = {"url": conn.url, "enabled": True}
        d.update(conn.runtime_options.get("hermes", {}))
        if conn.headers:
            d["headers"] = dict(conn.headers)
    else:
        d = {"command": conn.command, "args": list(conn.args)}
        if conn.env:
            d["env"] = dict(conn.env)
        d["enabled"] = True
        d.update(conn.runtime_options.get("hermes", {}))
    if conn.tools_include is not None:
        d["tools"] = {"include": list(conn.tools_include)}
    elif conn.tools_exclude is not None:
        d["tools"] = {"exclude": list(conn.tools_exclude)}
    return d


class HermesBackend(Backend):
    name = "hermes"

    def plan(self, pkg: Package, ctx: Context) -> Plan:
        p = Plan()
        mid = marker_id(pkg)
        config = ctx.home / ".hermes" / "config.yaml"
        if pkg.is_global:
            body = global_prompt_body(pkg, "hermes")
            if body:
                p.block(ctx.home / "AGENTS.md", "html", mid, body, "top", LEGACY_MARKERS.get(pkg.name, ()))
                p.notes.append("hermes: ~/AGENTS.md is cwd-discovered; sessions whose git root is elsewhere see only that project's AGENTS.md")
            if ctx.skills:
                skills_home = ctx.share_dir / "hermes" / pkg.name / "skills"
                for s in ctx.skills:
                    p.dirs[skills_home / s.name] = s.path
                p.yaml_list_items.add((config, ("skills", "external_dirs"), str(skills_home)))
        else:
            p.yaml_list_items.add((config, ("skills", "trusted_project_dirs"), str(pkg.root)))
        for c in pkg.connections:
            if c.wants("hermes"):
                p.yaml_keys[(config, ("mcp_servers", c.name))] = mcp_entry(c)
                if not pkg.is_global:
                    p.notes.append(f"hermes: connection {c.name} is registered globally; Hermes has no per-project MCP config")
        return p
