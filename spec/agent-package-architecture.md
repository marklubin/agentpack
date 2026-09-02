---
type: synthesis
status: active
region: structural
title: "Agent package architecture (agentpack)"
created: 2026-09-01
origin: { by: Mark + Claude, at: 2026-09-01, from: agent-package planning session after the Hermes-first refactor }
review: { cadence: 90d, last: 2026-09-01 }
supersedes: archive/2026-09-01-hermes-refactor/lane-plugin-architecture/spec/ (retired lane-plugin drafts)
evidence:
  - archive/2026-09-01-hermes-refactor/lane-plugin-architecture/spec/MANIFEST-SPEC.md
  - archive/2026-09-01-hermes-refactor/codex-salinas-lane-control-plane-hld.md
  - identity/HERMES_PROTOCOL.md
  - bin/sync-skills.sh
  - bin/sync-agent-instructions.sh
note: Design of record, approved by Mark 2026-09-01. Implemented 2026-09-01 in ~/agentpack (spec/ there is the canonical copy; this copy tracks it).
---

# Agent package architecture

An agent package is a git repository with a fixed layout that bundles prompts, skills,
MCP connections, and a scoped memory store, and compiles into the native surfaces of
Hermes, Claude Code, Codex, and OpenCode. The upstream repository is a template with an
empty memory store. You fork it, the fork is your package, and memory accumulates in the
fork through ordinary commits. Each host pins a ref of the fork and runs a sync timer that
fetches, compiles, and prunes. Working name for the format and the CLI: `agentpack`.

This supersedes the 2026-09-01 refactor ruling "keep the shape, drop the compiler". The
lane-plugin idea returns generalized, with one correction: the tool compiles into each
runtime's own config and skill homes and owns nothing at runtime.

## Rulings recorded 2026-09-01

| Question | Ruling |
|---|---|
| Ambition | Personal, built to publish |
| Toolchain home | New standalone repository for spec and CLI |
| v1 targets | Hermes, Claude Code, Codex, OpenCode, all required |
| Distribution | Pull and recompile timer per host, pinned ref |
| Scheduled tasks | Out of scope for v1 |
| Memory | Ontology declared by the package, records stored in the fork |
| Working name | `agentpack` |
| Skills directory | `.agents/skills/` |
| Memory record format | One Markdown file per record with typed frontmatter |
| Template relationship | Separate generic template repository; Mission Control is its first fork |
| Per-host `local/` override layer | Not in v1 |
| Hooks | Deferred |
| Verdict | Approved; write the spec and plan the first slice |

## Key decisions

### Fork model

**What.** The package repository is both definition and instance. Definition files
(manifest, instructions, skills, connection declarations, memory schema) are what upstream
maintains. Instance files (memory records) are what the fork owns. Users get a package by
forking the template; upstream changes arrive as git merges the user runs on purpose.

**Stakes.** This decides where memory lives and how it syncs. If memory lived outside the
repository, cross-host sync would need a service. If the package were installed rather
than forked, user customization would need an overlay format.

**Discarding.** A package registry with installed copies and a separate memory service.
Rejected because it adds a running component and a second sync path for something git
already does.

**Rationale.** Memory sync becomes git. Publishing is safe by construction because upstream
ships an empty store. Customization is editing the fork.

### Compile into native surfaces

**What.** The compiler writes only files and config keys each runtime already reads: skill
directories, marker blocks in instruction files, MCP entries in the runtime's own config.
It runs from a timer and exits.

**Stakes.** The archived compiler was retired because it duplicated native runtime features
and contradicted the charter. A parallel loader would repeat that.

**Discarding.** A unified projected surface per runtime with runtime-side enforcement (the
archived RUNTIME-PROJECTION-SPEC). Rejected because the enforcement half was never
buildable and the projection half duplicated what runtimes do natively.

**Rationale.** Every runtime already has a droppable skills directory, an instruction file
that tolerates a managed block, and an MCP config. Compiling into those is a thin
translation, not a framework.

