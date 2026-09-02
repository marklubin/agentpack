"""A Plan is everything one (package, target) wants on disk. The applier reconciles it
against the previous ownership state: writes what changed, prunes what is no longer wanted,
and never touches anything it did not write."""

from __future__ import annotations

import copy
import difflib
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import AgentpackError
from .markers import apply_block, remove_block, render_block
from .skills import materialize, remove_tree, tree_equal
from .state import TargetState
from .util import atomic_write_text


@dataclass
class Plan:
    files: dict[Path, str] = field(default_factory=dict)
    dirs: dict[Path, Path] = field(default_factory=dict)  # dst -> src
    blocks: dict[tuple[Path, str, str, str], str] = field(default_factory=dict)
    legacy: dict[str, tuple[str, ...]] = field(default_factory=dict)  # marker id -> legacy ids
    json_keys: dict[tuple[Path, tuple[str, ...]], object] = field(default_factory=dict)
    json_defaults: dict[Path, dict] = field(default_factory=dict)  # content when file is created
    yaml_keys: dict[tuple[Path, tuple[str, ...]], object] = field(default_factory=dict)
    yaml_list_items: set[tuple[Path, tuple[str, ...], str]] = field(default_factory=set)
    toml_tables: dict[tuple[Path, str], dict[str, dict]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def block(self, path: Path, style: str, marker_id: str, body: str, placement: str = "top", legacy: tuple[str, ...] = ()) -> None:
        self.blocks[(path, style, marker_id, placement)] = body
        if legacy:
            self.legacy[marker_id] = legacy


@dataclass
class Change:
    kind: str  # write | prune | note
    path: str
    detail: str = ""
    diff: str = ""

    def __str__(self) -> str:
        return f"{self.kind:6} {self.path}" + (f"  ({self.detail})" if self.detail else "")


class _IndentDumper(yaml.SafeDumper):
    """Indent sequences under their parent key, matching Hermes's own config writer."""

    def increase_indent(self, flow=False, indentless=False):  # noqa: D401
        return super().increase_indent(flow, False)


def _yaml_dump(data) -> str:
    return yaml.dump(data, Dumper=_IndentDumper, sort_keys=False, allow_unicode=True, default_flow_style=False)


def _set_key(d: dict, keys: tuple[str, ...], value) -> None:
    for k in keys[:-1]:
        nxt = d.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            d[k] = nxt
        d = nxt
    d[keys[-1]] = copy.deepcopy(value)


def _get_key(d: dict, keys: tuple[str, ...]):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _del_key(d: dict, keys: tuple[str, ...]) -> bool:
    for k in keys[:-1]:
        d = d.get(k) if isinstance(d, dict) else None
        if d is None:
            return False
    if isinstance(d, dict) and keys[-1] in d:
        del d[keys[-1]]
        return True
    return False


def _unified(path: Path, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(True), after.splitlines(True), fromfile=f"{path} (current)", tofile=f"{path} (planned)", n=2
        )
    )


TOML_TABLE_RE = re.compile(r"^\[(?P<name>[^\]]+)\]\s*(#.*)?$")


def _render_toml_tables(tables: dict[str, dict]) -> str:
    """Render {table_name: {key: scalar|list, subtable: {...}}} as TOML text."""
    out: list[str] = []

    def q(v) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, list):
            return "[" + ", ".join(q(x) for x in v) + "]"
        return json.dumps(str(v), ensure_ascii=False)

    def emit(name: str, body: dict) -> None:
        scalars = {k: v for k, v in body.items() if not isinstance(v, dict)}
        subs = {k: v for k, v in body.items() if isinstance(v, dict)}
        out.append(f"[{name}]")
        for k, v in scalars.items():
            key = k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k)
            out.append(f"{key} = {q(v)}")
        for k, v in subs.items():
            out.append("")
            sub = k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k)
            emit(f"{name}.{sub}", v)

    for i, (name, body) in enumerate(tables.items()):
        if i:
            out.append("")
        emit(name, body)
    return "\n".join(out) + "\n"


def _strip_toml_tables(text: str, names: set[str], protect: tuple[int, int] | None) -> tuple[str, list[str]]:
    """Remove top-level TOML tables (and their subtables) named in `names`, outside the
    protected line range. Returns (text, removed_names)."""
    lines = text.split("\n")
    keep: list[str] = []
    removed: list[str] = []
    skipping = False
    for i, line in enumerate(lines):
        m = TOML_TABLE_RE.match(line.strip()) if not line.startswith(" ") else None
        in_protected = protect is not None and protect[0] <= i <= protect[1]
        if m and not in_protected:
            tname = m.group("name").strip()
            owner = next((n for n in names if tname == n or tname.startswith(n + ".")), None)
            if owner:
                skipping = True
                if owner not in removed:
                    removed.append(owner)
                continue
            skipping = False
        elif m and in_protected:
            skipping = False
        if skipping:
            continue
        keep.append(line)
    # collapse runs of blank lines left behind
    joined = re.sub(r"\n{3,}", "\n\n", "\n".join(keep))
    return joined, removed


