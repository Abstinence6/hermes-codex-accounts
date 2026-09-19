"""Upgrade-resilient Telegram picker for Codex OAuth credential pools.

Install this directory under ``$HERMES_HOME/plugins/codex-accounts-telegram`` and
activate it with Hermes' normal plugin command. It uses the documented public
platform-handler registration API; core gateway files are not patched.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from pathlib import Path
from typing import Any

_CALLBACK_PREFIX = "ca:"
_CALLBACK_TTL_SECONDS = 10 * 60
_GROUP_REPLY = "For Codex account status and selection, open this bot's private DM."
_UNAUTHORIZED = "This account picker is not available to you."
_EXPIRED = "This account picker has expired. Run /codex_accounts again."


def _core_command_available() -> bool:
    """Whether this Hermes version already owns the Telegram account picker."""
    try:
        from hermes_cli.commands import resolve_command
        return getattr(resolve_command("codex_accounts"), "name", None) == "codex_accounts"
    except Exception:
        return False


def _thread_id(message: Any) -> str | None:
    value = getattr(message, "message_thread_id", None)
    return str(value) if value is not None else None


def _chat_id(message: Any) -> str:
    return str(getattr(getattr(message, "chat", None), "id", ""))


def _chat_type(message: Any) -> str:
    return str(getattr(getattr(message, "chat", None), "type", ""))


def _authorized(adapter: Any, user: Any, message: Any) -> bool:
    checker = getattr(adapter, "_is_callback_user_authorized", None)
    if not callable(checker):
        return False
    return bool(checker(
        str(getattr(user, "id", "")), chat_id=_chat_id(message), chat_type=_chat_type(message),
        thread_id=_thread_id(message), user_name=getattr(user, "first_name", None),
    ))


def _profile_scope(profile_home: Path):
    """Enter the owning profile scope for every account-pool read and mutation."""
    # Never fall back to the process/default profile. In a multiplexed gateway
    # that could display or reprioritize another profile's credential pool.
    from gateway.run import _profile_runtime_scope
    return _profile_runtime_scope(profile_home)


def _oauth_entries():
    from agent.credential_pool import load_pool

    pool = load_pool("openai-codex")
    entries = [entry for entry in pool.entries() if str(getattr(entry, "auth_type", "")) == "oauth"]
    return pool, entries


def _account_usage_lines(entry: Any) -> list[str]:
    """Return only safe, human-readable quota lines for one OAuth pool entry."""
    from agent.account_usage import fetch_account_usage, render_account_usage_lines

    snapshot = fetch_account_usage(
        "openai-codex",
        base_url=getattr(entry, "runtime_base_url", None),
        api_key=getattr(entry, "runtime_api_key", None),
    )
    if snapshot is None or not snapshot.available:
        return ["Limits: unavailable"]
    # The shared renderer owns the session/weekly/reset and banked-credit format.
    # Its first two lines identify the provider/plan; do not repeat them per account.
    lines = render_account_usage_lines(snapshot)
    return lines[2:] or ["Limits: unavailable"]


class _Picker:
    def __init__(self, adapter: Any, profile_home: Path) -> None:
        self._adapter = adapter
        self._profile_home = profile_home
        self._attempts: dict[str, dict[str, Any]] = {}

    def _purge_expired(self) -> None:
        now = time.monotonic()
        for token, state in list(self._attempts.items()):
            if state["expires_at"] <= now:
                self._attempts.pop(token, None)

    async def command(self, update: Any, context: Any) -> None:
        message = getattr(update, "effective_message", None)
        user = getattr(update, "effective_user", None)
        if message is None or user is None or not _authorized(self._adapter, user, message):
            return
        if getattr(context, "args", None):
            await message.reply_text("Use the account buttons; typed account numbers never switch credentials.")
            return
        if _chat_type(message) != "private":
            await message.reply_text(_GROUP_REPLY)
            return

        self._purge_expired()
        with _profile_scope(self._profile_home):
            pool, entries = _oauth_entries()
            # Keep the owning profile scope active for explicit-credential refreshes
            # performed by the usage API (for example after a 401 response).
            usage_lines = await asyncio.gather(*[
                asyncio.to_thread(_account_usage_lines, entry) for entry in entries
            ])
        if not entries:
            await message.reply_text("No Codex OAuth accounts are available. Run `hermes auth` to authenticate.")
            return

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        current = getattr(pool, "current", lambda: None)()
        current_id = getattr(current, "id", None)
        # Account numbers are stable within this one picker message and fit Telegram's button limit.
        # Fetch each entry through the account-usage API with its explicit runtime credential;
        # only rendered quota summaries leave this process, never credential metadata or secrets.
        lines = ["Codex OAuth accounts", "Choose the account Hermes should use first:"]
        buttons = []
        attempt_tokens = []
        for index, entry in enumerate(entries, start=1):
            token = secrets.token_urlsafe(12)
            attempt_tokens.append(token)
            label = f"Codex account {index}"
            if getattr(entry, "id", None) == current_id:
                label += " (active)"
            lines.append(f"• {label}")
            lines.extend(f"  {line}" for line in usage_lines[index - 1])
            buttons.append([InlineKeyboardButton(label, callback_data=f"{_CALLBACK_PREFIX}{token}")])
            self._attempts[token] = {
                "credential_id": str(getattr(entry, "id", "")),
                "user_id": str(getattr(user, "id", "")),
                "chat_id": _chat_id(message),
                "thread_id": _thread_id(message),
                "message_id": None,
                "expires_at": time.monotonic() + _CALLBACK_TTL_SECONDS,
            }
        sent = await message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))
        sent_id = getattr(sent, "message_id", None)
        for token in attempt_tokens:
            self._attempts[token]["message_id"] = str(sent_id) if sent_id is not None else None

    async def callback(self, update: Any, _context: Any) -> None:
        query = getattr(update, "callback_query", None)
        message = getattr(query, "message", None)
        user = getattr(query, "from_user", None)
        data = str(getattr(query, "data", ""))
        token = data.removeprefix(_CALLBACK_PREFIX)
        self._purge_expired()
        state = self._attempts.get(token)
        if query is None or message is None or user is None or not _authorized(self._adapter, user, message):
            if query is not None:
                await query.answer(_UNAUTHORIZED)
            return
        if (
            state is None
            or state["user_id"] != str(getattr(user, "id", ""))
            or state["chat_id"] != _chat_id(message)
            or state["thread_id"] != _thread_id(message)
            or state["message_id"] != str(getattr(message, "message_id", ""))
        ):
            await query.answer(_EXPIRED)
            return

        # Claim before persistence: Telegram may deliver a callback more than once.
        self._attempts.pop(token, None)
        credential_id = state["credential_id"]
        with _profile_scope(self._profile_home):
            pool, entries = _oauth_entries()
            valid = any(str(getattr(entry, "id", "")) == credential_id for entry in entries)
            moved = pool.move_entry(credential_id, 0) if valid else None
        if moved is None:
            await query.answer(_EXPIRED)
            return
        await query.answer("Active Codex account updated.")
        await query.edit_message_text("✅ Active Codex account updated. New Codex sessions will use it first.")


def register(ctx: Any) -> None:
    """Register only Telegram-native handlers; no core patch or config mutation."""
    # Newer Hermes versions dispatch this command through the gateway, which sends the card and
    # keyboard in one message. Registering a second PTB CommandHandler would send a second picker.
    if _core_command_available():
        return
    # Public, profile-aware helper; do not depend on PluginContext internals.
    from hermes_constants import get_hermes_home
    profile_home = get_hermes_home().resolve()

    # This declarative registration is the supported additive path to the Telegram
    # menu: the adapter derives its menu from plugin commands together with core
    # commands, preserving both sets when it calls setMyCommands.
    ctx.register_command(
        "codex_accounts",
        lambda _raw_args: "This command is available in an authorized private Telegram chat.",
        description="Show Codex OAuth account limits and select the active account",
    )

    def _wire(application: Any, adapter: Any) -> None:
        from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters

        picker = _Picker(adapter, profile_home)
        # Telegram command identifiers support underscores, not hyphens.  The second handler
        # preserves the historical typed ``/codex-accounts`` spelling without accepting numbers.
        application.add_handler(CommandHandler("codex_accounts", picker.command), group=-1)
        application.add_handler(
            MessageHandler(filters.Regex(r"^/codex-accounts(?:\s|$)"), picker.command), group=-1)
        application.add_handler(CallbackQueryHandler(picker.callback, pattern=rf"^{_CALLBACK_PREFIX}"), group=-1)

    ctx.register_platform_handler("telegram", _wire)
