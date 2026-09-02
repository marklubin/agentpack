"""Scoped memory: schema (ontology), records, derived index, rendered contract and skill."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import AgentpackError
from .util import parse_simple_yaml_frontmatter, split_frontmatter

CONTRACT_MARKER = "agentpack:memory"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
WRITE_MODES = ("agent", "approval")
PRIVACY = ("public", "personal", "sensitive", "highly-sensitive")


@dataclass
class MemoryType:
    name: str
    fields: list[str]
    index: list[str]
    write: str
    privacy: str
    description: str = ""


@dataclass
class MemorySchema:
    path: Path
    store: Path  # directory holding <type>/ subdirs and INDEX.md
    types: list[MemoryType]
    warnings: list[str] = field(default_factory=list)

    def type(self, name: str) -> MemoryType | None:
        return next((t for t in self.types if t.name == name), None)


@dataclass
class Record:
    path: Path
    type: str
    fields: dict[str, str]
    body: str


def load_schema(path: Path, root: Path) -> MemorySchema:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise AgentpackError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise AgentpackError(f"{path}: schema must be a mapping")
    errors: list[str] = []
    store = root / data.get("store", "memory")
    types: list[MemoryType] = []
    seen = set()
    for i, t in enumerate(data.get("types") or []):
        if not isinstance(t, dict):
            errors.append(f"types[{i}] must be a mapping")
            continue
        name = t.get("name")
        if not isinstance(name, str) or not SLUG_RE.match(name):
            errors.append(f"types[{i}].name must be a kebab-case slug")
            continue
        if name in seen:
            errors.append(f"duplicate type {name}")
        seen.add(name)
        fields = t.get("fields") or []
        if not isinstance(fields, list) or not fields or any(not isinstance(f, str) for f in fields):
            errors.append(f"{name}: fields must be a non-empty list of names")
            fields = []
        index = t.get("index") or fields[:2]
        if not isinstance(index, list) or any(f not in fields for f in index):
            errors.append(f"{name}: index must list a subset of fields")
            index = []
        write = t.get("write", "agent")
        if write not in WRITE_MODES:
            errors.append(f"{name}: write must be one of {list(WRITE_MODES)}")
        privacy = t.get("privacy", "personal")
        if privacy not in PRIVACY:
            errors.append(f"{name}: privacy must be one of {list(PRIVACY)}")
        types.append(
            MemoryType(
                name=name,
                fields=list(fields),
                index=list(index),
                write=write,
                privacy=privacy,
                description=str(t.get("description") or ""),
            )
        )
    if errors:
        raise AgentpackError(f"{path}:\n  - " + "\n  - ".join(errors))
    return MemorySchema(path=path, store=store, types=types)


def load_records(schema: MemorySchema) -> tuple[list[Record], list[str]]:
    """All records under <store>/<type>/. Returns (records, errors). Never raises on a bad record."""
    records: list[Record] = []
    errors: list[str] = []
    for t in schema.types:
        tdir = schema.store / t.name
        if not tdir.is_dir():
            continue
        for f in sorted(tdir.iterdir()):
            if f.is_dir() or not f.name.endswith(".md"):
                continue
            slug = f.name[:-3]
            rel = f.relative_to(schema.store.parent)
            if not SLUG_RE.match(slug):
                errors.append(f"{rel}: filename must be a kebab-case slug")
                continue
            text = f.read_text(encoding="utf-8")
            fm, body = split_frontmatter(text)
            if fm is None:
                errors.append(f"{rel}: missing frontmatter")
                continue
            try:
                meta = parse_simple_yaml_frontmatter(fm)
            except ValueError as exc:
                errors.append(f"{rel}: {exc}")
                continue
            rtype = meta.get("type")
            if rtype != t.name:
                errors.append(f"{rel}: type is {rtype!r}, expected {t.name!r} for this directory")
                continue
            fields: dict[str, str] = {}
            bad = False
            for name in t.fields:
                val = meta.get(name)
                if val is None or (isinstance(val, str) and not val.strip()):
                    if name == "fact" or name == "lesson" or name == "reason":
                        # long-form fields may live in the body
                        continue
                    errors.append(f"{rel}: missing field {name}")
                    bad = True
                    continue
                fields[name] = str(val)
            unknown = [k for k in meta if k not in ("type", *t.fields)]
            if unknown:
                errors.append(f"{rel}: unknown fields {', '.join(unknown)}")
                bad = True
            if bad:
                continue
            records.append(Record(path=f, type=t.name, fields=fields, body=body.strip()))
    # records in directories not declared by the schema
    if schema.store.is_dir():
        declared = {t.name for t in schema.types}
        for d in sorted(schema.store.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and d.name not in declared:
                stray = [p for p in d.glob("*.md") if _looks_like_record(p)]
                if stray:
                    errors.append(f"{d.relative_to(schema.store.parent)}: {len(stray)} record(s) of undeclared type")
    return records, errors


def _looks_like_record(p: Path) -> bool:
    try:
        fm, _ = split_frontmatter(p.read_text(encoding="utf-8"))
    except OSError:
        return False
    return bool(fm and re.search(r"^type:\s*\S", fm, re.M))


def render_index(schema: MemorySchema, records: list[Record]) -> str:
    out = [f"# Memory index (generated by agentpack, {len(records)} records)", ""]
    out.append("Do not edit. Regenerated from the records under each type directory.")
    for t in schema.types:
        recs = [r for r in records if r.type == t.name]
        out.append("")
        out.append(f"## {t.name} ({len(recs)})")
        if t.description:
            out.append("")
            out.append(t.description)
        if not recs:
            out.append("")
            out.append("(none)")
            continue
        out.append("")
        for r in recs:
            slug = r.path.name[:-3]
            parts = []
            for f in t.index:
                v = r.fields.get(f)
                if v is None and f in ("fact", "lesson", "reason"):
                    v = r.body.split("\n", 1)[0]
                if v:
                    parts.append(_one_line(v))
            summary = " · ".join(parts) if parts else _one_line(r.body.split("\n", 1)[0]) if r.body else ""
            out.append(f"- {slug}: {summary}" if summary else f"- {slug}")
    return "\n".join(out) + "\n"


def _one_line(s: str, limit: int = 140) -> str:
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def render_contract(schema: MemorySchema, root: Path, reads_from: list[tuple[str, Path]]) -> str:
    """Short block for AGENTS.md. Kept small because it is in every prompt."""
    store_rel = schema.store.relative_to(root)
    lines = [
        "## Memory for this package",
        "",
        f"Store: `{store_rel}/` in this repository. Read `{store_rel}/INDEX.md` before relying on prior facts.",
        f"Write a record as one file at `{store_rel}/<type>/<slug>.md` with the frontmatter template below.",
        "Never edit `INDEX.md`; it is regenerated. Do not write types not listed here.",
        "Search: skim the index, then `grep -ril <term> " + str(store_rel) + "/<type>/`, then read one record.",
        "The `remember` skill has the full procedure.",
        "",
        "| type | fields | write |",
        "|---|---|---|",
    ]
    for t in schema.types:
        rule = "append freely" if t.write == "agent" else "draft, then ask before saving"
        if t.privacy in ("sensitive", "highly-sensitive"):
            rule += f"; {t.privacy}"
        lines.append(f"| {t.name} | {', '.join(t.fields)} | {rule} |")
    if reads_from:
        lines.append("")
        lines.append("Read-only memory from other packages:")
        for name, path in reads_from:
            lines.append(f"- {name}: `{path}/INDEX.md`")
    lines += [
        "",
        "Template:",
        "",
        "```",
        "---",
        "type: <type>",
    ]
    example = schema.types[0] if schema.types else None
    if example:
        for f in example.fields:
            if f in ("fact", "lesson", "reason"):
                continue
            lines.append(f"{f}: ")
    lines += ["---", "<one record, one to three sentences>", "```"]
    return "\n".join(lines) + "\n"


def render_remember_skill(schema: MemorySchema, root: Path, pkg_name: str) -> str:
    store_rel = schema.store.relative_to(root)
    out = [
        "---",
        "name: remember",
        f"description: Use when you learn something durable about the {pkg_name} package's domain, or need to recall or search prior facts. Reads and writes the typed memory store under {store_rel}/.",
        "metadata:",
        "  generated_by: agentpack",
        "---",
        "",
        "# Remember",
        "",
        "Generated by agentpack from `memory/schema.yaml`. Do not edit by hand; edit the schema.",
        "",
        "## Where memory lives",
        "",
        f"- Store: `{store_rel}/` in this repository, one Markdown file per record under `{store_rel}/<type>/`.",
        f"- Index: `{store_rel}/INDEX.md`, regenerated by the tool. Never edit it.",
        "- Records are committed and pushed by the repository's normal autocommit. Nothing else syncs them.",
        "",
        "## Before you rely on a fact",
        "",
        "1. Read the index. It lists every record by type with its key fields.",
        f"2. If the index line is not enough, search: `grep -ril \"<term>\" {store_rel}/<type>/`, or match a field: `grep -l \"^company: Acme\" {store_rel}/*/*.md`.",
        "3. Read the one record you need. Records are short by rule.",
        "",
        "## When to write",
        "",
        "Write when a fact will matter in a later session and is not already recorded. Prefer updating an existing record over adding a near-duplicate: search first, then edit the existing file in place.",
        "",
        "## How to write",
        "",
        f"1. Pick the type. Only these types exist; anything else is not memory for this package.",
        "2. Choose a kebab-case slug that names the subject, for example `acme-hiring-freeze`.",
        f"3. Create `{store_rel}/<type>/<slug>.md` with the frontmatter for that type and one to three sentences of body.",
        "4. Do not touch the index. Do not write secrets, credentials, or anything from `private/`.",
        "",
        "## Types",
        "",
    ]
    for t in schema.types:
        out.append(f"### {t.name}")
        out.append("")
        if t.description:
            out.append(t.description)
            out.append("")
        out.append(f"- Fields: {', '.join(t.fields)}")
        out.append(f"- Index shows: {', '.join(t.index)}")
        out.append(f"- Privacy: {t.privacy}")
        if t.write == "agent":
            out.append("- Write rule: append freely, no approval needed.")
        else:
            out.append("- Write rule: draft the record and show it to the owner; save only after explicit approval. On a scheduled run, leave it as a proposal in your output instead of writing.")
        out.append("")
        out.append("```")
        out.append("---")
        out.append(f"type: {t.name}")
        for f in t.fields:
            if f in ("fact", "lesson", "reason"):
                continue
            out.append(f"{f}: ")
        out.append("---")
        out.append("<record body>")
        out.append("```")
        out.append("")
    out += [
        "## Validation",
        "",
        "`agentpack memory validate` runs on every sync and in the repository's pre-commit hook. A record with a missing field, an unknown field, a bad slug, or an undeclared type fails the run visibly. Fix the record; nothing is auto-corrected.",
    ]
    return "\n".join(out) + "\n"
