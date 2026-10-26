import unittest
import test_accounts as fixtures


class TelegramTests(unittest.TestCase):
    setUp = fixtures.AccountsTest.setUp
    tearDown = fixtures.AccountsTest.tearDown

    def test_native_callback_dispatch_owner_binding_and_selection(self):
        import asyncio
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock, patch
        from telegram import Update, CallbackQuery, User, Chat, Message
        from telegram.ext import Application, ApplicationHandlerStop
        from gateway.session import SessionSource
        from gateway.config import Platform
        self.command.owner_ids = lambda: ['42']
        source = SessionSource(platform=Platform.TELEGRAM, user_id='42', chat_id='42')
        with patch('agent.account_usage._fetch_codex_account_usage_read_only', return_value=None):
            self.command('list', platform='telegram', session_key='tg', session_id='conversation', source=source)
        app = Application.builder().token('123:fake-test-token').build()
        self.command.telegram_factory(app, None)
        markup = self.command.keyboard(source, 'tg', 'conversation')
        data = markup.inline_keyboard[0][0].callback_data
        handler = app.handlers[-20][0]
        def update(user_id):
            user = User(user_id, 'Test', False)
            message = Message(1, datetime.now(timezone.utc), Chat(42, 'private'))
            query = CallbackQuery('query', user, 'chat', message=message, data=data)
            query.set_bot(app.bot)
            return Update(1, callback_query=query)
        from types import SimpleNamespace
        async def exercise():
            with patch('telegram.Bot.answer_callback_query', new_callable=AsyncMock), patch('telegram.Bot.send_message', new_callable=AsyncMock) as send:
                bad = update(99)
                with self.assertRaises(ApplicationHandlerStop):
                    await handler.handle_update(bad, app, handler.check_update(bad), SimpleNamespace())
                self.assertNotIn('conversation', self.command.selected)
                good = update(42)
                with self.assertRaises(ApplicationHandlerStop):
                    await handler.handle_update(good, app, handler.check_update(good), SimpleNamespace())
                self.assertEqual('one', self.command.selected['conversation'])
                self.assertIn('Selected', send.call_args.kwargs['text'])
                # Old buttons must not be reinterpreted after a list refresh/reorder.
                stale = self.command.keyboard(source, 'tg', 'conversation').inline_keyboard[0][0].callback_data
                self.rows[0]['priority'] = 5
                import json
                self.auth.write_text(json.dumps(self.store))
                with patch('agent.account_usage._fetch_codex_account_usage_read_only', return_value=None):
                    self.command.run('list', 'tg', 'conversation', 'telegram', source)
                nonlocal data
                data = stale
                old = update(42)
                with self.assertRaises(ApplicationHandlerStop):
                    await handler.handle_update(old, app, handler.check_update(old), SimpleNamespace())
                self.assertEqual('one', self.command.selected['conversation'])
        asyncio.run(exercise())

    def test_keyboard_opaque_owner_bound_actions(self):
        from gateway.session import SessionSource
        from gateway.config import Platform
        self.command.owner_ids = lambda: ['42']
        source = SessionSource(platform=Platform.TELEGRAM, user_id='42', chat_id='42')
        from unittest.mock import patch
        with patch('agent.account_usage._fetch_codex_account_usage_read_only', return_value=None):
            self.command('list', platform='telegram', session_key='tg', session_id='conversation', source=source)
        markup = self.command.keyboard(source, 'tg', 'conversation')
        labels = [button.text for row in markup.inline_keyboard for button in row]
        for label in ('Обрати', 'Додати', 'Скинути ліміт', 'Перейменувати', 'Видалити'):
            self.assertIn(label, labels)
        for row in markup.inline_keyboard:
            for button in row:
                self.assertTrue(button.callback_data.startswith('cxa:'))
                self.assertLessEqual(len(button.callback_data), 64)
                self.assertNotIn('fake-token', button.callback_data)
