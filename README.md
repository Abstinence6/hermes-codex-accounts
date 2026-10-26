# Hermes Codex Accounts

Самостійний плагін для **Desktop, TUI, Telegram**, без змін ядра Hermes.

## Команди

- `/codex_accounts` без аргументів або `/codex_accounts list` — акаунти (власна назва + email), usage, час скидання і reset-кредити, якщо API їх повертає. Email береться лише з claims збереженого access token цього акаунта, без refresh чи зовнішнього lookup; за відсутності показується `email unavailable`. Назва після rename зберігається окремо.
- `/codex_accounts n` або `select n` — глобальний пріоритет акаунта **в межах поточного профілю**: вибраний stable ID переноситься на priority 0 у збереженому pool. `Active` у списку означає лише цей persisted preferred account, однаковий для всіх сесій/процесів, які читають цей profile store. Це не визначення credential поточного запиту. Уже створені runtime/SDK-клієнти та запити можуть утримувати попередні credentials; примусове перемикання всіх запущених сесій не гарантується.
- `/codex_accounts add` — штатний device OAuth без паролів/токенів у чаті; `add check` завершує вхід, `add cancel` скасовує очікування.
- `/codex_accounts rename n Нова назва` — перейменування.
- `/codex_accounts delete n` — видалення з pool Hermes після одноразового підтвердження; не видаляє OpenAI-акаунт, не відкликає токени та не видаляє зовнішній CLI login.
- `/codex_accounts reset n` — після підтвердження використовує доступний накопичений provider reset-кредит: GET usage → guard → POST consume → GET readback. Без кредиту/вичерпаного вікна POST не надсилається. Невизначений результат не повторюється автоматично; локальний cooldown reset не підставляється замість справжнього скидання.

Перед операціями за номером відкрийте свіжий список у тій самій сесії. Зміна складу/порядку робить старі номери та кнопки недійсними. Підтвердження delete/reset одноразове, на 60 секунд.

## Telegram

Використовується вже налаштований Telegram Application Hermes, без копіювання bot token чи другого polling-бота. Кнопки: **Обрати · Додати · Скинути ліміт · Перейменувати · Видалити**, оновлення списку, підтвердження та OAuth check/cancel. Перейменування приймає текстову відповідь; `/cancel` скасовує її.

Доступ за замовчуванням заборонений. Потрібен явний numeric Telegram user ID у `plugins.entries.codex-accounts.settings.telegram_owner_ids`. Дозволені лише приватні root-DM власника, не групи/канали/topics. Доступ до бота не дорівнює праву керувати акаунтами. Callback-и одноразові, непрозорі, з TTL та прив'язкою до owner/chat/session/snapshot.

## Встановлення

Потрібен Hermes із Telegram handler factory та відповідними Codex auth/usage helper-ами. Сумісність з усіма старими версіями не заявляється. Telegram потребує штатних залежностей та **`plugins.isolation: in_process`**; плагін не змінює цю політику автоматично.

```bash
hermes plugins install Abstinence6/hermes-codex-accounts --no-enable
hermes config set plugins.entries.codex-accounts.settings.telegram_owner_ids '["YOUR_NUMERIC_TELEGRAM_USER_ID"]'
hermes plugins enable codex-accounts
```

Замініть placeholder власним numeric ID. Загальна згода на плагіни та isolation мають відповідати політиці вашого Hermes. Для завантаження нового коду потрібне штатне перезавантаження owning-процесу, яке може перервати активні задачі. Публікація сама нічого не встановлює й не перезапускає.

### Міграція

Старий плагін цього репозиторію мав ID `codex-accounts-telegram` та лише змінював priority. Новий ID — **`codex-accounts`**. Якщо старий встановлений, перед увімкненням нового виконайте `hermes plugins disable codex-accounts-telegram`. Не тримайте активними два плагіни з однаковими командами. Стара версія збережена в Git history.

## Межі та безпека

Вибір змінює збережений pool order тільки після явної команди або авторизованої кнопки. Немає session pins, execution middleware, підміни заголовків чи refresh під час вибору. Майбутнє завантаження pool враховує цей порядок; фактичний вибір залежить також від host strategy, доступності, cooldown та квот. Інші профілі/borrowed global-root credentials не змінюються. Список залишається read-only.

Для вже запущених сесій немає гарантії негайного переходу. Потрібен runtime, який заново завантажує pool (зазвичай нова сесія або штатне відновлення/restart owning-процесу). Плагін сам нічого не перезапускає й не змінює історію. Застосування до всіх поточних runtime без core/API підтримки не заявляється.

В installed API `CredentialPool.move_entry(id, 0)` перезаписує priorities, але не переприв'язує SDK-клієнти/інші pool instances. У `hermes_cli.auth` немає wrapper-а для move. Тому команда використовує наявні `read_credential_pool` / `write_credential_pool` під reentrant auth-store lock, без нового `load_pool` (який може seed/normalize/persist). Raw rows зберігають metadata без dataclass round-trip. Після запису перевіряються exact target ID, весь порядок та незмінність усіх полів, крім priority, включно з tokens; при невідповідності успіх не заявляється й небезпечний rollback не виконується.

Refresh/запис використовують auth-store lock та merge API Hermes. OAuth identity — `(chatgpt_account_id, sub)`, тому учасники одного workspace не зливаються. Внутрішні host API потребують повторної перевірки після оновлення Hermes. Видалення не відкликає credentials, уже утримувані runtime.

## Перевірки

**Ізольовані тести** (команда запуску нижче). Перевіряються actual plugin loader/dispatch, persisted global ordering/readback, metadata/token safety, обмеження existing SDK через MockTransport, principal dedupe, usage URL allowlist, Telegram callbacks/owner/stale snapshot та reset GET/POST/GET.

З Python-середовища Hermes з доступними host modules та Telegram SDK:

```bash
python -B -m unittest discover -s tests -v
```

За потреби додайте host source і isolated Telegram dependencies до `PYTHONPATH` (Windows: `;`). Тести працюють з fake credentials і тимчасовим HOME; bot/OAuth/reset transport замокані.

Реєстрація команди явно використовує `argument_mode="mixed"`: непорожній `args_hint` без цього host перетворює на `text` у `commands.catalog`, хоча аргументи необов'язкові. Парсер уже трактує порожні аргументи як список. Тести перевіряють каталог і bare dispatch Desktop/TUI/Telegram.

**Live Desktop/TUI/Telegram E2E не заявляється.** Реальні акаунти не видалялися, OAuth login не запускався, reset-кредити не витрачалися. Окремий read-only live usage probe підтвердив незмінність auth.json. Опційно: `python scripts/live_list.py --home PATH_TO_HERMES_HOME` — це не заміна UI E2E.

[Hermes plugin docs](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins) · [Middleware](https://hermes-agent.nousresearch.com/docs/developer-guide/middleware)

[MIT License](LICENSE)