class Applier:
    def __init__(self, plan: Plan, prev: TargetState, dry_run: bool):
        self.plan = plan
        self.prev = prev
        self.dry_run = dry_run
        self.changes: list[Change] = []
        self.new = TargetState()

    def run(self) -> TargetState:
        self._files()
        self._dirs()
        self._blocks()
        self._json()
        self._yaml()
        self._toml()
        for n in self.plan.notes:
            self.changes.append(Change("note", "", n))
        return self.new

    # -- whole files -------------------------------------------------------
    def _files(self):
        wanted = {str(p) for p in self.plan.files}
        for path, content in self.plan.files.items():
            before = path.read_text(encoding="utf-8") if path.is_file() else ""
            owned = str(path) in self.prev.files
            if path.exists() and not owned and before != content:
                raise AgentpackError(f"{path}: exists and is not managed by agentpack; remove it or adopt it by hand")
            if before != content:
                self.changes.append(Change("write", str(path), "file", _unified(path, before, content)))
                if not self.dry_run:
                    atomic_write_text(path, content)
            self.new.files.append(str(path))
        for old in self.prev.files:
            if old not in wanted and Path(old).exists():
                self.changes.append(Change("prune", old, "file"))
                if not self.dry_run:
                    Path(old).unlink()

    # -- skill directories ---------------------------------------------------
    def _dirs(self):
        wanted = {str(p) for p in self.plan.dirs}
        for dst, src in self.plan.dirs.items():
            owned = str(dst) in self.prev.dirs
            if dst.exists() and not owned and not tree_equal(src, dst):
                raise AgentpackError(f"{dst}: exists and is not managed by agentpack; remove it or adopt it by hand")
            if not tree_equal(src, dst):
                self.changes.append(Change("write", str(dst), f"copy of {src}"))
                if not self.dry_run:
                    materialize(src, dst)
            self.new.dirs.append(str(dst))
        for old in self.prev.dirs:
            if old not in wanted and Path(old).exists():
                self.changes.append(Change("prune", old, "skill copy"))
                if not self.dry_run:
                    remove_tree(Path(old))

    # -- marker blocks -------------------------------------------------------
    def _blocks(self):
        wanted = {(str(p), s, m) for (p, s, m, _pl) in self.plan.blocks}
        texts: dict[Path, str] = {}

        def load(p: Path) -> str:
            if p not in texts:
                texts[p] = p.read_text(encoding="utf-8") if p.is_file() else ""
            return texts[p]

        for (path, style, mid, placement), body in self.plan.blocks.items():
            before = load(path)
            after = apply_block(before, style, mid, body, placement, self.plan.legacy.get(mid, ()))
            texts[path] = after
            self.new.blocks.append([str(path), style, mid, placement])
        for old in self.prev.blocks:
            p, style, mid = old[0], old[1], old[2]
            if (p, style, mid) not in wanted and Path(p).is_file():
                texts[Path(p)] = remove_block(load(Path(p)), style, mid)
                self.changes.append(Change("prune", p, f"block {mid}"))
        for path, after in texts.items():
            before = path.read_text(encoding="utf-8") if path.is_file() else ""
            if before != after:
                self.changes.append(Change("write", str(path), "managed block", _unified(path, before, after)))
                if not self.dry_run:
                    atomic_write_text(path, after)

    # -- JSON keys -----------------------------------------------------------
    def _json(self):
        by_path: dict[Path, dict] = {}
        for (path, keys), value in self.plan.json_keys.items():
            by_path.setdefault(path, {})[keys] = value
        prev_by_path: dict[str, list[tuple[str, ...]]] = {}
        for p, keys in self.prev.json_keys:
            prev_by_path.setdefault(p, []).append(tuple(keys))
        for path in set(by_path) | {Path(p) for p in prev_by_path}:
            before = path.read_text(encoding="utf-8") if path.is_file() else ""
            if before.strip():
                try:
                    data = json.loads(before)
                except json.JSONDecodeError as exc:
                    raise AgentpackError(f"{path}: invalid JSON, refusing to edit: {exc}") from exc
            else:
                data = copy.deepcopy(self.plan.json_defaults.get(path, {}))
            wanted = by_path.get(path, {})
            for keys, value in wanted.items():
                _set_key(data, keys, value)
                self.new.json_keys.append([str(path), list(keys)])
            for keys in prev_by_path.get(str(path), []):
                if keys not in wanted:
                    if _del_key(data, keys):
                        self.changes.append(Change("prune", str(path), "key " + ".".join(keys)))
            after = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
            if before.strip() and json.loads(before) == data:
                after = before  # semantically unchanged: keep the runtime's own formatting
            if before != after:
                self.changes.append(Change("write", str(path), "json keys", _unified(path, before, after)))
                if not self.dry_run:
                    atomic_write_text(path, after)

    # -- YAML keys and list items (Hermes config.yaml) ------------------------
    def _yaml(self):
        paths = {p for (p, _k) in self.plan.yaml_keys} | {p for (p, _k, _v) in self.plan.yaml_list_items}
        paths |= {Path(p) for p, _k in self.prev.yaml_keys} | {Path(p) for p, _k, _v in self.prev.yaml_list_items}
        for path in paths:
            before = path.read_text(encoding="utf-8") if path.is_file() else ""
            try:
                data = yaml.safe_load(before) if before.strip() else {}
            except yaml.YAMLError as exc:
                raise AgentpackError(f"{path}: invalid YAML, refusing to edit: {exc}") from exc
            if data is None:
                data = {}
            original = copy.deepcopy(data)
            wanted_keys = {k: v for (p, k), v in self.plan.yaml_keys.items() if p == path}
            wanted_items = {(k, v) for (p, k, v) in self.plan.yaml_list_items if p == path}
            for keys, value in wanted_keys.items():
                _set_key(data, keys, value)
                self.new.yaml_keys.append([str(path), list(keys)])
            for keys, value in sorted(wanted_items):
                lst = _get_key(data, keys)
                if lst is None:
                    _set_key(data, keys, [])
                    lst = _get_key(data, keys)
                if not isinstance(lst, list):
                    raise AgentpackError(f"{path}: {'.'.join(keys)} is not a list")
                if value not in lst:
                    lst.append(value)
                self.new.yaml_list_items.append([str(path), list(keys), value])
            for p, keys in self.prev.yaml_keys:
                if p == str(path) and tuple(keys) not in wanted_keys:
                    if _del_key(data, tuple(keys)):
                        self.changes.append(Change("prune", p, "key " + ".".join(keys)))
            for p, keys, value in self.prev.yaml_list_items:
                if p == str(path) and (tuple(keys), value) not in wanted_items:
                    lst = _get_key(data, tuple(keys))
                    if isinstance(lst, list) and value in lst:
                        lst.remove(value)
                        self.changes.append(Change("prune", p, f"{'.'.join(keys)} item {value}"))
            if data == original:
                continue
            after = _yaml_dump(data)
            if yaml.safe_load(after) != data:
                raise AgentpackError(f"{path}: YAML round-trip mismatch, refusing to write")
            self.changes.append(Change("write", str(path), "yaml keys", _unified(path, before, after)))
            if not self.dry_run:
                if path.is_file():
                    atomic_write_text(path.with_name(path.name + ".bak-agentpack"), before)
                atomic_write_text(path, after)

    # -- TOML marker blocks (Codex config.toml) -------------------------------
    def _toml(self):
        by_path: dict[Path, dict[str, dict[str, dict]]] = {}
        for (path, mid), tables in self.plan.toml_tables.items():
            by_path.setdefault(path, {})[mid] = tables
        prev_by_path: dict[str, list[str]] = {}
        for p, mid in self.prev.toml_tables:
            prev_by_path.setdefault(p, []).append(mid)
        for path in set(by_path) | {Path(p) for p in prev_by_path}:
            before = path.read_text(encoding="utf-8") if path.is_file() else ""
            text = before
            for mid in prev_by_path.get(str(path), []):
                if mid not in by_path.get(path, {}):
                    text = remove_block(text, "hash", mid)
                    self.changes.append(Change("prune", str(path), f"block {mid}"))
            for mid, tables in by_path.get(path, {}).items():
                body = _render_toml_tables(tables)
                # adopt any unmanaged table with the same name so TOML stays valid
                lines = text.split("\n")
                begin, end = f"# {mid}:begin", f"# {mid}:end"
                protect = None
                if begin in lines and end in lines:
                    protect = (lines.index(begin), lines.index(end))
                text, removed = _strip_toml_tables(text, set(tables), protect)
                for r in removed:
                    self.changes.append(Change("note", str(path), f"adopted existing table [{r}] into block {mid}"))
                text = apply_block(text, "hash", mid, body, placement="end")
                self.new.toml_tables.append([str(path), mid])
            if text != before:
                try:
                    tomllib.loads(text)
                except tomllib.TOMLDecodeError as exc:
                    raise AgentpackError(f"{path}: planned edit would produce invalid TOML: {exc}") from exc
                self.changes.append(Change("write", str(path), "toml block", _unified(path, before, text)))
                if not self.dry_run:
                    if path.is_file():
                        atomic_write_text(path.with_name(path.name + ".bak-agentpack"), before)
                    atomic_write_text(path, text)
