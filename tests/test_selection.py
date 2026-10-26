import json
import base64
import unittest
from unittest.mock import patch
import test_accounts as fixtures


class SelectionTests(unittest.TestCase):
    setUp = fixtures.AccountsTest.setUp
    tearDown = fixtures.AccountsTest.tearDown
    list_accounts = fixtures.AccountsTest.list_accounts

    def test_list_marks_global_preference_and_preserves_identity(self):
        self.rows[1]['label'] = 'Work <account>'
        payload = base64.urlsafe_b64encode(json.dumps({'email': 'work@example.invalid'}).encode()).decode().rstrip('=')
        self.rows[1]['access_token'] = 'fake.' + payload + '.fake'
        self.auth.write_text(json.dumps(self.store))
        self.list_accounts()
        self.assertIn('Global preferred', self.command('2', session_key='test'))
        before = self.auth.read_bytes()
        with patch('agent.account_usage._fetch_codex_account_usage_read_only', return_value=None):
            output = self.command('list', session_key='test', session_id='conversation')
            other = self.command('list', session_key='test', session_id='other')
        self.assertIn('1. Work ＜account＞ — work@example.invalid (id=two) [Active]', output)
        self.assertEqual(output, other)
        self.assertEqual(1, output.count('[Active]'))
        self.assertEqual(before, self.auth.read_bytes())

    def test_list_follows_new_persisted_preference_not_cached_state(self):
        self.list_accounts()
        self.rows.pop(0)
        self.auth.write_text(json.dumps(self.store))
        before = self.auth.read_bytes()
        with patch('agent.account_usage._fetch_codex_account_usage_read_only', return_value=None):
            output = self.command('list', session_key='test')
        self.assertIn('1. Second — email unavailable (id=two) [Active]', output)
        self.assertIn('runtime account is not inferred', output)
        self.assertEqual(before, self.auth.read_bytes())

    def test_empty_pool_has_no_active_marker(self):
        self.auth.write_text(json.dumps({'credential_pool': {'openai-codex': []}}))
        with patch('hermes_cli.auth._load_global_auth_store', return_value={}):
            output = self.list_accounts()
        self.assertNotIn('[Active]', output)
        self.assertIn('No persisted', output)
