---
name: agentpack
description: "Use when managing agentpack itself or any agent package on this host: creating or forking a package, adding skills, connections, or memory types, installing a package on a host, running or debugging sync, checking what is compiled into Hermes, Claude Code, Codex, or OpenCode, or when a runtime config carries an agentpack marker block."
---

# Managing agentpack and packages

agentpack compiles agent packages (git repos with `package.yaml`, `AGENTS.md`,
`.agents/skills/`, `connections/`, `memory/`) into the native surfaces of Hermes, Claude
Code, Codex, and OpenCode. It runs from a timer, writes only files and config keys it owns,
and exits. The design of record is `~/agentpack/spec/agent-package-architecture.md`.

## Where things are

| Thing | Path |
|---|---|
| Tool repo and CLI | `~/agentpack`, `~/agentpack/bin/agentpack` (linked at `~/.local/bin/agentpack`) |
| Host manifest (which packages this host installs) | `~/.config/agentpack/packages.yaml` |
| Ownership state (what the tool wrote, for prune) | `~/.local/state/agentpack/state.json` |
| Materialized copies for Hermes | `~/.local/share/agentpack/hermes/<package>/skills/` |
| Timer and its log | `agentpack-sync.timer` (10 min); `journalctl --user -u agentpack-sync.service` |
| Built-in template | `~/agentpack/template/` |

Runtime surfaces the tool writes into, all inside `# agentpack:<pkg>` or
`<!-- agentpack:<pkg> -->` markers or under recorded keys: `~/.claude/CLAUDE.md`,
`~/.claude/skills/`, `~/.claude.json`, `~/AGENTS.md`, `~/.hermes/config.yaml`
(`skills.external_dirs`, `skills.trusted_project_dirs`, `mcp_servers.*`),
`~/.codex/AGENTS.md`, `~/.codex/skills/`, `~/.codex/config.toml`,
`~/.config/opencode/opencode.json`, and inside project packages `CLAUDE.md`,
`.claude/skills/` (gitignored), `.mcp.json`, `.codex/config.toml`, `.opencode/opencode.json`.

## Rules

- Change the package, then sync. Never hand-edit a generated file: `memory/INDEX.md`, the
  `remember` skill, the `agentpack:memory` block in `AGENTS.md`, or anything between
  agentpack markers in a runtime file. The next sync overwrites it.
- Never put a secret in a package. Connection headers and env values are `${VAR}`
  references; validation rejects literals. Each host provides the variable.
- Skills go in `.agents/skills/<name>/SKILL.md` with `name` and `description` frontmatter.
  `metadata.internal: true` keeps a skill in the repo but out of every runtime.
- Sensitivity gates projection: `sensitive` and `highly-sensitive` packages are project
  scope only. Narrow `targets` in the package or in the host manifest; never widen.
- Scheduled tasks are not part of a package. Hermes cron and the JOBS.md review rule are
  untouched by agentpack.
- Pushing a package, creating a remote, or publishing the template needs Mark's say. Local
  commits inside a package are ordinary work.

## Routine tasks

**See what is compiled and whether it drifted**
```
agentpack status
```
DRIFT means the checkout moved after the last compile; the next sync clears it.

**Sync now, or preview first**
```
agentpack sync --dry-run --diff
agentpack sync
```

**Create a package**
```
agentpack new ~/my-pack                       # from the built-in template
agentpack new ~/my-pack --from <template-url> # fork a template repo; sets `upstream`
```
Then add it to `~/.config/agentpack/packages.yaml` with a `ref` and `targets`, and sync.

**Turn an existing repo into a package**
```
agentpack init ~/existing-repo
```
Adds the layout without overwriting, sets `core.hooksPath` to `.githooks`. Edit
`package.yaml`, then register it in the host manifest.

**Add a skill**: create `.agents/skills/<name>/SKILL.md`, run `agentpack validate
--package <dir>`, commit, sync. Project-scope skills are read natively by Hermes, Codex, and
OpenCode; Claude Code gets a gitignored copy under `.claude/skills/`.

**Add a connection**: one YAML in `connections/`, list it in `package.yaml`. Fields:
`name`, `transport` (`http` or `stdio`), `url` or `command` plus `args`, `headers` or `env`
with `${VAR}` values, optional `tools.include`, `targets`, and `runtime_options` for
per-runtime passthrough keys. Two packages must not declare the same connection name for
the same runtime; the global package owns shared servers.

**Add a memory type**: edit `memory/schema.yaml` (`name`, `fields`, `index`, `write:
agent|approval`, `privacy`), then `agentpack memory render --package <dir>`. That
regenerates the index, the `remember` skill, and the contract block. Records are
`memory/<type>/<slug>.md`, one each, typed frontmatter. `agentpack memory validate` runs on
every sync and in the pre-commit hook.

**Remove a package from a host**: delete its entry from `packages.yaml` and sync. Prune
removes exactly what the state file says was written. To retire a target for one package,
narrow `targets` and sync.

**Merge template updates into a fork**
```
agentpack upstream merge --package <dir>
```
Manual by design. Sync never rebases or merges on its own.

**Upgrade the tool**: `git -C ~/agentpack pull` (or merge), then
`python3 -m unittest discover -s ~/agentpack/tests`, then `agentpack sync --dry-run`.

## Verifying a change landed

- Claude Code: new session; `ls ~/.claude/skills/<name>`; block present in `~/.claude/CLAUDE.md`.
- Hermes: `hermes skills list | grep <name>`; `hermes mcp list`; MCP config auto-reloads,
  the skills index rebuilds on the next prompt.
- Codex: `ls ~/.codex/skills/<name>`; `python3 -c 'import tomllib;tomllib.load(open("/home/mark/.codex/config.toml","rb"))'` parses.
- OpenCode: inherits Claude's skills and instructions; check `~/.config/opencode/opencode.json` for connections.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `exists and is not managed by agentpack` | A file the tool wants to own already exists with different content. Move or delete it, or make it match, then sync. |
| `malformed managed markers` | A runtime file has an unmatched or duplicated agentpack marker. Fix the markers by hand once. |
| `YAML round-trip mismatch, refusing to write` | Hermes config contains something PyYAML cannot reproduce. Nothing was written; inspect `~/.hermes/config.yaml`. |
| `planned edit would produce invalid TOML` | Codex config would not parse after the edit. Nothing was written; look for an unmanaged table with the same name. |
| Sync reports `diverged` or `dirty` | The package checkout is not fast-forwardable. Sync compiled what is checked out; resolve the repo by hand. |
| Timer failed | `journalctl --user -u agentpack-sync.service -n 50`. Failures also route through `salinas-maintenance-failure@`. |
| Pre-commit says agentpack not on PATH | The committing process lacks `~/.local/bin`. Records were not validated in that commit; the next sync validates them. |
| Hermes does not see project skills | The repo must be in `skills.trusted_project_dirs`; sync adds it for project-scope packages. |
| A previous `.bak-agentpack` file | The tool keeps one rolling backup beside each runtime config it rewrites. Safe to delete. |

## Not in v1

Scheduled tasks, hooks, per-package evals (design note in `~/agentpack/spec/evals-next-iteration.md`), Cursor and Gemini backends, a package registry.
