"""agentpack command line."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from . import TARGETS, AgentpackError, __version__
from .backends import BACKENDS, Context
from .budgets import check_budgets
from .hostcfg import host_config_path, load_host_packages
from .manifest import MANIFEST, Package, load_package
from .markers import apply_block
from .memory import CONTRACT_MARKER, load_records, load_schema, render_contract, render_index, render_remember_skill
from .plan import Applier, Change, Plan
from .skills import discover
from .state import State, TargetState
from .util import atomic_write_text, git, git_head, git_is_repo

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "template"


class Paths:
    def __init__(self, home: Path):
        self.home = home
        self.state_file = home / ".local" / "state" / "agentpack" / "state.json"
        self.share_dir = home / ".local" / "share" / "agentpack"


# ---------------------------------------------------------------------------
# memory (in-repo generation)
# ---------------------------------------------------------------------------

def memory_render(pkg: Package, dry_run: bool, reads_from: list[tuple[str, Path]] | None = None) -> tuple[list[Change], list[str]]:
    """Validate records, regenerate INDEX.md, the contract block, and the remember skill."""
    changes: list[Change] = []
    if pkg.memory_schema is None:
        return changes, []
    schema = load_schema(pkg.memory_schema, pkg.root)
    records, errors = load_records(schema)

    def put(path: Path, content: str, label: str) -> None:
        before = path.read_text(encoding="utf-8") if path.is_file() else ""
        if before != content:
            changes.append(Change("write", str(path), label))
            if not dry_run:
                atomic_write_text(path, content)

    put(schema.store / "INDEX.md", render_index(schema, records), "memory index")
    if schema.types:
        put(pkg.skills_dir / "remember" / "SKILL.md", render_remember_skill(schema, pkg.root, pkg.name), "remember skill")
        contract = render_contract(schema, pkg.root, reads_from or [])
        before = pkg.contract.read_text(encoding="utf-8")
        after = apply_block(before, "html", CONTRACT_MARKER, contract, placement="end")
        if before != after:
            changes.append(Change("write", str(pkg.contract), "memory contract block"))
            if not dry_run:
                atomic_write_text(pkg.contract, after)
    return changes, errors


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------

def compile_package(
    root: Path,
    paths: Paths,
    state: State,
    targets: list[str] | None,
    host_targets: list[str] | None,
    dry_run: bool,
    known_packages: dict[str, Path] | None = None,
) -> tuple[bool, list[Change]]:
    pkg = load_package(root)
    reads_from = []
    for other in pkg.memory_reads_from:
        other_root = (known_packages or {}).get(other)
        if other_root is None:
            print(f"warning: {pkg.name}: memory.reads_from {other} is not installed on this host")
            continue
        reads_from.append((other, other_root / "memory"))
    mem_changes, mem_errors = memory_render(pkg, dry_run, reads_from)
    changes: list[Change] = list(mem_changes)
    if mem_errors:
        for e in mem_errors:
            print(f"error: {pkg.name}: memory: {e}")
    skills = discover(pkg)
    allowed = pkg.allowed_targets(host_targets)
    wanted = [t for t in (targets or allowed) if t in allowed]
    skipped = [t for t in (targets or []) if t not in allowed]
    if skipped:
        print(f"note: {pkg.name}: targets not allowed by package or host: {', '.join(skipped)}")
    ctx = Context(home=paths.home, share_dir=paths.share_dir, skills=skills)
    ok = not mem_errors
    for target in wanted:
        plan = BACKENDS[target]().plan(pkg, ctx)
        problems = check_budgets(pkg, target, plan, paths.home)
        for level, msg in problems:
            print(f"{level}: {pkg.name}: {msg}")
        if any(level == "error" for level, _ in problems):
            ok = False
            continue
        prev = state.target(pkg.name, target)
        app = Applier(plan, prev, dry_run)
        try:
            new_state = app.run()
        except AgentpackError as exc:
            print(f"error: {pkg.name}/{target}: {exc}")
            ok = False
            continue
        for ch in app.changes:
            ch.path = ch.path or f"{pkg.name}/{target}"
        changes.extend(app.changes)
        if not dry_run:
            state.set_target(pkg.name, target, new_state)
    # targets that were compiled before but are no longer wanted: prune everything
    for target in list(state.package(pkg.name)["targets"]):
        if target not in wanted:
            app = Applier(Plan(), state.target(pkg.name, target), dry_run)
            app.run()
            changes.extend(app.changes)
            if not dry_run:
                state.drop_target(pkg.name, target)
    if not dry_run:
        rec = state.package(pkg.name)
        rec["commit"] = git_head(pkg.root)
        rec["root"] = str(pkg.root)
        rec["version"] = pkg.version
        rec["scope"] = pkg.scope
    return ok, changes


def print_changes(changes: list[Change], show_diff: bool) -> None:
    if not changes:
        print("  nothing to change")
        return
    for ch in changes:
        print(f"  {ch}")
        if show_diff and ch.diff:
            for line in ch.diff.rstrip("\n").split("\n"):
                print(f"    {line}")


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------

def update_checkout(root: Path, ref: str | None) -> str:
    """Fetch and fast-forward the pinned ref. Never rebases. Returns a one-line status."""
    if not git_is_repo(root):
        return "not a git repository; compiled as-is"
    if not ref:
        return "no ref pinned; compiled as-is"
    remotes = git(root, "remote").stdout.split()
    if "origin" not in remotes:
        return "no origin remote; compiled as-is"
    fetch = git(root, "fetch", "--quiet", "origin", ref, check=False)
    if fetch.returncode != 0:
        return f"fetch failed: {fetch.stderr.strip()}; compiled as-is"
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip()
    if branch != ref:
        return f"checkout is on {branch!r}, pinned ref is {ref!r}; compiled as-is"
    dirty = git(root, "status", "--porcelain", check=False).stdout.strip()
    local = git(root, "rev-parse", "HEAD").stdout.strip()
    remote = git(root, "rev-parse", "FETCH_HEAD").stdout.strip()
    if local == remote:
        return "up to date"
    base = git(root, "merge-base", local, remote, check=False).stdout.strip()
    if base == local:
        if dirty:
            return "behind origin but working tree is dirty; left untouched"
        ff = git(root, "merge", "--ff-only", "--quiet", "FETCH_HEAD", check=False)
        if ff.returncode != 0:
            return f"fast-forward failed: {ff.stderr.strip()}"
        return f"fast-forwarded to {remote[:12]}"
    if base == remote:
        return "ahead of origin (unpushed local commits); left untouched"
    return "diverged from origin; left untouched, needs a manual merge"


def cmd_sync(args) -> int:
    paths = Paths(args.home)
    state = State(paths.state_file)
    hosts = load_host_packages(paths.home)
    known: dict[str, Path] = {}
    for hp in hosts:
        if (hp.path / MANIFEST).is_file():
            try:
                known[load_package(hp.path).name] = hp.path
            except AgentpackError:
                pass
    failed = 0
    seen: set[str] = set()
    for hp in hosts:
        print(f"== {hp.path}")
        print(f"  checkout: {update_checkout(hp.path, hp.ref)}")
        try:
            pkg_name = load_package(hp.path).name
            seen.add(pkg_name)
            ok, changes = compile_package(hp.path, paths, state, None, hp.targets, args.dry_run, known)
        except AgentpackError as exc:
            print(f"error: {exc}")
            failed += 1
            continue
        print_changes(changes, args.diff)
        if not ok:
            failed += 1
    # packages removed from the host manifest: prune their outputs
    for name in list(state.data["packages"]):
        if name not in seen:
            print(f"== {name} (removed from host manifest)")
            for target in list(state.package(name)["targets"]):
                app = Applier(Plan(), state.target(name, target), args.dry_run)
                app.run()
                print_changes(app.changes, args.diff)
            if not args.dry_run:
                state.drop_package(name)
    if not args.dry_run:
        state.save()
    if failed:
        print(f"sync: {failed} package(s) failed")
        return 1
    print("sync: ok" + (" (dry run)" if args.dry_run else ""))
    return 0


# ---------------------------------------------------------------------------
# other commands
# ---------------------------------------------------------------------------

def cmd_validate(args) -> int:
    pkg = load_package(args.package)
    for w in pkg.warnings:
        print(f"warning: {w}")
    skills = discover(pkg)
    errors: list[str] = []
    if pkg.memory_schema:
        schema = load_schema(pkg.memory_schema, pkg.root)
        _, errors = load_records(schema)
        for e in errors:
            print(f"error: memory: {e}")
    print(
        f"{pkg.name} {pkg.version} ({pkg.scope}, {pkg.sensitivity}): "
        f"{len(skills)} skills, {len(pkg.connections)} connections, targets {', '.join(pkg.targets)}"
    )
    return 1 if errors else 0


def cmd_compile(args) -> int:
    paths = Paths(args.home)
    state = State(paths.state_file)
    targets = args.target or None
    ok, changes = compile_package(args.package, paths, state, targets, None, args.dry_run)
    print_changes(changes, args.diff)
    if not args.dry_run:
        state.save()
    return 0 if ok else 1


def cmd_status(args) -> int:
    paths = Paths(args.home)
    state = State(paths.state_file)
    if not state.data["packages"]:
        print("no packages compiled on this host")
        return 0
    for name, rec in sorted(state.data["packages"].items()):
        root = Path(rec.get("root") or "")
        head = git_head(root) if root.exists() else None
        drift = "" if head == rec.get("commit") else f"  DRIFT: checkout {head} vs compiled {rec.get('commit')}"
        print(f"{name} {rec.get('version', '')} [{rec.get('scope', '')}] {root} @ {rec.get('commit')}{drift}")
        for target, ts in sorted(rec.get("targets", {}).items()):
            n = sum(len(v) for v in ts.values())
            print(f"  {target}: {n} owned items")
    return 0


def cmd_memory(args) -> int:
    pkg = load_package(args.package)
    if pkg.memory_schema is None:
        print(f"{pkg.name}: no memory schema declared")
        return 0
    schema = load_schema(pkg.memory_schema, pkg.root)
    records, errors = load_records(schema)
    if args.memory_cmd == "validate":
        for e in errors:
            print(f"error: {e}")
        print(f"{pkg.name}: {len(records)} valid records, {len(errors)} errors")
        return 1 if errors else 0
    if args.memory_cmd in ("index", "render"):
        changes, errors = memory_render(pkg, dry_run=False)
        for e in errors:
            print(f"error: {e}")
        if args.memory_cmd == "index":
            # render() also refreshes the skill and contract; index alone is what the hook wants
            pass
        for ch in changes:
            print(f"  {ch}")
        if args.git_add and git_is_repo(pkg.root):
            for ch in changes:
                git(pkg.root, "add", "--", ch.path, check=False)
        return 1 if errors else 0
    return 2


def _write_template(dest: Path, name: str, force: bool) -> list[str]:
    created = []
    for src in sorted(TEMPLATE_DIR.rglob("*")):
        rel = src.relative_to(TEMPLATE_DIR)
        target = dest / rel
        if src.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if target.exists() and not force:
            continue
        content = src.read_text(encoding="utf-8").replace("__PACKAGE_NAME__", name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if src.stat().st_mode & 0o111:
            target.chmod(target.stat().st_mode | 0o755)
        created.append(str(rel))
    return created


def cmd_new(args) -> int:
    dest = Path(args.dir).resolve()
    if dest.exists() and any(dest.iterdir()):
        raise AgentpackError(f"{dest}: exists and is not empty")
    name = args.name or re.sub(r"[^a-z0-9-]+", "-", dest.name.lower()).strip("-")
    if args.source:
        subprocess.run(["git", "clone", "--quiet", args.source, str(dest)], check=True)
        remotes = git(dest, "remote").stdout.split()
        if "origin" in remotes:
            git(dest, "remote", "rename", "origin", "upstream")
    else:
        dest.mkdir(parents=True)
        subprocess.run(["git", "init", "--quiet", "-b", "main", str(dest)], check=True)
        _write_template(dest, name, force=True)
    mpath = dest / MANIFEST
    if mpath.is_file():
        text = mpath.read_text(encoding="utf-8")
        text = re.sub(r"^name:.*$", f"name: {name}", text, count=1, flags=re.M)
        mpath.write_text(text, encoding="utf-8")
    git(dest, "config", "core.hooksPath", ".githooks")
    git(dest, "add", "-A")
    git(dest, "commit", "--quiet", "-m", f"agentpack: new package {name}", check=False)
    print(f"created package {name} at {dest}")
    return 0


def cmd_init(args) -> int:
    dest = Path(args.dir).resolve()
    if not dest.is_dir():
        raise AgentpackError(f"{dest}: not a directory")
    name = args.name or re.sub(r"[^a-z0-9-]+", "-", dest.name.lower()).strip("-")
    created = _write_template(dest, name, force=False)
    if git_is_repo(dest):
        git(dest, "config", "core.hooksPath", ".githooks")
    for rel in created:
        print(f"  created {rel}")
    print(f"initialized {name} at {dest}; edit {MANIFEST} to declare what the package exposes")
    return 0


def cmd_upstream(args) -> int:
    root = Path(args.package).resolve()
    if not git_is_repo(root):
        raise AgentpackError(f"{root}: not a git repository")
    if "upstream" not in git(root, "remote").stdout.split():
        raise AgentpackError(f"{root}: no `upstream` remote; add one with `git remote add upstream <url>`")
    git(root, "fetch", "--quiet", "upstream")
    head = git(root, "symbolic-ref", "refs/remotes/upstream/HEAD", check=False).stdout.strip()
    ref = head.rsplit("/", 1)[-1] if head else "main"
    res = git(root, "merge", "--no-edit", f"upstream/{ref}", check=False)
    print(res.stdout.strip() or res.stderr.strip())
    return res.returncode


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentpack", description="Compile agent packages into runtime-native surfaces.")
    p.add_argument("--version", action="version", version=f"agentpack {__version__}")
    p.add_argument("--home", type=Path, default=Path(os.environ.get("AGENTPACK_HOME", Path.home())), help="home directory to compile into (default: $HOME)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("validate", help="validate a package")
    s.add_argument("--package", type=Path, default=Path.cwd())
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("compile", help="compile one package into runtime surfaces")
    s.add_argument("--package", type=Path, default=Path.cwd())
    s.add_argument("--target", action="append", choices=TARGETS)
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--diff", action="store_true", help="show unified diffs of planned edits")
    s.set_defaults(func=cmd_compile)

    s = sub.add_parser("sync", help="update and compile every package in the host manifest")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--diff", action="store_true")
    s.set_defaults(func=cmd_sync)

    s = sub.add_parser("status", help="show compiled packages and drift")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("memory", help="validate records, regenerate the index and rendered contract")
    s.add_argument("memory_cmd", choices=["validate", "index", "render"])
    s.add_argument("--package", type=Path, default=Path.cwd())
    s.add_argument("--git-add", action="store_true", help="stage regenerated files (for pre-commit)")
    s.set_defaults(func=cmd_memory)

    s = sub.add_parser("new", help="create a package from the template or a template repository")
    s.add_argument("dir")
    s.add_argument("--from", dest="source", help="template repository URL or path (default: built-in template)")
    s.add_argument("--name")
    s.set_defaults(func=cmd_new)

    s = sub.add_parser("init", help="add the package layout to an existing repository")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("--name")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("upstream", help="merge the template's upstream into this fork")
    s.add_argument("upstream_cmd", choices=["merge"])
    s.add_argument("--package", type=Path, default=Path.cwd())
    s.set_defaults(func=cmd_upstream)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.home.is_absolute() or str(args.home) == "/":
        print("error: --home must be an absolute path other than /", file=sys.stderr)
        return 2
    try:
        return args.func(args)
    except AgentpackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"error: {' '.join(exc.cmd)} failed: {exc.stderr.strip() if exc.stderr else exc}", file=sys.stderr)
        return 1
    except (yaml.YAMLError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
