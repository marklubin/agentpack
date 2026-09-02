# agentpack

Compile harness-agnostic agent packages into the native surfaces of Hermes, Claude Code,
Codex, and OpenCode.

An agent package is a git repository with a fixed layout: `package.yaml`, `AGENTS.md`,
`.agents/skills/`, `connections/`, and a typed `memory/` store. The upstream repository is a
template with an empty memory store. You fork it, the fork is your package, and memory
accumulates in the fork. Each host pins a ref of the fork and runs `agentpack sync` on a
timer. The design of record is `spec/agent-package-architecture.md`.

## Install

Needs Python 3.11+ and PyYAML. No other dependencies.

```
git clone <this repo> ~/agentpack
ln -s ~/agentpack/bin/agentpack ~/.local/bin/agentpack
mkdir -p ~/.config/agentpack
```

List the packages this host installs in `~/.config/agentpack/packages.yaml`:

```yaml
packages:
  - path: ~/mission-control
    ref: main
    targets: [hermes, claude, codex, opencode]
  - path: ~/job-search
    ref: main
    targets: [hermes, claude]
```

Then `agentpack sync`, or install the timer:

```
cp systemd/agentpack-sync.* ~/.config/systemd/user/
systemctl --user enable --now agentpack-sync.timer
```

The unit is generic. Host-specific routing such as `OnFailure=` goes in a drop-in under
`~/.config/systemd/user/agentpack-sync.service.d/`.

## The `agentpack` skill

This repository is itself a global-scope package that ships one skill, `agentpack`, covering
how to manage the tool and its packages on a host. Add `~/agentpack` to the host manifest
and every runtime gets it.

## Commands

| Command | What it does |
|---|---|
| `agentpack new DIR [--from URL]` | Create a package from the built-in template or a template repository |
| `agentpack init [DIR]` | Add the package layout to an existing repository without overwriting |
| `agentpack validate --package DIR` | Check the manifest, skills, connections, and memory records |
| `agentpack compile --package DIR [--target T] [--dry-run --diff]` | Compile one package into this host's runtimes |
| `agentpack sync [--dry-run --diff]` | Fetch every pinned ref, fast-forward, compile, prune |
| `agentpack status` | Compiled packages and drift between checkout and compiled commit |
| `agentpack memory validate\|render --package DIR` | Validate records, regenerate the index, contract block, and `remember` skill |
| `agentpack upstream merge --package DIR` | Merge the template's `upstream` remote into a fork |

## What gets written where

| Component | Hermes | Claude Code | Codex | OpenCode |
|---|---|---|---|---|
| Prompt, project scope | native `AGENTS.md` | `CLAUDE.md` containing `@AGENTS.md` | native `AGENTS.md` | native `AGENTS.md` |
| Prompt, global scope | marker block in `~/AGENTS.md` | marker block in `~/.claude/CLAUDE.md` | marker block in `~/.codex/AGENTS.md` | reads Claude's file; nothing written |
| Skills, project scope | native `.agents/skills` plus `skills.trusted_project_dirs` | copies in `.claude/skills/` (gitignored) | native | native |
| Skills, global scope | copies under `~/.local/share/agentpack/hermes/<pkg>/skills` plus `skills.external_dirs` | copies in `~/.claude/skills/` | copies in `~/.codex/skills/` | reads Claude's; nothing written |
| Connection | `mcp_servers.<name>` in `config.yaml` | `.mcp.json` or `~/.claude.json` | `[mcp_servers.<name>]` block in `config.toml` | `mcp.<name>` in `opencode.json` |
| Memory | contract block in `AGENTS.md` plus a generated `remember` skill, same for every runtime | | | |

Rules the tool holds itself to:

- It deletes only what it wrote. Ownership lives in `~/.local/state/agentpack/state.json`.
- Content outside its marker blocks survives. Blocks left by the retired mission-control
  materializer are adopted in place.
- Output is byte-stable: a second run with no input change writes nothing.
- Secrets never enter a package. Connection headers must be `${VAR}` references; each
  runtime gets them in its own spelling (`${VAR}`, `env_http_headers`, `{env:VAR}`).
- Instruction files fit the runtime. It reads Hermes's `context_file_max_chars` and Codex's
  `project_doc_max_bytes`, refuses to write a block that would be truncated, and warns when a
  package's own `AGENTS.md` exceeds the cap.
- Sync never rebases. A diverged checkout is reported and compiled as-is.
- Every edit to a runtime config is validated by re-parsing before it is written, and a
  `.bak-agentpack` copy of the previous file sits beside it.

## Memory

`memory/schema.yaml` declares types. Records are one Markdown file each under
`memory/<type>/<slug>.md` with typed frontmatter. `INDEX.md` is derived; agents never edit
it. The compiler renders the schema into a short contract at the end of `AGENTS.md` and a
`remember` skill with the full read and write procedure. `agentpack memory validate` runs on
every sync and in the template's pre-commit hook; malformed records fail the run visibly.

## Not in v1

Scheduled tasks, hooks, Cursor and Gemini backends, a package registry, and enforcing
per-tool allowlists on runtimes that lack them (rendered as policy text instead).

## Tests

```
python3 -m unittest discover -s tests -v
```
