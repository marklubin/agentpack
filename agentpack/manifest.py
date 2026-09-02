"""package.yaml loading and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import SCOPES, SENSITIVITIES, SPEC_VERSION, TARGETS, AgentpackError
from .connections import Connection, load_connection

MANIFEST = "package.yaml"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass
class Fragment:
    path: Path
    targets: list[str]


@dataclass
class Package:
    root: Path
    name: str
    version: str
    scope: str
    sensitivity: str
    targets: list[str]
    contract: Path
    fragments: list[Fragment]
    skills_dir: Path
    skills_include: list[str] | None  # None means all
    skills_exclude: list[str]
    connections: list[Connection]
    memory_schema: Path | None
    memory_reads_from: list[str]
    hermes_cron_skills: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_global(self) -> bool:
        return self.scope == "global"

    def allowed_targets(self, host_targets: list[str] | None) -> list[str]:
        if host_targets is None:
            return list(self.targets)
        return [t for t in self.targets if t in host_targets]


def load_package(root: Path) -> Package:
    root = root.resolve()
    mpath = root / MANIFEST
    if not mpath.is_file():
        raise AgentpackError(f"{root}: no {MANIFEST}")
    try:
        data = yaml.safe_load(mpath.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise AgentpackError(f"{mpath}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise AgentpackError(f"{mpath}: manifest must be a mapping")

    errors: list[str] = []
    warnings: list[str] = []

    if data.get("spec") != SPEC_VERSION:
        errors.append(f"spec must be {SPEC_VERSION}")
    name = data.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        errors.append("name must be a lowercase kebab-case slug")
    version = data.get("version", "0.0.0")
    if not isinstance(version, str):
        errors.append("version must be a string")
    scope = data.get("scope", "project")
    if scope not in SCOPES:
        errors.append(f"scope must be one of {list(SCOPES)}")
    sensitivity = data.get("sensitivity", "personal")
    if sensitivity not in SENSITIVITIES:
        errors.append(f"sensitivity must be one of {list(SENSITIVITIES)}")
    targets = data.get("targets") or list(TARGETS)
    if not isinstance(targets, list) or any(t not in TARGETS for t in targets):
        errors.append(f"targets must be a subset of {list(TARGETS)}")
    if scope == "global" and sensitivity in ("sensitive", "highly-sensitive"):
        errors.append("a sensitive package cannot be global scope")

    prompts = data.get("prompts") or {}
    if not isinstance(prompts, dict):
        errors.append("prompts must be a mapping")
        prompts = {}
    contract_rel = prompts.get("contract", "AGENTS.md")
    contract = root / contract_rel
    if not contract.is_file():
        errors.append(f"prompts.contract not found: {contract_rel}")
    fragments: list[Fragment] = []
    for i, frag in enumerate(prompts.get("fragments") or []):
        if isinstance(frag, str):
            frag = {"path": frag}
        if not isinstance(frag, dict) or not isinstance(frag.get("path"), str):
            errors.append(f"prompts.fragments[{i}] must have a path")
            continue
        fpath = root / frag["path"]
        if not fpath.is_file():
            errors.append(f"prompts.fragments[{i}] not found: {frag['path']}")
        ftargets = frag.get("targets") or list(targets if isinstance(targets, list) else TARGETS)
        if not isinstance(ftargets, list) or any(t not in TARGETS for t in ftargets):
            errors.append(f"prompts.fragments[{i}].targets must be a subset of {list(TARGETS)}")
        fragments.append(Fragment(path=fpath, targets=list(ftargets)))
    if fragments and scope == "project":
        errors.append("prompts.fragments are only supported for global scope; project packages use AGENTS.md")

    skills = data.get("skills") or {}
    if not isinstance(skills, dict):
        errors.append("skills must be a mapping")
        skills = {}
    skills_dir = root / skills.get("dir", ".agents/skills")
    include = skills.get("include", "all")
    if include == "all":
        skills_include = None
    elif isinstance(include, list) and all(isinstance(s, str) for s in include):
        skills_include = list(include)
    else:
        errors.append("skills.include must be 'all' or a list of names")
        skills_include = None
    skills_exclude = skills.get("exclude") or []
    if not isinstance(skills_exclude, list):
        errors.append("skills.exclude must be a list")
        skills_exclude = []
    if not skills_dir.is_dir() and (skills_include or not skills_dir.exists()):
        if skills_include:
            errors.append(f"skills.dir not found: {skills_dir}")
        else:
            warnings.append(f"skills.dir not found, package declares no skills: {skills_dir}")

    connections: list[Connection] = []
    for i, cpath in enumerate(data.get("connections") or []):
        if not isinstance(cpath, str):
            errors.append(f"connections[{i}] must be a path")
            continue
        p = root / cpath
        if not p.is_file():
            errors.append(f"connections[{i}] not found: {cpath}")
            continue
        try:
            connections.append(load_connection(p))
        except AgentpackError as exc:
            errors.append(str(exc))
    seen = set()
    for c in connections:
        if c.name in seen:
            errors.append(f"duplicate connection name: {c.name}")
        seen.add(c.name)

    memory = data.get("memory") or {}
    if not isinstance(memory, dict):
        errors.append("memory must be a mapping")
        memory = {}
    memory_schema = None
    if memory.get("schema"):
        memory_schema = root / memory["schema"]
        if not memory_schema.is_file():
            errors.append(f"memory.schema not found: {memory['schema']}")
        if scope == "global":
            errors.append("memory is only supported for project scope in v1")
    reads_from = memory.get("reads_from") or []
    if not isinstance(reads_from, list) or any(not isinstance(r, str) for r in reads_from):
        errors.append("memory.reads_from must be a list of package names")

    hermes = data.get("hermes") or {}
    if not isinstance(hermes, dict):
        errors.append("hermes must be a mapping")
        hermes = {}
    cron_skills = hermes.get("cron_skills") or []
    if not isinstance(cron_skills, list) or any(not isinstance(x, str) for x in cron_skills):
        errors.append("hermes.cron_skills must be a list of skill names")
        cron_skills = []
    for cron_skill in cron_skills:
        if not (skills_dir / cron_skill / "SKILL.md").is_file():
            errors.append(f"hermes.cron_skills: {cron_skill} has no SKILL.md under {skills_dir}")

    if errors:
        raise AgentpackError(f"{mpath}:\n  - " + "\n  - ".join(errors))

    return Package(
        root=root,
        name=name,
        version=version,
        scope=scope,
        sensitivity=sensitivity,
        targets=list(targets),
        contract=contract,
        fragments=fragments,
        skills_dir=skills_dir,
        skills_include=skills_include,
        skills_exclude=list(skills_exclude),
        connections=connections,
        memory_schema=memory_schema,
        memory_reads_from=list(reads_from),
        hermes_cron_skills=list(cron_skills),
        warnings=warnings,
    )
