# CLAUDE.md

## Commands

```bash
uv sync
uv run rb-yandex-direct auth login
uv run rb-yandex-direct auth status --check
uv run rb-yandex-direct whoami
uv run rb-yandex-direct campaigns list --state ON
uv run pytest                          # --snapshot-update после правки справки
uv run scripts/release.py --check      # весь гейт перед каждым коммитом
uv run rb-yandex-direct mcp
```

## Architecture

**Four modes:** Python library, CLI (`rb-yandex-direct`), MCP server (`rb-yandex-direct mcp`), планируемый Claude Code скилл `/direct-report`.

**Source layout:** `src/rb_yandex_direct/`

- `core/auth.py` — токен через rb-yandex-oauth (`PROFILE`, `store`, `resolve_token()`), `auth status` по §8, маппинг ошибок API в CliError (53/54/58/513/1002 → exit 3, прочее → 5).
- `core/oauth.py` — `YandexOAuth`. Три потока: authorization-code с локальным callback (основной), OOB (ручная вставка кода), device flow. Scope: `direct:api passport:business`.
- `core/client.py` — `DirectClient`. JSON-RPC-подобный вызов v5: `POST /json/v5/<service>` с `{"method": ..., "params": ...}`. Ошибки — в теле под `error`, код 1002 = невалидный токен. Заголовки: `Authorization: Bearer`, `Client-Login`, `Accept-Language`, `Use-Operator-Units`. Логирует `Units` и `RequestId` из ответа.
- `core/reports.py` — `ReportsClient`. Отдельный базовый URL, polling 200/201/202 по `retryIn`, парсинг TSV в `list[dict]`.
- `core/errors.py` — `DirectAPIError` (с `.is_auth_error`), `DirectAuthError`.
- `cli.py` — Click. Группы:
  - **Клиенты/баланс:** `auth login/refresh/logout/status`, `whoami`, `clients`, `client` (update/update-agency), `accounts`.
  - **Кампании:** `campaigns list/suspend/resume/archive/unarchive/update/set-budget/set-negative-keywords/add-json/delete`.
  - **Группы объявлений:** `adgroups list/add/update/delete/set-negative-keywords`.
  - **Объявления:** `ads list/moderate/suspend/resume/archive/unarchive/delete/moderation/add-text/add-json`.
  - **Ключи и ставки:** `keywords list/suspend/resume/delete/add/update/check-volume/dedup`, `bids list/set/set-auto`, `modifiers list/add/set/delete/toggle`.
  - **Минус-слова:** `minus-sets list/add/update/delete`.
  - **Расширения:** `sitelinks list/add/delete`, `vcards list/add/delete`, `extensions list/add/moderate/delete`.
  - **Креативы:** `images list/add/delete`, `creatives list/add-video-extension`, `turbo list`.
  - **Ретаргетинг:** `retargeting list/add/update/delete`, `audiences list/add/suspend/resume/delete/set-bid`.
  - **P3:** `feeds list/add-json/update-json/delete`, `businesses`, `leads`, `dynamic-targets list/add-json/set-bid/suspend/resume/delete`, `smart-targets list/add-json/set-bid/suspend/resume/delete`.
  - **Инфраструктура:** `dict get`, `changes check/dictionaries`, `report campaigns/ads/queries/account/custom`, `mcp`.
- `mcp_server.py` — FastMCP. ~40 инструментов. Write-tools требуют `confirm=true` — без него возвращают dry-run-описание операции. Логи в `~/.local/state/logs/mcp-rb-yandex-direct.log`.

**API v5 endpoints (подтверждено WebFetch с yandex.ru/dev/direct и context7 из /dragonsigh/yandex-direct-api-docs):**

- Prod: `https://api.direct.yandex.com/json/v5/<service>`
- Sandbox: `https://api-sandbox.direct.yandex.com/json/v5/<service>`
- OAuth authorize: `https://oauth.yandex.ru/authorize?response_type=code&client_id=...&redirect_uri=...&scope=direct:api+passport:business`
- OAuth token: `POST https://oauth.yandex.ru/token` (grant_type=authorization_code | refresh_token | device_code)
- OAuth register: `https://oauth.yandex.ru/?dialog=create-client-entry`
- Заявка на Direct API: `https://direct.yandex.ru/registered/main.pl?cmd=apiCertificationRequestList` (до 7 дней модерации для prod)