### Memory as ontology plus files

**What.** The package declares memory types in `memory/schema.yaml`. Records are one
Markdown file each with typed frontmatter under `memory/<type>/`. The index is derived.
The compiler renders the schema into a short contract in the package instructions and a
generated `remember` skill.

**Stakes.** Only Hermes and Claude Code have file-droppable native memory, and they
disagree on format. Without a package-level definition, "scoped memory" is a folder and a
request to be tidy.

**Discarding.** Routing runtime-native memory into the package store. Rejected because
Codex and OpenCode have no file surface, and native stores are per-cwd or global, not
per-package. Native memory stays advisory.

**Rationale.** Files with typed frontmatter are something every runtime can be told to
write from a template in prose, can grep, and can merge without conflict.

### Skills at `.agents/skills/`

**What.** The package's canonical skills directory is `.agents/skills/`.

**Stakes.** Hermes, Codex, and OpenCode read that path natively at project scope. A
top-level `skills/` directory would need a compiled copy for every runtime.

**Discarding.** Top-level `skills/` for template readability. Rejected because zero compile
for three of four runtimes outweighs a hidden directory.

### Standalone toolchain

**What.** The spec, the CLI, and the template live outside Mission Control.

**Stakes.** Mission Control is one package among several. If the tool lived in its `bin/`,
every fork of the template would depend on Mark's personal control plane.

## Model

```
upstream template ──fork──> your fork (definition + memory records)
                               │  autocommit + push (existing timers)
                               │  pull pinned ref (agentpack-sync.timer)
                               ▼
                            host ──agentpack sync──> ~/.hermes/config.yaml
                                                     ~/.claude/skills, ~/.claude/CLAUDE.md
                                                     ~/.codex/config.toml, ~/.codex/skills
                                                     ~/.config/opencode/opencode.json
upstream ┄┄merge when you choose┄┄> your fork
```

Three properties follow. Memory sync is git. Publishing never exposes records because
upstream ships an empty store. User-level customization is the fork itself.

## Package layout

A package is valid when this layout is present and `package.yaml` validates. The template
repository is a valid, empty package. Everything else in the repository is the package's
own business and the compiler ignores it, so an existing lane repository becomes a package
by adding four files.

```
package.yaml            manifest
AGENTS.md               the package's instructions; read natively by Hermes, Codex, OpenCode
prompts/                optional fragments listed in the manifest
.agents/skills/         Agent Skills format, <name>/SKILL.md
connections/            one MCP server per file, secrets by env var name
memory/
  schema.yaml           the memory ontology
  <type>/<slug>.md      records, one per file (instance)
  INDEX.md              derived by the tool (instance)
private/                never compiled, never projected
README.md
```

Definition files: `package.yaml`, `AGENTS.md`, `prompts/`, `.agents/skills/`,
`connections/`, `memory/schema.yaml`. Instance files: `memory/<type>/`, `memory/INDEX.md`.
The manifest does not mark the split; it is fixed by the layout.

## Manifest

The compiler reads only the manifest to learn what a package exposes. It never introspects
skill bodies or memory records.

```yaml
spec: 1
name: job-search
version: 0.3.0
scope: project            # project | global
sensitivity: personal     # public | personal | sensitive | highly-sensitive
targets: [hermes, claude, codex, opencode]

prompts:
  contract: AGENTS.md
  fragments:
    - path: prompts/policy.md
      targets: [hermes, claude]     # optional narrowing

skills:
  dir: .agents/skills
  include: all            # or an explicit list
  exclude: []

connections:
  - connections/oxnard.yaml

memory:
  schema: memory/schema.yaml
  reads_from: []          # other package names, explicit allowlist
```

- `scope: global` compiles into the runtime's home. Personal policy such as Mission
  Control is global. `scope: project` compiles into the repository and per-project runtime
  config. Lanes are project scope.
- `sensitivity` gates projection. `sensitive` and above can only be project scope and
  never write into a shared home.
