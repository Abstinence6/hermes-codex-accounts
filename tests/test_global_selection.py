"""Global preference safety; synthetic isolated auth store only."""
import copy
import json
import unittest
from unittest.mock import patch
import test_accounts as fixtures


class GlobalSelectionTests(unittest.TestCase):
    setUp = fixtures.AccountsTest.setUp
    tearDown = fixtures.AccountsTest.tearDown
    list_accounts = fixtures.AccountsTest.list_accounts

    def saved(self):
        return json.loads(self.auth.read_text())['credential_pool']['openai-codex']

    def test_select_persists_only_order_and_survives_reload(self):
        before = copy.deepcopy(self.rows)
        self.list_accounts()
        with patch('agent.credential_pool.load_pool', side_effect=AssertionError('must not load pool')):
            output = self.command('2', session_key='test')
        self.assertIn('Global preferred', output)
        self.assertIn('Existing runtimes/sessions', output)
        saved = self.saved()
        self.assertEqual(['two', 'one'], [r['id'] for r in saved])
        self.assertEqual([0, 1], [r['priority'] for r in saved])
        strip = lambda rows: {r['id']: {k: v for k, v in r.items() if k != 'priority'} for r in rows}
        self.assertEqual(strip(before), strip(saved))
        other = self.plugin.AccountsCommand(self.home)
        with patch('agent.account_usage._fetch_codex_account_usage_read_only', return_value=None):
            text = other('', session_id='another')
        self.assertIn('1. Second — email unavailable (id=two) [Active]', text)
        self.assertIn('global preferred', text)
        self.assertEqual(1, text.count('[Active]'))
        self.assertFalse(hasattr(other, 'selected'))

    def test_stale_expired_invalid_and_missing_snapshot(self):
        before = self.auth.read_bytes()
        self.assertIn('changed or expired', self.command('2', session_key='test'))
        self.list_accounts()
        for arg in ('0', '3', 'select 99'):
            self.assertIn('Invalid account index', self.command(arg, session_key='test'))
        stamp, fingerprint = self.command.views[('', 'test')]
        self.command.views[('', 'test')] = (stamp - 601, fingerprint)
        self.assertIn('expired', self.command('2', session_key='test'))
        self.assertEqual(before, self.auth.read_bytes())
        self.list_accounts()
        self.rows[1]['label'] = 'new name'
        self.auth.write_text(json.dumps(self.store))
        before = self.auth.read_bytes()
        self.assertIn('changed', self.command('2', session_key='test'))
        self.assertEqual(before, self.auth.read_bytes())

    def test_readback_detects_noop_writer_and_token_damage(self):
        from hermes_cli import auth
        real_write = auth.write_credential_pool
        for damage in (False, True):
            self.auth.write_text(json.dumps(self.store))
            self.list_accounts()
            def write(provider, rows, **kwargs):
                if damage:
                    rows[0]['access_token'] = 'damaged-fake-token'
                    return real_write(provider, rows, **kwargs)
            with patch.object(auth, 'write_credential_pool', side_effect=write):
                output = self.command('select 2', session_key='test')
            self.assertIn('could not be verified', output)
            self.assertNotIn('Global preferred account set', output)
            self.assertNotIn('damaged-fake-token', output)

    def test_latest_tokens_not_list_snapshot(self):
        self.list_accounts()
        self.rows[1]['access_token'] = 'rotated-fake-token'
        self.rows[1]['refresh_token'] = 'rotated-fake-refresh'
        self.auth.write_text(json.dumps(self.store))
        self.assertIn('Global preferred', self.command('select 2', session_key='test'))
        self.assertEqual('rotated-fake-token', self.saved()[0]['access_token'])
        self.assertEqual('rotated-fake-refresh', self.saved()[0]['refresh_token'])

    def test_duplicate_or_missing_ids_refuse_without_write(self):
        for ident in ('one', '', None):
            self.rows[1]['id'] = ident
            self.auth.write_text(json.dumps(self.store))
            self.list_accounts()
            before = self.auth.read_bytes()
            self.assertIn('Refused:', self.command('2', session_key='test'))
            self.assertEqual(before, self.auth.read_bytes())

    def test_borrowed_pool_and_profile_mismatch_refuse(self):
        from hermes_cli import auth
        self.list_accounts()
        with patch.object(auth, '_load_auth_store', return_value={'credential_pool': {}}), \
                patch.object(auth, 'read_credential_pool', return_value=copy.deepcopy(self.rows)), \
                patch.object(auth, 'write_credential_pool') as write:
            self.assertIn('owning profile', self.command('2', session_key='test'))
            write.assert_not_called()
        self.command.home = self.home / 'other'
        self.assertIn('another profile', self.command('2', session_key='test'))

    def test_existing_sdk_keeps_bound_credential(self):
        import httpx
        from openai import OpenAI
        from test_surfaces import SurfaceTests
        from hermes_cli.middleware import run_llm_execution_middleware
        manager = SurfaceTests.load_manager(self)
        self.command = manager._plugin_commands['codex_accounts']['handler']
        self.list_accounts()
        wire = []
        def transport(request):
            wire.append(request.headers['Authorization'])
            return httpx.Response(200, json={'id': 'response', 'object': 'response', 'created_at': 0, 'output': []})
        with OpenAI(api_key='fake-token-one', base_url='https://chatgpt.com/backend-api/codex',
                    http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
            with patch('hermes_cli.plugins._delivery_manager', return_value=manager):
                for switch in (False, True):
                    if switch:
                        self.assertIn('Global preferred', self.command('2', session_key='test'))
                    result = run_llm_execution_middleware({'model': 'test', 'input': 'same history'},
                        lambda request: client.responses.create(**request), session_id='conversation',
                        provider='openai-codex', api_mode='codex_responses', base_url=str(client.base_url))
                    self.assertEqual('response', result.id)
        self.assertEqual(['Bearer fake-token-one'] * 2, wire)
        self.assertEqual('two', self.saved()[0]['id'])
