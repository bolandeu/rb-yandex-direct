# Реестр API v5 и план покрытия

Чек-лист всех методов Яндекс.Директ API v5 с приоритезацией для
специалиста-медиабайера. Закрываем сверху вниз.

**Легенда:**

- `[ ]` не реализовано — `[x]` готово
- **Слои:** `PY` = метод в `DirectClient`/`ReportsClient`, `CLI` = команда
- **Приоритеты:**
  - **P0** — ежедневный рабочий инструмент, без этого пакет бесполезен
  - **P1** — еженедельное применение, критично для оптимизации
  - **P2** — периодическое применение, нужно для автоматизации
  - **P3** — редкое применение, можно отложить

---

## P0 — ежедневно: мониторинг, ставки, модерация

Что делает специалист каждый день: смотрит отчёты → правит ставки →
добавляет минус-слова → приостанавливает/возобновляет кампании →
следит за балансом.

### Отчёты и аналитика

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | reports.run | Запустить TSV-отчёт с polling |
| [x] | [x] | reports/CAMPAIGN_PERFORMANCE_REPORT | Эффективность кампаний (impressions/clicks/cost/ctr) |
| [x] | [x] | reports/AD_PERFORMANCE_REPORT | Эффективность объявлений |
| [x] | [x] | reports/SEARCH_QUERY_PERFORMANCE_REPORT | Поисковые запросы — источник минус-слов и инсайтов |
| [x] | [x] | reports/ACCOUNT_PERFORMANCE_REPORT | Итог по аккаунту |
| [x] | [x] | reports/CUSTOM_REPORT | Произвольная разбивка |

### Баланс и клиент

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | agencyclients.get / clients.get | Список клиентов, поиск по домену/логину |
| [x] | [ ] | clients.getClientsUnits | Остаток баллов API |
| [ ] | [ ] | clients.getBalance | Остаток средств на счетах клиентов (для агентств) |

### Кампании — чтение и управление активностью

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | campaigns.get | Список кампаний с фильтрами |
| [x] | [x] | campaigns.suspend | Приостановить (до 1000 за вызов) |
| [x] | [x] | campaigns.resume | Возобновить |
| [x] | [x] | campaigns.archive | Архивировать (P1 подтянулось) |
| [x] | [x] | campaigns.unarchive | Разархивировать (P1 подтянулось) |

### Группы объявлений — чтение

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | adgroups.get | Список групп по кампании/типу |

### Ключевые фразы — чтение и ставки

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | keywords.get | Список фраз в группе |
| [x] | [x] | keywords.suspend | Остановить фразу |
| [x] | [x] | keywords.resume | Включить фразу |
| [x] | [x] | keywords.delete | Удалить фразу (P1 подтянулось) |
| [x] | [x] | keywordbids.get | Текущие ставки (search + network) |
| [x] | [x] | keywordbids.set | Ручные ставки |
| [x] | [x] | keywordbids.setAuto | Приоритет для авто-стратегий (P1 подтянулось) |

### Минус-слова

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | adgroups.update (NegativeKeywords) | Минус-слова в группе (шорткат `set_adgroup_negative_keywords` + CLI `adgroups set-negative-keywords`) |
| [x] | [x] | campaigns.update (NegativeKeywords) | Минус-слова в кампании (шорткат `set_campaign_negative_keywords` — внутри type-specific блока) |
| [x] | [x] | negativekeywordsharedsets.get | Наборы общих минус-слов |
| [x] | [x] | negativekeywordsharedsets.update | Пополнить набор |

### Модерация

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | ads.get (State=OFF + Status) | Список объявлений в модерации/отклонённых |
| [x] | [x] | ads.moderate | Отправить на модерацию |
| [x] | [x] | ads.suspend | Остановить (P1 подтянулось) |
| [x] | [x] | ads.resume | Включить (P1 подтянулось) |

### Изменения

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | changes.checkDictionaries | Timestamp текущего состояния словарей |
| [x] | [x] | changes.checkCampaigns | Что изменилось в кампаниях с момента X |
| [x] | [ ] | changes.check | Массовая проверка изменений (для инкр. синка) |

**Итог P0: 20 методов API → 20 PY / 20 CLI ✓ ЗАКРЫТ ПОЛНОСТЬЮ (Спринт 1 + 2).**
Вдобавок подтянуто 6 методов из P1: campaigns.archive/unarchive, keywords.delete,
keywordbids.setAuto, ads.suspend/resume.

---

## P1 — еженедельно: оптимизация, масштабирование

Что делает специалист регулярно: анализирует ретаргетинг, обновляет
тексты объявлений, расширяет семантику, ставит корректировки.

