# agentpack

This repository is the agentpack tool: spec, CLI, template, and its own operating skill.
Read `README.md` for usage and `spec/agent-package-architecture.md` for the design of record.

- Run the tests before and after any change: `python3 -m unittest discover -s tests`.
- The compiler writes only what it records in the state file. Every new output kind needs
  a matching prune path and a test.
- Keep the template a valid, empty package. `agentpack new` copies it verbatim.
- No dependencies beyond Python 3.11 and PyYAML.
