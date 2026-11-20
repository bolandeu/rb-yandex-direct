# AGENTS.md

Guidance for coding agents working on the **rb-yandex-direct** package (import `rb_yandex_direct`, command `yd`) itself. Pointers for agents. Antagor shows the changing state (statuses, branches, tasks): `antagor board`.

- Decisions and why: `docs/adr/` (format: `docs/adr/README.md`).
- The package Standard: https://github.com/bolandeu/python-package-gate/blob/main/skills/cli-builder/reference/standard.md (sections by name, for example «Install»).
- The gate before a commit: `gate check`, on this machine (Standard, CI). It is the only gate: no workflow runs it.

## Architect only

A worker does not need this section: Antagor cuts it from the worker's brief.

## Commands

```bash
uv sync
uv run yd auth login
uv run yd auth status --check
uv run yd whoami
uv run yd campaigns list --state ON --json
uv run yd doctor
uv run pytest                          # --snapshot-update после правки справки
# весь гейт — шаг `gate check` в .gitea/workflows/ci.yml; запускать ту команду
```

## Architecture

Шаблон cli-generator (`.copier-answers.yml`, обновление — `uvx copier update --trust --defaults`,
см. скилл cli-builder, режим Update). Python-библиотека `rb_yandex_direct` и CLI `yd` на Typer;
дистрибутив `rb-yandex-direct`. MCP-сервера нет — агенты работают через CLI (`yd --ai`).

- `cli.py` — корень: глобальные `--login`, `--sandbox/--prod`, `--json`, `--dry-run`, `--non-interactive`, `--project`.
- `commands/<группа>.py` — по модулю на группу, `commands/groups.py` — реестр групп; команды тонкие:
  параметры → `emit_list` / `emit_object` / `mutate` из `commands/_common.py`. `mutate` — единая
  семантика изменений: `--dry-run` (запрос к API) → `require_confirmation` (`--confirm`) → вызов →
  разбор `*Results`; поэлементные ошибки API — отчёт целиком и exit 5.
- `core/services.py` — проект `.yd/config.toml` (кабинет и песочница по умолчанию), выбор кабинета
  (`--login` → проект → `YANDEX_DIRECT_LOGIN`; подстрока логина из `YANDEX_DIRECT_MANAGED_LOGINS`),
  фабрики клиентов, рубли ↔ микроединицы. Сложная сборка payload — в `core/`, не в командах.
- `core/errors.py` — коды ошибок шаблона на базе `yandex_oauth.errors.CliError` (чтобы `output.guard`
  ловил и ошибки общей библиотеки); `DirectAPIError`: коды учётных данных 53/54/58/513/1002 →
  `AUTH_REQUIRED` (exit 3), прочее → `PROVIDER_ERROR` (exit 5), в JSON — `api_code`, `request_id`.
- `providers/direct.py` — `DirectClient`: `POST /json/v5/<service>` `{"method", "params"}`, ошибки в теле
  под `error`; ретраи 52/506/1000/1001, HTTP 429/5xx, сети; заголовки `Client-Login`,
  `Use-Operator-Units`; `Units`/`RequestId` — в лог (`--verbose`). `DirectProvider.health_check` —
  один `clients.get` для `auth status --check`. `providers/reports.py` — TSV-отчёты с polling.
  `providers/oauth.py` — потоки входа (localhost callback, OOB, device flow).
- `providers/live.py` + `core/live.py` — API v4 Live (`POST /live/v4/json/`, `{"method", "param", "token"}`):
  Wordstat, прогноз, события, цели, теги, финансы. Финансовые методы — finance_token
  (sha256 мастер-токена, номера операции, метода и логина) и растущий номер операции в
  `user_data_dir("yd")/finance.json`; мастер-токен — слот keychain `yandex-oauth:direct_finance`
  или `YANDEX_OAUTH_DIRECT_FINANCE_MASTER_TOKEN`/`…_FINANCE_LOGIN`; финансовые вызовы не повторяются.
- `providers/browser/` — веб-интерфейс без API (Мастер кампаний, история изменений): тонкая обёртка
  над браузерным слоем direct-cli (MIT, Playwright + куки Chrome) из optional extra `[browser]`;
  без extra — DEPENDENCY_TOO_OLD. Состояние — `user_data_dir("yd")/browser`. Тесты подменяют
  библиотеку (`tests/fake_browser.py`) и идут без extra.
- Сборка сложных тел запросов — `core/campaign_payloads.py`, `core/strategy.py`, `core/ads.py`,
  `core/report_payloads.py`, `core/client_payloads.py`: правила сверены с WSDL, лишние и недостающие
  поля отсекаются до запроса.
- `commands/auth.py` — свой `login` (приложение Директа — `YANDEX_OAUTH_DIRECT_CLIENT_ID`, не общий
  `YANDEX_CLIENT_ID` ym/ywm), хранение и обновление токена — rb-yandex-oauth; `auth status` — §8.

