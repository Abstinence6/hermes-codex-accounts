import json
from unittest.mock import patch
import test_accounts as fixtures
import unittest


class AddTests(unittest.TestCase):
    setUp = fixtures.AccountsTest.setUp
    tearDown = fixtures.AccountsTest.tearDown

    def test_add_check_saves_new_account_and_rejects_duplicate(self):
        import base64
        import httpx
        payload = {'https://api.openai.com/auth': {'chatgpt_account_id': 'new-account'}, 'sub': 'new-user', 'exp': 4000000000}
        token = 'fake.' + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=') + '.fake'
        from hermes_cli import auth_codex
        for duplicate in (False, True):
            with patch.object(auth_codex, '_codex_request_device_code', return_value={'user_code': 'FAKE', 'device_auth_id': 'fake-device', 'interval': 3}):
                self.command('add', session_id='session')
            for state in self.command.logins.values():
                state['next'] = 0
            client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={'authorization_code': 'fake-code', 'code_verifier': 'fake-verifier'})))
            with patch.object(auth_codex, '_codex_http_client', return_value=client), patch.object(auth_codex, '_codex_exchange_authorization_code', return_value={'access_token': token, 'refresh_token': 'fake-new-refresh'}):
                text = self.command('add check', session_id='session')
            self.assertIn('already exists' if duplicate else 'Added', text)
            rows = json.loads(self.auth.read_text())['credential_pool']['openai-codex']
            self.assertEqual(3, len(rows))
            self.assertEqual(self.rows, rows[:2])
            self.assertEqual(token, rows[2]['access_token'])

    def complete_login(self, claims):
        import base64
        import httpx
        token = 'fake.' + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=') + '.fake'
        with patch('hermes_cli.auth_codex._codex_request_device_code', return_value={'user_code': 'FAKE', 'device_auth_id': 'fake', 'interval': 3}):
            self.command('add', session_id='session')
        for state in self.command.logins.values():
            state['next'] = 0
        client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={})))
        with patch('hermes_cli.auth_codex._codex_http_client', return_value=client), patch('hermes_cli.auth_codex._codex_exchange_authorization_code', return_value={'access_token': token}):
            return self.command('add check', session_id='session')

    def test_workspace_members_are_distinct_principals(self):
        for subject in ('alice', 'bob'):
            claims = {'https://api.openai.com/auth': {'chatgpt_account_id': 'workspace'}, 'sub': subject, 'exp': 4000000000}
            self.assertIn('Added', self.complete_login(claims))
            before = self.auth.read_bytes()
            self.assertIn('already exists', self.complete_login(claims))
            self.assertEqual(before, self.auth.read_bytes())
        self.assertEqual(4, len(json.loads(self.auth.read_text())['credential_pool']['openai-codex']))

    def test_missing_principal_claims_refuse_without_save(self):
        for claims in ({}, {'sub': 'alice'}, {'https://api.openai.com/auth': {'chatgpt_account_id': 'workspace'}},
                       {'sub': ' ', 'https://api.openai.com/auth': {'chatgpt_account_id': 'workspace'}}):
            with self.subTest(claims=claims):
                before = self.auth.read_bytes()
                self.assertIn('Refused:', self.complete_login(claims))
                self.assertEqual(before, self.auth.read_bytes())

    def test_add_cancel_bound_to_session(self):
        with patch('hermes_cli.auth_codex._codex_request_device_code', return_value={'user_code': 'FAKE-CODE', 'device_auth_id': 'private-device', 'interval': 5}):
            text = self.command('add', session_id='session')
        self.assertIn('https://auth.openai.com/codex/device', text)
        self.assertIn('FAKE-CODE', text)
        self.assertNotIn('private-device', text)
        self.assertIn('No pending', self.command('add cancel', session_id='other'))
        self.assertIn('Cancelled', self.command('add cancel', session_id='session'))
        self.assertIn('No pending', self.command('add check', session_id='session'))
        self.assertEqual(self.store, json.loads(self.auth.read_text()))
