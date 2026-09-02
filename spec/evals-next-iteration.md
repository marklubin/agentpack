# Package evals (deferred to the next iteration)

Design note from 2026-09-01. Not implemented. Recorded so the next iteration starts here.

## Two layers, one format

- **Surface evals** are static: the compiled target reflects the package (skill directory
  where the runtime looks, MCP entry with the right allowlist, prompt block or contract in
  place, trust record present). Generated from the manifest, no authoring, run on every
  sync; a failure fails the sync because it is a compiler bug.
- **Behavior evals** launch the runtime headless with a prompt and grade what it did. Cost
  model calls and are noisy, so they run on demand and nightly, never in the sync timer.

Both live in the package as `evals/<name>.yaml`.

## Eval file

```yaml
name: remembers-company-fact
kind: behavior
targets: [hermes, claude, codex, opencode]
requires: []            # e.g. [connection:oxnard, network]; unmet -> skip with reason
runs: 3
pass_at: 2
setup:
  files:
    memory/company-fact/acme-freeze.md: |
      ---
      type: company-fact
      company: Acme
      source: recruiter call
      observed_at: 2026-08-28
      ---
      Acme froze backend hiring through Q4.
prompt: |
  I just learned from a recruiter that Brightline requires three days a week on site.
  Record it, then tell me what we know about Acme's hiring.
expect:
  - record_written: { type: company-fact, fields: { company: Brightline } }
  - records_valid: true
  - skill_loaded: remember
  - answer_contains: "froze backend hiring"
  - no_tool_call: { pattern: "email_send_email" }
```

Graders (deterministic, on the normalized transcript or the working tree after the run):
`record_written`, `records_valid`, `skill_loaded`, `tool_called`, `no_tool_call`,
`file_changed`, `file_unchanged`, `file_matches`, `answer_contains`, `answer_matches`, and an
optional LLM-judged `rubric` that the template evals do not use.

## Isolation

Per run: clone the package at HEAD into scratch, apply `setup.files`, compile into a scratch
home with the existing `--home` machinery, seed credentials by linking each runtime's auth
files read-only (per-adapter seed list, nothing copied or printed), launch the runtime with
its home variable pointed at the scratch home and cwd in the clone, capture, grade, discard.

## Adapter contract

```
launch(prompt, cwd, home) -> Transcript
Transcript: final_text, tool_calls[{server, name, args}], skills_loaded[], files_changed[], exit_code, raw_path
```

Claude Code, Codex, and OpenCode emit structured events in their non-interactive modes.
Hermes needs a spike to confirm tool calls are parseable. A runtime that cannot yield a
signal marks the dependent graders unsupported and evals needing them skip with a reason.

## Results

`~/.local/state/agentpack/evals/<package>/<target>/<timestamp>.json`, a printed
package-by-target matrix, nonzero exit on any failure, and `--record` to write a summary
into the package when a fork should carry its own scorecard.

## Open calls

1. LLM-judged rubrics in v1 or deterministic only (recommend: ship the grader, keep template
   evals deterministic).
2. Nightly behavior run as a systemd timer, Hermes cron, or manual.
3. Credential seeding by read-only links into the scratch home versus running against the
   real home with only a scratch clone.

Build order: surface evals and the adapter contract, then the Claude adapter, then the rest.
