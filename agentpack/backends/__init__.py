from .base import Context
from .claude import ClaudeBackend
from .codex import CodexBackend
from .hermes import HermesBackend
from .opencode import OpenCodeBackend
from .pi import PiBackend

BACKENDS = {
    "claude": ClaudeBackend,
    "hermes": HermesBackend,
    "codex": CodexBackend,
    "opencode": OpenCodeBackend,
    "pi": PiBackend,
}

__all__ = ["BACKENDS", "Context"]
