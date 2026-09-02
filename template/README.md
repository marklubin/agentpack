# __PACKAGE_NAME__

An agent package: instructions, skills, MCP connections, and a typed memory store in one
git repository, compiled into Hermes, Claude Code, Codex, and OpenCode by `agentpack`.

- `package.yaml` declares what the package exposes.
- `AGENTS.md` is the contract every runtime reads.
- `.agents/skills/<name>/SKILL.md` are skills in the shared Agent Skills format.
- `connections/*.yaml` declare MCP servers with secrets by environment variable name.
- `memory/schema.yaml` declares memory types; records accumulate under `memory/<type>/`.

Fork this repository to get your own copy. Memory records stay in your fork. Merge the
template's updates with `agentpack upstream merge` when you choose.
