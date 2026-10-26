"""Executable evidence: supported middleware cannot see SDK-owned credentials."""
import base64
import json
from unittest.mock import patch

import test_accounts as fixtures
import unittest


class RuntimeIdentitySeamTests(unittest.TestCase):
    setUp = fixtures.AccountsTest.setUp
    tearDown = fixtures.AccountsTest.tearDown

    def test_sdk_identity_changes_without_middleware_identity_changing(self):
        import httpx
        from openai import OpenAI
        from agent.codex_headers import apply_required_codex_headers
        from agent.codex_responses_adapter import _preflight_codex_api_kwargs
        from hermes_cli.middleware import run_llm_execution_middleware
        from test_surfaces import SurfaceTests

        def token(subject, generation):
            claims = {'sub': subject, 'exp': 4000000000, 'generation': generation,
                      'https://api.openai.com/auth': {'chatgpt_account_id': 'shared-workspace'}}
            payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
            return 'fake.' + payload + '.signature'

        tokens = [token('member-a', 1), token('member-a', 2), token('member-b', 1)]
        for row, access in zip(self.rows, (tokens[1], tokens[2])):
            row['access_token'] = access
        self.auth.write_text(json.dumps(self.store))
        before = self.auth.read_bytes()
        manager = SurfaceTests.load_manager(self)
        self.command = manager._plugin_commands['codex_accounts']['handler']
        visible, wire = [], []
        payload = {'model': 'test', 'instructions': 'same', 'input': [{'role': 'user', 'content': 'same'}]}
        context = dict(session_id='conversation', provider='openai-codex', api_mode='codex_responses',
                       base_url='https://chatgpt.com/backend-api/codex')

        def transport(request):
            # Fake credentials only. Record full token to distinguish shared-workspace members.
            wire.append((request.headers['Authorization'], request.headers['ChatGPT-Account-ID']))
            return httpx.Response(200, json={'id': 'same-response', 'object': 'response',
                                            'created_at': 0, 'output': []})

        # Exercise the actual loader-registered supported seam and capture its SDK input.
        with patch('hermes_cli.plugins._delivery_manager', return_value=manager):
            for access in tokens:  # initial runtime, refreshed token, fallback workspace member
                options = dict(api_key=access, base_url=context['base_url'], max_retries=0)
                apply_required_codex_headers(options, access_token=access, base_url=context['base_url'])
                with OpenAI(**options, http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
                    def downstream(request):
                        visible.append((dict(request), dict(context)))
                        return client.responses.create(**_preflight_codex_api_kwargs(request))
                    result = run_llm_execution_middleware(_preflight_codex_api_kwargs(payload), downstream, **context)
                    self.assertEqual('same-response', result.id)
        self.assertEqual(visible[0], visible[1])
        self.assertEqual(visible[1], visible[2])
        self.assertNotIn('extra_headers', visible[0][0])
        self.assertEqual([('Bearer ' + access, 'shared-workspace') for access in tokens], wire)
        with patch('agent.account_usage._fetch_codex_account_usage_read_only', return_value=None):
            for sid in ('conversation', 'other', ''):
                output = self.command('list', session_key='test', session_id=sid)
                # The UI marker is now the persisted global preferred pool row,
                # not an assertion about SDK/runtime identity. The request inputs
                # above still prove that this marker cannot identify a bound client.
                self.assertIn('[Active]', output)
                self.assertIn('global preferred', output)
                self.assertNotIn('automatic runtime account is unknown', output)
        self.assertFalse(hasattr(self.command, 'selected'))
        self.assertEqual(before, self.auth.read_bytes())