- `targets` is the package's allowed runtimes. The host manifest can narrow it, never widen.
- `version` is semver for humans. Hosts pin a git ref; compiled markers embed the commit.

Dropped from the archived manifest: the runtime enum in code, the connector catalog as a
prose allowlist, the absolute-path lane registry, the authority block, the schedule block.

## Components

### Prompts

The package holds `AGENTS.md` as its contract and optional fragments under `prompts/`.
Plain Markdown, no templating.

Project scope: `AGENTS.md` is read natively by Hermes, Codex, and OpenCode. The compiler
writes a one-line `CLAUDE.md` containing `@AGENTS.md` for Claude Code. Global scope: a
managed marker block appended to each runtime's global instruction file. Package prompts
layer below host policy and can be stricter, never weaker.

### Skills

`.agents/skills/<name>/SKILL.md`. The frontmatter (`name`, `description`) is already
identical across all four runtimes.

Project scope: nothing to compile for Hermes, Codex, and OpenCode, plus a Hermes
`skills.trusted_project_dirs` entry. Claude Code gets real directory copies under
`.claude/skills/`, gitignored. Global scope: copies into `~/.claude/skills` and
`~/.codex/skills`; Hermes gets copies under `~/.local/share/agentpack/hermes/<pkg>/skills`
and a `skills.external_dirs` entry pointing there, so include and exclude rules hold;
OpenCode gets nothing because it already scans `~/.claude/skills`.

One copy per runtime. Prune only names the tool wrote.

### Connections

One neutral YAML per MCP server. Secrets are env var names, never values.

```yaml
name: oxnard
transport: http            # http | stdio
url: https://example.workers.dev/mcp
headers:
  X-MCP-Secret: ${OXNARD_MCP_SECRET}
tools:
  include: [finance_accounts, finance_transactions, email_list_emails]
```

Compiles to each runtime's own MCP config in its own spelling. `tools.include` is enforced
natively only by Hermes. For the other three the compiler renders the allowlist into the
prompt block as policy text and says so in the compile report.

### Memory

`memory/schema.yaml` declares types. Each type has a name, fields, a write rule, a privacy
class, and which fields appear on the index line.

```yaml
types:
  - name: company-fact
    fields: [company, fact, source, observed_at]
    index: [fact, source, observed_at]
    write: agent          # agents append freely
    privacy: personal
  - name: outreach-decision
    fields: [company, decision, reason]
    index: [decision]
    write: approval       # agent drafts, Mark confirms
    privacy: sensitive
```

A record:

```markdown
---
type: company-fact
company: Acme
source: recruiter call
observed_at: 2026-08-28
---
Acme froze backend hiring through Q4; the platform team is exempt.
```

**How an agent learns to write.** The agent never reads the schema. The compiler renders it
two ways, both committed in the fork:

1. A managed marker block at the bottom of the package's `AGENTS.md`: store path, read
   the index first, the type table with fields and write rules, a frontmatter template.
   About fifteen lines, because it is in every prompt.
2. A generated `.agents/skills/remember/SKILL.md`: when to write, slug rules, update
   instead of duplicate, privacy classes, what "approval" means on each runtime, how to
   search. Loads on demand.

**How an agent reads.** `memory/INDEX.md` is derived, one line per record from
frontmatter, grouped by type, showing the fields the schema marks for the index. The agent
never edits it. Beyond the index the agent greps the store with its shell tool and reads
the one record it needs. Cross-package reads render the other package's store as read-only
when `reads_from` allows it.

**Enforcement.** `agentpack memory validate` runs in the sync timer and fails the run on a
malformed record. The fork ships a pre-commit hook doing the same and regenerating the
index. Nothing is silently fixed; failures surface through the existing
maintenance-failure email path.

Runtime-native memory (Hermes `MEMORY.md`, Claude's per-project memory directory, Codex's
sqlite store) stays advisory and is never canonical for the package. Past a few thousand
records the natural step is a search MCP server over the store, declared as an ordinary
connection. Not v1.

