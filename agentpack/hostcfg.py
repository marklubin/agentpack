"""Host manifest: ~/.config/agentpack/packages.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from . import TARGETS, AgentpackError
from .util import expand_home


@dataclass
class HostPackage:
    path: Path
    ref: str | None
    targets: list[str] | None


def host_config_path(home: Path) -> Path:
    return home / ".config" / "agentpack" / "packages.yaml"


def load_host_packages(home: Path) -> list[HostPackage]:
    path = host_config_path(home)
    if not path.is_file():
        raise AgentpackError(f"{path}: not found; list packages there to use `agentpack sync`")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise AgentpackError(f"{path}: invalid YAML: {exc}") from exc
    entries = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise AgentpackError(f"{path}: expected a top-level `packages:` list")
    out: list[HostPackage] = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict) or not isinstance(e.get("path"), str):
            raise AgentpackError(f"{path}: packages[{i}] needs a path")
        targets = e.get("targets")
        if targets is not None and (not isinstance(targets, list) or any(t not in TARGETS for t in targets)):
            raise AgentpackError(f"{path}: packages[{i}].targets must be a subset of {list(TARGETS)}")
        ref = e.get("ref")
        if ref is not None and not isinstance(ref, str):
            raise AgentpackError(f"{path}: packages[{i}].ref must be a string")
        out.append(HostPackage(path=expand_home(e["path"], home), ref=ref, targets=targets))
    return out
