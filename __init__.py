"""Standalone profile-local Codex accounts, OAuth, and session-scoped middleware."""
from pathlib import Path
import threading
import secrets
import time

from hermes_constants import get_hermes_home

PROVIDER = 'openai-codex'
USAGE = ('/codex_accounts list | n | select n | add [check|cancel] | reset n | delete n | rename n label\n'
         'Deletion and provider reset require confirmation. List before using an index. Quota resets are provider-controlled.')


class AccountsCommand:
    def __init__(self, home, owner_ids=lambda: []):
        self.home = Path(home).resolve()
        self.owner_ids = owner_ids
        self.lock = threading.RLock()
        self.views = {}
        self.pending = {}
        self.selected = {}
        self.logins = {}
        self.buttons = {}
        self.renames = {}
        self.telegram = None

    def __call__(self, raw_args, *, session_key='', session_id='', platform='', source=None):
        try:
            output = self.run(raw_args, session_key, session_id, platform, source)
            if platform == 'telegram' and self.telegram is not None and not output.startswith('Refused:'):
                return self.telegram_reply(output, source, session_key, session_id)
            return output
        except Exception:
            return 'Codex accounts unavailable: store/API/lock failure. No success is confirmed; run list again.'

    def run(self, raw_args, session_key, session_id, platform, source):
        if Path(get_hermes_home()).resolve() != self.home:
            return 'Refused: plugin belongs to another profile.'
        if platform == 'telegram':
            owners = self.owner_ids()
            if (not isinstance(owners, list) or source is None
                    or getattr(getattr(source, 'platform', None), 'value', None) != 'telegram'
                    or source.chat_type != 'dm' or source.is_bot or source.thread_id
                    or str(source.chat_id or '') != str(source.user_id or '')
                    or str(source.user_id or '') not in {str(x) for x in owners if str(x).isdigit()}):
                return 'Refused: Telegram requires an explicitly configured owner in a private DM.'
            session_key = f'{session_key}:{source.user_id}:{source.chat_id}' if session_key else ''
        elif platform not in ('', 'cli', 'local', 'desktop', 'tui'):
            return 'Refused: unsupported account management surface.'
        args = raw_args.strip().split()
        if (len(args) == 1 and args[0].isdigit()) or (len(args) == 2 and args[0] == 'select' and args[1].isdigit()):
            if not session_id:
                return 'Account activation unavailable: a stable conversation session_id is required. No changes.'
            from hermes_cli.auth import read_credential_pool
            with self.lock:
                rows = sorted(read_credential_pool(PROVIDER), key=lambda r: r.get('priority', 0))
                key = (platform, session_key or session_id)
                view = self.views.get(key)
                if not view or time.monotonic() - view[0] > 600 or view[1] != self.fingerprint(rows):
                    return 'Account list changed or expired. Run /codex_accounts list again.'
                index = int(args[-1]) - 1
                if not 0 <= index < len(rows):
                    return 'Invalid account index.'
                self.selected[session_id] = rows[index]['id']
            return ('Selected account for the next supported Codex request in this same conversation. '
                    'In-flight requests, auxiliary calls, other sessions and core pool priority are unchanged. '
                    'Selection is process-local; provider failures refuse rather than rotate accounts.')
        if not args:
            args = ['list']
        key = (platform, session_key or session_id)
        if args and args[0] == 'add':
            if not key[1] or not session_id:
                return 'Refused: add requires a conversation identity.'
            return self.add(args, (key, session_id))
        if args != ['list']:
            return self.mutate(args, key)
        from hermes_cli.auth import read_credential_pool
        from agent.credential_pool import PooledCredential
        rows = sorted(read_credential_pool(PROVIDER), key=lambda r: r.get('priority', 0))
        with self.lock:
            self.views[key] = (time.monotonic(), self.fingerprint(rows))
            self.pending.pop(key, None)
            selected = self.selected.get(session_id) if session_id else None
        lines = ['Codex accounts (persisted order; Active means a conversation-local request pin):']
        if selected is None:
            lines.append('No session selection; automatic runtime account is unknown.')
        elif not any(row.get('id') == selected for row in rows):
            lines.append('Session-selected account unavailable; supported pinned requests refuse rather than fall back.')
        for n, row in enumerate(rows, 1):
            entry = PooledCredential.from_dict(PROVIDER, row)
            marker = ' [Active]' if selected is not None and row.get('id') == selected else ''
            lines.append(f'{n}. {self.text(entry.label)} — {self.email(entry.access_token)} (id={self.text(entry.id)}){marker}')
            lines.extend('   ' + self.text(line) for line in self.usage(entry))
        if not rows:
            lines.append('No persisted Codex accounts. Use /codex_accounts add to start explicit OAuth login.')
        return '\n'.join(lines)

    def keyboard(self, source, session_key, session_id, output=''):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from hermes_cli.auth import read_credential_pool
        with self.lock:
            now = time.monotonic()
            self.buttons = {k: v for k, v in self.buttons.items() if v[0] > now}
            snapshot = self.fingerprint(sorted(read_credential_pool(PROVIDER), key=lambda r: r.get('priority', 0)))
            def button(label, raw):
                opaque = 'cxa:' + secrets.token_hex(12)
                self.buttons[opaque] = (now + 120, str(source.user_id), str(source.chat_id),
                                       source, session_key, session_id, raw, snapshot)
                return InlineKeyboardButton(label, callback_data=opaque)
            rows = sorted(read_credential_pool(PROVIDER), key=lambda r: r.get('priority', 0))
            key = ('telegram', f'{session_key}:{source.user_id}:{source.chat_id}' if session_key else session_id)
            view = self.views.get(key)
            markup = []
            if view and now - view[0] <= 600 and view[1] == self.fingerprint(rows):
                for n in range(1, len(rows) + 1):
                    markup.append([button('Обрати', str(n)), button('Скинути ліміт', f'reset {n}')])
                    markup.append([button('Перейменувати', f'rename {n}'), button('Видалити', f'delete {n}')])
            markup.append([button('Додати', 'add'), button('Оновити', 'list')])
            if ((key, session_id) in self.logins):
                markup.append([button('Перевірити вхід', 'add check'), button('Скасувати вхід', 'add cancel')])
            import re
            match = re.search(r'/codex_accounts ((?:delete|reset) \d+ confirm [a-f0-9]+)', output)
            if match:
                markup.append([button('Підтвердити', match.group(1))])
            return InlineKeyboardMarkup(markup)

    async def telegram_reply(self, output, source, session_key, session_id):
        try:
            await self.telegram.bot.send_message(chat_id=source.chat_id, text=output[:3900], parse_mode=None,
                reply_markup=None if output.startswith('Refused:') else self.keyboard(source, session_key, session_id, output))
            return ''
        except Exception:
            return output + '\nTelegram buttons unavailable; use command equivalents.'

    def button_run(self, raw, key, sid, source, snapshot):
        from hermes_cli import auth
        with self.lock, auth._auth_store_lock():
            rows = sorted(auth.read_credential_pool(PROVIDER), key=lambda r: r.get('priority', 0))
            if snapshot != self.fingerprint(rows):
                return 'Account list changed. Run /codex_accounts list again.'
            return self.run(raw, key, sid, 'telegram', source)

    def telegram_factory(self, application, adapter):
        from telegram.ext import CallbackQueryHandler, MessageHandler, filters, ApplicationHandlerStop
        self.telegram = application

        async def callback(update, context):
            query = update.callback_query
            with self.lock:
                state = self.buttons.get(query.data)
                if (not state or state[0] < time.monotonic() or not query.message
                        or str(query.from_user.id) != state[1] or str(query.message.chat.id) != state[2]
                        or query.message.chat.type != 'private' or query.from_user.is_bot):
                    await query.answer('Кнопка недійсна або прострочена.', show_alert=True)
                    raise ApplicationHandlerStop
                self.buttons.pop(query.data, None)
            _, _, _, source, key, sid, raw, snapshot = state
            from hermes_cli.auth import read_credential_pool
            import asyncio
            current = self.fingerprint(sorted(read_credential_pool(PROVIDER), key=lambda r: r.get('priority', 0)))
            if snapshot != current:
                await query.answer('Список змінився. Оновіть його.', show_alert=True)
                raise ApplicationHandlerStop
            # Re-authorize every click against current owner settings and profile before mutation.
            if raw.startswith('rename ') and len(raw.split()) == 2:
                authorized = self.run('rename', key, sid, 'telegram', source)
                if authorized.startswith('Refused:'):
                    output = authorized
                else:
                    self.renames[(state[1], state[2])] = (time.monotonic() + 120, source, key, sid, raw, snapshot)
                    output = 'Надішліть нову назву звичайним текстом протягом 120 секунд; /cancel скасовує.'
            else:
                try:
                    output = await asyncio.to_thread(self.button_run, raw, key, sid, source, snapshot)
                except Exception:
                    output = 'Codex operation unavailable; no success confirmed. Run list again.'
            await query.answer()
            await self.telegram_reply(output, source, key, sid)
            raise ApplicationHandlerStop

        owner = self
        class RenameFilter(filters.MessageFilter):
            def filter(self, message):
                user = message.from_user
                return bool(user and (str(user.id), str(message.chat.id)) in owner.renames)

        async def rename(update, context):
            message = update.effective_message
            state = self.renames.pop((str(message.from_user.id), str(message.chat.id)), None)
            if not state:
                return
            expiry, source, key, sid, raw, snapshot = state
            from hermes_cli.auth import read_credential_pool
            current = self.fingerprint(sorted(read_credential_pool(PROVIDER), key=lambda r: r.get('priority', 0)))
            if snapshot != current:
                output = 'Список змінився. Оновіть його.'
            elif expiry < time.monotonic() or message.text == '/cancel':
                output = 'Перейменування скасовано або прострочене.'
            elif message.chat.type != 'private' or message.from_user.is_bot:
                output = 'Refused: private owner DM required.'
            else:
                import asyncio
                output = await asyncio.to_thread(self.button_run, raw + ' ' + (message.text or ''), key, sid, source, snapshot)
            await self.telegram_reply(output, source, key, sid)
            raise ApplicationHandlerStop

        # Negative group precedes the core catch-all. Exact callback prefix avoids swallowing
        # unrelated core buttons; only a pending rename consumes a plain-text message.
        application.add_handler(CallbackQueryHandler(callback, pattern=r'^cxa:[a-f0-9]{24}$'), group=-20)
        application.add_handler(MessageHandler(RenameFilter() & filters.TEXT, rename), group=-20)

    def add(self, args, key):
        from hermes_cli import auth, auth_codex as oauth
        from agent.credential_pool import _codex_principal_identity
        issuer = 'https://auth.openai.com'
        with self.lock:
            now = time.monotonic()
            self.logins = {k: v for k, v in self.logins.items() if v['expires'] > now}
            if args == ['add', 'cancel']:
                return 'Cancelled login.' if self.logins.pop(key, None) else 'No pending login.'
            if args == ['add']:
                if key in self.logins:
                    return 'Login already pending. Use /codex_accounts add check or add cancel.'
                device = oauth._codex_request_device_code(issuer, oauth.CODEX_OAUTH_CLIENT_ID)
                lifetime = min(900, max(1, int(device.get('expires_in', 900))))
                self.logins[key] = {'device': device, 'expires': now + lifetime, 'next': now + device['interval']}
                return ('Open https://auth.openai.com/codex/device and enter code ' + self.text(device['user_code'])
                        + f'. Never send passwords or tokens here. Expires in {lifetime} seconds. '
                        'Then /codex_accounts add check; /codex_accounts add cancel cancels locally.')
            if args != ['add', 'check']:
                return '/codex_accounts add | add check | add cancel'
            state = self.logins.get(key)
            if not state:
                return 'No pending login (or expired). Use /codex_accounts add.'
            if now < state['next']:
                return 'Login pending. Wait before checking again.'
            state['next'] = now + state['device']['interval']
            # One official protocol poll per explicit check; never block handler on an OAuth loop.
            with oauth._codex_http_client(timeout=15.0) as client:
                response = client.post(issuer + '/api/accounts/deviceauth/token', json={
                    'device_auth_id': state['device']['device_auth_id'], 'user_code': state['device']['user_code']},
                    headers={'Content-Type': 'application/json'})
            if response.status_code in (403, 404):
                return 'Login pending. Finish browser sign-in, then add check.'
            response.raise_for_status()
            tokens = oauth._codex_exchange_authorization_code(issuer, oauth.CODEX_OAUTH_CLIENT_ID, response.json())
            self.logins.pop(key, None)
            identity = _codex_principal_identity(tokens['access_token'])
            if not identity:
                return 'Refused: OAuth returned no account identity. No account saved.'
            with auth._auth_store_lock():
                rows = auth.read_credential_pool(PROVIDER)
                if any(_codex_principal_identity(r.get('access_token', '')) == identity for r in rows):
                    return 'Account already exists; existing credentials were not overwritten.'
                owned = auth._load_auth_store().get('credential_pool', {}).get(PROVIDER, [])
                if {r['id'] for r in rows} != {r['id'] for r in owned}:
                    return 'Refused: borrowed pool must be managed in its owning profile.'
                bases = auth._token_pairs_by_id(rows)
                ident = secrets.token_hex(12)
                rows.append({'id': ident, 'label': 'Codex account', 'auth_type': 'oauth',
                             'source': 'manual:codex-accounts:' + ident, 'priority': len(rows),
                             'access_token': tokens['access_token'], 'refresh_token': tokens.get('refresh_token', ''),
                             'base_url': 'https://chatgpt.com/backend-api/codex'})
                auth.write_credential_pool(PROVIDER, rows, token_bases=bases)
                if not any(r['id'] == ident for r in auth.read_credential_pool(PROVIDER)):
                    return 'Account save could not be verified.'
            self.views.clear()
            return 'Added account to this profile. Run /codex_accounts list; not automatically selected.'

    @staticmethod
    def text(value):
        # Plain, one-line text on Ink, Desktop Markdown, and Telegram HTML/Markdown surfaces.
        import unicodedata
        clean = ''.join(c if not unicodedata.category(c).startswith('C') else ' ' for c in str(value))
        return clean.translate(str.maketrans({'[': '［', ']': '］', '<': '＜', '>': '＞',
                                             '`': 'ˋ', '*': '∗', '_': '＿'}))

    @classmethod
    def email(cls, token):
        # Display metadata only, never authentication/authorization. Decode only this
        # persisted account's token; do not refresh or resolve another credential.
        from hermes_cli.auth import _decode_jwt_claims
        import re
        try:
            claims = _decode_jwt_claims(token or '')
            profile = claims.get('https://api.openai.com/profile')
            candidates = [claims.get('email')]
            if isinstance(profile, dict):
                candidates.append(profile.get('email'))
            for value in candidates:
                if (isinstance(value, str) and len(value) <= 254
                        and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value)):
                    return cls.text(value)
        except Exception:
            pass
        return 'email unavailable'

    @staticmethod
    def fingerprint(rows):
        return tuple((r.get('id'), r.get('label'), r.get('priority', 0), r.get('source')) for r in rows)

    def mutate(self, args, key):
        valid = (len(args) >= 3 and args[0] == 'rename') or (
            args and args[0] in ('delete', 'reset') and (len(args) == 2 or (len(args) == 4 and args[2] == 'confirm')))
        if not valid or not args[1].isascii() or not args[1].isdigit():
            return USAGE
        label = ' '.join(args[2:]) if args[0] == 'rename' else ''
        if args[0] == 'rename' and (len(label) > 100 or any(ord(c) < 32 for c in label)):
            return 'Label must contain 1-100 printable characters.'
        if not key[1]:
            return 'Refused: a session identity is required for mutations.'
        from hermes_cli import auth
        # Same reentrant cross-process auth lock used by pool writers and refresh persistence.
        # Re-read INSIDE it: never overwrite tokens from a list-time snapshot.
        with self.lock, auth._auth_store_lock():
            rows = sorted(auth.read_credential_pool(PROVIDER), key=lambda r: r.get('priority', 0))
            view = self.views.get(key)
            if not view or time.monotonic() - view[0] > 600 or view[1] != self.fingerprint(rows):
                return 'Account list changed or expired. Run /codex_accounts list again.'
            index = int(args[1]) - 1
            if not 0 <= index < len(rows):
                return 'Invalid account index. Run /codex_accounts list.'
            owned = auth._load_auth_store().get('credential_pool', {}).get(PROVIDER, [])
            if {r['id'] for r in owned} != {r['id'] for r in rows}:
                return 'Refused: borrowed credentials must be managed in their owning profile.'
            if args[0] == 'reset':
                return self.reset(args, key, rows, index)
            if args[0] == 'delete':
                return self.delete(args, key, rows, index, auth)
            rows[index] = {**rows[index], 'label': label}
            auth.write_credential_pool(PROVIDER, rows, token_bases=auth._token_pairs_by_id(rows))
            saved = auth.read_credential_pool(PROVIDER)
            if not any(r['id'] == rows[index]['id'] and r['label'] == label for r in saved):
                return 'Rename could not be verified. Run list again.'
            self.views.pop(key, None)
            return 'Renamed account. Run /codex_accounts list before the next change.'

    def reset(self, args, key, rows, index):
        row = rows[index]
        pending_key = ('reset', key)
        if len(args) == 2:
            code = secrets.token_hex(4)
            self.pending[pending_key] = (time.monotonic(), row['id'], self.fingerprint(rows), code)
            return (f'Request provider reset for #{index + 1} {self.text(row.get("label", ""))}? '
                    'Consumes one banked reset credit ONLY if the provider advertises availability and an exhausted window. '
                    'Not an arbitrary quota reset or local cooldown clear.\n'
                    f'Within 60 seconds: /codex_accounts reset {index + 1} confirm {code}')
        pending = self.pending.pop(pending_key, None)
        if (not pending or time.monotonic() - pending[0] > 60 or pending[1] != row['id']
                or pending[2] != self.fingerprint(rows) or not secrets.compare_digest(pending[3], args[3])):
            return 'Confirmation invalid or expired.'
        from agent import account_usage as usage
        from agent.codex_headers import is_official_codex_base_url
        import httpx
        import uuid
        token = row.get('access_token')
        base = row.get('base_url') or 'https://chatgpt.com/backend-api/codex'
        if not token or not is_official_codex_base_url(base):
            return 'Provider reset unavailable: missing token or unsupported route. No local reset substituted.'
        usage_url, _, consume_url = usage._codex_backend_urls(base)
        headers = usage._codex_headers(token, None)
        # Reuse the exact installed /usage reset protocol, without its global cooldown-clearing
        # side effect or implicit credential fallback/refresh. Never retry an uncertain POST.
        with httpx.Client(timeout=15.0) as client:
            response = client.get(usage_url, headers=headers)
            response.raise_for_status()
            payload = response.json()
            available = usage._codex_banked_resets(payload)
            refused = usage._codex_reset_guard(payload, available, False)
            if refused:
                return 'Provider reset not requested: ' + self.text(refused.message) + ' No local reset substituted.'
            try:
                response = client.post(consume_url, headers={**headers, 'Content-Type': 'application/json'},
                                       json={'redeem_request_id': str(uuid.uuid4())})
                response.raise_for_status()
                status = response.json().get('code')
            except Exception:
                return 'Reset request outcome unknown/unconfirmed. Do not blindly retry; run list to check provider status. No local reset substituted.'
            if status != 'reset':
                return 'Provider did not confirm reset (status=' + self.text(status) + '). No local reset substituted.'
            try:
                after = client.get(usage_url, headers=headers)
                after.raise_for_status()
                after.json()
            except Exception:
                return 'Provider confirmed reset redemption; usage readback unavailable. No local cooldowns changed.'
        return 'Provider confirmed reset redemption; usage status read back. No local cooldowns or other accounts changed. Run list for quota/reset timestamps.'

    def delete(self, args, key, rows, index, auth):
        row = rows[index]
        if len(args) == 2:
            code = secrets.token_hex(4)
            self.pending[key] = (time.monotonic(), row['id'], self.fingerprint(rows), code)
            return (f"Remove account #{index + 1} {self.text(row.get('label', ''))} "
                    f"(id={self.text(row['id'])}) from this Hermes pool only?\n"
                    f"Within 60 seconds send /codex_accounts delete {index + 1} confirm {code}\n"
                    'This does not delete your OpenAI account or external CLI login. Existing runtimes may retain it.')
        pending = self.pending.pop(key, None)
        if (not pending or time.monotonic() - pending[0] > 60 or pending[1] != row['id']
                or pending[2] != self.fingerprint(rows) or not secrets.compare_digest(pending[3], args[3])):
            return 'Confirmation invalid or expired. Run /codex_accounts delete n again.'
        # Do not unlink external auth files or revoke upstream grants. Suppress a seeded source
        # through the core API so a later load cannot silently re-import the removed row.
        source = row.get('source') or ''
        if source and not source.startswith('manual'):
            auth.suppress_credential_source(PROVIDER, source)
        remaining = [{**r, 'priority': p} for p, r in enumerate(r for r in rows if r['id'] != row['id'])]
        auth.write_credential_pool(PROVIDER, remaining, removed_ids=[row['id']],
                                   token_bases=auth._token_pairs_by_id(rows))
        if any(r['id'] == row['id'] for r in auth.read_credential_pool(PROVIDER)):
            return 'Removal could not be verified. Run list again.'
        self.views.pop(key, None)
        return 'Removed from Hermes pool only. Existing runtimes are unchanged; start a new session.'

    @staticmethod
    def refuse():
        # A local middleware short-circuit, explicitly NOT an upstream model response.
        from openai.types.chat import ChatCompletion
        return ChatCompletion(id='codex-accounts-local-refusal', created=0, model='local-policy',
                              object='chat.completion', choices=[{'index': 0, 'finish_reason': 'stop',
                              'message': {'role': 'assistant', 'content':
                              'Codex account request refused locally: selected account unavailable, unsupported route, or provider error. No fallback account was used.'}}])

    def execute(self, *, request, next_call, session_id='', provider='', api_mode='', base_url='', **context):
        # Late injection keeps secrets out of request observers/debug dumps. Do not raise from
        # this middleware: the host deliberately fails open before next_call on exceptions.
        with self.lock:
            ident = self.selected.get(session_id)
        if ident is None:
            return next_call(request)
        try:
            from agent.codex_headers import is_official_codex_base_url, codex_account_headers
            from hermes_cli import auth
            from hermes_cli.auth_codex import _codex_access_token_is_expiring, refresh_codex_oauth_pure
            if Path(get_hermes_home()).resolve() != self.home:
                return self.refuse()
            if provider != PROVIDER or api_mode != 'codex_responses' or not is_official_codex_base_url(base_url):
                return self.refuse()
            with auth._auth_store_lock():
                rows = auth.read_credential_pool(PROVIDER)
                row = next((r for r in rows if r['id'] == ident), None)
                if not row or not row.get('access_token'):
                    return self.refuse()
                token = row['access_token']
                if _codex_access_token_is_expiring(token, 60):
                    owned = auth._load_auth_store().get('credential_pool', {}).get(PROVIDER, [])
                    if not any(r['id'] == ident for r in owned):
                        return self.refuse()
                    bases = auth._token_pairs_by_id(rows)
                    row.update(refresh_codex_oauth_pure(token, row.get('refresh_token', '')))
                    auth.write_credential_pool(PROVIDER, rows, token_bases=bases)
                    token = row['access_token']
                identity = codex_account_headers(token)
                if not identity.get('ChatGPT-Account-ID'):
                    return self.refuse()
            outgoing = dict(request)
            headers = {k: v for k, v in (request.get('extra_headers') or {}).items()
                       if k.lower() not in ('authorization', 'chatgpt-account-id', 'x-openai-internal-codex-residency')}
            # Empty residency overrides a stale client default for a non-residency account.
            headers['x-openai-internal-codex-residency'] = ''
            headers.update(identity)
            headers['Authorization'] = 'Bearer ' + token
            outgoing['extra_headers'] = headers
            return next_call(outgoing)
        except InterruptedError:
            raise
        except Exception as exc:
            # The host wraps downstream Exception instances; re-raise its wrapper so
            # it unwraps the original interrupt (including partial response state).
            from hermes_cli.middleware import _DownstreamExecutionError
            original = exc
            while isinstance(original, _DownstreamExecutionError):
                original = original.original
            if isinstance(original, InterruptedError) or not isinstance(original, Exception):
                raise
            # Includes downstream errors: don't let core rotation attribute selected-account
            # failures to its stale pool identity. A pin never silently falls back.
            return self.refuse()

    @staticmethod
    def usage(entry):
        if not entry.access_token:
            return ['Usage unavailable (no access token); not refreshed.']
        from agent.account_usage import _fetch_codex_account_usage_read_only, render_account_usage_lines
        from agent.codex_headers import is_official_codex_base_url
        try:
            if not is_official_codex_base_url(entry.runtime_base_url):
                return ['Usage unavailable (unsupported API); not refreshed.']
            snapshot = _fetch_codex_account_usage_read_only(entry.runtime_base_url, entry.access_token)
            if snapshot is not None:
                return render_account_usage_lines(snapshot)
        except Exception:
            # Exceptions can include URLs, response bodies or credentials. Never echo them.
            pass
        return ['Usage unavailable (expired token, network, or unsupported API); not refreshed.']


def register(ctx):
    command = AccountsCommand(get_hermes_home(), lambda: ctx.get_config('telegram_owner_ids', []))
    ctx.register_middleware('llm_execution', command.execute)
    ctx.register_telegram_handler(command.telegram_factory)
    for name in ('codex_accounts', 'codex-accounts'):
        # Messaging gateway normalizes underscores to hyphens before handler lookup.
        ctx.register_command(name, command, 'Codex account usage and safe pool management',
                             args_hint='[list | n | add | reset n | delete n | rename n label]',
                             argument_mode='mixed')
