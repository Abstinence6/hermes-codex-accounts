import json
import unittest
from unittest.mock import patch
import httpx
import test_accounts as fixtures


class ResetTests(unittest.TestCase):
    setUp = fixtures.AccountsTest.setUp
    tearDown = fixtures.AccountsTest.tearDown
    list_accounts = fixtures.AccountsTest.list_accounts

    def test_reset_unavailable_never_posts_or_changes_local_status(self):
        self.list_accounts()
        prompt = self.command('reset 1', session_key='test')
        code = prompt.split('confirm ')[1].split()[0]
        before = self.auth.read_bytes()
        methods = []
        def transport(req):
            methods.append(req.method)
            return httpx.Response(200, json={'rate_limit_reset_credits': {'available_count': 0}})
        with patch('httpx.Client', return_value=httpx.Client(transport=httpx.MockTransport(transport))):
            self.assertIn('not requested', self.command('reset 1 confirm ' + code, session_key='test'))
        self.assertEqual(['GET'], methods)
        self.assertEqual(before, self.auth.read_bytes())

    def test_reset_stale_index_and_unauthorized_owner_do_not_request(self):
        self.list_accounts()
        self.rows.reverse()
        self.rows[0]['priority'], self.rows[1]['priority'] = 0, 1
        self.auth.write_text(json.dumps(self.store))
        with patch('httpx.Client', side_effect=AssertionError('must not contact provider')):
            self.assertIn('changed', self.command('reset 1', session_key='test'))
            self.assertIn('owner', self.command('reset 1', platform='telegram', session_id='s'))

    def test_provider_reset_requires_confirmation_and_reads_back_nth_account(self):
        self.list_accounts()
        before = self.auth.read_bytes()
        calls = []
        payload = {'rate_limit': {'primary_window': {'used_percent': 100}}, 'rate_limit_reset_credits': {'available_count': 1}}
        def transport(req):
            calls.append((req.method, req.headers['authorization']))
            return httpx.Response(200, json={'code': 'reset'} if req.method == 'POST' else payload)
        client = httpx.Client(transport=httpx.MockTransport(transport))
        with patch('httpx.Client', return_value=client):
            prompt = self.command('reset 2', session_key='test')
            self.assertIn('confirm', prompt)
            self.assertEqual([], calls)
            code = prompt.split('confirm ')[1].split()[0]
            output = self.command('reset 2 confirm ' + code, session_key='test')
        self.assertIn('Provider confirmed', output)
        self.assertEqual([('GET', 'Bearer fake-token-two'), ('POST', 'Bearer fake-token-two'), ('GET', 'Bearer fake-token-two')], calls)
        self.assertEqual(before, self.auth.read_bytes())