### Группы объявлений

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | adgroups.get | Список групп (дубликат, уже сделан в P0) |
| [x] | [x] | adgroups.add | Создать группу (Спринт 5B) |
| [x] | [x] | adgroups.update | Обновить группу (Спринт 5B) |
| [x] | [x] | adgroups.delete | Удалить (Спринт 5B) |

### Объявления

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | ads.get | Список объявлений (дубликат, уже сделан в P0) |
| [x] | [x] | ads.add | Создать объявление — шорткат TextAd + add-json (Спринт 5B) |
| [x] | [x] | ads.update | Обновить (Спринт 5B, через update_ads dict) |
| [x] | [x] | ads.suspend | Остановить (дубликат из P0) |
| [x] | [x] | ads.resume | Включить (дубликат из P0) |
| [x] | [x] | ads.archive | Архивировать (Спринт 5B) |
| [x] | [x] | ads.unarchive | Восстановить из архива (Спринт 5B) |
| [x] | [x] | ads.delete | Удалить (Спринт 5B) |

### Ключевые фразы — расширение

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | keywords.add | Добавить фразы (batch до 1000, Спринт 5A) |
| [x] | [x] | keywords.update | Обновить фразу (Спринт 5A) |
| [x] | [x] | keywords.delete | Удалить (сделано в Спринте 2) |
| [x] | [x] | keywordsresearch.deduplicate | Убрать пересечения во фразах |
| [x] | [x] | keywordsresearch.hasSearchVolume | Проверить, есть ли спрос |
| [x] | [x] | keywordbids.setAuto | Стратегические ставки под автоматики (Спринт 2) |

### Корректировки ставок

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | bidmodifiers.get | Корректировки по устройствам/регионам/демо |
| [x] | [x] | bidmodifiers.add | Добавить корректировку (Спринт 5A) |
| [x] | [x] | bidmodifiers.set | Изменить значение (Спринт 5A) |
| [x] | [x] | bidmodifiers.delete | Удалить (Спринт 5A) |
| [x] | [x] | bidmodifiers.toggle | Вкл/выкл по связке уровень+тип (Спринт 5A) |

### Кампании — управление бюджетами

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | campaigns.update | Дневной бюджет, имя, даты (Спринт 5A) |
| [x] | [x] | campaigns.archive | Заархивировать (Спринт 2, бонусом из P0) |
| [x] | [x] | campaigns.unarchive | Разархивировать (Спринт 2, бонусом из P0) |

### Ретаргетинг и аудитории

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | retargetinglists.get | Списки ретаргетинга |
| [x] | [x] | retargetinglists.add | Новый список (цели Метрики, Спринт 5C) |
| [x] | [x] | retargetinglists.update | Правила списка (Спринт 5C) |
| [x] | [x] | retargetinglists.delete | Удалить (Спринт 5C) |
| [x] | [x] | audiencetargets.get | Таргетинг на аудитории в группах |
| [x] | [x] | audiencetargets.add | Привязать аудиторию к группе (Спринт 5C) |
| [x] | [x] | audiencetargets.suspend | Остановить (Спринт 5C) |
| [x] | [x] | audiencetargets.resume | Включить (Спринт 5C) |
| [x] | [x] | audiencetargets.setBids | Ставки для аудитории (сверено с официальной докой: `Bids: [{Id\|AdGroupId\|CampaignId, ContextBid, StrategyPriority}]`) |
| [x] | [x] | audiencetargets.delete | Удалить (Спринт 5C) |

**Итог P1: 35 методов API → 35 PY / 35 CLI — ✓ ЗАКРЫТО.**

---

## P2 — периодически: расширения, креативы, справочники

Настройка расширений, загрузка креативов, справочные данные
для отчётов и новых кампаний.

### Расширения объявлений

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | sitelinks.get | Наборы быстрых ссылок |
| [x] | [x] | sitelinks.add | Создать набор |
| [x] | [x] | sitelinks.delete | Удалить набор |
| [x] | [x] | vcards.get | Визитки |
| [x] | [x] | vcards.add | Создать визитку |
| [x] | [x] | vcards.delete | Удалить |
| [x] | [x] | adextensions.get | Уточнения (callouts) |
| [x] | [x] | adextensions.add | Добавить |
| [x] | [x] | adextensions.moderate | Модерация |
| [x] | [x] | adextensions.delete | Удалить |

### Креативы — изображения, видео, турбо

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | adimages.get | Список изображений |
| [x] | [x] | adimages.add | Загрузить изображение (base64 из файла) |
| [x] | [x] | adimages.delete | Удалить по хэшу |
| [x] | [x] | creatives.get | Видео/HTML5/Smart креативы (read) |
| [x] | [x] | creatives.add | VideoExtensionCreative по VideoId (до 10 за вызов) |
| [x] | [x] | turbopages.get | Турбо-страницы (read) |