**API v5 endpoints (подтверждено WebFetch с yandex.ru/dev/direct и context7 из /dragonsigh/yandex-direct-api-docs):**

- Prod: `https://api.direct.yandex.com/json/v5/<service>`
- Sandbox: `https://api-sandbox.direct.yandex.com/json/v5/<service>`
- OAuth authorize: `https://oauth.yandex.ru/authorize?response_type=code&client_id=...&redirect_uri=...&scope=direct:api+passport:business`
- OAuth token: `POST https://oauth.yandex.ru/token` (grant_type=authorization_code | refresh_token | device_code)
- OAuth register: `https://oauth.yandex.ru/?dialog=create-client-entry`
- Заявка на Direct API: `https://direct.yandex.ru/registered/main.pl?cmd=apiCertificationRequestList` (до 7 дней модерации для prod)

**Credentials:** rb-yandex-oauth — keychain `yandex-oauth:direct` (свой слот, не общий `yandex-oauth:yandex`: общее приложение не прошло заявку на API Директа, код 58) или env `YANDEX_OAUTH_DIRECT_*`; готовый токен — `YANDEX_DIRECT_TOKEN`. `.env` не читается. Тесты изолированы от keychain фикстурой `tests/conftest.py`.

**Справка = docstring'и команд** (`src/rb_yandex_direct/commands/*.py`): резюме, `--json`-форма, `Example: {cli} …`, `help=` у каждого параметра. Тесты: `tests/test_help.py` (контракт + снапшоты), `tests/test_examples.py` (каждый Example выполняется против замоканного API; изменяющим добавляется `--confirm --non-interactive`), `tests/test_cmd_<группа>.py`.

**Raw-dict подход:** ответы API — dict как есть (JSON-ключи API), без pydantic-моделей; валидация — на входе.
Для сложных структур CLI принимает `--from-json` (`add-json`/`update-json`), частые случаи — типизированными опциями в рублях.

**Индекс документации API:** `docs/api_links.json` — сервисы v5 × методы (Strategies и DynamicFeedAdTargets в нём нет — сверяйте по WSDL) с URL на `yandex.com/dev/direct/doc/en/*`. Генерируется из sitemap + ручного дополнения: `uv run scripts/build_api_index.py`. Использовать так: смотри ключ `services.<service>.methods.<method>` → WebFetch по URL, если нужна сверка формата запроса.

**Мульти-аккаунт через «представителя»:**

- OAuth scope `direct:api passport:business` (у нас уже в `oauth.py`) → токен ходит в любой кабинет, где владелец токена назначен представителем в Директе.
- Список таких логинов API не отдаёт — храним в env `YANDEX_DIRECT_MANAGED_LOGINS=a@yandex.ru,b@yandex.ru`.
- `yd accounts` — сверху `agencyclients.get` (для агентств), снизу дополнение `clients.get` под каждым managed-логином; собирает валюту/баллы/ошибки.
- CLI `--login` принимает неполное имя (подстрока): `--login shop` → `my-shop@yandex.ru`, если уникально в managed-списке. Полный логин (`foo@yandex.ru`) передаётся as-is.
- Без модерации приложения (код 58) всё это отбивается на первом API-вызове — заявка обязательна, одна на app.

## Каждое заметное изменение выходит релизом

Серверы, другие инструменты и Mac ставят только по тегам, не из `main`:
влитое без релиза изменение для них не существует. Релиз — `antagor publish`
(Архитектор выпускает сам; ломающее для вызывающих — минорная версия на 0.x).
Тег назвать в отчёте (`~/Work/tools/docs/standard-release.md` §3).

## Инструмент в системе

Инструмент — один из сервисов `~/Work/tools/`: корневой агент его
деплоит, хранит ключи (секрет-менеджер) и бэкапит данные (S3). Полные правила —
`~/Work/tools/docs/standard-release.md` §13.

- **Сообщать корневому агенту** (в отчёте пользователю, рядом с тегом
  релиза): новая или переименованная переменная окружения / ключ, новая
  локальная база или новый путь к данным, новая или убранная зависимость от
  другого инструмента, обновлённый токен сохраняется локально, ломающий релиз.
- **Потребители**: перед ломающим изменением проверить, кто пользуется
  инструментом (корневой `AGENTS.md` → Service map), и назвать их в отчёте.
- **Серверы Linux без экрана**: сначала переменные окружения, keychain
  необязателен (его отсутствие при заданной переменной — не ошибка); имена
  переменных — уже существующие; без TTY никаких вопросов; без путей только для Mac.
- **Локальные данные** — в `platformdirs.user_data_dir("<tool>")`, не в
  репозитории; всё состояние — в файле базы, миграции делает сам инструмент;
  сам инструмент данные никуда не выгружает.
