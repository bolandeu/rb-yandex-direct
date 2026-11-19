# rb-yandex-direct

Яндекс.Директ — Python-библиотека `rb_yandex_direct` и CLI `yd`: API v5, v4 Live (Wordstat, прогноз, финансы) и веб-интерфейс (Мастер кампаний, история изменений).

---

## Установка

```bash
yd --version
```

Из тега: `"rb-yandex-direct @ git+https://homeserver.tailee01ab.ts.net:3000/bolandeu/yandex-direct.git@vX.Y.Z"`. Обновление — `uv tool upgrade rb-yandex-direct`.

Разработка:

```bash
uv sync
# весь гейт — шаг `gate check` в .gitea/workflows/ci.yml: запускать ту команду
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
| `YANDEX_OAUTH_DIRECT_FINANCE_MASTER_TOKEN`, `YANDEX_OAUTH_DIRECT_FINANCE_LOGIN` | финансовые методы v4 Live (`finance`, `shared-account`) без keychain; иначе `yd finance setup` |
| `YANDEX_DIRECT_SANDBOX=true`, `YANDEX_DIRECT_USE_OPERATOR_UNITS=true` | песочница; баллы оператора |

`auth status --json` — отчёт по контракту §8 стандарта tools (`tools/docs/standard-release.md`).

---

## Команды

Голый `yd` печатает список команд, `yd <команда> --help` — описание, `--json`-форму
и пример. Справка — это docstring'и команд в `src/rb_yandex_direct/commands/*.py`: поменял
поведение команды — поменяй её docstring в том же коммите (хуки `.claude/settings.json`,
`.githooks/pre-commit`), потом `uv run pytest --snapshot-update` и просмотри diff `tests/snapshots/help/`.

- `--json` у каждой команды: `{"ok": true, …}` в stdout; ошибка — `{"ok": false, "error": {code, message, action}}`.
- Изменения в кабинете: `--dry-run` — показать запрос к API; без него — вопрос `y/n`;
  `--confirm --non-interactive` — без вопроса (агенты — только после dry-run, показанного человеку).
- Кабинет: `--login` → `.yd/config.toml` проекта (`yd init --client-login …`) → `YANDEX_DIRECT_LOGIN`.
- `yd doctor`, `yd auth status --check` — диагностика; `yd skill install` / `yd --ai` — памятка для агентов.

---

## Версии и релизы

Стандарт — `~/Work/tools/docs/standard-release.md`. Версии в `pyproject.toml` нет — она из git-тега.
`CHANGELOG.md` руками не правят: его пишет `antagor publish`, он же выпускает релиз.

---

## Архитектура

```
src/rb_yandex_direct/
├── cli.py                  # корень Typer: глобальные опции, подключение групп
├── commands/               # по модулю на группу; groups.py — реестр; _common.py — списки, mutate (dry-run/confirm)
├── core/
│   ├── auth.py             # токен через rb-yandex-oauth (keychain yandex-oauth:direct / env)
│   ├── services.py         # проект .yd/, кабинет (--login → проект → env), клиенты API, рубли↔микро
│   ├── errors.py           # CliError-коды; DirectAPIError → AUTH_REQUIRED (3) / PROVIDER_ERROR (5)
│   └── models.py, version.py, deps.py
├── providers/
│   ├── direct.py           # DirectClient (JSON v5, ретраи, Units) + DirectProvider.health_check
│   ├── reports.py          # ReportsClient (TSV, polling)
│   └── oauth.py            # потоки входа: localhost callback, OOB, device flow
├── credentials/manager.py  # keychain/env — общая реализация rb-yandex-oauth
└── data/SKILL.md           # памятка для агентов (yd --ai)
```

**API v5:** prod `https://api.direct.yandex.com/json/v5/<service>`, sandbox
`https://api-sandbox.direct.yandex.com/json/v5/<service>`, отчёты — `/json/v5/reports` (TSV, polling 200/201/202).