**Credentials:** rb-yandex-oauth — keychain `yandex-oauth:direct` (свой слот, не общий `yandex-oauth:yandex`: общее приложение не прошло заявку на API Директа, код 58) или env `YANDEX_OAUTH_DIRECT_*`; готовый токен — `YANDEX_DIRECT_TOKEN`. `.env` не читается. Тесты изолированы от keychain фикстурой `tests/conftest.py`.

**Справка = docstring'и команд в `cli.py`** (Click, `[tool.cli-generator] commands` в pyproject): у каждой команды строка `Example: rb-yandex-direct …`, у каждой опции `help=`. Тесты: `tests/test_help.py` (контракт + снапшоты), `tests/test_examples.py` (каждый Example выполняется против замоканного API), `tests/test_mcp_tools.py` (каждый MCP-инструмент, dry-run и confirm).

**host_id (в webmaster) здесь не применяется** — аналог «кто клиент»: `Client-Login` из `list_clients`. MCP принимает `login` опциональным параметром каждого инструмента, чтобы Claude мог автоматически находить клиента по домену/названию (как `list_hosts` в webmaster).

**Покрытие API:** P0 + P1 + P2 + P3 — 98/98 методов × 3 слоя (Python/CLI/MCP).
Для сложных структур (ads.add/campaigns.add/feeds.add/targets.add/clients.update) CLI принимает
`--from-json`. Для часто используемого создания TextAd сделан шорткат `ads add-text` + CLI
для bids/modifiers/keywords по-человечески с `--search-bid` в рублях.

**Что ещё не сделано:**
- Скилл `/direct-report` (collect_direct.py + analyze_direct.py) — черновик в scripts/.
- Pydantic-модели для ответов — не вводили, сохраняем raw-dict подход с валидацией на входе.
- `AdVideos` сервис для загрузки видео — не нужен, используется только как источник VideoId для `creatives.add`.

**Предохранитель:** MCP write-tools требуют `confirm=true`; CLI write-команды — интерактивный `y/n`, `-y/--yes` — без вопроса.

**API Units логируются** при verbose-режиме: `Units: used/daily/weekly`.

**Ошибки учётных данных** (53, 54, 58, 513, 1002) → `core.auth.as_cli_error` → exit 3 с подсказкой `auth login`.

**Индекс документации API:** `docs/api_links.json` — 27 сервисов × методы с URL на `yandex.com/dev/direct/doc/en/*`. Генерируется из sitemap + ручного дополнения: `uv run scripts/build_api_index.py`. Использовать так: смотри ключ `services.<service>.methods.<method>` → WebFetch по URL, если нужна сверка формата запроса.

**Мульти-аккаунт через «представителя»:**

- OAuth scope `direct:api passport:business` (у нас уже в `oauth.py`) → токен ходит в любой кабинет, где владелец токена назначен представителем в Директе.
- Список таких логинов API не отдаёт — храним в env `YANDEX_DIRECT_MANAGED_LOGINS=a@yandex.ru,b@yandex.ru`.
- `rb-yandex-direct accounts` — сверху `agencyclients.get` (для агентств), снизу дополнение `clients.get` под каждым managed-логином; собирает валюту/баллы/ошибки.
- MCP: `list_managed_accounts` делает то же для Claude — первый шаг при фразе «посмотри у клиента X».
- CLI `--login` принимает неполное имя (подстрока): `--login shop` → `my-shop@yandex.ru`, если уникально в managed-списке. Полный логин (`foo@yandex.ru`) передаётся as-is.
- Без модерации приложения (код 58) всё это отбивается на первом API-вызове — заявка обязательна, одна на app.

## Каждое заметное изменение выходит релизом

Серверы, другие инструменты и Mac ставят только по тегам, не из `main`:
влитое без релиза изменение для них не существует. Изменение с фрагментом
changelog закончено только после релиза: влить в `main` →
`uv run scripts/release.py patch|minor|major` → попросить пользователя
сделать push с `--follow-tags` → назвать новый тег в отчёте. Служебные коммиты
(без фрагмента) ждут следующего релиза. Не оставлять фрагмент на `main` без
релиза, не назвав причину (`~/Projects/tools/docs/standard-release.md` §3).
