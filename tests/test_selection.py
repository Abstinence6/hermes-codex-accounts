import json
import base64
from unittest.mock import patch
import test_accounts as fixtures


import unittest


class SelectionTests(unittest.TestCase):
    setUp = fixtures.AccountsTest.setUp
    tearDown = fixtures.AccountsTest.tearDown
    list_accounts = fixtures.AccountsTest.list_accounts
    def test_same_session_switch_at_execution_boundary(self):
        import httpx
        from openai import OpenAI
        for row in self.rows:
            payload = {'https://api.openai.com/auth': {'chatgpt_account_id': row['id']}, 'exp': 4000000000}
            row['access_token'] = 'fake.' + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=') + '.fake'
        self.auth.write_text(json.dumps(self.store))
        from test_surfaces import SurfaceTests
        from hermes_cli.plugin_command_dispatch import invoke_plugin_command
        from hermes_cli.middleware import run_llm_execution_middleware
        from agent.codex_responses_adapter import _preflight_codex_api_kwargs
        manager = SurfaceTests.load_manager(self)
        self.command = manager._plugin_commands['codex_accounts']['handler']
        self.list_accounts()
        seen = []
        def transport(request):
            seen.append(request.headers['chatgpt-account-id'])
            return httpx.Response(200, json={'id': 'response', 'object': 'response', 'created_at': 0, 'output': []})
        client = OpenAI(api_key='original', base_url='https://chatgpt.com/backend-api/codex', http_client=httpx.Client(transport=httpx.MockTransport(transport)))
        context = dict(session_id='conversation', provider='openai-codex', api_mode='codex_responses', base_url=str(client.base_url))
        history = [{'role': 'user', 'content': 'unchanged'}]
        before = self.auth.read_bytes()
        for n in (1, 2):
            self.assertIn('Selected', invoke_plugin_command(self.command, str(n), session_key='test', session_id='conversation'))
            with patch('hermes_cli.plugins._delivery_manager', return_value=manager):
                result = run_llm_execution_middleware({'model': 'test', 'instructions': 'same instructions', 'input': history}, lambda request: client.responses.create(**_preflight_codex_api_kwargs(request)), **context)
            self.assertEqual('response', result.id)
        self.assertEqual(['one', 'two'], seen)
        self.assertEqual([{'role': 'user', 'content': 'unchanged'}], history)
        self.assertEqual(before, self.auth.read_bytes())
        client.close()

    def test_pinned_route_failure_never_falls_through_host_chain(self):
        from test_surfaces import SurfaceTests
        from hermes_cli.middleware import run_llm_execution_middleware
        from agent.codex_responses_adapter import _preflight_codex_api_kwargs
        manager = SurfaceTests.load_manager(self)
        self.command = manager._plugin_commands['codex_accounts']['handler']
        self.list_accounts()
        self.command('1', session_key='test', session_id='conversation')
        with patch('hermes_cli.plugins._delivery_manager', return_value=manager):
            for base, provider in [('https://attacker.invalid', 'openai-codex'), ('https://chatgpt.com/backend-api/codex', 'openrouter')]:
                result = run_llm_execution_middleware({}, lambda request: self.fail('unsafe network'), session_id='conversation', provider=provider, api_mode='codex_responses', base_url=base)
                self.assertEqual('codex-accounts-local-refusal', result.id)
            self.assertEqual('untouched', run_llm_execution_middleware({}, lambda request: 'untouched', session_id='different'))

    def test_refresh_and_provider_failure_are_account_scoped(self):
        def token(exp):
            return 'fake.' + base64.urlsafe_b64encode(json.dumps({'exp': exp, 'https://api.openai.com/auth': {'chatgpt_account_id': 'one'}}).encode()).decode().rstrip('=') + '.fake'
        self.rows[0]['access_token'] = token(1)
        self.auth.write_text(json.dumps(self.store))
        self.list_accounts()
        self.command('1', session_key='test', session_id='conversation')
        request = {'extra_headers': {'chatgpt-account-id': 'old', 'Authorization': 'old'}}
        calls = []
        def downstream(payload):
            calls.append(payload)
            raise RuntimeError('fake provider token detail must never be returned')
        with patch('hermes_cli.auth_codex.refresh_codex_oauth_pure', return_value={'access_token': token(4000000000), 'refresh_token': 'rotated'}) as refresh:
            result = self.command.execute(request=request, next_call=downstream, session_id='conversation', provider='openai-codex', api_mode='codex_responses', base_url='https://chatgpt.com/backend-api/codex')
        self.assertEqual(1, refresh.call_count)
        self.assertIn('refused', result.choices[0].message.content)
        self.assertNotIn('detail', result.choices[0].message.content)
        self.assertEqual('one', calls[0]['extra_headers']['ChatGPT-Account-ID'])
        self.assertEqual('old', request['extra_headers']['Authorization'])
        saved = json.loads(self.auth.read_text())['credential_pool']['openai-codex']
        self.assertEqual('rotated', saved[0]['refresh_token'])
        self.assertEqual(self.rows[1], saved[1])

    def test_control_flow_and_partial_response_survive_host_chain(self):
        import asyncio
        from test_surfaces import SurfaceTests
        from hermes_cli.middleware import run_llm_execution_middleware
        token = 'fake.' + base64.urlsafe_b64encode(json.dumps({
            'https://api.openai.com/auth': {'chatgpt_account_id': 'one'},
            'exp': 4000000000}).encode()).decode().rstrip('=') + '.fake'
        self.rows[0]['access_token'] = token
        self.auth.write_text(json.dumps(self.store))
        manager = SurfaceTests.load_manager(self)
        self.command = manager._plugin_commands['codex_accounts']['handler']
        self.command.selected['conversation'] = 'one'
        context = dict(session_id='conversation', provider='openai-codex',
                       api_mode='codex_responses', base_url='https://chatgpt.com/backend-api/codex')
        for error in (InterruptedError('stop/redirect'), KeyboardInterrupt(), asyncio.CancelledError()):
            error.partial_response = object()
            partial = error.partial_response
            calls = []
            def downstream(request):
                calls.append(request)
                raise error
            for use_host in (False, True):
                with self.subTest(error=type(error).__name__, host=use_host):
                    calls.clear()
                    with patch('hermes_cli.plugins._delivery_manager', return_value=manager):
                        with self.assertRaises(type(error)) as caught:
                            if use_host:
                                run_llm_execution_middleware({}, downstream, **context)
                            else:
                                self.command.execute(request={}, next_call=downstream, **context)
                    self.assertIs(error, caught.exception)
                    self.assertIs(partial, caught.exception.partial_response)
                    self.assertEqual(1, len(calls))

    def test_stream_result_lifecycle_is_not_wrapped_or_consumed(self):
        from test_surfaces import SurfaceTests
        from hermes_cli.middleware import run_llm_execution_middleware
        from unittest.mock import Mock
        manager = SurfaceTests.load_manager(self)
        self.command = manager._plugin_commands['codex_accounts']['handler']
        self.command.selected['conversation'] = 'one'
        stream = Mock()
        with patch('agent.codex_headers.codex_account_headers', return_value={'ChatGPT-Account-ID': 'one'}), patch('hermes_cli.plugins._delivery_manager', return_value=manager):
            result = run_llm_execution_middleware({}, lambda request: stream,
                session_id='conversation', provider='openai-codex', api_mode='codex_responses',
                base_url='https://chatgpt.com/backend-api/codex')
        self.assertIs(stream, result)
        self.assertEqual([], stream.mock_calls)

    def test_missing_selected_credential_refuses_without_network(self):
        self.list_accounts()
        self.assertIn('Selected', self.command('1', session_key='test', session_id='conversation'))
        self.auth.write_text(json.dumps({'credential_pool': {'openai-codex': []}}))
        with patch('builtins.print'):
            result = self.command.execute(request={}, next_call=lambda request: self.fail('network called'), session_id='conversation', provider='openai-codex', api_mode='codex_responses', base_url='https://chatgpt.com/backend-api/codex')
        self.assertIn('refused', result.choices[0].message.content)
