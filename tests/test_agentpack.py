"""End-to-end tests against a scratch HOME. Run: python3 -m unittest discover -s tests -v"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentpack import AgentpackError  # noqa: E402
from agentpack.cli import main  # noqa: E402
from agentpack.connections import load_connection  # noqa: E402
from agentpack.markers import apply_block, remove_block  # noqa: E402


def run(*args: str) -> int:
    return main(list(args))


class MarkerTests(unittest.TestCase):
    def test_insert_replace_remove_and_legacy_adoption(self):
        text = "# mine\nkeep this\n"
        t1 = apply_block(text, "html", "agentpack:x", "body one\n")
        self.assertTrue(t1.startswith("<!-- agentpack:x:begin -->\nbody one\n<!-- agentpack:x:end -->\n\n# mine"))
        t2 = apply_block(t1, "html", "agentpack:x", "body two\n")
        self.assertIn("body two", t2)
        self.assertNotIn("body one", t2)
        self.assertEqual(t2.count("agentpack:x:begin"), 1)
        legacy = "<!-- old:id:begin -->\nold\n<!-- old:id:end -->\n\ntail\n"
        t3 = apply_block(legacy, "html", "agentpack:x", "new\n", legacy_ids=("old:id",))
        self.assertEqual(t3, "<!-- agentpack:x:begin -->\nnew\n<!-- agentpack:x:end -->\n\ntail\n")
        self.assertEqual(remove_block(t3, "html", "agentpack:x"), "tail\n")
        with self.assertRaises(AgentpackError):
            apply_block("<!-- agentpack:x:begin -->\n<!-- agentpack:x:begin -->\n", "html", "agentpack:x", "b")


class ConnectionTests(unittest.TestCase):
    def test_rejects_literal_secret_in_header(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.yaml"
            p.write_text("name: c\ntransport: http\nurl: https://x.test/mcp\nheaders:\n  X-Key: abcdefghijklmnopqrstuvwxyz0123456789\n")
            with self.assertRaises(AgentpackError):
                load_connection(p)
            p.write_text("name: c\ntransport: http\nurl: https://x.test/mcp\nheaders:\n  X-Key: ${X_KEY}\n")
            c = load_connection(p)
            self.assertEqual(c.env_refs(), ["X_KEY"])


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="agentpack-test-"))
        self.home = self.tmp / "home"
        for d in (".claude", ".codex", ".hermes", ".config/opencode"):
            (self.home / d).mkdir(parents=True)
        (self.home / ".hermes" / "config.yaml").write_text("model:\n  default: m\nskills:\n  external_dirs:\n    - /keep/me\nmcp_servers:\n  other:\n    url: http://keep\n")
        (self.home / ".codex" / "config.toml").write_text('model = "x"\n\n[mcp_servers.router]\nurl = "https://old.test/mcp"\n\n[projects."/x"]\ntrust_level = "trusted"\n')
        (self.home / ".claude" / "CLAUDE.md").write_text("<!-- mission-control:global-agent-instructions:begin -->\nold\n<!-- mission-control:global-agent-instructions:end -->\n\n# Global Rules\nkeep\n")
        (self.home / ".claude.json").write_text('{"mcpServers": {"router": {"type": "http", "url": "https://old.test/mcp"}}, "other": 1}')
        self.pkg = self.tmp / "pkg"
        self.assertEqual(run("new", str(self.pkg), "--name", "demo"), 0)
        (self.pkg / "memory" / "schema.yaml").write_text(
            "store: memory\ntypes:\n  - name: fact\n    fields: [subject, fact, source, observed_at]\n    index: [fact, source]\n    write: agent\n    privacy: personal\n"
        )
        (self.pkg / "memory" / "fact").mkdir()
        (self.pkg / "memory" / "fact" / "one.md").write_text("---\ntype: fact\nsubject: s\nsource: src\nobserved_at: 2026-01-01\n---\nA fact.\n")
        (self.pkg / "connections" / "router.yaml").write_text("name: router\ntransport: http\nurl: https://new.test/mcp\nheaders:\n  X-Key: ${R_KEY}\ntools:\n  include: [a]\n")
        self.manifest = (self.pkg / "package.yaml").read_text().replace("connections: []", "connections:\n  - connections/router.yaml")
        (self.pkg / "package.yaml").write_text(self.manifest)
        skill = self.pkg / ".agents" / "skills" / "hello"
        skill.mkdir()
        (skill / "SKILL.md").write_text("---\nname: hello\ndescription: Say hello.\n---\nhi\n")
        subprocess.run(["git", "-C", str(self.pkg), "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.pkg), "commit", "-qm", "fixture"], check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_project_scope_compile_prune_and_idempotency(self):
        self.assertEqual(run("--home", str(self.home), "compile", "--package", str(self.pkg)), 0)
        self.assertEqual((self.pkg / "CLAUDE.md").read_text(), "@AGENTS.md\n")
        self.assertTrue((self.pkg / ".claude" / "skills" / "hello" / "SKILL.md").is_file())
        self.assertTrue((self.pkg / ".claude" / "skills" / "remember" / "SKILL.md").is_file())
        self.assertIn("agentpack:memory:begin", (self.pkg / "AGENTS.md").read_text())
        self.assertIn("- one: A fact. · src", (self.pkg / "memory" / "INDEX.md").read_text())
        hermes = yaml.safe_load((self.home / ".hermes" / "config.yaml").read_text())
        self.assertEqual(hermes["skills"]["external_dirs"], ["/keep/me"])
        self.assertEqual(hermes["skills"]["trusted_project_dirs"], [str(self.pkg)])
        self.assertEqual(hermes["mcp_servers"]["router"]["headers"], {"X-Key": "${R_KEY}"})
        self.assertEqual(hermes["mcp_servers"]["other"], {"url": "http://keep"})
        codex = tomllib.loads((self.pkg / ".codex" / "config.toml").read_text())
        self.assertEqual(codex["mcp_servers"]["router"]["env_http_headers"], {"X-Key": "R_KEY"})
        oc = json.loads((self.pkg / ".opencode" / "opencode.json").read_text())
        self.assertEqual(oc["mcp"]["router"]["headers"], {"X-Key": "{env:R_KEY}"})
        mcp = json.loads((self.pkg / ".mcp.json").read_text())
        self.assertEqual(mcp["mcpServers"]["router"]["url"], "https://new.test/mcp")

        # idempotent: nothing changes on a second run
        before = {p: p.read_bytes() for p in self.pkg.rglob("*") if p.is_file() and ".git/" not in str(p)}
        self.assertEqual(run("--home", str(self.home), "compile", "--package", str(self.pkg)), 0)
        after = {p: p.read_bytes() for p in self.pkg.rglob("*") if p.is_file() and ".git/" not in str(p)}
        self.assertEqual(before, after)

        # drop the connection and the skill: prune removes exactly them, keeps the rest
        (self.pkg / "package.yaml").write_text(self.manifest.replace("connections:\n  - connections/router.yaml", "connections: []"))
        shutil.rmtree(skill)
        self.assertEqual(run("--home", str(self.home), "compile", "--package", str(self.pkg)), 0)
        hermes = yaml.safe_load((self.home / ".hermes" / "config.yaml").read_text())
        self.assertNotIn("router", hermes["mcp_servers"])
        self.assertIn("other", hermes["mcp_servers"])
        self.assertFalse((self.pkg / ".claude" / "skills" / "hello").exists())
        self.assertTrue((self.pkg / ".claude" / "skills" / "remember").exists())
        self.assertNotIn("router", json.loads((self.pkg / ".mcp.json").read_text())["mcpServers"])

    def test_global_scope_adopts_legacy_block_and_unmanaged_tables(self):
        (self.pkg / "package.yaml").write_text(
            "spec: 1\nname: mission-control\nversion: 1.0.0\nscope: global\nsensitivity: personal\n"
            "prompts:\n  contract: AGENTS.md\n  fragments:\n    - path: prompts/policy.md\n"
            "skills:\n  dir: .agents/skills\nconnections:\n  - connections/router.yaml\n"
        )
        (self.pkg / "prompts").mkdir()
        (self.pkg / "prompts" / "policy.md").write_text("---\ntype: x\n---\n\n# Policy\nbe good\n")
        self.assertEqual(run("--home", str(self.home), "compile", "--package", str(self.pkg)), 0)
        claude_md = (self.home / ".claude" / "CLAUDE.md").read_text()
        self.assertEqual(claude_md, "<!-- agentpack:mission-control:begin -->\n# Policy\nbe good\n<!-- agentpack:mission-control:end -->\n\n# Global Rules\nkeep\n")
        self.assertTrue((self.home / ".claude" / "skills" / "hello" / "SKILL.md").is_file())
        cj = json.loads((self.home / ".claude.json").read_text())
        self.assertEqual(cj["mcpServers"]["router"]["url"], "https://new.test/mcp")
        self.assertEqual(cj["other"], 1)
        codex_text = (self.home / ".codex" / "config.toml").read_text()
        codex = tomllib.loads(codex_text)
        self.assertEqual(codex["mcp_servers"]["router"]["url"], "https://new.test/mcp")
        self.assertEqual(codex["projects"]["/x"]["trust_level"], "trusted")
        self.assertEqual(codex_text.count("[mcp_servers.router]"), 1)
        hermes = yaml.safe_load((self.home / ".hermes" / "config.yaml").read_text())
        self.assertIn(str(self.home / ".local/share/agentpack/hermes/mission-control/skills"), hermes["skills"]["external_dirs"])
        # global scope may not carry memory
        self.assertFalse((self.pkg / "memory" / "INDEX.md").exists())

    def test_memory_validation_reports_bad_records(self):
        (self.pkg / "memory" / "fact" / "bad.md").write_text("---\ntype: fact\nsubject: s\nextra: nope\n---\nx\n")
        self.assertEqual(run("memory", "validate", "--package", str(self.pkg)), 1)
        self.assertEqual(run("--home", str(self.home), "compile", "--package", str(self.pkg)), 1)

    def test_sync_prunes_packages_removed_from_host_manifest(self):
        cfg = self.home / ".config" / "agentpack"
        cfg.mkdir(parents=True)
        (cfg / "packages.yaml").write_text(f"packages:\n  - path: {self.pkg}\n    targets: [hermes]\n")
        self.assertEqual(run("--home", str(self.home), "sync"), 0)
        hermes = yaml.safe_load((self.home / ".hermes" / "config.yaml").read_text())
        self.assertIn("router", hermes["mcp_servers"])
        self.assertFalse((self.pkg / "CLAUDE.md").exists())  # claude not a host target
        (cfg / "packages.yaml").write_text("packages: []\n")
        self.assertEqual(run("--home", str(self.home), "sync"), 0)
        hermes = yaml.safe_load((self.home / ".hermes" / "config.yaml").read_text())
        self.assertNotIn("router", hermes["mcp_servers"])
        self.assertEqual(hermes["skills"].get("trusted_project_dirs"), [])


if __name__ == "__main__":
    unittest.main()
