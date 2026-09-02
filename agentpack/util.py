"""Small shared helpers: frontmatter, git, atomic writes."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (frontmatter_text, body). Frontmatter is the leading --- block, if any."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :])
    return None, text


def body_without_frontmatter(text: str) -> str:
    """Body with frontmatter and leading blank lines removed, ending in exactly one newline."""
    _, body = split_frontmatter(text)
    body = body.lstrip("\n")
    return body.rstrip("\n") + "\n" if body.strip() else ""


def parse_simple_yaml_frontmatter(fm: str | None) -> dict:
    """Parse frontmatter with PyYAML; malformed frontmatter raises ValueError."""
    if not fm:
        return {}
    import yaml

    try:
        data = yaml.safe_load(fm)
    except yaml.YAMLError as exc:  # noqa: PERF203
        raise ValueError(f"invalid frontmatter: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("frontmatter is not a mapping")
    return data


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def git_head(root: Path) -> str | None:
    try:
        return git(root, "rev-parse", "--short=12", "HEAD").stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def git_is_repo(root: Path) -> bool:
    try:
        return git(root, "rev-parse", "--is-inside-work-tree").stdout.strip() == "true"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def atomic_write_text(path: Path, content: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        if mode is not None:
            os.chmod(tmp, mode)
        elif path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def expand_home(p: str, home: Path) -> Path:
    if p == "~":
        return home
    if p.startswith("~/"):
        return home / p[2:]
    return Path(os.path.expandvars(p))
