# rb-yandex-direct

Клиент Яндекс.Директ API v5 — Python-библиотека, CLI и MCP-сервер.

**Статус:** MVP (skeleton + OAuth). Дальше — расширение набора сервисов
(кампании CRUD, adgroups, ads, keywords, bids, retargeting, дашборд).

---

## Установка (dev)

```bash
cd ~/Projects/libs/rb-yandex-direct
uv sync --all-extras
```

---

## Регистрация приложения (разово)

По официальной документации
(<https://yandex.ru/dev/direct/doc/ru/concepts/register>):

1. Создай приложение: <https://oauth.yandex.ru/?dialog=create-client-entry>
   — «Для доступа к API или отладки». Права:
   - `direct:api` — управление рекламой
   - `passport:business` — работа от имени организации

2. Сохрани `ClientID` и `Client secret` — это OAuth-креды приложения.

3. Подай заявку на API: [direct.yandex.ru → Настройки API → Мои заявки](https://direct.yandex.ru/registered/main.pl?cmd=apiCertificationRequestList).
   - **Полный доступ** — для prod (до 7 дней модерации).
   - **Тестовый доступ** — сразу, только для песочницы
     (`https://api-sandbox.direct.yandex.com/json/v5/`).

---

## OAuth (получение токена пользователя)

Клиентские OAuth-креды (из шага 1) задаются один раз:

```bash
export YANDEX_DIRECT_CLIENT_ID=xxx
export YANDEX_DIRECT_CLIENT_SECRET=yyy
```

Потом один из способов:

### Интерактивно (браузер + локальный callback)

```bash
rb-yandex-direct auth
```

Откроется браузер, после подтверждения токен сохранится в `.env`
(или в `~/Projects/_shared/credentials/.env.shared`, если файл существует):

```env
YANDEX_DIRECT_TOKEN=y0_AgAAA...
YANDEX_DIRECT_REFRESH_TOKEN=y0_Ag...
YANDEX_DIRECT_TOKEN_EXPIRES=2027-04-20T10:00:00+00:00
```

### Out-of-band (без браузера, ssh)

```bash
rb-yandex-direct auth --oob
```

Откроешь URL в любом браузере, скопируешь код со страницы подтверждения,
вставишь в терминал.

### Device flow (код на другом устройстве)

```bash
rb-yandex-direct auth --device
```

### Обновить истёкший токен

```bash
rb-yandex-direct auth refresh
```

---

## Базовые CLI-команды

```bash
rb-yandex-direct whoami                        # проверить токен
rb-yandex-direct clients                       # список клиентов агентства
rb-yandex-direct sandbox on                    # переключить на песочницу
rb-yandex-direct campaigns list                # кампании
rb-yandex-direct campaigns list --state ON --type TEXT_CAMPAIGN
rb-yandex-direct --login petrov campaigns list # от имени клиента агентства
rb-yandex-direct report --date-from 2026-04-01 --date-to 2026-04-19 -o r.tsv
rb-yandex-direct mcp                           # MCP-сервер stdio
```

---

## MCP (Claude Desktop / Claude Code)

```bash
claude mcp add rb-yandex-direct -- uv run rb-yandex-direct mcp
```

Реализованные инструменты (скелет):
`list_clients`, `list_campaigns`, `get_campaign`, `suspend_campaigns*`,
`resume_campaigns*`, `get_balance`, `run_report`.

Write-операции (`*`) требуют `confirm=true` — предохранитель.

---

## Архитектура

```
src/rb_yandex_direct/
├── cli.py                  # Click CLI
├── mcp_server.py           # FastMCP
└── core/
    ├── oauth.py            # authorization code + OOB + device flow + refresh
    ├── client.py           # DirectClient (JSON v5, headers, units)
    ├── reports.py          # ReportsClient (TSV, polling)
    └── errors.py           # DirectAPIError (код 1002 = auth)
```

**API v5:**
- Production: `https://api.direct.yandex.com/json/v5/<service>`
- Sandbox: `https://api-sandbox.direct.yandex.com/json/v5/<service>`
- Reports: `https://api.direct.yandex.com/json/v5/reports` (TSV, polling 200/201/202)

**Логи MCP:** `~/.local/state/logs/mcp-rb-yandex-direct.log`