### Справочники

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | dictionaries.get (Currencies) | Список валют |
| [x] | [x] | dictionaries.get (TimeZones) | Часовые пояса |
| [x] | [x] | dictionaries.get (GeoRegions) | Регионы для таргетинга |
| [x] | [x] | dictionaries.get (AdCategories) | Категории объявлений |
| [x] | [x] | dictionaries.get (OperationSystemVersions) | Версии ОС |
| [x] | [x] | dictionaries.get (ProductivityIndicators) | Индикаторы эффективности |
| [x] | [x] | dictionaries.get (AutoBusinesses) | Справочник авто для бизнеса |

**Итог P2: 23 метода API → 23 PY / 23 CLI — ✓ ЗАКРЫТО.**

---

## P3 — редко: кампании с нуля, фиды, лиды

Создание новых кампаний, работа с товарными фидами, сбор лидов
с форм. Обычно делается руками в интерфейсе, автоматизация нужна
агентствам и для массового деплоя.

### Кампании — CRUD

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | campaigns.add | Создать кампанию (через JSON со структурой TextCampaign/SmartCampaign/... BiddingStrategy) |
| [x] | [x] | campaigns.delete | Удалить (жёстко, после archive) |

### Агентство и клиенты

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | clients.update | Изменить настройки клиента (CLI `client update --from-json`) |
| [x] | [x] | agencyclients.update | Настройки агентского доступа (`client update-agency --from-json`) |

### Динамический и смарт-таргетинг

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | dynamictextadtargets.get/delete/suspend/resume | Динамические объявления (read + state) |
| [x] | [x] | dynamictextadtargets.add/setBids | Добавление (`add-json`) + ставки (`set-bid`) |
| [x] | [x] | smartadtargets.get/delete/suspend/resume | Смарт-баннеры (read + state) |
| [x] | [x] | smartadtargets.add/setBids | Добавление (`add-json`) + ставки (`set-bid`) |

### Фиды и бизнес-данные

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | feeds.get | Фиды |
| [x] | [x] | feeds.add | Загрузить YML (через JSON-конфиг) |
| [x] | [x] | feeds.update | Обновить (`feeds update-json --from-json`) |
| [x] | [x] | feeds.delete | Удалить |
| [x] | [x] | businesses.get | Бизнес-данные (read) |
| [x] | [x] | leads.get | Лиды с форм (read) |

### Общие минус-слова — полная CRUD

| PY  | CLI | Сервис.метод | Назначение |
|---|---|---|---|
| [x] | [x] | negativekeywordsharedsets.add | Создать набор |
| [x] | [x] | negativekeywordsharedsets.delete | Удалить |

**Итог P3: ~20 методов API → 20 PY / 20 CLI — ✓ ЗАКРЫТО.
Для сложных структур (clients/agencyclients/feeds/targets add) CLI принимает `--from-json`.**

---

## Сводная таблица

| Приоритет | Методов API | Python | CLI | % от всей работы |
|---|---|---|---|---|
| **P0 (ежедневно)** | 20 | 20 | 20 | 22% |
| **P1 (еженедельно)** | 35 | 35 | 35 | 39% |
| **P2 (периодически)** | 23 | 23 | 23 | 26% |
| **P3 (редко)** | 20 | 20 | 20 | 13% |
| **Всего** | **~98** | **98** | **98** | **100% ✓** |

## Очерёдность внедрения

1. **Спринт 1 (P0-read):** все `get` из P0 в Python + CLI →
   специалист уже может полностью наблюдать кабинет.
2. **Спринт 2 (P0-write):** `suspend/resume` кампаний и ключей,
   `keywordbids.set`, минус-слова, `ads.moderate` → управление на
   ходу.
3. **Спринт 3 (P0-reports):** шаблоны 5 стандартных отчётов с
   форматированием (`report --preset search-queries`, и т.д.) +
   скилл `/direct-report`.
4. **Спринт 4 (P1-read):** чтение ads/adgroups/keywords/bidmodifiers/
   retargetinglists/audiencetargets.
5. **Спринт 5 (P1-write):** CRUD ads/adgroups/keywords/bidmodifiers,
   настройка ретаргетинга.
6. **Спринт 6 (P2):** расширения + креативы + словари.
7. **Спринт 7 (P3):** создание кампаний с нуля, фиды, лиды,
   дин./смарт-таргетинг.

После каждого спринта обновляется этот файл — чекбоксы становятся
`[x]`, появляются ссылки на исходники.
