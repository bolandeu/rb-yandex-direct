# Changelog

Все заметные изменения rb-yandex-direct. Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии — [SemVer](https://semver.org/lang/ru/) (на 0.x ломающие изменения — минорная версия).
Файл собирается из фрагментов `changelog.d/` командой `scripts/release.py`; руками не править.

<!-- towncrier release notes start -->

## [0.2.0] - 2026-09-27

### Added

- `auth status [--check] [--json]` — отчёт о токене по контракту §8 стандарта tools (источник, срок, остаток баллов API; exit 3 при проблеме), а также `auth logout` и `--version`. Отказ Директа по учётным данным (коды 53, 54, 58, 513, 1002) — exit 3, прочие ошибки API в `whoami` — exit 5.

### Changed

- Авторизация — через общую библиотеку rb-yandex-oauth: токен в keychain ОС (слот `yandex-oauth:direct`, отдельный от общего токена ym/ywm) и обновляется сам по refresh_token. Без keychain — переменные `YANDEX_OAUTH_DIRECT_REFRESH_TOKEN`/`_CLIENT_ID`/`_CLIENT_SECRET`; готовый токен — `YANDEX_DIRECT_TOKEN`. Файлы `.env` больше не читаются и не пишутся. **Ломающее:** вход теперь `rb-yandex-direct auth login` (был голый `auth`); прежние `YANDEX_DIRECT_REFRESH_TOKEN`/`YANDEX_DIRECT_TOKEN_EXPIRES` не читаются — выполните `auth login` заново.
- Голый `rb-yandex-direct` или группа без подкоманды печатает справку и выходит с кодом 0 (раньше — код 2).
- Стандарт релизов tools: версия из git-тега (`rb-yandex-direct --version`), CHANGELOG из фрагментов `changelog.d/`, гейт `scripts/release.py --check`, справка команд с обязательными `Example:` и снапшотами.

### Removed

- Команды `sandbox on|off|show` (писала `.env`) и `auth show` удалены: окружение — флаг `--sandbox/--prod` или `YANDEX_DIRECT_SANDBOX=true`, токен — `auth status`. Удалён `OAuthToken.to_env_dict()`.

### Security

- Обновлены зависимости с известными уязвимостями (starlette, python-multipart, cryptography, pyjwt и др.); `mcp` ограничен `>=1.28.1,<2`.


## [0.1.0] - 2026-09-27

### Added

- Библиотека, CLI `rb-yandex-direct` и MCP-сервер для API Яндекс.Директа v5: 98 методов (кампании, группы,
  объявления, ключи и ставки, корректировки, ретаргетинг, минус-наборы, расширения, фиды, таргетинги, отчёты).
