"""Skill discovery and real-directory materialization."""

from __future__ import annotations

import filecmp
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import AgentpackError
from .manifest import Package
from .util import parse_simple_yaml_frontmatter, split_frontmatter

GENERATED_SKILLS = ("remember",)


@dataclass
class Skill:
    name: str
    path: Path
    description: str
    internal: bool


def discover(pkg: Package) -> list[Skill]:
    """Every <skills_dir>/<name>/SKILL.md that passes include/exclude and is not internal."""
    if not pkg.skills_dir.is_dir():
        return []
    found: list[Skill] = []
    errors: list[str] = []
    for entry in sorted(pkg.skills_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue
        fm, _ = split_frontmatter(skill_md.read_text(encoding="utf-8"))
        try:
            meta = parse_simple_yaml_frontmatter(fm)
        except ValueError as exc:
            errors.append(f"{skill_md}: {exc}")
            continue
        name = meta.get("name") or entry.name
        if name != entry.name:
            errors.append(f"{skill_md}: frontmatter name {name!r} does not match directory {entry.name!r}")
            continue
        desc = meta.get("description")
        if not isinstance(desc, str) or not desc.strip():
            errors.append(f"{skill_md}: description is required")
            continue
        md = meta.get("metadata") or {}
        internal = bool(isinstance(md, dict) and md.get("internal") in (True, "true", "yes", "on"))
        found.append(Skill(name=entry.name, path=entry, description=desc.strip(), internal=internal))
    if errors:
        raise AgentpackError("invalid skills:\n  - " + "\n  - ".join(errors))

    names = {s.name for s in found}
    if pkg.skills_include is not None:
        missing = [n for n in pkg.skills_include if n not in names]
        if missing:
            raise AgentpackError(f"skills.include names not found: {', '.join(missing)}")
    selected = []
    for s in found:
        if s.internal:
            continue
        if pkg.skills_include is not None and s.name not in pkg.skills_include:
            continue
        if s.name in pkg.skills_exclude:
            continue
        selected.append(s)
    return selected


def tree_equal(a: Path, b: Path) -> bool:
    if not (a.is_dir() and b.is_dir()):
        return False
    cmp = filecmp.dircmp(a, b, ignore=[])
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return False
    return all(tree_equal(a / d, b / d) for d in cmp.common_dirs)


def materialize(src: Path, dst: Path) -> bool:
    """Real-directory copy of src at dst, replaced atomically. Returns True if changed."""
    if tree_equal(src, dst):
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{dst.name}.", dir=str(dst.parent)))
    try:
        shutil.rmtree(tmp)
        shutil.copytree(src, tmp, symlinks=False)
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        elif dst.is_dir():
            old = Path(tempfile.mkdtemp(prefix=f".{dst.name}.old.", dir=str(dst.parent)))
            shutil.rmtree(old)
            os.rename(dst, old)
            os.rename(tmp, dst)
            shutil.rmtree(old)
            return True
        os.rename(tmp, dst)
        return True
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def remove_tree(path: Path) -> bool:
    if path.is_symlink() or path.is_file():
        path.unlink()
        return True
    if path.is_dir():
        shutil.rmtree(path)
        return True
    return False