## Compile targets

Every cell names a surface the runtime already has. "Native" means the package file is
read as-is. Verified against the four homes on salinas on 2026-09-01.

| Component | Hermes | Claude Code | Codex | OpenCode |
|---|---|---|---|---|
| Prompt, project | native `AGENTS.md` | `CLAUDE.md` with `@AGENTS.md` | native `AGENTS.md` | native `AGENTS.md` |
| Prompt, global | marker block in `~/AGENTS.md` | marker block in `~/.claude/CLAUDE.md` | marker block in `~/.codex/AGENTS.md` | reads `~/.claude/CLAUDE.md`; write nothing |
| Skills, project | native `.agents/skills` plus trust entry | copy to `.claude/skills/` | native `.agents/skills` | native `.agents/skills` |
| Skills, global | `skills.external_dirs` entry | copy to `~/.claude/skills/` | copy to `~/.codex/skills/` | scans `~/.claude/skills`; write nothing |
| Connection | `mcp_servers.<n>` in `config.yaml`, `${VAR}`, `tools.include`, auto-reload | `.mcp.json` or `~/.claude.json`, `${VAR}` | `[mcp_servers.<n>]` in `config.toml`, `env_http_headers` name map | `mcp.<n>` in `opencode.json`, `{env:VAR}`, `command` as one array |
| Memory | contract in prompt block | contract in prompt block | contract in prompt block | contract in prompt block |
| Reload | MCP auto; skills on next prompt build | new session | skills watched live; MCP restart | new session |

Cautions:

- Claude Code skips symlinked skill directories; OpenCode follows them. Always materialize
  real directories.
- Trust gates need a record, not just a file. Hermes project skills load only when the
  repository is in `skills.trusted_project_dirs`. The compiler writes the artifact and its
  trust record, and prunes both.
- OpenCode reads Claude's home by default. Global scope writes to Claude only and lets
  OpenCode inherit, or OpenCode warns on duplicate names.
- Hermes MCP auto-reload invalidates the prompt cache. A sync run touches `config.yaml` at
  most once.
- Hermes global instructions are cwd-discovered. `~/AGENTS.md` applies to sessions under
  `$HOME`; sessions started elsewhere see only project scope.

## Customization layers

Three layers. Each can narrow or add; none can widen privacy or secret rules set above it.

1. **Upstream template.** Definition defaults, empty memory.
2. **Your fork.** The package. Edit any definition file, accumulate memory, merge upstream
   with `agentpack upstream merge` when you choose.
3. **Host manifest.** `~/.config/agentpack/packages.yaml`: which packages this host
   installs, at which ref, into which runtimes.

```yaml
packages:
  - path: ~/mission-control
    ref: main
    targets: [hermes, claude, codex, opencode]
  - path: ~/job-search-late-2026
    ref: main
    targets: [hermes, claude]
  - path: ~/courtney-knowledge-store
    ref: main
    targets: [hermes]
```

A gitignored per-host `local/` override layer was considered and left out of v1. Add it
when a real per-host difference appears.

## Distribution and updates

Each host runs one systemd user timer, `agentpack-sync.timer`, modeled on
`dotfiles-pull`: fetch, fast-forward the pinned ref, compile, prune. Failure routes through
`salinas-maintenance-failure@`.

- Sync never rebases. A diverged fork is left untouched and reported. Memory writes go
  through the existing autocommit timers, so divergence means something unusual happened.
- Upstream merges are manual. `agentpack upstream merge` wraps `git merge upstream/main`.
  Records are one file each and additive, so upstream rarely touches them.
- `~/.local/state/agentpack/state.json` records every file and config key the tool wrote,
  per package and commit. Prune deletes only what is in state and absent from the new
  compile. This generalizes `identity/skills/managed-skill-names.txt`.
