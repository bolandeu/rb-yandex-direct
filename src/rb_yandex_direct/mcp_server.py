"""MCP-сервер rb-yandex-direct (stdio).

P0 read-инструменты. Write (suspend/resume/set) — в последующих спринтах.
Все write-tools при добавлении обязаны требовать confirm=true.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from mcp.server.fastmcp import FastMCP

from rb_yandex_direct.core.client import DirectClient
from rb_yandex_direct.core.reports import ReportsClient

load_dotenv()

LOG_PATH = Path.home() / ".local/state/logs/mcp-rb-yandex-direct.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(LOG_PATH, rotation="5 MB", retention=3, level="INFO")

mcp = FastMCP("rb-yandex-direct")


def _client(login: str | None = None, sandbox: bool | None = None) -> DirectClient:
    token = os.getenv("YANDEX_DIRECT_TOKEN")
    if not token:
        raise RuntimeError("Не задан YANDEX_DIRECT_TOKEN. Авторизуйся: rb-yandex-direct auth")
    sb = sandbox if sandbox is not None else os.getenv("YANDEX_DIRECT_SANDBOX", "").lower() == "true"
    return DirectClient(
        token=token,
        client_login=login or os.getenv("YANDEX_DIRECT_LOGIN"),
        sandbox=sb,
        use_operator_units=os.getenv("YANDEX_DIRECT_USE_OPERATOR_UNITS", "").lower() == "true",
    )


def _reports(login: str | None = None) -> ReportsClient:
    token = os.getenv("YANDEX_DIRECT_TOKEN")
    if not token:
        raise RuntimeError("Не задан YANDEX_DIRECT_TOKEN")
    return ReportsClient(
        token=token,
        client_login=login or os.getenv("YANDEX_DIRECT_LOGIN"),
        sandbox=os.getenv("YANDEX_DIRECT_SANDBOX", "").lower() == "true",
    )


# ---- Клиенты и баланс ----


def _managed_logins() -> list[str]:
    raw = os.getenv("YANDEX_DIRECT_MANAGED_LOGINS", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


@mcp.tool()
async def list_clients(login: str | None = None) -> list[dict]:
    """Список клиентов агентства (или запись о себе для обычного аккаунта).

    Используй в первую очередь, чтобы найти нужный Client-Login по
    домену/названию клиента.
    """
    return await _client(login).list_clients()


@mcp.tool()
async def list_managed_accounts() -> list[dict]:
    """Все кабинеты, к которым у юзера есть доступ (агентский или представитель).

    Сначала вызывает `agencyclients.get` — если ты агентство, вернёт подопечных.
    Затем дополняет логинами из env YANDEX_DIRECT_MANAGED_LOGINS и делает
    `clients.get` под каждым, чтобы собрать валюту, баллы, статус.

    Используй как первый шаг, когда пользователь просит «посмотри у клиента X»:
    тут ты получишь список логинов и сможешь сопоставить с именем/доменом.
    """
    token = os.getenv("YANDEX_DIRECT_TOKEN")
    if not token:
        raise RuntimeError("Нет YANDEX_DIRECT_TOKEN")
    sandbox = os.getenv("YANDEX_DIRECT_SANDBOX", "").lower() == "true"
    use_op = os.getenv("YANDEX_DIRECT_USE_OPERATOR_UNITS", "").lower() == "true"

    seen: dict[str, dict] = {}
    try:
        agency = DirectClient(token=token, sandbox=sandbox, use_operator_units=use_op)
        for c in await agency.list_clients():
            seen[c.get("Login")] = c
    except Exception:  # noqa: S110 — не агентство: списка подопечных нет, это обычный случай
        pass

    for managed_login in _managed_logins():
        if managed_login in seen:
            continue
        c = DirectClient(token=token, client_login=managed_login, sandbox=sandbox, use_operator_units=use_op)
        try:
            items = await c.list_clients()
            seen[managed_login] = items[0] if items else {"Login": managed_login}
        except Exception as e:
            seen[managed_login] = {"Login": managed_login, "_error": str(e)}

    return list(seen.values())


@mcp.tool()
async def get_clients_units(logins: list[str] | None = None, login: str | None = None) -> list[dict]:
    """Остаток баллов API по клиентам (RateLimit / DailyLimit)."""
    return await _client(login).get_clients_units(logins=logins)


# ---- Кампании ----


@mcp.tool()
async def list_campaigns(
    login: str | None = None,
    state: str | None = None,
    type: str | None = None,
) -> list[dict]:
    """Список кампаний клиента.

    Args:
        state: ON | OFF | SUSPENDED | ENDED | CONVERTED | ARCHIVED
        type: TEXT_CAMPAIGN | MCBANNER_CAMPAIGN | CPM_BANNER_CAMPAIGN |
              SMART_CAMPAIGN | MOBILE_APP_CAMPAIGN | UNIFIED_CAMPAIGN | ...
    """
    criteria: dict = {}
    if state:
        criteria["States"] = [state]
    if type:
        criteria["Types"] = [type]
    return await _client(login).list_campaigns(selection_criteria=criteria)


@mcp.tool()
async def get_campaign(campaign_id: int, login: str | None = None) -> dict:
    """Подробная информация об одной кампании."""
    c = await _client(login).get_campaign(campaign_id)
    return c or {}


# ---- Группы объявлений ----


@mcp.tool()
async def list_adgroups(
    campaign_ids: list[int] | None = None,
    types: list[str] | None = None,
    login: str | None = None,
) -> list[dict]:
    """Группы объявлений указанных кампаний."""
    return await _client(login).list_adgroups(campaign_ids=campaign_ids, types=types)


# ---- Объявления ----


@mcp.tool()
async def list_ads(
    campaign_ids: list[int] | None = None,
    adgroup_ids: list[int] | None = None,
    states: list[str] | None = None,
    statuses: list[str] | None = None,
    login: str | None = None,
) -> list[dict]:
    """Объявления с фильтрами.

    Args:
        states: ON | OFF | SUSPENDED | OFF_BY_MONITORING | ARCHIVED
        statuses: ACCEPTED | DRAFT | MODERATION | PREACCEPTED | REJECTED — модерация
    """
    return await _client(login).list_ads(
        campaign_ids=campaign_ids,
        adgroup_ids=adgroup_ids,
        states=states,
        statuses=statuses,
    )


@mcp.tool()
async def list_ads_in_moderation(
    campaign_ids: list[int] | None = None,
    login: str | None = None,
) -> list[dict]:
    """Объявления, ждущие модерации или отклонённые (шорткат)."""
    return await _client(login).list_ads_in_moderation(campaign_ids=campaign_ids)


# ---- Ключи и ставки ----


@mcp.tool()
async def list_keywords(
    adgroup_ids: list[int] | None = None,
    campaign_ids: list[int] | None = None,
    states: list[str] | None = None,
    login: str | None = None,
) -> list[dict]:
    """Ключевые фразы групп/кампаний."""
    return await _client(login).list_keywords(
        adgroup_ids=adgroup_ids,
        campaign_ids=campaign_ids,
        states=states,
    )


@mcp.tool()
async def get_keyword_bids(
    keyword_ids: list[int] | None = None,
    adgroup_ids: list[int] | None = None,
    campaign_ids: list[int] | None = None,
    login: str | None = None,
) -> list[dict]:
    """Текущие ставки по фразам (search + network).

    Обязательно указать хотя бы один из фильтров.
    """
    return await _client(login).get_keyword_bids(
        keyword_ids=keyword_ids,
        adgroup_ids=adgroup_ids,
        campaign_ids=campaign_ids,
    )


# ---- Общие минус-слова ----


@mcp.tool()
async def list_negative_keyword_shared_sets(login: str | None = None) -> list[dict]:
    """Наборы общих минус-слов клиента."""
    return await _client(login).list_negative_keyword_shared_sets()


# ---- Изменения ----


@mcp.tool()
async def check_dictionaries(timestamp: str) -> dict:
    """Актуальность справочников на указанный timestamp (ISO 8601 UTC).

    Возвращает Timestamp — если он больше переданного, словари обновились.
    """
    token = os.getenv("YANDEX_DIRECT_TOKEN")
    if not token:
        raise RuntimeError("Нет YANDEX_DIRECT_TOKEN")
    c = DirectClient(token=token)
    return await c.check_dictionaries(timestamp)


@mcp.tool()
async def check_campaign_changes(
    timestamp: str,
    campaign_ids: list[int] | None = None,
    adgroup_ids: list[int] | None = None,
    ad_ids: list[int] | None = None,
    login: str | None = None,
) -> dict:
    """Что изменилось в кампаниях с указанного timestamp (changes.checkCampaigns)."""
    return await _client(login).check_campaign_changes(
        timestamp=timestamp,
        campaign_ids=campaign_ids,
        adgroup_ids=adgroup_ids,
        ad_ids=ad_ids,
    )


@mcp.tool()
async def check_changes(
    timestamp: str,
    campaign_ids: list[int] | None = None,
    adgroup_ids: list[int] | None = None,
    ad_ids: list[int] | None = None,
    login: str | None = None,
) -> dict:
    """Массовая проверка изменений — для инкрементального синка (changes.check)."""
    return await _client(login).check_changes(
        timestamp=timestamp,
        campaign_ids=campaign_ids,
        adgroup_ids=adgroup_ids,
        ad_ids=ad_ids,
    )


# ---- Отчёты ----


@mcp.tool()
async def report_campaigns(
    date_from: str,
    date_to: str,
    login: str | None = None,
) -> list[dict]:
    """CAMPAIGN_PERFORMANCE_REPORT: impressions / clicks / cost / ctr / conversions по кампаниям."""
    rep = await _reports(login).campaign_performance(date_from, date_to)
    return rep.parse()


@mcp.tool()
async def report_ads(
    date_from: str,
    date_to: str,
    login: str | None = None,
) -> list[dict]:
    """AD_PERFORMANCE_REPORT: эффективность объявлений."""
    rep = await _reports(login).ad_performance(date_from, date_to)
    return rep.parse()


@mcp.tool()
async def report_search_queries(
    date_from: str,
    date_to: str,
    campaign_ids: list[int] | None = None,
    login: str | None = None,
) -> list[dict]:
    """SEARCH_QUERY_PERFORMANCE_REPORT: реальные пользовательские запросы, источник минус-слов."""
    rep = await _reports(login).search_query_performance(date_from, date_to, campaign_ids)
    return rep.parse()


@mcp.tool()
async def report_account(
    date_from: str,
    date_to: str,
    login: str | None = None,
) -> list[dict]:
    """ACCOUNT_PERFORMANCE_REPORT: итог по всему аккаунту."""
    rep = await _reports(login).account_performance(date_from, date_to)
    return rep.parse()


# ---- P1 read: корректировки, ретаргетинг, аудитории, исследование ключей ----


@mcp.tool()
async def list_bid_modifiers(
    campaign_ids: list[int] | None = None,
    adgroup_ids: list[int] | None = None,
    types: list[str] | None = None,
    login: str | None = None,
) -> list[dict]:
    """Корректировки ставок. types: MOBILE_ADJUSTMENT, DEMOGRAPHICS_ADJUSTMENT,
    RETARGETING_ADJUSTMENT, REGIONAL_ADJUSTMENT, VIDEO_ADJUSTMENT, INCOME_GRADE_ADJUSTMENT.
    """
    return await _client(login).list_bid_modifiers(
        campaign_ids=campaign_ids,
        adgroup_ids=adgroup_ids,
        types=types,
    )


@mcp.tool()
async def list_retargeting_lists(
    types: list[str] | None = None,
    login: str | None = None,
) -> list[dict]:
    """Списки ретаргетинга. types: RETARGETING (цели Метрики), AUDIENCE,
    SHARED_AUDIENCE, YANDEX_PROVIDER.
    """
    return await _client(login).list_retargeting_lists(types=types)


@mcp.tool()
async def list_audience_targets(
    adgroup_ids: list[int] | None = None,
    campaign_ids: list[int] | None = None,
    states: list[str] | None = None,
    login: str | None = None,
) -> list[dict]:
    """Привязки аудиторий к группам — показывает где и с какой ставкой работает ретаргетинг."""
    return await _client(login).list_audience_targets(
        adgroup_ids=adgroup_ids,
        campaign_ids=campaign_ids,
        states=states,
    )


@mcp.tool()
async def keywords_has_search_volume(
    keywords: list[str],
    region_ids: list[int] | None = None,
    login: str | None = None,
) -> list[dict]:
    """Проверить наличие поискового спроса у фраз.

    Returns: [{Phrase, HasSearchVolume}]. region_ids — регионы Яндекса
    (213=Москва, 2=СПб). None → по всей России.
    """
    return await _client(login).keywords_has_search_volume(keywords, region_ids=region_ids)


@mcp.tool()
async def keywords_deduplicate(
    keyword_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Найти дубли среди фраз и приостановить копии (write-операция)."""
    if not confirm:
        return _dry_run("keywordsresearch.deduplicate", keyword_ids=keyword_ids, login=login)
    return await _client(login).keywords_deduplicate(keyword_ids)


