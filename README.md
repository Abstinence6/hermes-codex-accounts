# Codex Accounts Telegram Plugin

English | [Українська](#українська)

This Hermes plugin provides the Telegram `/codex_accounts` picker for Hermes
versions that do not ship a native gateway handler. It shows generic Codex OAuth
account labels and safe account-usage limits, then promotes the chosen account to
the front of that profile's credential pool using an inline button.

## Requirements

- Hermes `>=0.21.1`
- A configured Telegram gateway
- At least one Codex OAuth account (`hermes auth`)

## Install

Install from GitHub with Hermes' native plugin installer:

```bash
hermes plugins install Abstinence6/hermes-codex-accounts --enable
hermes gateway restart
```

The installer clones the repository into the active profile's plugin directory,
runs Hermes' plugin security scan, and records its source revision. Do not copy
files into the Hermes checkout manually.

To remove the plugin:

```bash
hermes plugins remove codex-accounts-telegram
hermes gateway restart
```

## Compatibility

Current Hermes versions can include a native Telegram `/codex_accounts` gateway
handler. When that canonical command is present, this plugin intentionally
registers neither its command nor Telegram handlers. This prevents duplicate
picker messages and makes the plugin a safe fallback for older Hermes releases.

## Commands and UX

- `/codex_accounts` is the canonical Telegram command and the menu spelling.
- `/codex-accounts` remains accepted when typed for backwards compatibility.

In an authorized private Telegram chat, the command renders one inline-picker
message. Each generic account button shows its current state and safe Session /
Weekly quota summary; selecting it updates the same message with confirmation.
In a group, the plugin returns only a safe instruction to open the bot's private
DM and does not read account data.

The plugin never sends credential IDs, tokens, account labels, or raw quota
responses to Telegram. Callback IDs are random, expire after ten minutes, are
bound to the initiating user/chat/thread/message, and are consumed before the
credential priority changes.

## Українська

Це плагін Hermes для Telegram-команди `/codex_accounts` у версіях Hermes, де
ще немає штатного gateway-обробника. У приватному авторизованому чаті він показує
одну картку-вибір з узагальненими назвами Codex OAuth-акаунтів і безпечними
лімітами Session/Weekly. Натискання кнопки змінює ту саму картку на підтвердження
та ставить вибраний акаунт першим у credential pool активного профілю.

Штатне встановлення з GitHub:

```bash
hermes plugins install Abstinence6/hermes-codex-accounts --enable
hermes gateway restart
```

Видалення:

```bash
hermes plugins remove codex-accounts-telegram
hermes gateway restart
```

Якщо у вашій версії Hermes уже є штатний `/codex_accounts`, плагін безпечно не
реєструє власні handlers. Це унеможливлює дублювання повідомлень. У групах плагін
не читає дані акаунтів і просить відкрити приватний DM з ботом.

## License

[MIT](LICENSE)