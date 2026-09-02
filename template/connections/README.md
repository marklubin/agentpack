# Connections

One MCP server per YAML file, listed in `package.yaml` under `connections:`.
Secrets are never written here. Header and env values must be `${VAR}` references that
each host resolves from its own environment.

```yaml
name: example
transport: http            # http | stdio
url: https://example.test/mcp
headers:
  Authorization: ${EXAMPLE_TOKEN}
tools:
  include: [search, fetch] # enforced natively by Hermes; policy text elsewhere
targets: [hermes, claude, codex, opencode, pi]
runtime_options:           # optional per-runtime passthrough keys
  hermes: { connect_timeout: 30 }
```

For a stdio server use `command:` plus `args:` and an optional `env:` map.
