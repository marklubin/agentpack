"""Connection declarations: one MCP server per YAML file, secrets by env var name only."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import TARGETS, AgentpackError

ENV_REF = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")
# Anything that looks like a credential literal: long token-ish strings, common key prefixes.
SECRET_LIKE = re.compile(r"(sk-[A-Za-z0-9]{8,}|[A-Za-z0-9_\-]{32,}|Bearer\s+\S{16,})")


@dataclass
class Connection:
    name: str
    transport: str  # http | stdio
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    tools_include: list[str] | None = None
    tools_exclude: list[str] | None = None
    targets: list[str] = field(default_factory=lambda: list(TARGETS))
    runtime_options: dict[str, dict] = field(default_factory=dict)
    source: Path | None = None

    def env_refs(self) -> list[str]:
        refs = []
        for v in list(self.headers.values()) + list(self.env.values()) + [self.url or ""]:
            for m in re.finditer(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", v):
                refs.append(m.group(1))
        return sorted(set(refs))

    def wants(self, target: str) -> bool:
        return target in self.targets


def load_connection(path: Path) -> Connection:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise AgentpackError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise AgentpackError(f"{path}: connection file must be a mapping")
    errors = []
    name = data.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", name):
        errors.append("name must be a lowercase slug")
    transport = data.get("transport")
    if transport not in ("http", "stdio"):
        errors.append("transport must be http or stdio")
    url = data.get("url")
    command = data.get("command")
    if transport == "http" and not isinstance(url, str):
        errors.append("http transport requires url")
    if transport == "stdio" and not isinstance(command, str):
        errors.append("stdio transport requires command")
    headers = data.get("headers") or {}
    env = data.get("env") or {}
    args = data.get("args") or []
    if not isinstance(headers, dict) or not all(isinstance(v, str) for v in headers.values()):
        errors.append("headers must map header names to strings")
    if not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values()):
        errors.append("env must map variable names to strings")
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        errors.append("args must be a list of strings")
    tools = data.get("tools") or {}
    if not isinstance(tools, dict):
        errors.append("tools must be a mapping with include or exclude")
        tools = {}
    include = tools.get("include")
    exclude = tools.get("exclude")
    if include is not None and exclude is not None:
        errors.append("tools.include and tools.exclude are mutually exclusive")
    targets = data.get("targets") or list(TARGETS)
    if not isinstance(targets, list) or any(t not in TARGETS for t in targets):
        errors.append(f"targets must be a subset of {list(TARGETS)}")
    runtime_options = data.get("runtime_options") or {}
    if not isinstance(runtime_options, dict) or any(
        k not in TARGETS or not isinstance(v, dict) for k, v in runtime_options.items()
    ):
        errors.append("runtime_options must map a target name to a mapping")

    # Secret hygiene: header and env values must be ${VAR} references, never literals.
    if isinstance(headers, dict):
        for k, v in headers.items():
            if isinstance(v, str) and not ENV_REF.match(v):
                errors.append(f"headers.{k}: value must be a ${{VAR}} reference, not a literal")
    if isinstance(env, dict):
        for k, v in env.items():
            if isinstance(v, str) and SECRET_LIKE.search(v) and not ENV_REF.match(v):
                errors.append(f"env.{k}: value looks like a secret; use a ${{VAR}} reference")
    if isinstance(url, str) and SECRET_LIKE.search(url.split("://", 1)[-1].split("/", 1)[-1]):
        errors.append("url: contains a token-like segment; move it to a header env reference")

    if errors:
        raise AgentpackError(f"{path}: " + "; ".join(errors))
    return Connection(
        name=name,
        transport=transport,
        url=url,
        headers=dict(headers),
        command=command,
        args=list(args),
        env=dict(env),
        tools_include=list(include) if include is not None else None,
        tools_exclude=list(exclude) if exclude is not None else None,
        targets=list(targets),
        runtime_options={k: dict(v) for k, v in runtime_options.items()},
        source=path,
    )
