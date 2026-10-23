# Changelog

All notable changes to this project are documented here. Versions follow
[SemVer](https://semver.org/) (while at `0.x`, a minor bump may break).

The changelog is written by `antagor publish`; don't edit it by hand.

## [0.3.0] - 2026-09-30

### Added

- API Директа v4 Live (то, чего нет в v5): `wordstat create|list|get|delete|run` (статистика запросов), `forecast create|list|get|delete|run` (прогноз бюджета), `events list` (журнал событий), `goals stat|retargeting`, `tags campaigns|banners|set-campaign|set-banners`, `suggest` (подсказки фраз), `v4 ping|version`. ДЕНЬГИ: `finance setup|status|forget|units|credit-limits|check-payment|invoice|pay|transfer` и `shared-account list|update|deposit|invoice|transfer|enable` — мастер-токен в keychain `yandex-oauth:direct_finance` или env `YANDEX_OAUTH_DIRECT_FINANCE_MASTER_TOKEN` + `YANDEX_OAUTH_DIRECT_FINANCE_LOGIN`; финансовый токен и растущий номер операции CLI считает сам (номер хранится в `platformdirs.user_data_dir("yd")/finance.json`); все денежные операции — через `--dry-run` и `--confirm`.
- `agency list|add-organization|add-member|update|update-json` — клиенты агентства (AgencyClients, в т.ч. addPassportOrganization/Member); `clients update` с типизированными опциями. `client update-agency` → `agency update-json`.
- `campaigns add text|unified|dynamic|smart|mobile-app|cpm-banner` — создание кампании из опций (стратегия и её параметры в рублях, бюджет, настройки, счётчики, ключевые цели, площадки, минус-фразы) с проверкой по WSDL до запроса; `campaigns set-strategy` — смена стратегии; `campaigns get` отдаёт кампанию целиком (все *CampaignFieldNames); `campaigns list --status/--payment-status`.
- `dict geo-regions` (поиск регионов), `dict names`, `changes campaigns`, `report types`; `report *`: `--range`, `--goal`, `--attribution-model`, `--vat/--no-vat`, `--micros`, `--dry-run`, в `report custom` ещё `--filter`, `--order-by`, `--adgroup`, `--limit`, `--mode`; строки отчёта — список в `--json` (числа — числами); `feeds add|update` по ссылке или файлом.
- `strategies list|add|update|archive|unarchive|add-json` — пакетные стратегии (сервис Strategies).
- Веб-интерфейс Директа (то, чего нет в API), extra `browser`: `masters` — Мастер кампаний (`list`, `get`, `audience`, `counters`, `target-actions`, `suspend`/`resume`/`archive`/`delete`/`launch`/`copy`, экспериментально `add`, `update` и `images list|add|delete|set`), `history get` — история изменений кабинета, `browser login|status|doctor|logout` — сессия Яндекса (свой профиль Chromium, снимок кук Chrome или свежие куки Chrome). Браузерный слой — пакет direct-cli (MIT, axisrow/direct-cli, закреплён на коммите). Установка: `uv tool install --reinstall "rb-yandex-direct[browser] @ git+…"` и `playwright install chromium`. Данные сессии — в `platformdirs.user_data_dir("yd")/browser`.
- Объявления и группы: `ads get`, `ads update` (TextAd, уточнения --callout-add/remove/set), `ads update-json`, типизированное создание `ads add-responsive`, `add-mobile-app`, `add-image`, `add-builder`, `add-shopping` (и ListingAd), в `ads add-text` — прайс-дополнение, видеодополнение, организация, уточнения, маркировка ЕРИР; `adgroups get`, `adgroups add --type text|dynamic|dynamic-feed|mobile-app|smart|unified`, `adgroups update-json`, фильтры списков (`--status`, `--serving-status`, `--type`, `--mobile`, `--vcard`, `--sitelink-set`, `--image-hash`, `--extension`, `--tag`). Новая группа `videos list|add` (AdVideos). `sitelinks add --link 'Заголовок|URL|Описание'`, `vcards add` с опциями полей, фильтры `--id` у sitelinks/vcards/extensions/turbo/businesses/creatives/images.
- Таргетинг и ставки на новой архитектуре: `keywords`, `bids` (KeywordBids), новая группа `bids-classic` (сервис Bids: цены позиций, охват, автоподбор по позиции), `modifiers`, `minus-sets`, `retargeting` (+ `add-json`), `audiences`, `dynamic-targets`, новая группа `dynamic-feed-targets` (DynamicFeedAdTargets), `smart-targets` (+ `update`). Типизированное создание условий (`--condition OPERAND:OPERATOR:ARG1|ARG2`, ставки в рублях), фильтры списков `--id/--adgroup/--campaign/--state/--status/--serving-status/--field`, у корректировок — все 13 типов (`--os`, `--serp-layout`, `--grade`…), у фраз — настройки автотаргетинга (`--autotargeting-phrase`, `--autotargeting Exact=YES`).

### Changed

- Команда переименована: `rb-yandex-direct` → `yd` (дистрибутив по-прежнему `rb-yandex-direct`). Ломающее: скрипты, вызывающие `rb-yandex-direct`, нужно поправить; поле `tool` в `auth status --json` теперь `yd`. После обновления: `uv tool install --reinstall`.
- Команды структуры объявлений (ломающее): `sitelinks add --from-json` → `sitelinks add-json`, `vcards add --from-json` → `vcards add-json`; `leads` фильтрует по `--turbo-page` (так требует API), а не по кампании; `extensions moderate` убрана — такого метода в API нет; `adgroups list` и `ads list` требуют `--campaign`, `--adgroup` или `--id` (без них API отвечает ошибкой), `ads moderation` — `--campaign`; `set-negative-keywords --words 'a,b'` → `-w a -w b`; `extensions list --state` принимает ON/DELETED (значения API).
- Ломающее: `modifiers toggle` удалён (метода нет в API v5); `audiences/dynamic-targets/smart-targets set-bid` → `set-bids` с областью `--id|--adgroup|--campaign`; `keywords update --id N` → `keywords update N` (без `--priority`: приоритет — `bids set --priority`); `bids set-auto` теперь задаёт правило автоподбора (`--target-traffic-volume` / `--target-coverage`, `--bid-ceiling`), а не приоритет; `keywords dedup` только рассчитывает подсказки (фразы, `--from-file` или `--adgroup`) и ничего не меняет; `minus-sets` принимает `-w/--word` вместо `--words a,b`; `smart-targets set-bids` — `--average-cpc/--average-cpa` вместо `--bid`.
- Переход на архитектуру cli-generator (Typer): `--json` у каждой команды (конверт `{ok, …}` в stdout, ошибки — `{ok: false, error: {code, message, action}}`), `--dry-run`/`--confirm`/`--non-interactive` у всех изменяющих команд вместо `-y/--yes`, `--output FILE` убран (`--json > file`), `doctor`, `init`/`status`/`config` (проект `.yd/config.toml` с кабинетом по умолчанию), `skill install` и `--ai` (памятка для агентов). Ошибки Директа: учётные данные (53/54/58/513/1002) — `AUTH_REQUIRED`, exit 3; прочие — `PROVIDER_ERROR`, exit 5, с `api_code` и `request_id`; временные сбои (52/506/1000/1001, HTTP 429/5xx, сеть) повторяются. `client update` → `clients update-json`.

### Removed

- Удалён MCP-сервер (`rb-yandex-direct mcp`, entry point `mcp.servers`) и зависимость `mcp`: агенты работают через CLI `yd`.

### Fixed

- Запросы приведены к WSDL API v5: `keywordbids.get` (Search/NetworkFieldNames вместо полей Search/Network), `bidmodifiers.get` (обязательный Levels и *FieldNames по типам), `bidmodifiers.add` (массивы DemographicsAdjustments/RegionalAdjustments/…), `smartadtargets` (SmartAdTargets и AverageCpc/AverageCpa вместо Filters/Bid), `keywordsresearch.hasSearchVolume`/`deduplicate` (SelectionCriteria, Keywords-объекты), `negativekeywordsharedsets.update` (плоский массив фраз), `retargetinglists.get` (без несуществующего CryptaScoring), `keywords.get` (UserParam1/2 вместо UserParam).
- Запросы сверены с WSDL API v5: `ads add-text` передаёт обязательное поле `Mobile` (по умолчанию NO) — раньше API отклонял объявление; `leads`, `turbo list`, `businesses`, `extensions list` запрашивали несуществующие поля и фильтры и получали ошибку; `sitelinks list`/`vcards list` без фильтра больше не шлют пустой SelectionCriteria; имена блоков типа групп (CpmBannerKeywordsAdGroup, UnifiedAdGroup, TextAdGroupFeedParams…) в проверке `adgroups add-json`; ошибки формы запроса — INVALID_ARGUMENTS (exit 2) до обращения к API, а не UNEXPECTED.
- Запросы, которые API отвергал: `changes.checkCampaigns`/`checkDictionaries` слали лишние поля, `changes.check` — несуществующие FieldNames, `feeds.get` — устаревшие поля, `dict get` предлагал несуществующие справочники; минус-фразы кампании клались в блок типа вместо верхнего уровня CampaignUpdateItem; убран несуществующий метод `clients.getClientsUnits`. Отчёты: имя отчёта — хэш параметров (повтор с другими параметрами больше не падает), суммы по умолчанию с НДС.
- Памятка для агентов `data/SKILL.md` не попадала в репозиторий и пакет: `.gitignore` игнорировал любую папку `data/`, теперь — только корневую.
- Человеческий вывод ошибок больше не теряет текст в квадратных скобках (например `rb-yandex-direct[browser]` в подсказке установки).


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
