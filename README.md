# rb-yandex-direct

Клиент Яндекс.Директ API v5 — Python-библиотека и CLI `yd`.

---

## Установка

```bash
uv tool install "git+https://github.com/bolandeu/yandex-direct.git@v0.2.0"
yd --version
```

Репозиторий приватный: HTTPS работает после `gh auth login` (или `gh auth setup-git`),
иначе — `git+ssh://git@github.com/bolandeu/yandex-direct.git@vX.Y.Z`. Обновление — `uv tool upgrade rb-yandex-direct`.

Разработка:

```bash
uv sync
scripts/install_hooks.sh            # один раз на клон: git-хуки справки из .githooks/
uv run scripts/release.py --check   # весь гейт: lock, ruff, ty, pytest (покрытие ≥ 90%), фрагмент, сборка wheel
```

---

## Регистрация приложения (разово)

По официальной документации (<https://yandex.ru/dev/direct/doc/ru/concepts/register>):

1. Создай приложение: <https://oauth.yandex.ru/?dialog=create-client-entry> — права
   `direct:api` (управление рекламой) и `passport:business` (работа от имени организации).
2. Сохрани `ClientID` и `Client secret`.
3. Подай заявку на API: [direct.yandex.ru → Настройки API → Мои заявки](https://direct.yandex.ru/registered/main.pl?cmd=apiCertificationRequestList).
   - **Полный доступ** — для prod (до 7 дней модерации). Без подтверждённой заявки API отвечает кодом 58.
   - **Тестовый доступ** — сразу, только для песочницы (`--sandbox`).

---

## Авторизация

Токен — через общую библиотеку [rb-yandex-oauth](https://github.com/bolandeu/yandex-oauth):
keychain ОС, автообновление по refresh_token. У Директа **свой слот** `yandex-oauth:direct`
(не общий токен ym/ywm: тому приложению нужна своя заявка на API Директа). Файлы `.env` не читаются.

```bash
yd auth login --client-id <id> --client-secret <secret>   # браузер → localhost
yd auth login --oob       # код со страницы подтверждения вручную (ssh)
yd auth login --device    # подтверждение на другом устройстве
yd auth login --token y0_...   # готовый токен (без автообновления)
yd auth status --check    # источник, срок, остаток баллов; exit 3 — проблема
yd auth refresh | logout
```

| Переменная окружения | Зачем |
|---|---|
| `YANDEX_OAUTH_DIRECT_REFRESH_TOKEN`, `…_CLIENT_ID`, `…_CLIENT_SECRET` | сервер без keychain: токен получается по refresh_token и обновляется в памяти |
| `YANDEX_OAUTH_DIRECT_<FIELD>` | переопределить одно поле из keychain |
| `YANDEX_DIRECT_TOKEN` | готовый access-токен без автообновления (разовые запуски) |
| `YANDEX_DIRECT_CLIENT_ID`, `YANDEX_DIRECT_CLIENT_SECRET` | прежние имена приложения для `auth login` (legacy) |
| `YANDEX_DIRECT_LOGIN` | Client-Login по умолчанию (не секрет) |
| `YANDEX_DIRECT_MANAGED_LOGINS` | кабинеты, где владелец токена — представитель (`accounts`) |
| `YANDEX_DIRECT_SANDBOX=true`, `YANDEX_DIRECT_USE_OPERATOR_UNITS=true` | песочница; баллы оператора |

`auth status --json` — отчёт по контракту §8 стандарта tools (`tools/docs/standard-release.md`).

---

## Команды

Голый `yd` печатает список команд, `yd <команда> --help` — описание
и пример. Справка — это docstring'и команд в `src/rb_yandex_direct/cli.py`: поменял поведение
команды — поменяй её docstring в том же коммите (хуки `.claude/settings.json`, `.githooks/pre-commit`),
потом `uv run pytest --snapshot-update` и просмотри diff `tests/snapshots/help/`.

Write-команды спрашивают подтверждение; `-y/--yes` — без вопроса.

---

## Версии и релизы

Стандарт — `~/Projects/tools/docs/standard-release.md`. Версии в `pyproject.toml` нет — она из git-тега.
`CHANGELOG.md` руками не правят: каждое изменение — фрагмент `uv run towncrier create +<slug>.<type>.md -c "…"`.
Релиз с `main`: `uv run scripts/release.py patch|minor|major` (гейт, CHANGELOG, коммит, тег); push — отдельно.

---

## Архитектура

```
src/rb_yandex_direct/
├── cli.py                  # Click CLI
└── core/
    ├── auth.py             # токен через rb-yandex-oauth, auth status (§8)
    ├── oauth.py            # потоки входа: localhost callback, OOB, device flow
    ├── client.py           # DirectClient (JSON v5, headers, units)
    ├── reports.py          # ReportsClient (TSV, polling)
    └── errors.py           # DirectAPIError
```

**API v5:** prod `https://api.direct.yandex.com/json/v5/<service>`, sandbox
`https://api-sandbox.direct.yandex.com/json/v5/<service>`, отчёты — `/json/v5/reports` (TSV, polling 200/201/202).
