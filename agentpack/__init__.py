"""agentpack: compile harness-agnostic agent packages into runtime-native surfaces."""

__version__ = "0.1.0"

SPEC_VERSION = 1
TARGETS = ("hermes", "claude", "codex", "opencode", "pi")
SCOPES = ("project", "global")
SENSITIVITIES = ("public", "personal", "sensitive", "highly-sensitive")


class AgentpackError(Exception):
    """Base class for user-facing failures. Message is printed without a traceback."""