- Output is byte-stable. Two runs with no input change produce identical bytes.
- Markers carry the package name only (`<!-- agentpack:job-search:begin -->`), so output
  stays byte-stable across commits. The compiled commit is recorded in the state file, and
  `agentpack status` compares it to the checkout per package.

Scaffolding: `agentpack new <dir> --from <template-url>` clones the template, sets it as
the `upstream` remote, rewrites `name` in the manifest, and leaves an empty store.
GitHub's "use this template" plus `agentpack init` does the same.

## Safety invariants

- No secret values in a package. Connections reference `${VAR}` only. Validation rejects
  anything that looks like a literal key.
- `private/` is never compiled.
- Sensitivity gates projection. A `sensitive` or `highly-sensitive` package is project
  scope only, and its memory types never render into a global surface.
- The tool deletes only what it wrote. Content outside markers survives.
- No runtime loader. The compiler runs from a timer and exits.
- A package cannot create, enable, or alter a Hermes cron job. The JOBS.md one-by-one
  review rule is untouched.

## Migration plan

Thin vertical slice first, verified, then expand. Each slice ends at "implemented and
locally validated"; Mark reviews before the old path retires.

1. **Repository skeleton.** Create `~/agentpack` with `spec/` (this document, moved),
   `agentpack` CLI (Python, PyYAML only), and `template/` holding the empty package. The
   separate template repository is split out when the first fork other than Mission
   Control needs it.
2. **Mission Control as a global package, Claude Code backend.** Add `package.yaml`,
   point `skills.dir` at `identity/skills` for now, declare `identity/agent-policy/*.md`
   as prompt fragments and `connections/mcp-router.yaml`. `agentpack compile --target
   claude --dry-run` must reproduce today's `~/.claude/skills` and the CLAUDE.md managed
   block byte for byte except the marker rename. That diff is the acceptance test. The
   three `bin/sync-*.sh` scripts retire only after Mark accepts.
3. **Hermes backend.** `skills.external_dirs`, `mcp_servers` with `${VAR}` and
   `tools.include`, `~/AGENTS.md` marker block. Verify a Hermes session sees the skills
   index and the narrowed Oxnard tools.
4. **Codex and OpenCode backends.** Codex includes removing the duplicated learning-review
   hook registration and the stale managed block in `~/.codex/AGENTS.md`. OpenCode is
   mostly connection config because it inherits Claude's skills and instructions.
5. **Memory in the job-search package.** Schema, `remember` skill, index, validate,
   pre-commit hook. Job search already has `.agents/skills` and a `memory/` directory.
6. **Remaining lanes and the timer.** Courtney as `highly-sensitive`, Hermes only.
   Finance with no skills and a read-only Oxnard connection. `agentpack-sync.timer` on
   salinas, then a second host, which is where distribution is actually proven.

## Not in v1

- Scheduled tasks.
- Hooks. Codex, Claude, and Hermes have shell hooks with different trust records; OpenCode
  uses TypeScript plugins.
- Cursor and Gemini backends. The retired projection code in git history before `e6ca7cd`
  shows the conventions.
- A package registry or marketplace. Distribution is a git URL.
- Enforcing per-tool allowlists on runtimes that lack them.
- Runtime-native memory import or export.

## Evidence

- Runtime surfaces: `~/.hermes/hermes-agent/hermes_cli/config_defaults.py`,
  `agent/skill_utils.py`, `hermes_cli/mcp_config.py`; `~/.claude/plugins/cache/*/*/*/.mcp.json`;
  `~/.codex/config.toml`; the OpenCode binary's `src/skill/discovery.ts` and
  `src/session/instruction.ts` string tables. Surveyed 2026-09-01.
- Archived design: `archive/2026-09-01-hermes-refactor/lane-plugin-architecture/spec/`
  and local branches `lane-plugin-architecture/phase-{0-spec-docs,1-self-host,4-compiler}`.
- Review walkthrough with Mark's recorded calls: claude.ai artifact
  `19fa1af8-964b-40b2-b7ea-f739ff4009b2`.
