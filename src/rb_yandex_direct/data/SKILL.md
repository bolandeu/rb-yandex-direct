---
name: yd
description: Правила работы агента с CLI yd (Яндекс.Директ) — установка, JSON-вывод, коды выхода, токен, выбор кабинета, dry-run/--confirm для изменений. Вызывать, когда задача касается рекламных кабинетов Директа — кампаний, ставок, отчётов, Wordstat, Мастера кампаний.
---

# yd — Яндекс.Директ

Всё про конкретные команды — в самом CLI: `yd` без аргументов печатает версию и
список команд, `yd <команда> --help` — описание, параметры и пример. Здесь только
то, чего `--help` не скажет. Если CLI запускается, а файлы не читаются, — `yd --ai`
печатает этот документ.

## Установка (если `yd --version` не работает)

```bash
```

From the git tag instead:

```bash
uv tool install "rb-yandex-direct @ git+https://github.com/bolandeu/rb-yandex-direct.git@vX.Y.Z"
```

Replace `vX.Y.Z` with the latest release tag (install from a tag, never a
branch: [the Standard](https://github.com/bolandeu/cli-generator/src/branch/main/skills/cli-builder/reference/standard.md), Install).

Same command on macOS, Linux and Windows; `uv tool upgrade rb-yandex-direct`
updates it. Do not run from source unless asked to develop the CLI.

## Правила

- **`--json` у каждой команды.** Читайте stdout, не разбирайте человеческий вывод.
  stdout — только данные, stderr — диагностика. Списки: `{"ok": true, "count": N, "<объекты>": [...]}`.
- **Деньги.** В JSON суммы и ставки — как в API, в микроединицах валюты
  (×1 000 000). Опции команд (`--daily-budget`, `--search-bid`, …) принимают рубли.
- **Кабинет.** `--login` (Client-Login) → `direct.login` из проекта `.yd/config.toml`
  (`yd init --client-login …`) → `YANDEX_DIRECT_LOGIN` → свой кабинет. «Посмотри у
  клиента X» — сначала `yd accounts --json`, затем `--login <логин>`; `--login`
  принимает и часть логина из `YANDEX_DIRECT_MANAGED_LOGINS`.
- **Токен** — в keychain ОС или переменных окружения, никогда в аргументах и
  конфиге. `yd auth status --check --json` — откуда токен, жив ли он, остаток баллов
  (значений не печатает; exit 3 — проблема). Вход — `yd auth login`; не просите
  пользователя вставить токен в командную строку.
- **Изменения в кабинете** — команды, у которых в `--help` есть `--dry-run` и
  `--confirm` (остановка, удаление, ставки, бюджеты, создание, платежи). Всегда:
  сначала `--dry-run` (показывает точный запрос к API), покажите его пользователю,
  получите явное согласие, затем `--confirm --non-interactive`. Никогда не переходите
  к `--confirm`, не показав человеку dry-run. Особенно — `finance` (деньги) и
  `delete` (необратимо).
- **API v4 Live** (`wordstat`, `forecast`, `events`, `goals`, `tags`, `suggest`,
  `finance`, `shared-account`, `v4`) — тот же токен и `--login`; суммы там в валюте,
  не в микроединицах. `finance`/`shared-account` двигают ДЕНЬГИ и требуют мастер-токен:
  `yd finance setup` (keychain) или env `YANDEX_OAUTH_DIRECT_FINANCE_MASTER_TOKEN` +
  `YANDEX_OAUTH_DIRECT_FINANCE_LOGIN`; финансовый токен и номер операции CLI считает сам.
  Мастер-токен не просите вставить в командную строку; `yd finance status --json` —
  готовность без значений.
- **Частичный отказ.** Если API отклонил часть объектов, изменяющая команда выводит
  полный отчёт (`succeeded`, `failed`, `errors` с кодами Директа) и выходит с кодом 5.
- **`--non-interactive`** — у всего, что может спросить: вместо зависания — ошибка.
- **`yd doctor --json`** — первым делом, если что-то не так: версия, проект,
  токен, кабинет по умолчанию, песочница.
- **Песочница** — `--sandbox` (или `YANDEX_DIRECT_SANDBOX=true`): проверка запросов
  без трат; нужен тестовый доступ к API.
- **Баллы API** ограничены: не перебирайте кабинет поштучно, берите списки
  фильтрами (`--campaign`, `--id` повторяемые); `--verbose` показывает `Units`.
- **Веб-интерфейс** (`masters` — Мастер кампаний, `history` — история изменений) —
  у них нет API, они идут через браузер (Playwright) с сессией Яндекса. Нужен extra:
  `uv tool install --reinstall "rb-yandex-direct[browser] @ …"` + `playwright install chromium`;
  без него эти команды отвечают DEPENDENCY_TOO_OLD. Сессия: `yd browser status --json`
  (что будет использовано, без сети), `yd browser doctor --json` (что не так). Нет сессии
  (AUTH_REQUIRED) — попросите пользователя выполнить `yd browser login` (окно для ручного
  входа) или `yd browser login --from-chrome` (куки из его Chrome); сами не входите.
  Кабинет — тот, где пользователь вошёл в браузере: `--login` здесь не действует. Браузерные
  команды медленные (секунды–минуты) и хрупкие к смене разметки Яндекса: изменения в
  Мастере — только после `--dry-run` и согласия, как и остальные.
- **`yd describe --json`** — вся CLI одним машиночитаемым документом OpenCLI (команды, опции,
  коды выхода, переменные окружения): голый документ, без конверта `{"ok": ...}`.

## Ошибки

Конверт ошибки: `{"ok": false, "error": {"code", "message", "action"}}`; у ошибок
Директа ещё `api_code` и `request_id`. Порядок чтения: код выхода → `error.code` →
`error.action` (готовая следующая команда).

    0  ok
    1  общая (UNEXPECTED — баг: повторите с --verbose и сообщите; ABORTED — пользователь отказался)
    2  неверные аргументы
    3  нужна авторизация / Директ не принял токен (коды 53, 54, 58, 513, 1002) → yd auth login
    4  проект не создан → yd init
    5  ошибка Директа или сети (временные сбои уже повторены) → повторить позже
    6  CLI старее, чем нужно проекту → uv tool upgrade rb-yandex-direct

Автоматически повторять имеет смысл только код 5 без `failed` в отчёте.