# ---- Write-инструменты ----
# Безопасный паттерн: без confirm=true возвращаем описание операции
# (dry-run), что даёт Claude шанс показать пользователю план перед
# выполнением.


def _dry_run(action: str, **details) -> dict:
    return {
        "requires_confirm": True,
        "action": action,
        "note": "Повтори вызов с confirm=true для выполнения.",
        **details,
    }


@mcp.tool()
async def suspend_campaigns(
    campaign_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Приостановить кампании. Требует confirm=true."""
    if not confirm:
        return _dry_run("campaigns.suspend", campaign_ids=campaign_ids, login=login)
    return await _client(login).suspend_campaigns(campaign_ids)


@mcp.tool()
async def resume_campaigns(
    campaign_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Возобновить приостановленные кампании."""
    if not confirm:
        return _dry_run("campaigns.resume", campaign_ids=campaign_ids, login=login)
    return await _client(login).resume_campaigns(campaign_ids)


@mcp.tool()
async def archive_campaigns(
    campaign_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Архивировать кампании (должны быть suspended, без остатка средств)."""
    if not confirm:
        return _dry_run("campaigns.archive", campaign_ids=campaign_ids, login=login)
    return await _client(login).archive_campaigns(campaign_ids)


@mcp.tool()
async def suspend_keywords(
    keyword_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Остановить ключевые фразы."""
    if not confirm:
        return _dry_run("keywords.suspend", keyword_ids=keyword_ids, login=login)
    return await _client(login).suspend_keywords(keyword_ids)


@mcp.tool()
async def resume_keywords(
    keyword_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Включить ключи."""
    if not confirm:
        return _dry_run("keywords.resume", keyword_ids=keyword_ids, login=login)
    return await _client(login).resume_keywords(keyword_ids)


@mcp.tool()
async def delete_keywords(
    keyword_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Удалить ключи безвозвратно."""
    if not confirm:
        return _dry_run("keywords.delete", keyword_ids=keyword_ids, login=login, irreversible=True)
    return await _client(login).delete_keywords(keyword_ids)


@mcp.tool()
async def set_keyword_bids(
    bids: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Установить ручные ставки.

    bids — список объектов:
      {"KeywordId": 123, "SearchBid": 30000000, "NetworkBid": 20000000}
    Цены в микро-единицах валюты (рубли × 1_000_000).
    """
    if not confirm:
        return _dry_run("keywordbids.set", count=len(bids), sample=bids[:3])
    return await _client(login).set_keyword_bids(bids)


@mcp.tool()
async def set_keyword_bids_auto(
    bids: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Приоритеты ключей для авто-стратегий.

    bids: [{"KeywordId": 123, "StrategyPriority": "HIGH|NORMAL|LOW"}]
    """
    if not confirm:
        return _dry_run("keywordbids.setAuto", count=len(bids), sample=bids[:3])
    return await _client(login).set_keyword_bids_auto(bids)


@mcp.tool()
async def moderate_ads(
    ad_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Отправить объявления на модерацию (DRAFT → MODERATION)."""
    if not confirm:
        return _dry_run("ads.moderate", ad_ids=ad_ids, login=login)
    return await _client(login).moderate_ads(ad_ids)


@mcp.tool()
async def suspend_ads(ad_ids: list[int], login: str | None = None, confirm: bool = False) -> dict:
    if not confirm:
        return _dry_run("ads.suspend", ad_ids=ad_ids, login=login)
    return await _client(login).suspend_ads(ad_ids)


@mcp.tool()
async def resume_ads(ad_ids: list[int], login: str | None = None, confirm: bool = False) -> dict:
    if not confirm:
        return _dry_run("ads.resume", ad_ids=ad_ids, login=login)
    return await _client(login).resume_ads(ad_ids)


@mcp.tool()
async def archive_ads(ad_ids: list[int], login: str | None = None, confirm: bool = False) -> dict:
    if not confirm:
        return _dry_run("ads.archive", ad_ids=ad_ids)
    return await _client(login).archive_ads(ad_ids)


@mcp.tool()
async def unarchive_ads(ad_ids: list[int], login: str | None = None, confirm: bool = False) -> dict:
    if not confirm:
        return _dry_run("ads.unarchive", ad_ids=ad_ids)
    return await _client(login).unarchive_ads(ad_ids)


@mcp.tool()
async def delete_ads(
    ad_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Удалить объявления безвозвратно."""
    if not confirm:
        return _dry_run("ads.delete", ad_ids=ad_ids, irreversible=True)
    return await _client(login).delete_ads(ad_ids)


@mcp.tool()
async def add_text_ad(
    adgroup_id: int,
    title: str,
    text: str,
    href: str,
    title2: str | None = None,
    display_url_path: str | None = None,
    ad_image_hash: str | None = None,
    sitelink_set_id: int | None = None,
    vcard_id: int | None = None,
    turbo_page_id: int | None = None,
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Шорткат: создать одно текстовое объявление (TextAd).

    Лимиты: Title ≤ 56, Title2 ≤ 30, Text ≤ 81, Href ≤ 1024.
    """
    if not confirm:
        return _dry_run("ads.add[TextAd]", adgroup_id=adgroup_id, title=title, text=text, href=href)
    return await _client(login).add_text_ad(
        adgroup_id=adgroup_id,
        title=title,
        text=text,
        href=href,
        title2=title2,
        display_url_path=display_url_path,
        ad_image_hash=ad_image_hash,
        sitelink_set_id=sitelink_set_id,
        vcard_id=vcard_id,
        turbo_page_id=turbo_page_id,
    )


@mcp.tool()
async def add_ads(
    ads: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Создать объявления любых типов (до 1000 за вызов).

    Каждый элемент: `AdGroupId` + ровно один type-specific блок:
    TextAd, DynamicTextAd, MobileAppAd, TextImageAd, MobileAppImageAd,
    TextAdBuilderAd, MobileAppAdBuilderAd, CpcVideoAdBuilderAd,
    MobileAppCpcVideoAdBuilderAd, CpmBannerAdBuilderAd, CpmVideoAdBuilderAd,
    SmartAdBuilderAd, ShoppingAd, ListingAd.
    """
    if not confirm:
        return _dry_run("ads.add", count=len(ads), sample=ads[:2])
    return await _client(login).add_ads(ads)


@mcp.tool()
async def update_ads(
    ads: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Обновить объявления. Каждый элемент: `Id` + один type-specific блок."""
    if not confirm:
        return _dry_run("ads.update", count=len(ads), sample=ads[:2])
    return await _client(login).update_ads(ads)


@mcp.tool()
async def add_adgroups(
    groups: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Создать группы объявлений (до 1000 за вызов).

    Каждый элемент: `{Name, CampaignId, RegionIds, NegativeKeywords?: {Items}}`.
    Для нестандартных типов — type-specific блок: MobileAppAdGroup,
    DynamicTextAdGroup, CpmBannerAdGroup, SmartAdGroup и т.д.
    """
    if not confirm:
        return _dry_run("adgroups.add", count=len(groups), sample=groups[:2])
    return await _client(login).add_adgroups(groups)


@mcp.tool()
async def update_adgroups(
    groups: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Обновить группы объявлений. Элементы содержат `Id`."""
    if not confirm:
        return _dry_run("adgroups.update", count=len(groups), sample=groups[:2])
    return await _client(login).update_adgroups(groups)


@mcp.tool()
async def delete_adgroups(
    adgroup_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    if not confirm:
        return _dry_run("adgroups.delete", adgroup_ids=adgroup_ids, irreversible=True)
    return await _client(login).delete_adgroups(adgroup_ids)


@mcp.tool()
async def add_keywords(
    keywords: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Добавить ключевые фразы в группу (до 1000 за вызов).

    keywords: [{"AdGroupId": 123, "Keyword": "купить пылесос",
                "Bid": 30000000, "ContextBid": 20000000,
                "StrategyPriority": "NORMAL"}]
    Цены в микро (рубли × 1_000_000), указывать только при ручной стратегии.
    """
    if not confirm:
        return _dry_run(
            "keywords.add",
            count=len(keywords),
            adgroup_ids=sorted({k.get("AdGroupId") for k in keywords if k.get("AdGroupId")}),
            sample=keywords[:3],
        )
    return await _client(login).add_keywords(keywords)


@mcp.tool()
async def update_keywords(
    keywords: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Обновить ключевые фразы.

    keywords: [{"Id": 123, "Keyword": "...", "StrategyPriority": "HIGH",
                "UserParam1": "...", "UserParam2": "..."}]
    """
    if not confirm:
        return _dry_run("keywords.update", count=len(keywords), sample=keywords[:3])
    return await _client(login).update_keywords(keywords)


@mcp.tool()
async def update_campaigns(
    campaigns: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Обновить кампании батчем (campaigns.update).

    Каждый элемент обязан содержать `Id`; остальные поля — `Name`,
    `StartDate`, `EndDate`, `DailyBudget: {Amount, Mode}`, плюс
    type-specific блок (`TextCampaign`, `SmartCampaign`, ...).
    Amount — в микро (рубли × 1_000_000).
    Mode: STANDARD (равномерно) | DISTRIBUTED (ускоренно).
    """
    if not confirm:
        return _dry_run("campaigns.update", count=len(campaigns), sample=campaigns[:3])
    return await _client(login).update_campaigns(campaigns)


@mcp.tool()
async def set_campaign_negative_keywords(
    campaign_id: int,
    negative_keywords: list[str],
    campaign_type: str = "TextCampaign",
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Заменить минус-слова на уровне кампании (полный список заменяет).

    В API минус-слова лежат внутри type-specific блока кампании, поэтому
    нужно знать campaign_type: TextCampaign | DynamicTextCampaign |
    UnifiedCampaign | SmartCampaign | MobileAppCampaign | McBannerCampaign |
    CpmBannerCampaign | CpmVideoCampaign | CpmPriceCampaign | ContentPromotionCampaign.
    """
    if not confirm:
        return _dry_run(
            "campaigns.update[NegativeKeywords]",
            campaign_id=campaign_id,
            campaign_type=campaign_type,
            keywords_count=len(negative_keywords),
        )
    return await _client(login).set_campaign_negative_keywords(
        campaign_id,
        negative_keywords,
        campaign_type=campaign_type,
    )


@mcp.tool()
async def set_adgroup_negative_keywords(
    adgroup_id: int,
    negative_keywords: list[str],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Заменить минус-слова на уровне группы (полный список заменяет)."""
    if not confirm:
        return _dry_run(
            "adgroups.update[NegativeKeywords]",
            adgroup_id=adgroup_id,
            keywords_count=len(negative_keywords),
        )
    return await _client(login).set_adgroup_negative_keywords(
        adgroup_id,
        negative_keywords,
    )


@mcp.tool()
async def set_campaign_daily_budget(
    campaign_id: int,
    amount_rub: float,
    mode: str = "STANDARD",
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Шорткат: сменить дневной бюджет кампании в рублях.

    mode: STANDARD (равномерно) | DISTRIBUTED (ускоренно).
    """
    if not confirm:
        return _dry_run(
            "campaigns.update[DailyBudget]",
            campaign_id=campaign_id,
            amount_rub=amount_rub,
            mode=mode,
        )
    return await _client(login).set_campaign_daily_budget(campaign_id, amount_rub, mode=mode)


@mcp.tool()
async def add_bid_modifiers(
    modifiers: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Добавить корректировки ставок.

    Каждый элемент — `CampaignId` **или** `AdGroupId` + один type-specific блок:
        MobileAdjustment / DesktopAdjustment / DemographicsAdjustment /
        RetargetingAdjustment / RegionalAdjustment / VideoAdjustment /
        IncomeGradeAdjustment.
    Значение BidModifier: 0-1200 (100 = без корректировки, 0 = отключить показы).
    """
    if not confirm:
        return _dry_run("bidmodifiers.add", count=len(modifiers), sample=modifiers[:3])
    return await _client(login).add_bid_modifiers(modifiers)


@mcp.tool()
async def set_bid_modifiers(
    modifiers: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Изменить значение существующих корректировок.

    modifiers: [{"Id": <id>, "BidModifier": <0..1200>}]
    """
    if not confirm:
        return _dry_run("bidmodifiers.set", count=len(modifiers), sample=modifiers[:3])
    return await _client(login).set_bid_modifiers(modifiers)


@mcp.tool()
async def delete_bid_modifiers(
    modifier_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Удалить корректировки по Id."""
    if not confirm:
        return _dry_run("bidmodifiers.delete", modifier_ids=modifier_ids, irreversible=True)
    return await _client(login).delete_bid_modifiers(modifier_ids)


@mcp.tool()
async def add_retargeting_lists(
    lists: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Создать списки ретаргетинга (до 1000 за вызов).

    Каждый элемент:
      {"Name": "...", "Type": "RETARGETING"|"AUDIENCE" (default RETARGETING),
       "Description": "...",
       "Rules": [{"Operator": "ALL"|"ANY"|"NONE",
                  "Arguments": [{"ExternalId": <goal_id>, "MembershipLifeSpan": <1..540>}]}]}

    Для интересов мобильных приложений ExternalId с префиксом 10/20/30
    (short/long/any term).
    """
    if not confirm:
        return _dry_run(
            "retargetinglists.add",
            count=len(lists),
            names=[lst.get("Name") for lst in lists[:5]],
        )
    return await _client(login).add_retargeting_lists(lists)


@mcp.tool()
async def update_retargeting_lists(
    lists: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Обновить списки ретаргетинга.

    lists: [{"Id": ..., "Name"?, "Description"?, "Rules"?}]
    """
    if not confirm:
        return _dry_run("retargetinglists.update", count=len(lists), sample=lists[:3])
    return await _client(login).update_retargeting_lists(lists)


@mcp.tool()
async def delete_retargeting_lists(
    list_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Удалить списки ретаргетинга по Id."""
    if not confirm:
        return _dry_run("retargetinglists.delete", list_ids=list_ids, irreversible=True)
    return await _client(login).delete_retargeting_lists(list_ids)


@mcp.tool()
async def add_audience_targets(
    targets: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Привязать аудитории (списки ретаргетинга или интересы) к группам.

    targets: [{"AdGroupId": ..., "RetargetingListId": ... | "InterestId": ...,
               "ContextBid": <микро>, "StrategyPriority": "LOW|NORMAL|HIGH"}]
    """
    if not confirm:
        return _dry_run("audiencetargets.add", count=len(targets), sample=targets[:3])
    return await _client(login).add_audience_targets(targets)


@mcp.tool()
async def suspend_audience_targets(
    target_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Остановить привязки аудиторий (до 10000 за вызов)."""
    if not confirm:
        return _dry_run("audiencetargets.suspend", target_ids=target_ids)
    return await _client(login).suspend_audience_targets(target_ids)


@mcp.tool()
async def resume_audience_targets(
    target_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Включить привязки аудиторий."""
    if not confirm:
        return _dry_run("audiencetargets.resume", target_ids=target_ids)
    return await _client(login).resume_audience_targets(target_ids)


@mcp.tool()
async def delete_audience_targets(
    target_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Удалить привязки аудиторий."""
    if not confirm:
        return _dry_run("audiencetargets.delete", target_ids=target_ids, irreversible=True)
    return await _client(login).delete_audience_targets(target_ids)


@mcp.tool()
async def set_audience_target_bids(
    bids: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Ставки/приоритет для привязок аудиторий (до 10000 за вызов).

    Элемент: `{Id | AdGroupId | CampaignId, ContextBid, StrategyPriority}`.
    Id/AdGroupId/CampaignId — ровно один в каждом элементе:
      - Id — конкретная привязка;
      - AdGroupId — все привязки в группе;
      - CampaignId — все привязки в кампании.
    ContextBid в микро (рубли × 1_000_000), только для ручных стратегий.
    StrategyPriority (LOW|NORMAL|HIGH) — только для авто-стратегий.
    """
    if not confirm:
        return _dry_run("audiencetargets.setBids", count=len(bids), sample=bids[:3])
    return await _client(login).set_audience_target_bids(bids)


@mcp.tool()
async def toggle_bid_modifiers(
    toggles: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Включить/выключить корректировки по связке (кампания/группа + тип).

    toggles: [{"CampaignId": 1, "Type": "DEMOGRAPHICS_ADJUSTMENT", "Enabled": "NO"}]
    Type: DEMOGRAPHICS_ADJUSTMENT | RETARGETING_ADJUSTMENT | REGIONAL_ADJUSTMENT |
          SERP_LAYOUT_ADJUSTMENT | INCOME_GRADE_ADJUSTMENT.
    Enabled: YES | NO. Можно использовать AdGroupId вместо CampaignId.
    """
    if not confirm:
        return _dry_run("bidmodifiers.toggle", count=len(toggles), sample=toggles[:3])
    return await _client(login).toggle_bid_modifiers(toggles)


@mcp.tool()
async def add_negative_keyword_shared_sets(
    sets: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Создать наборы общих минус-слов (до 30 за вызов).

    sets: [{"Name": "...", "NegativeKeywords": ["фраза1", "фраза2"]}]
    В отличие от update, NegativeKeywords — плоский массив, а не {Items: [...]}.
    """
    if not confirm:
        return _dry_run(
            "negativekeywordsharedsets.add",
            count=len(sets),
            names=[s.get("Name") for s in sets[:5]],
        )
    return await _client(login).add_negative_keyword_shared_sets(sets)


@mcp.tool()
async def delete_negative_keyword_shared_sets(
    set_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Удалить наборы общих минус-слов (до 30 за вызов).

    Не удалит наборы, привязанные к группам — вернёт Warning.
    """
    if not confirm:
        return _dry_run(
            "negativekeywordsharedsets.delete",
            set_ids=set_ids,
            irreversible=True,
        )
    return await _client(login).delete_negative_keyword_shared_sets(set_ids)


@mcp.tool()
async def update_negative_keyword_shared_set(
    set_id: int,
    name: str | None = None,
    negative_keywords: list[str] | None = None,
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Обновить набор общих минус-слов.

    negative_keywords — полный список (заменяет текущий). Для добавления
    сначала вызови list_negative_keyword_shared_sets, объедини списки и
    передай результат.
    """
    if not confirm:
        return _dry_run(
            "negativekeywordsharedsets.update",
            set_id=set_id,
            name=name,
            keywords_count=len(negative_keywords) if negative_keywords else None,
        )
    return await _client(login).update_negative_keyword_shared_set(
        set_id=set_id,
        name=name,
        negative_keywords=negative_keywords,
    )


@mcp.tool()
async def report_custom(
    report_type: str,
    date_from: str,
    date_to: str,
    field_names: list[str],
    login: str | None = None,
) -> list[dict]:
    """Произвольный отчёт v5 с указанием типа и полей."""
    rep = await _reports(login).run(
        report_type=report_type,
        field_names=field_names,
        date_from=date_from,
        date_to=date_to,
    )
    return rep.parse()


# ---- P3: campaigns CRUD, clients, feeds, businesses, leads, dynamic/smart targets ----


@mcp.tool()
async def add_campaigns(
    campaigns: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Создать кампании (не более 10 за вызов).

    Элементы: {Name, StartDate, EndDate?, DailyBudget?: {Amount, Mode},
               <TypeBlock>: {BiddingStrategy, ...}}.
    TypeBlock: TextCampaign | DynamicTextCampaign | MobileAppCampaign |
               CpmBannerCampaign | CpmVideoCampaign | SmartCampaign |
               UnifiedCampaign | CpmPriceCampaign | ContentPromotionCampaign |
               McBannerCampaign.
    Цены — в микро. BiddingStrategy — сверяйся с доками.
    """
    if not confirm:
        return _dry_run("campaigns.add", count=len(campaigns), sample=campaigns[:1])
    return await _client(login).add_campaigns(campaigns)


@mcp.tool()
async def delete_campaigns(
    campaign_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Удалить кампании безвозвратно (должны быть archived)."""
    if not confirm:
        return _dry_run("campaigns.delete", campaign_ids=campaign_ids, irreversible=True)
    return await _client(login).delete_campaigns(campaign_ids)


@mcp.tool()
async def update_client(
    fields: dict,
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Изменить настройки клиента (НДС, уведомления, контакты)."""
    if not confirm:
        return _dry_run("clients.update", fields=fields)
    return await _client(login).update_client(fields)


@mcp.tool()
async def update_agency_client(
    fields: dict,
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Изменить настройки агентского доступа к клиенту."""
    if not confirm:
        return _dry_run("agencyclients.update", fields=fields)
    return await _client(login).update_agency_client(fields)


@mcp.tool()
async def list_feeds(login: str | None = None) -> list[dict]:
    """Товарные фиды клиента."""
    return await _client(login).list_feeds()


@mcp.tool()
async def add_feeds(
    feeds: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Создать фиды (через URL или FileContent)."""
    if not confirm:
        return _dry_run("feeds.add", count=len(feeds), sample=feeds[:1])
    return await _client(login).add_feeds(feeds)


@mcp.tool()
async def update_feeds(
    feeds: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    if not confirm:
        return _dry_run("feeds.update", count=len(feeds), sample=feeds[:1])
    return await _client(login).update_feeds(feeds)


@mcp.tool()
async def delete_feeds(
    feed_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    if not confirm:
        return _dry_run("feeds.delete", feed_ids=feed_ids, irreversible=True)
    return await _client(login).delete_feeds(feed_ids)


@mcp.tool()
async def list_businesses(login: str | None = None) -> list[dict]:
    """Бизнес-данные (Яндекс.Бизнес) клиента."""
    return await _client(login).list_businesses()


@mcp.tool()
async def list_leads(
    campaign_ids: list[int] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    login: str | None = None,
) -> list[dict]:
    """Лиды с lead-форм и Турбо-страниц (за последние 30 дней по умолчанию)."""
    return await _client(login).list_leads(
        campaign_ids=campaign_ids,
        date_from=date_from,
        date_to=date_to,
    )


@mcp.tool()
async def list_dynamic_text_ad_targets(
    adgroup_ids: list[int] | None = None,
    campaign_ids: list[int] | None = None,
    login: str | None = None,
) -> list[dict]:
    """Условия таргетинга для динамических объявлений."""
    return await _client(login).list_dynamic_text_ad_targets(
        adgroup_ids=adgroup_ids,
        campaign_ids=campaign_ids,
    )


@mcp.tool()
async def add_dynamic_text_ad_targets(
    targets: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Добавить условия таргетинга для DynamicTextAd.

    targets: [{"AdGroupId": ..., "Name": ..., "Condition": {...}}].
    """
    if not confirm:
        return _dry_run("dynamictextadtargets.add", count=len(targets), sample=targets[:1])
    return await _client(login).add_dynamic_text_ad_targets(targets)


@mcp.tool()
async def suspend_dynamic_text_ad_targets(
    target_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    if not confirm:
        return _dry_run("dynamictextadtargets.suspend", target_ids=target_ids)
    return await _client(login).suspend_dynamic_text_ad_targets(target_ids)


@mcp.tool()
async def resume_dynamic_text_ad_targets(
    target_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    if not confirm:
        return _dry_run("dynamictextadtargets.resume", target_ids=target_ids)
    return await _client(login).resume_dynamic_text_ad_targets(target_ids)


@mcp.tool()
async def delete_dynamic_text_ad_targets(
    target_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    if not confirm:
        return _dry_run("dynamictextadtargets.delete", target_ids=target_ids, irreversible=True)
    return await _client(login).delete_dynamic_text_ad_targets(target_ids)


@mcp.tool()
async def set_dynamic_text_ad_target_bids(
    bids: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """bids: [{Id, Bid (микро), ContextBid, StrategyPriority}]"""
    if not confirm:
        return _dry_run("dynamictextadtargets.setBids", count=len(bids), sample=bids[:3])
    return await _client(login).set_dynamic_text_ad_target_bids(bids)


@mcp.tool()
async def list_smart_ad_targets(
    adgroup_ids: list[int] | None = None,
    campaign_ids: list[int] | None = None,
    login: str | None = None,
) -> list[dict]:
    """Условия таргетинга для смарт-баннеров."""
    return await _client(login).list_smart_ad_targets(
        adgroup_ids=adgroup_ids,
        campaign_ids=campaign_ids,
    )


@mcp.tool()
async def add_smart_ad_targets(
    targets: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    if not confirm:
        return _dry_run("smartadtargets.add", count=len(targets), sample=targets[:1])
    return await _client(login).add_smart_ad_targets(targets)


@mcp.tool()
async def suspend_smart_ad_targets(
    target_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    if not confirm:
        return _dry_run("smartadtargets.suspend", target_ids=target_ids)
    return await _client(login).suspend_smart_ad_targets(target_ids)


@mcp.tool()
async def resume_smart_ad_targets(
    target_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    if not confirm:
        return _dry_run("smartadtargets.resume", target_ids=target_ids)
    return await _client(login).resume_smart_ad_targets(target_ids)


@mcp.tool()
async def delete_smart_ad_targets(
    target_ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    if not confirm:
        return _dry_run("smartadtargets.delete", target_ids=target_ids, irreversible=True)
    return await _client(login).delete_smart_ad_targets(target_ids)


@mcp.tool()
async def set_smart_ad_target_bids(
    bids: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """bids: [{Id, Bid (микро), StrategyPriority}]"""
    if not confirm:
        return _dry_run("smartadtargets.setBids", count=len(bids), sample=bids[:3])
    return await _client(login).set_smart_ad_target_bids(bids)


# ---- P2: расширения объявлений ----


@mcp.tool()
async def list_sitelinks(login: str | None = None) -> list[dict]:
    """Все наборы быстрых ссылок клиента."""
    return await _client(login).list_sitelinks()


@mcp.tool()
async def add_sitelinks(
    sitelinks: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Создать набор быстрых ссылок (1-8 ссылок в наборе).

    sitelinks — список объектов {"Title", "Href" | "TurboPageId", "Description"?}.
    Title ≤ 30 симв., Description ≤ 60 симв. Редактирование невозможно —
    создай новый набор и переподключи к объявлениям.
    """
    if not confirm:
        return _dry_run("sitelinks.add", count=len(sitelinks), sample=sitelinks[:2])
    return await _client(login).add_sitelinks([{"Sitelinks": sitelinks}])


@mcp.tool()
async def delete_sitelinks(
    ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Удалить наборы быстрых ссылок. Нельзя удалить привязанные к объявлениям."""
    if not confirm:
        return _dry_run("sitelinks.delete", ids=ids, irreversible=True)
    return await _client(login).delete_sitelinks(ids)


@mcp.tool()
async def list_vcards(
    campaign_ids: list[int] | None = None,
    login: str | None = None,
) -> list[dict]:
    """Визитки клиента."""
    return await _client(login).list_vcards(campaign_ids=campaign_ids)


@mcp.tool()
async def add_vcards(
    vcards: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Создать визитки.

    Обязательные поля: CampaignId, Country, City, CompanyName, WorkTime,
    Phone: {CountryCode, CityCode, PhoneNumber}.
    """
    if not confirm:
        return _dry_run("vcards.add", count=len(vcards), sample=vcards[:2])
    return await _client(login).add_vcards(vcards)


@mcp.tool()
async def delete_vcards(
    ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    if not confirm:
        return _dry_run("vcards.delete", ids=ids, irreversible=True)
    return await _client(login).delete_vcards(ids)


@mcp.tool()
async def list_ad_extensions(
    states: list[str] | None = None,
    statuses: list[str] | None = None,
    login: str | None = None,
) -> list[dict]:
    """Уточнения (callouts)."""
    return await _client(login).list_ad_extensions(states=states, statuses=statuses)


@mcp.tool()
async def add_ad_extensions(
    callout_texts: list[str],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Создать уточнения-callouts (до 1000 за вызов).

    Каждый текст ≤ 25 символов. Дубли вернут Warning.
    """
    items = [{"Callout": {"CalloutText": t}} for t in callout_texts]
    if not confirm:
        return _dry_run("adextensions.add", count=len(items), texts=callout_texts[:5])
    return await _client(login).add_ad_extensions(items)


@mcp.tool()
async def moderate_ad_extensions(
    ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Отправить уточнения на модерацию."""
    if not confirm:
        return _dry_run("adextensions.moderate", ids=ids)
    return await _client(login).moderate_ad_extensions(ids)


@mcp.tool()
async def delete_ad_extensions(
    ids: list[int],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    if not confirm:
        return _dry_run("adextensions.delete", ids=ids, irreversible=True)
    return await _client(login).delete_ad_extensions(ids)


@mcp.tool()
async def list_ad_images(
    associated: str | None = None,
    login: str | None = None,
) -> list[dict]:
    """Изображения клиента. associated: YES (привязанные) | NO (свободные)."""
    return await _client(login).list_ad_images(associated=associated)


@mcp.tool()
async def add_ad_images_from_file(
    file_paths: list[str],
    image_type: str = "AUTO",
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Загрузить изображения с диска (до 100 за вызов, рекомендуется ≤3).

    Ответ содержит AdImageHash для каждой картинки — используй хэш при
    создании/обновлении объявлений. image_type: REGULAR | WIDE | FIXED_IMAGE | AUTO.
    """
    import base64

    if not confirm:
        return _dry_run("adimages.add", file_paths=file_paths, image_type=image_type)
    items = []
    for p in file_paths:
        path = Path(p)
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        items.append({"ImageData": data, "Name": path.name, "Type": image_type})
    return await _client(login).add_ad_images(items)


@mcp.tool()
async def delete_ad_images(
    hashes: list[str],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Удалить изображения по хэшам. Нельзя удалить привязанные к объявлениям."""
    if not confirm:
        return _dry_run("adimages.delete", hashes=hashes, irreversible=True)
    return await _client(login).delete_ad_images(hashes)


@mcp.tool()
async def list_creatives(
    types: list[str] | None = None,
    login: str | None = None,
) -> list[dict]:
    """Креативы: IMAGE_CREATIVE, HTML5_CREATIVE, VIDEO_EXTENSION_CREATIVE,
    CPC_VIDEO_CREATIVE, CPM_VIDEO_CREATIVE, SMART_CREATIVE.
    """
    return await _client(login).list_creatives(types=types)


@mcp.tool()
async def add_creatives(
    creatives: list[dict],
    login: str | None = None,
    confirm: bool = False,
) -> dict:
    """Создать креативы (до 10 за вызов).

    API поддерживает только VideoExtensionCreative:
        `[{"VideoExtensionCreative": {"VideoId": "<id>"}}]`
    VideoId получается через AdVideos (загрузка видео) — отдельный сервис.
    """
    if not confirm:
        return _dry_run("creatives.add", count=len(creatives), sample=creatives[:1])
    return await _client(login).add_creatives(creatives)


@mcp.tool()
async def list_turbopages(login: str | None = None) -> list[dict]:
    """Турбо-страницы клиента."""
    return await _client(login).list_turbopages()


@mcp.tool()
async def get_dictionaries(
    dictionary_names: list[str],
    login: str | None = None,
) -> dict:
    """Справочники API: валюты, регионы, таймзоны, категории.

    Допустимые имена: Currencies, TimeZones, GeoRegions, AdCategories,
    OperationSystemVersions, ProductivityIndicators, SupplyChainStages,
    AutoBusinesses, Constants, LegalPersonDocumentTypes, SubjectSchema.
    """
    return await _client(login).get_dictionaries(dictionary_names)


def serve() -> None:
    logger.info("MCP rb-yandex-direct starting (sandbox={})", os.getenv("YANDEX_DIRECT_SANDBOX"))
    mcp.run()


if __name__ == "__main__":
    serve()
