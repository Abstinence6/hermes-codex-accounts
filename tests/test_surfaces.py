"""Installed Hermes loader and dispatch seams. No running bot/GUI or real credentials."""
import asyncio
from pathlib import Path
from unittest.mock import patch

import test_accounts as fixtures
ROOT = fixtures.ROOT


import unittest

class SurfaceTests(unittest.TestCase):
    setUp = fixtures.AccountsTest.setUp
    tearDown = fixtures.AccountsTest.tearDown

    def load_manager(self):
        from hermes_cli.plugins import PluginManager
        from hermes_cli.plugins_manifest import parse_manifest_file
        manifest = parse_manifest_file(ROOT / 'plugin.yaml', ROOT, 'user', '')
        self.assertIsNotNone(manifest)
        manager = PluginManager(scope_key=str(self.home))
        # Exercise the real directory importer + register(ctx), not a fake PluginContext.
        # Keep the test in-process so the read-only usage network seam can be isolated.
        with patch.object(manager, '_runs_in_plugin_host', return_value=False):
            manager._load_plugin(manifest)
        self.assertTrue(manager._plugins['codex-accounts'].enabled)
        self.addCleanup(manager.unload, 'codex-accounts')
        self.assertIn('codex_accounts', manager._plugin_commands)
        self.assertIn('codex-accounts', manager._plugin_commands)
        return manager

    def test_real_loader_desktop_and_tui_dispatch(self):
        import importlib
        import tui_gateway.methods_tools as server
        _dispatch_plugin = server._dispatch_plugin
        manager = self.load_manager()
        lookup = lambda name: (manager._plugin_commands.get(name) or {}).get('handler')
        for surface in ('desktop', 'tui'):
            # methods_tools is normally rebound onto server globals. Supply host context only;
            # execute its real plugin dispatch/result resolver without booting a gateway server.
            with self.subTest(surface=surface), patch.multiple(server, create=True,
                    _plugin_command_handler=lookup, _tools_mod=importlib.import_module,
                    _set_session_context=lambda *a, **kw: [], _clear_session_context=lambda tokens: None,
                    _session_source=lambda session: session['source'],
                    _ok=lambda rid, result: {'id': rid, 'result': result}), \
                    patch('agent.account_usage._fetch_codex_account_usage_read_only', return_value=None):
                direct = server._run_plugin_command(lookup('codex_accounts'), 'list',
                                             {'session_key': surface, 'source': surface}, surface)
                self.assertIn('1. First', direct)
                reply = _dispatch_plugin('req', {'session_id': surface},
                                         {'session_key': surface, 'source': surface}, 'codex_accounts', 'list')
                self.assertIsNotNone(reply)
                self.assertEqual('plugin', reply['result']['type'])
                self.assertIn('1. First', reply['result']['output'])

    def test_real_telegram_normalized_dispatch_and_owner_refusal(self):
        from gateway.run_inbound_hooks import GatewayInboundHooksMixin
        from gateway.session import SessionSource
        from gateway.config import Platform
        from hermes_cli.plugin_command_dispatch import invoke_plugin_command
        manager = self.load_manager()
        handler = manager._plugin_commands['codex_accounts']['handler']
        handler.owner_ids = lambda: ['42']

        class Runner(GatewayInboundHooksMixin):
            async def _hm_run_plugin_handler(self, fn, event, source):
                # Real inbound name normalization; authenticated source forwarded through actual
                # plugin call boundary. Not a live Telegram adapter/bot or full gateway lifecycle.
                return invoke_plugin_command(fn, event, source=source, session_key='telegram-test', platform='telegram')

        lookup = lambda name: (manager._plugin_commands.get(name) or {}).get('handler')
        source = SessionSource(platform=Platform.TELEGRAM, chat_id='42', user_id='42')
        before = self.auth.read_bytes()
        with patch('hermes_cli.plugins.get_plugin_command_handler', lookup), \
                patch('agent.account_usage._fetch_codex_account_usage_read_only', return_value=None):
            handled, output, command = asyncio.run(Runner()._hm_dispatch_plugin_command('list', source, 'codex_accounts'))
            self.assertTrue(handled)
            self.assertIn('1. First', output)
            source.user_id = '99'
            handled, output, command = asyncio.run(Runner()._hm_dispatch_plugin_command('ren 1 Bad', source, 'codex_accounts'))
            self.assertTrue(handled)
            self.assertIn('owner', output)
        self.assertEqual(before, self.auth.read_bytes())
