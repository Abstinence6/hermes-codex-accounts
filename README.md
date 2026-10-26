# Hermes Codex Accounts

Самостійний плагін для **Desktop, TUI, Telegram**, без змін ядра Hermes.

## Команди

- `/codex_accounts` або `list` — акаунти, usage, час скидання і reset-кредити, якщо API їх повертає.
- `/codex_accounts n` або `select n` — вибір акаунта для наступного підтримуваного Codex-запиту **в тій самій сесії зі збереженням історії**.
- `/codex_accounts add` — штатний device OAuth без паролів/токенів у чаті; `add check` завершує вхід, `add cancel` скасовує очікування.
- `/codex_accounts rename n Нова назва` — перейменування.
- `/codex_accounts delete n` — видалення з pool Hermes після одноразового підтвердження; не видаляє OpenAI-акаунт, не відкликає токени та не видаляє зовнішній CLI login.
- `/codex_accounts reset n` — після підтвердження використовує доступний накопичений provider reset-кредит: GET usage → guard → POST consume → GET readback. Без кредиту/вичерпаного вікна POST не надсилається. Невизначений результат не повторюється автоматично; локальний cooldown reset не підставляється замість справжнього скидання.

Перед операціями за номером відкрийте свіжий список у тій самій сесії. Зміна складу/порядку робить старі номери та кнопки недійсними. Підтвердження delete/reset одноразове, на 60 секунд.

## Telegram

Використовується вже налаштований Telegram Application Hermes, без копіювання bot token чи другого polling-бота. Кнопки: **Обрати · Додати · Скинути ліміт · Перейменувати · Видалити**, оновлення списку, підтвердження та OAuth check/cancel. Перейменування приймає текстову відповідь; `/cancel` скасовує її.

Доступ за замовчуванням заборонений. Потрібен явний numeric Telegram user ID у `plugins.entries.codex-accounts.settings.telegram_owner_ids`. Дозволені лише приватні root-DM власника, не групи/канали/topics. Доступ до бота не дорівнює праву керувати акаунтами. Callback-и одноразові, непрозорі, з TTL та прив'язкою до owner/chat/session/snapshot.

## Встановлення

Потрібен Hermes із supported execution middleware, Telegram handler factory та відповідними Codex auth/usage helper-ами. Сумісність з усіма старими версіями не заявляється. Telegram потребує штатних залежностей та **`plugins.isolation: in_process`**; плагін не змінює цю політику автоматично.

```bash
hermes plugins install Abstinence6/hermes-codex-accounts --no-enable
hermes config set plugins.entries.codex-accounts.settings.telegram_owner_ids '["YOUR_NUMERIC_TELEGRAM_USER_ID"]'
hermes plugins enable codex-accounts
```

Замініть placeholder власним numeric ID. Загальна згода на плагіни та isolation мають відповідати політиці вашого Hermes. Для завантаження нового коду потрібне штатне перезавантаження owning-процесу, яке може перервати активні задачі. Публікація сама нічого не встановлює й не перезапускає.

### Міграція

Старий плагін цього репозиторію мав ID `codex-accounts-telegram` та лише змінював priority. Новий ID — **`codex-accounts`**. Якщо старий встановлений, перед увімкненням нового виконайте `hermes plugins disable codex-accounts-telegram`. Не тримайте активними два плагіни з однаковими командами. Стара версія збережена в Git history.

## Межі та безпека

Вибір діє через штатний `llm_execution` middleware на наступний Codex Responses-запит, не на запит, який уже виконується. Pins process-local і губляться після reload/restart. Auxiliary calls, інші сесії та зовнішній app-server runtime не перемикаються. Core pool usage attribution не переприв'язується.

Токени додаються після request observers/debug dumps і лише для перевіреного official HTTPS endpoint; custom proxy не підтримуються. Помилка pinned-запиту повертає явно позначену локальну відмову без тихого fallback. Stop/cancel і caller-owned stream lifecycle збережені.

Refresh/запис використовують auth-store lock та merge API Hermes. OAuth identity — `(chatgpt_account_id, sub)`, тому учасники одного workspace не зливаються. Внутрішні host API потребують повторної перевірки після оновлення Hermes. Видалення не відкликає credentials, уже утримувані runtime.

## Перевірки

**31 ізольований тест PASS; незалежне повторне рев'ю APPROVE.** Перевірено actual plugin loader/dispatch, same-session SDK MockTransport A→B, principal dedupe/refresh, usage URL allowlist, interrupts/stream ownership, Telegram callbacks/owner/stale snapshot та reset GET/POST/GET.

З Python-середовища Hermes з доступними host modules та Telegram SDK:

```bash
python -B -m unittest discover -s tests -v
```

За потреби додайте host source і isolated Telegram dependencies до `PYTHONPATH` (Windows: `;`). Тести працюють з fake credentials і тимчасовим HOME; bot/OAuth/reset transport замокані.

**Live Desktop/TUI/Telegram E2E не заявляється.** Реальні акаунти не видалялися, OAuth login не запускався, reset-кредити не витрачалися. Окремий read-only live usage probe підтвердив незмінність auth.json. Опційно: `python scripts/live_list.py --home PATH_TO_HERMES_HOME` — це не заміна UI E2E.

[Hermes plugin docs](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins) · [Middleware](https://hermes-agent.nousresearch.com/docs/developer-guide/middleware)

[MIT License](LICENSE)
