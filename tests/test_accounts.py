import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hermes_constants import set_hermes_home_override, reset_hermes_home_override

ROOT = Path(__file__).resolve().parents[1]


def load_plugin():
    spec = importlib.util.spec_from_file_location('codex_accounts_plugin', ROOT / '__init__.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AccountsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])
        self.home = Path(self.tmp.name)
        self.scope = set_hermes_home_override(self.home)
        self.rows = [dict(id='one', label='First', priority=0, auth_type='oauth',
                          source='manual:test', base_url='https://chatgpt.com/backend-api/codex', access_token='fake-token-one', refresh_token='fake-refresh'),
                     dict(id='two', label='Second', priority=1, auth_type='oauth',
                          source='manual:test2', base_url='https://chatgpt.com/backend-api/codex', access_token='fake-token-two')]
        self.store = {'version': 1, 'providers': {}, 'credential_pool': {'openai-codex': self.rows}}
        self.auth = self.home / 'auth.json'
        self.auth.write_text(json.dumps(self.store), encoding='utf-8')
        self.plugin = load_plugin()
        self.command = self.plugin.AccountsCommand(self.home)

    def tearDown(self):
        reset_hermes_home_override(self.scope)
        self.tmp.cleanup()

    def test_usage_untrusted_url_never_fetches(self):
        from types import SimpleNamespace
        for url in ('https://attacker.invalid/backend-api/codex',
                    'http://chatgpt.com/backend-api/codex',
                    'https://chatgpt.com:444/backend-api/codex', 'not a URL'):
            with self.subTest(url=url), patch('agent.account_usage._fetch_codex_account_usage_read_only') as fetch:
                result = self.command.usage(SimpleNamespace(access_token='fake-secret', runtime_base_url=url))
                fetch.assert_not_called()
                self.assertIn('unavailable', result[0])

    def test_list_read_only_and_honest_unavailable(self):
        before = self.auth.read_bytes()
        with patch('agent.account_usage._fetch_codex_account_usage_read_only', return_value=None):
            result = self.command('list', session_key='test')
        self.assertIn('1. First', result)
        self.assertIn('2. Second', result)
        self.assertIn('unavailable', result)
        self.assertNotIn('fake-token', result)
        self.assertEqual(before, self.auth.read_bytes())

    def list_accounts(self):
        with patch('agent.account_usage._fetch_codex_account_usage_read_only', return_value=None):
            return self.command('list', session_key='test')

    def test_rename_persists_only_label(self):
        self.list_accounts()
        self.assertIn('Renamed', self.command('ren 2 Work account', session_key='test'))
        after = json.loads(self.auth.read_text())
        self.store['credential_pool']['openai-codex'][1]['label'] = 'Work account'
        after.pop('updated_at', None)
        self.assertEqual(self.store, after)
        self.assertIn('ren n label', self.command('ren 2', session_key='test'))


    def test_delete_requires_bound_confirmation(self):
        self.list_accounts()
        before = self.auth.read_bytes()
        prompt = self.command('del 2', session_key='test')
        self.assertIn('confirm', prompt)
        self.assertEqual(before, self.auth.read_bytes())
        code = prompt.split('confirm ')[1].split()[0]
        self.assertNotIn('Removed', self.command(f'del 2 confirm {code}', session_key='other'))
        self.assertIn('Removed', self.command(f'del 2 confirm {code}', session_key='test'))
        self.assertEqual(['one'], [r['id'] for r in json.loads(self.auth.read_text())['credential_pool']['openai-codex']])
        self.assertNotIn('Removed', self.command(f'del 2 confirm {code}', session_key='test'))


    def test_selection_explicitly_refuses_without_reordering(self):
        before = self.auth.read_bytes()
        for args in ('2', 'select 2'):
            self.assertIn('activation unavailable', self.command(args, session_key='test'))
        self.assertEqual(before, self.auth.read_bytes())

    def test_telegram_requires_explicit_owner_dm(self):
        from gateway.session import SessionSource
        from gateway.config import Platform
        source = SessionSource(platform=Platform.TELEGRAM, chat_id='42', user_id='42')
        before = self.auth.read_bytes()
        self.assertIn('owner', self.command('ren 1 Hijacked', session_key='test', platform='telegram', source=source))
        self.command.owner_ids = lambda: ['42']
        with patch('agent.account_usage._fetch_codex_account_usage_read_only', return_value=None):
            self.assertIn('1. First', self.command('list', session_key='test', platform='telegram', source=source))
        source.chat_type = 'group'
        self.assertIn('owner', self.command('ren 1 Hijacked', session_key='test', platform='telegram', source=source))
        source.chat_type = 'dm'
        source.user_id = '99'
        self.assertIn('owner', self.command('ren 1 Hijacked', session_key='test', platform='telegram', source=source))
        self.assertEqual(before, self.auth.read_bytes())
        source.user_id = '42'
        self.assertIn('Renamed', self.command('ren 1 Owner label', session_key='test', platform='telegram', source=source))


    def test_stale_index_and_expired_confirmation_do_not_mutate(self):
        self.list_accounts()
        prompt = self.command('del 1', session_key='test')
        code = prompt.split('confirm ')[1].split()[0]
        stamp, ident, view, pending_code = self.command.pending[('', 'test')]
        self.command.pending[('', 'test')] = (stamp - 61, ident, view, pending_code)
        before = self.auth.read_bytes()
        self.assertIn('expired', self.command(f'del 1 confirm {code}', session_key='test'))
        self.assertEqual(before, self.auth.read_bytes())
        changed = json.loads(self.auth.read_text())
        changed['credential_pool']['openai-codex'][0]['priority'] = 8
        self.auth.write_text(json.dumps(changed))
        before = self.auth.read_bytes()
        self.assertIn('changed', self.command('ren 1 Wrong', session_key='test'))
        self.assertEqual(before, self.auth.read_bytes())

    def test_rename_preserves_concurrent_token_rotation(self):
        self.list_accounts()
        changed = json.loads(self.auth.read_text())
        changed['credential_pool']['openai-codex'][0]['access_token'] = 'new-generation'
        changed['credential_pool']['openai-codex'][0]['refresh_token'] = 'new-refresh'
        self.auth.write_text(json.dumps(changed))
        self.assertIn('Renamed', self.command('ren 1 Work', session_key='test'))
        row = json.loads(self.auth.read_text())['credential_pool']['openai-codex'][0]
        self.assertEqual(('new-generation', 'new-refresh'), (row['access_token'], row['refresh_token']))

    def test_missing_token_never_resolves_or_refreshes_another_account(self):
        self.rows[0].pop('access_token')
        self.auth.write_text(json.dumps(self.store))
        with patch('agent.account_usage._fetch_codex_account_usage_read_only', return_value=None) as fetch:
            self.assertIn('no access token', self.command('list', session_key='test'))
            self.assertEqual(1, fetch.call_count)

    def test_surface_output_disarms_control_and_markup(self):
        self.rows[0]['label'] = '[red]<b>Account</b>\x1b[31m\nFake row'
        self.auth.write_text(json.dumps(self.store))
        text = self.list_accounts()
        self.assertNotIn('\x1b', text)
        self.assertNotIn('[red]', text)
        self.assertNotIn('<b>', text)
        self.assertNotIn('\nFake row', text)

    def test_telegram_mismatched_dm_chat_is_denied(self):
        from gateway.session import SessionSource
        from gateway.config import Platform
        self.command.owner_ids = lambda: ['42']
        source = SessionSource(platform=Platform.TELEGRAM, chat_id='99', user_id='42')
        self.assertIn('owner', self.command('list', platform='telegram', source=source))


    def test_live_usage_parser_renders_percent_and_reset_without_refresh(self):
        from agent.account_usage import _fetch_codex_account_usage_read_only
        payload = {'plan_type': 'plus', 'rate_limit': {
            'primary_window': {'used_percent': 25, 'reset_at': 2000000000, 'limit_window_seconds': 18000}}}
        with patch('agent.account_usage._get_json', return_value=payload) as get:
            result = self.command('list', session_key='test')
        self.assertEqual(2, get.call_count)
        self.assertIn('25% used', result)
        self.assertIn('resets', result)
        self.assertNotIn('fake-token', result)

    def test_seeded_delete_suppresses_source_without_external_file_deletion(self):
        self.rows[1]['source'] = 'codex_cli'
        self.auth.write_text(json.dumps(self.store))
        external = self.home / 'external-login.json'
        external.write_text('must stay untouched')
        self.list_accounts()
        prompt = self.command('del 2', session_key='test')
        self.assertIn('Second', prompt)
        code = prompt.split('confirm ')[1].split()[0]
        self.assertIn('Removed', self.command(f'del 2 confirm {code}', session_key='test'))
        saved = json.loads(self.auth.read_text())
        self.assertIn('codex_cli', saved['suppressed_sources']['openai-codex'])
        self.assertEqual('must stay untouched', external.read_text())

    def test_exception_does_not_disclose_secrets(self):
        with patch('hermes_cli.auth.read_credential_pool', side_effect=RuntimeError('fake-token-one')):
            result = self.command('list', session_key='test')
        self.assertIn('unavailable', result)
        self.assertNotIn('fake-token', result)


if __name__ == '__main__':
    unittest.main()
