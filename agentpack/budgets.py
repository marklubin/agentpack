"""Instruction-file budgets. A runtime that truncates a context file silently is worse than
a compile error, so the compiler refuses to write a file over the runtime's cap and warns
about package-native files it does not write but the runtime will read."""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

from .manifest import Package
from .markers import apply_block
from .plan import Plan

HERMES_DEFAULT_CAP = 20_000  # Hermes's dynamic floor when context_file_max_chars is unset
CODEX_DEFAULT_CAP = 32_768  # Codex project_doc_max_bytes default


def hermes_cap(home: Path) -> int:
    cfg = home / ".hermes" / "config.yaml"
    try:
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return HERMES_DEFAULT_CAP
    val = data.get("context_file_max_chars") if isinstance(data, dict) else None
    return val if isinstance(val, int) and val > 0 else HERMES_DEFAULT_CAP


def codex_cap(home: Path) -> int:
    cfg = home / ".codex" / "config.toml"
    try:
        data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return CODEX_DEFAULT_CAP
    val = data.get("project_doc_max_bytes")
    return val if isinstance(val, int) and val > 0 else CODEX_DEFAULT_CAP


CAPS = {"hermes": hermes_cap, "codex": codex_cap}


def check_budgets(pkg: Package, target: str, plan: Plan, home: Path) -> list[tuple[str, str]]:
    """Return (level, message) pairs. `error` means a file agentpack would write exceeds the
    cap; `warning` means a package-native file the runtime reads directly exceeds it."""
    fn = CAPS.get(target)
    if fn is None:
        return []
    cap = fn(home)
    out: list[tuple[str, str]] = []
    for (path, style, mid, placement), body in plan.blocks.items():
        if style != "html":
            continue
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        predicted = apply_block(current, style, mid, body, placement, plan.legacy.get(mid, ()))
        if len(predicted) > cap:
            out.append(
                (
                    "error",
                    f"{target}: {path} would be {len(predicted)} chars, over the {cap}-char context-file "
                    f"cap, and {target} would truncate it. Not written. Trim this package's prompts for "
                    f"{target} or drop {target} from their targets.",
                )
            )
    if not pkg.is_global and pkg.contract.is_file():
        size = len(pkg.contract.read_text(encoding="utf-8"))
        if size > cap:
            out.append(
                (
                    "warning",
                    f"{target}: {pkg.contract} is {size} chars, over the {cap}-char cap; {target} "
                    f"truncates it in sessions inside this package. Trim it or raise the cap.",
                )
            )
    return out
