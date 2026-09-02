"""Ownership state: everything the tool wrote, so prune deletes only that."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .util import atomic_write_text

STATE_VERSION = 1


@dataclass
class TargetState:
    files: list[str] = field(default_factory=list)
    dirs: list[str] = field(default_factory=list)
    blocks: list[list[str]] = field(default_factory=list)  # [path, style, marker_id, placement]
    json_keys: list[list] = field(default_factory=list)  # [path, [key, ...]]
    yaml_keys: list[list] = field(default_factory=list)  # [path, [key, ...]]
    yaml_list_items: list[list] = field(default_factory=list)  # [path, [key, ...], value]
    toml_tables: list[list[str]] = field(default_factory=list)  # [path, marker_id]

    def to_json(self) -> dict:
        return {
            "files": sorted(self.files),
            "dirs": sorted(self.dirs),
            "blocks": sorted(self.blocks),
            "json_keys": sorted(self.json_keys),
            "yaml_keys": sorted(self.yaml_keys),
            "yaml_list_items": sorted(self.yaml_list_items),
            "toml_tables": sorted(self.toml_tables),
        }

    @classmethod
    def from_json(cls, d: dict) -> "TargetState":
        return cls(
            files=list(d.get("files", [])),
            dirs=list(d.get("dirs", [])),
            blocks=[list(x) for x in d.get("blocks", [])],
            json_keys=[list(x) for x in d.get("json_keys", [])],
            yaml_keys=[list(x) for x in d.get("yaml_keys", [])],
            yaml_list_items=[list(x) for x in d.get("yaml_list_items", [])],
            toml_tables=[list(x) for x in d.get("toml_tables", [])],
        )


class State:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict = {"version": STATE_VERSION, "packages": {}}
        if path.is_file():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{path}: corrupt state file: {exc}") from exc
            self.data.setdefault("packages", {})

    def package(self, name: str) -> dict:
        return self.data["packages"].setdefault(name, {"commit": None, "root": None, "targets": {}})

    def target(self, name: str, target: str) -> TargetState:
        d = self.package(name)["targets"].get(target)
        return TargetState.from_json(d) if d else TargetState()

    def set_target(self, name: str, target: str, ts: TargetState) -> None:
        self.package(name)["targets"][target] = ts.to_json()

    def drop_target(self, name: str, target: str) -> None:
        self.package(name)["targets"].pop(target, None)

    def drop_package(self, name: str) -> None:
        self.data["packages"].pop(name, None)

    def save(self) -> None:
        atomic_write_text(self.path, json.dumps(self.data, indent=2, sort_keys=True) + "\n")
