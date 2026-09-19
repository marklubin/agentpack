import contextlib
import io
import unittest

import yaml

from test_agentpack import EndToEndTests, run
from agentpack import AgentpackError
from agentpack.manifest import load_package


class ProfileTests(EndToEndTests):
    def profile_manifest(self, profiles):
        data = yaml.safe_load(self.manifest)
        data.update(scope='global', sensitivity='personal')
        data.pop('memory', None)
        data['hermes'] = {'profiles': profiles}
        (self.pkg / 'package.yaml').write_text(yaml.safe_dump(data))
        return data

    def test_projection_preservation_idempotency_and_prune(self):
        (self.pkg / 'conversation.md').write_text('---\ntype: convention\n---\nTalk directly.\n')
        (self.pkg / 'worker.md').write_text('Return evidence to the coordinator.\n')
        root = self.home / '.hermes'
        worker = root / 'profiles' / 'worker'
        worker.mkdir(parents=True)
        (worker / 'config.yaml').write_text('tts:\n  provider: local\n')
        (worker / '.env').write_text('PRIVATE=keep\n')
        profiles = {
            'default': {'soul': 'conversation.md', 'settings': {'agent.reasoning_effort': 'low'}},
            'worker': {'soul': 'worker.md', 'settings': {'agent.reasoning_effort': 'medium'}},
        }
        self.profile_manifest(profiles)
        args = ('--home', str(self.home), 'compile', '--package', str(self.pkg), '--target', 'hermes')
        self.assertEqual(run(*args), 0)
        cfg = yaml.safe_load((worker / 'config.yaml').read_text())
        self.assertEqual(cfg['agent']['reasoning_effort'], 'medium')
        self.assertEqual(cfg['tts']['provider'], 'local')
        self.assertIn('router', cfg['mcp_servers'])
        self.assertTrue(cfg['skills']['external_dirs'])
        self.assertEqual((root / 'SOUL.md').read_text(), 'Talk directly.\n')
        before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
        self.assertEqual(run(*args), 0)
        self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*') if p.is_file()})
        self.profile_manifest({'default': profiles['default']})
        self.assertEqual(run(*args), 0)
        cfg = yaml.safe_load((worker / 'config.yaml').read_text())
        self.assertNotIn('router', cfg['mcp_servers'])
        self.assertNotIn('reasoning_effort', cfg['agent'])
        self.assertFalse((worker / 'SOUL.md').exists())
        self.assertEqual((worker / '.env').read_text(), 'PRIVATE=keep\n')
        self.assertEqual(cfg['tts']['provider'], 'local')

    def test_rejects_path_escape_secret_settings_and_project_scope(self):
        for profiles in [
            {'../escape': {}},
            {'worker': {'soul': '../outside.md'}},
            {'worker': {'settings': {'api_key': 'secret'}}},
            {'worker': {'settings': {'agent.max_turns': True}}},
            {'worker': {'settings': {'agent.reasoning_effort': 'bad'}}},
        ]:
            with self.subTest(profiles=profiles):
                self.profile_manifest(profiles)
                with self.assertRaises(AgentpackError):
                    load_package(self.pkg)
        data = self.profile_manifest({'worker': {}})
        data['scope'] = 'project'
        (self.pkg / 'package.yaml').write_text(yaml.safe_dump(data))
        with self.assertRaises(AgentpackError):
            load_package(self.pkg)

    def test_respects_named_profile_prompt_cap(self):
        (self.pkg / 'worker.md').write_text('x' * 101)
        self.profile_manifest({'worker': {'soul': 'worker.md'}})
        worker = self.home / '.hermes' / 'profiles' / 'worker'
        worker.mkdir(parents=True)
        (worker / 'config.yaml').write_text('context_file_max_chars: 100\n')
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run('--home', str(self.home), 'compile', '--package', str(self.pkg), '--target', 'hermes'), 1)
        self.assertFalse((worker / 'SOUL.md').exists())
        self.assertEqual((worker / 'config.yaml').read_text(), 'context_file_max_chars: 100\n')
