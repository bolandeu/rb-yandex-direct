"""DirectClient — обёртка над Яндекс.Директ API v5.

Формат v5: POST JSON {"method": "...", "params": {...}} на
https://api.direct.yandex.com/json/v5/<service>. Ответ всегда 200 — ошибки
приходят в теле под ключом "error" (код 1002 = неверный токен).

Пагинация: SelectionCriteria + Page {Limit, Offset}. Если в ответе есть
LimitedBy — это offset следующей порции.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from ..core.ads import (
    AD_FIELDS,
    AD_TYPE_FIELDS,
    ADGROUP_FIELDS,
    ADGROUP_TYPE_FIELDS,
    validate_adgroups,
    validate_ads,
)
from ..core.errors import DirectAPIError, InvalidArguments
from ..core.version import DEV_VERSION, cli_name, installed_version
from .base import Health, Provider, Quota

log = logging.getLogger(__name__)

PROD_BASE = "https://api.direct.yandex.com/json/v5"
SANDBOX_BASE = "https://api-sandbox.direct.yandex.com/json/v5"


# Разумные дефолты полей для быстрой отладки в CLI.
DEFAULT_CAMPAIGN_FIELDS = [
    "Id",
    "Name",
    "State",
    "Status",
    "Type",
    "StartDate",
    "EndDate",
    "DailyBudget",
    "Currency",
    "ClientInfo",
]
DEFAULT_ADGROUP_FIELDS = [
    "Id",
    "Name",
    "CampaignId",
    "Type",
    "Status",
    "RegionIds",
    "TrackingParams",
]
DEFAULT_AD_FIELDS = [
    "Id",
    "AdGroupId",
    "CampaignId",
    "Type",
    "State",
    "Status",
    "AdCategories",
]
DEFAULT_AD_TEXT_FIELDS = ["Title", "Title2", "Text", "Href", "Mobile", "DisplayUrlPath"]
DEFAULT_KEYWORD_FIELDS = [
    "Id",
    "Keyword",
    "AdGroupId",
    "CampaignId",
    "State",
    "Status",
    "ServingStatus",
    "Bid",
    "ContextBid",
    "StrategyPriority",
]
# KeywordBids.get: общие поля — FieldNames, вложенные Search/Network — свои *FieldNames.
DEFAULT_KEYWORD_BID_FIELDS = ["KeywordId", "AdGroupId", "CampaignId", "ServingStatus", "StrategyPriority"]
DEFAULT_KEYWORD_BID_SEARCH_FIELDS = ["Bid", "AutotargetingSearchBidIsAuto", "AuctionBids"]
DEFAULT_KEYWORD_BID_NETWORK_FIELDS = ["Bid", "Coverage"]
# Bids.get (классический сервис ставок): цены позиций и прогноз охвата — в самих полях.
DEFAULT_BID_FIELDS = [
    "KeywordId",
    "AdGroupId",
    "CampaignId",
    "Bid",
    "ContextBid",
    "StrategyPriority",
    "ServingStatus",
    "MinSearchPrice",
    "CurrentSearchPrice",
]
# BidModifiers.get: у каждого типа корректировки свой *FieldNames (без них блок не приходит).
BID_MODIFIER_SUBFIELDS = {
    "MobileAdjustment": ["BidModifier", "OperatingSystemType"],
    "DesktopAdjustment": ["BidModifier"],
    "SmartTvAdjustment": ["BidModifier"],
    "TabletAdjustment": ["BidModifier", "OperatingSystemType"],
    "DesktopOnlyAdjustment": ["BidModifier"],
    "DemographicsAdjustment": ["Gender", "Age", "BidModifier", "Enabled"],
    "RetargetingAdjustment": ["RetargetingConditionId", "BidModifier", "Accessible", "Enabled"],
    "RegionalAdjustment": ["RegionId", "BidModifier", "Enabled"],
    "VideoAdjustment": ["BidModifier"],
    "SmartAdAdjustment": ["BidModifier"],
    "SerpLayoutAdjustment": ["SerpLayout", "BidModifier", "Enabled"],
    "IncomeGradeAdjustment": ["Grade", "BidModifier", "Enabled"],
    "AdGroupAdjustment": ["BidModifier"],
}


# Ответы «не сейчас», а не «нет»: повторяем с экспоненциальной паузой.
# 52 — сервер авторизации временно недоступен, 506 — превышен лимит соединений,
# 1000 — сервис временно недоступен, 1001 — внутренняя ошибка сервера.
RETRY_API_CODES = frozenset({52, 506, 1000, 1001})
RETRY_HTTP = frozenset({429, 502, 503, 504})


class DirectClient:
    """Клиент Яндекс.Директ API v5.

    Args:
        token: OAuth-токен (без префикса Bearer).
        client_login: логин рекламодателя для агентского доступа.
            Для своего аккаунта можно оставить None.
        sandbox: переключатель на тестовую песочницу.
        use_operator_units: для агентств — расход баллов API идёт со счёта
            оператора, а не клиента. Включается отдельным заголовком.
        language: Accept-Language. По умолчанию ru.
        timeout: таймаут httpx.
        transport: для тестов (`httpx.MockTransport`); в рабочем коде None.

    Сеть и временные сбои (RETRY_API_CODES, HTTP 429/5xx, таймауты) повторяются
    `retries` раз; дальше — DirectAPIError (PROVIDER_ERROR, exit 5). Ошибки
    учётных данных — DirectAPIError с кодом AUTH_REQUIRED (exit 3).
    """

    retries: int = 2
    backoff: float = 1.0

    def __init__(
        self,
        token: str,
        client_login: str | None = None,
        sandbox: bool = False,
        use_operator_units: bool = False,
        language: str = "ru",
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.token = token
        self.client_login = client_login
        self.base_url = SANDBOX_BASE if sandbox else PROD_BASE
        self.sandbox = sandbox
        self.use_operator_units = use_operator_units
        self.language = language
        self.timeout = timeout
        self.transport = transport
        self.last_units: str | None = None
        self.last_request_id: str | None = None

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.token}",
            "Accept-Language": self.language,
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": f"{cli_name()}/{installed_version() or DEV_VERSION}",
        }
        if self.client_login:
            h["Client-Login"] = self.client_login
        if self.use_operator_units:
            h["Use-Operator-Units"] = "true"
        if extra:
            h.update(extra)
        return h

    async def call(
        self,
        service: str,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Вызвать метод сервиса v5. Возвращает содержимое `result`."""
        url = f"{self.base_url}/{service}"
        body = {"method": method, "params": params or {}}
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        attempt = 0
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            while True:
                try:
                    resp = await client.post(url, content=payload, headers=self._headers(extra_headers))
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    if attempt < self.retries:
                        attempt += 1
                        await asyncio.sleep(self.backoff * 2 ** (attempt - 1))
                        continue
                    raise DirectAPIError(0, "Сеть", f"{type(exc).__name__}: {exc}") from exc
                self.last_units = resp.headers.get("Units")
                self.last_request_id = resp.headers.get("RequestId")
                data = self._parse(resp)
                err = data.get("error")
                code = int(err.get("error_code", 0)) if err else resp.status_code
                if (code in RETRY_API_CODES or resp.status_code in RETRY_HTTP) and attempt < self.retries:
                    attempt += 1
                    await asyncio.sleep(self.backoff * 2 ** (attempt - 1))
                    continue
                break
        if resp.status_code >= 500 and "error" not in data:
            raise DirectAPIError(resp.status_code, "Server error", resp.text[:500], self.last_request_id)
        if "error" in data:
            err = data["error"]
            raise DirectAPIError(
                error_code=int(err.get("error_code", 0)),
                error_string=err.get("error_string", ""),
                error_detail=err.get("error_detail", ""),
                request_id=self.last_request_id,
            )
        if self.last_units:
            log.debug("%s.%s Units: %s RequestId: %s", service, method, self.last_units, self.last_request_id)
        return data.get("result", {})

    def _parse(self, resp: httpx.Response) -> dict[str, Any]:
        try:
            data = resp.json()
        except ValueError as exc:
            if resp.status_code >= 500:
                return {}
            raise DirectAPIError(resp.status_code, "Invalid JSON", str(exc), self.last_request_id) from exc
        return data if isinstance(data, dict) else {}

    async def _paginated_get(
        self,
        service: str,
        result_key: str,
        params: dict[str, Any],
        page_limit: int = 500,
    ) -> list[dict]:
        """Общий хелпер пагинации через LimitedBy."""
        params = dict(params)
        params.setdefault("Page", {"Limit": page_limit})
        out: list[dict] = []
        while True:
            result = await self.call(service, "get", params)
            out.extend(result.get(result_key, []))
            limited_by = result.get("LimitedBy")
            if not limited_by:
                return out
            params["Page"] = {"Limit": page_limit, "Offset": int(limited_by)}

    # --- Клиенты и агентство ---

    async def list_clients(self, field_names: list[str] | None = None) -> list[dict]:
        """Для агентств — список клиентов; для обычного аккаунта — запись о себе."""
        fields = field_names or ["Login", "ClientInfo", "AccountQuality", "Currency"]
        try:
            result = await self.call(
                "agencyclients",
                "get",
                {
                    "SelectionCriteria": {},
                    "FieldNames": fields,
                },
            )
            return result.get("Clients", [])
        except DirectAPIError as e:
            if e.error_code == 8100:
                result = await self.call("clients", "get", {"FieldNames": fields})
                return result.get("Clients", [])
            raise

    async def get_clients_units(self, logins: list[str] | None = None) -> list[dict]:
        """Остаток баллов API по клиентам (заменяет устаревшее get_balance)."""
        params: dict[str, Any] = {}
        if logins:
            params["SelectionCriteria"] = {"Logins": logins}
        result = await self.call("clients", "getClientsUnits", params)
        return result.get("ClientsUnits", [])

    # Псевдоним для совместимости со старым кодом
    get_balance = get_clients_units

    # --- Кампании ---

    async def list_campaigns(
        self,
        field_names: list[str] | None = None,
        selection_criteria: dict | None = None,
        page_limit: int = 500,
    ) -> list[dict]:
        return await self._paginated_get(
            "campaigns",
            "Campaigns",
            {
                "SelectionCriteria": selection_criteria or {},
                "FieldNames": field_names or DEFAULT_CAMPAIGN_FIELDS,
            },
            page_limit=page_limit,
        )

    async def get_campaign(self, campaign_id: int, field_names: list[str] | None = None) -> dict | None:
        result = await self.call(
            "campaigns",
            "get",
            {
                "SelectionCriteria": {"Ids": [campaign_id]},
                "FieldNames": field_names or DEFAULT_CAMPAIGN_FIELDS,
            },
        )
        items = result.get("Campaigns", [])
        return items[0] if items else None

    # --- Группы объявлений ---

    async def list_adgroups(
        self,
        campaign_ids: list[int] | None = None,
        adgroup_ids: list[int] | None = None,
        types: list[str] | None = None,
        field_names: list[str] | None = None,
        page_limit: int = 1000,
        *,
        statuses: list[str] | None = None,
        serving_statuses: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> list[dict]:
        """Группы объявлений; API требует CampaignIds или Ids."""
        criteria: dict[str, Any] = {}
        if campaign_ids:
            criteria["CampaignIds"] = campaign_ids
        if adgroup_ids:
            criteria["Ids"] = adgroup_ids
        if types:
            criteria["Types"] = types
        if statuses:
            criteria["Statuses"] = statuses
        if serving_statuses:
            criteria["ServingStatuses"] = serving_statuses
        if tags:
            criteria["Tags"] = tags
        return await self._paginated_get(
            "adgroups",
            "AdGroups",
            {
                "SelectionCriteria": criteria,
                "FieldNames": field_names or DEFAULT_ADGROUP_FIELDS,
            },
            page_limit=page_limit,
        )

    # --- Объявления ---

    async def list_ads(
        self,
        campaign_ids: list[int] | None = None,
        adgroup_ids: list[int] | None = None,
        ad_ids: list[int] | None = None,
        states: list[str] | None = None,
        statuses: list[str] | None = None,
        types: list[str] | None = None,
        field_names: list[str] | None = None,
        text_ad_field_names: list[str] | None = None,
        extra_type_fields: dict[str, list[str]] | None = None,
        page_limit: int = 1000,
        *,
        extra_criteria: dict[str, Any] | None = None,
    ) -> list[dict]:
        """Список объявлений.

        Args:
            statuses: фильтр по статусу модерации: ACCEPTED, DRAFT,
                MODERATION, PREACCEPTED, REJECTED, UNKNOWN.
            text_ad_field_names: доп. поля для TextAd (Title, Text, Href...).
            extra_type_fields: словарь `{"MobileAppAdFieldNames": [...],
                "DynamicTextAdFieldNames": [...]}` для других типов.
        """
        criteria: dict[str, Any] = {}
        if ad_ids:
            criteria["Ids"] = ad_ids
        if campaign_ids:
            criteria["CampaignIds"] = campaign_ids
        if adgroup_ids:
            criteria["AdGroupIds"] = adgroup_ids
        if states:
            criteria["States"] = states
        if statuses:
            criteria["Statuses"] = statuses
        if types:
            criteria["Types"] = types
        if extra_criteria:  # Mobile, VCardIds, SitelinkSetIds, AdImageHashes, AdExtensionIds, …
            criteria.update(extra_criteria)

        params: dict[str, Any] = {
            "SelectionCriteria": criteria,
            "FieldNames": field_names or DEFAULT_AD_FIELDS,
        }
        if text_ad_field_names is not False:  # None → дефолты, [] → не запрашивать
            params["TextAdFieldNames"] = text_ad_field_names or DEFAULT_AD_TEXT_FIELDS
        if extra_type_fields:
            params.update(extra_type_fields)

        return await self._paginated_get("ads", "Ads", params, page_limit=page_limit)

    async def get_ad(self, ad_id: int) -> dict | None:
        """Одно объявление со всеми полями всех типов."""
        result = await self.call(
            "ads", "get", {"SelectionCriteria": {"Ids": [ad_id]}, "FieldNames": AD_FIELDS, **AD_TYPE_FIELDS}
        )
        items = result.get("Ads", [])
        return items[0] if items else None

    async def list_ads_in_moderation(
        self,
        campaign_ids: list[int] | None = None,
    ) -> list[dict]:
        """Шорткат: объявления, ждущие модерации или отклонённые."""
        return await self.list_ads(
            campaign_ids=campaign_ids,
            statuses=["DRAFT", "MODERATION", "PREACCEPTED", "REJECTED"],
        )

    # --- Ключевые фразы ---

    async def list_keywords(
        self,
        adgroup_ids: list[int] | None = None,
        campaign_ids: list[int] | None = None,
        keyword_ids: list[int] | None = None,
        states: list[str] | None = None,
        field_names: list[str] | None = None,
        page_limit: int = 10000,
        *,
        statuses: list[str] | None = None,
        serving_statuses: list[str] | None = None,
        modified_since: str | None = None,
    ) -> list[dict]:
        """Ключевые фразы (keywords.get) по Id, группам, кампаниям, состоянию, статусу, показам."""
        criteria: dict[str, Any] = {}
        if keyword_ids:
            criteria["Ids"] = keyword_ids
        if adgroup_ids:
            criteria["AdGroupIds"] = adgroup_ids
        if campaign_ids:
            criteria["CampaignIds"] = campaign_ids
        if states:
            criteria["States"] = states
        if statuses:
            criteria["Statuses"] = statuses
        if serving_statuses:
            criteria["ServingStatuses"] = serving_statuses
        if modified_since:
            criteria["ModifiedSince"] = modified_since
        return await self._paginated_get(
            "keywords",
            "Keywords",
            {
                "SelectionCriteria": criteria,
                "FieldNames": field_names or DEFAULT_KEYWORD_FIELDS,
            },
            page_limit=page_limit,
        )

    # --- Ставки ключевых фраз ---

    async def get_keyword_bids(
        self,
        keyword_ids: list[int] | None = None,
        adgroup_ids: list[int] | None = None,
        campaign_ids: list[int] | None = None,
        field_names: list[str] | None = None,
        page_limit: int = 10000,
        *,
        serving_statuses: list[str] | None = None,
        search_field_names: list[str] | None = None,
        network_field_names: list[str] | None = None,
    ) -> list[dict]:
        """Ставки и торги (keywordbids.get): нужен хотя бы один из keyword/adgroup/campaign."""
        criteria = _bids_criteria(keyword_ids, adgroup_ids, campaign_ids, serving_statuses)
        return await self._paginated_get(
            "keywordbids",
            "KeywordBids",
            {
                "SelectionCriteria": criteria,
                "FieldNames": field_names or DEFAULT_KEYWORD_BID_FIELDS,
                "SearchFieldNames": search_field_names or DEFAULT_KEYWORD_BID_SEARCH_FIELDS,
                "NetworkFieldNames": network_field_names or DEFAULT_KEYWORD_BID_NETWORK_FIELDS,
            },
            page_limit=page_limit,
        )

    async def list_bids(
        self,
        keyword_ids: list[int] | None = None,
        adgroup_ids: list[int] | None = None,
        campaign_ids: list[int] | None = None,
        field_names: list[str] | None = None,
        *,
        serving_statuses: list[str] | None = None,
    ) -> list[dict]:
        """Классический сервис Bids (bids.get): ставки, цены позиций, прогноз охвата в сетях."""
        criteria = _bids_criteria(keyword_ids, adgroup_ids, campaign_ids, serving_statuses)
        return await self._paginated_get(
            "bids",
            "Bids",
            {"SelectionCriteria": criteria, "FieldNames": field_names or DEFAULT_BID_FIELDS},
            page_limit=10000,
        )

    # --- Минус-слова общие ---

    async def list_negative_keyword_shared_sets(
        self,
        ids: list[int] | None = None,
        field_names: list[str] | None = None,
    ) -> list[dict]:
        criteria: dict[str, Any] = {}
        if ids:
            criteria["Ids"] = ids
        return await self._paginated_get(
            "negativekeywordsharedsets",
            "NegativeKeywordSharedSets",
            {
                "SelectionCriteria": criteria,
                "FieldNames": field_names or ["Id", "Name", "NegativeKeywords"],
            },
            page_limit=1000,
        )

    # --- Изменения ---

    async def check_dictionaries(self, timestamp: str) -> dict:
        """Проверить timestamp актуальности справочников."""
        return await self.call(
            "changes",
            "checkDictionaries",
            {
                "FieldNames": ["Timestamp"],
                "Timestamp": timestamp,
            },
        )

    async def check_campaign_changes(
        self,
        timestamp: str,
        campaign_ids: list[int] | None = None,
        adgroup_ids: list[int] | None = None,
        ad_ids: list[int] | None = None,
    ) -> dict:
        """`changes.checkCampaigns` — что изменилось с момента timestamp."""
        params: dict[str, Any] = {
            "FieldNames": ["CampaignIds", "ModifiedCampaignIds", "Timestamp"],
            "Timestamp": timestamp,
        }
        if campaign_ids:
            params["CampaignIds"] = campaign_ids
        if adgroup_ids:
            params["AdGroupIds"] = adgroup_ids
        if ad_ids:
            params["AdIds"] = ad_ids
        return await self.call("changes", "checkCampaigns", params)

    async def check_changes(
        self,
        timestamp: str,
        campaign_ids: list[int] | None = None,
        adgroup_ids: list[int] | None = None,
        ad_ids: list[int] | None = None,
        field_names: list[str] | None = None,
    ) -> dict:
        """`changes.check` — массовая проверка для инкрементального синка."""
        params: dict[str, Any] = {
            "FieldNames": field_names
            or [
                "CampaignIds",
                "AdGroupIds",
                "AdIds",
                "Timestamp",
                "ModifiedCampaignIds",
                "ModifiedAdGroupIds",
                "ModifiedAdIds",
                "NotFoundCampaignIds",
                "NotFoundAdGroupIds",
                "NotFoundAdIds",
            ],
            "Timestamp": timestamp,
        }
        if campaign_ids:
            params["CampaignIds"] = campaign_ids
        if adgroup_ids:
            params["AdGroupIds"] = adgroup_ids
        if ad_ids:
            params["AdIds"] = ad_ids
        return await self.call("changes", "check", params)

    # --- Write: управление активностью ---

    async def suspend_campaigns(self, ids: list[int]) -> dict:
        """Приостановить кампании (до 1000 за вызов). Возвращает SuspendResults."""
        return await self.call("campaigns", "suspend", {"SelectionCriteria": {"Ids": ids}})

    async def resume_campaigns(self, ids: list[int]) -> dict:
        return await self.call("campaigns", "resume", {"SelectionCriteria": {"Ids": ids}})

    async def archive_campaigns(self, ids: list[int]) -> dict:
        return await self.call("campaigns", "archive", {"SelectionCriteria": {"Ids": ids}})

    async def unarchive_campaigns(self, ids: list[int]) -> dict:
        return await self.call("campaigns", "unarchive", {"SelectionCriteria": {"Ids": ids}})

    async def suspend_keywords(self, ids: list[int]) -> dict:
        return await self.call("keywords", "suspend", {"SelectionCriteria": {"Ids": ids}})

    async def resume_keywords(self, ids: list[int]) -> dict:
        return await self.call("keywords", "resume", {"SelectionCriteria": {"Ids": ids}})

    async def delete_keywords(self, ids: list[int]) -> dict:
        return await self.call("keywords", "delete", {"SelectionCriteria": {"Ids": ids}})

    async def add_keywords(self, keywords: list[dict]) -> dict:
        """Добавить ключевые фразы (batch до 1000).

        Каждый элемент:
            {"AdGroupId": 123, "Keyword": "купить пылесос",
             "Bid": 30_000_000, "ContextBid": 20_000_000,
             "StrategyPriority": "NORMAL", "UserParam1": "...", "UserParam2": "..."}
        Цены в микро (рубли × 1_000_000), задаются только при ручной стратегии.
        """
        if not keywords:
            raise ValueError("keywords пустой")
        if len(keywords) > 1000:
            raise ValueError("keywords.add — не более 1000 за вызов")
        return await self.call("keywords", "add", {"Keywords": keywords})

    async def update_keywords(self, keywords: list[dict]) -> dict:
        """Обновить ключевые фразы.

        Элемент: {"Id": 123, "Keyword": "...", "StrategyPriority": "...",
                  "UserParam1": "...", "UserParam2": "..."}
        """
        if not keywords:
            raise ValueError("keywords пустой")
        return await self.call("keywords", "update", {"Keywords": keywords})

    # --- Write: кампании ---

    async def update_campaigns(self, campaigns: list[dict]) -> dict:
        """Обновить кампании батчем.

        Каждый элемент должен содержать `Id`; остальные поля — как в
        `campaigns.update` API: `Name`, `StartDate`, `EndDate`,
        `DailyBudget: {Amount, Mode}`, плюс type-specific блок
        (`TextCampaign`, `SmartCampaign`, ...). Amount — в микро.
        """
        if not campaigns:
            raise ValueError("campaigns пустой")
        return await self.call("campaigns", "update", {"Campaigns": campaigns})

    async def set_campaign_negative_keywords(
        self,
        campaign_id: int,
        negative_keywords: list[str],
        campaign_type: str = "TextCampaign",
    ) -> dict:
        """Заменить список минус-слов на уровне кампании.

        Минус-слова в v5 лежат **внутри type-specific блока**:
            `{"Id": ..., "TextCampaign": {"NegativeKeywords": {"Items": [...]}}}`.
        campaign_type — ключ блока: `TextCampaign`, `DynamicTextCampaign`,
        `UnifiedCampaign`, `SmartCampaign`, `MobileAppCampaign`,
        `McBannerCampaign`, `CpmBannerCampaign`, `CpmVideoCampaign`,
        `CpmPriceCampaign`, `ContentPromotionCampaign`.
        Передаёт полный список — заменяет существующий.
        """
        if campaign_type not in self._CAMPAIGN_TYPE_KEYS:
            raise ValueError(
                f"неизвестный campaign_type={campaign_type!r}, ожидается один из: {sorted(self._CAMPAIGN_TYPE_KEYS)}"
            )
        return await self.update_campaigns(
            [
                {
                    "Id": campaign_id,
                    campaign_type: {"NegativeKeywords": {"Items": negative_keywords}},
                }
            ]
        )

    async def set_adgroup_negative_keywords(
        self,
        adgroup_id: int,
        negative_keywords: list[str],
    ) -> dict:
        """Заменить минус-слова на уровне группы.

        Передаётся полный список (заменяет текущие, не добавляет).
        """
        return await self.update_adgroups(
            [
                {
                    "Id": adgroup_id,
                    "NegativeKeywords": {"Items": negative_keywords},
                }
            ]
        )

    async def set_campaign_daily_budget(
        self,
        campaign_id: int,
        amount_rub: float,
        mode: str = "STANDARD",
    ) -> dict:
        """Шорткат: поменять дневной бюджет в рублях.

        mode: STANDARD (равномерно) или DISTRIBUTED (ускоренно).
        Amount в микро — `amount_rub × 1_000_000`. Нужны права «менять бюджет».
        """
        return await self.update_campaigns(
            [
                {
                    "Id": campaign_id,
                    "DailyBudget": {"Amount": int(amount_rub * 1_000_000), "Mode": mode},
                }
            ]
        )

    # --- Write: ставки ---

    async def set_keyword_bids(self, bids: list[dict]) -> dict:
        """Установить ручные ставки.

        Каждый элемент — dict вида:
            {"KeywordId": 123, "SearchBid": 30_000_000, "NetworkBid": 20_000_000}
        (цены в микро — домножай рубли на 1_000_000).
        """
        return await self.call("keywordbids", "set", {"KeywordBids": bids})

    async def set_keyword_bids_auto(self, bids: list[dict]) -> dict:
        """Автоматически подбирать ставку по правилу (keywordbids.setAuto).

        Элемент: {"KeywordId"|"AdGroupId"|"CampaignId": ..., "BiddingRule": {"SearchByTrafficVolume":
        {"TargetTrafficVolume", "IncreasePercent"?, "BidCeiling"?} | "NetworkByCoverage": {...}}}.
        Приоритет авто-стратегии задаётся не здесь, а в `set` (StrategyPriority).
        """
        return await self.call("keywordbids", "setAuto", {"KeywordBids": bids})

    # --- Write: объявления ---

    async def moderate_ads(self, ids: list[int]) -> dict:
        """Отправить объявления на модерацию (из DRAFT в MODERATION)."""
        return await self.call("ads", "moderate", {"SelectionCriteria": {"Ids": ids}})

    async def suspend_ads(self, ids: list[int]) -> dict:
        return await self.call("ads", "suspend", {"SelectionCriteria": {"Ids": ids}})

    async def resume_ads(self, ids: list[int]) -> dict:
        return await self.call("ads", "resume", {"SelectionCriteria": {"Ids": ids}})

    async def archive_ads(self, ids: list[int]) -> dict:
        return await self.call("ads", "archive", {"SelectionCriteria": {"Ids": ids}})

    async def unarchive_ads(self, ids: list[int]) -> dict:
        return await self.call("ads", "unarchive", {"SelectionCriteria": {"Ids": ids}})

    async def delete_ads(self, ids: list[int]) -> dict:
        return await self.call("ads", "delete", {"SelectionCriteria": {"Ids": ids}})

    async def add_ads(self, ads: list[dict]) -> dict:
        """Создать объявления (до 1000 за вызов): у каждого `AdGroupId` и ровно один блок типа.

        Блоки: TextAd, ResponsiveAd, DynamicTextAd, MobileAppAd, TextImageAd, MobileAppImageAd,
        TextAdBuilderAd, MobileAppAdBuilderAd, MobileAppCpcVideoAdBuilderAd, CpmBannerAdBuilderAd,
        CpcVideoAdBuilderAd, CpmVideoAdBuilderAd, SmartAdBuilderAd, ShoppingAd, ListingAd
        (`core.ads.AD_TYPE_BLOCKS`). Ошибка формы — InvalidArguments до запроса.
        """
        validate_ads(ads)
        return await self.call("ads", "add", {"Ads": ads})

    async def add_text_ad(
        self,
        adgroup_id: int,
        title: str,
        text: str,
        href: str,
        *,
        title2: str | None = None,
        display_url_path: str | None = None,
        mobile: str | None = None,
        age_label: str | None = None,
        vcard_id: int | None = None,
        sitelink_set_id: int | None = None,
        ad_image_hash: str | None = None,
        turbo_page_id: int | None = None,
    ) -> dict:
        """Шорткат: добавить одно текстовое объявление. `Mobile` в API обязателен — по умолчанию NO."""
        text_ad: dict[str, Any] = {"Title": title, "Text": text, "Href": href, "Mobile": mobile or "NO"}
        ad: dict[str, Any] = {"AdGroupId": adgroup_id, "TextAd": text_ad}
        for key, value in [
            ("Title2", title2),
            ("DisplayUrlPath", display_url_path),
            ("AgeLabel", age_label),
            ("VCardId", vcard_id),
            ("SitelinkSetId", sitelink_set_id),
            ("AdImageHash", ad_image_hash),
            ("TurboPageId", turbo_page_id),
        ]:
            if value is not None:
                text_ad[key] = value
        return await self.add_ads([ad])

    async def update_ads(self, ads: list[dict]) -> dict:
        """Изменить объявления: у каждого `Id` и ровно один блок типа с изменяемыми полями."""
        validate_ads(ads, update=True)
        return await self.call("ads", "update", {"Ads": ads})

    # --- Группы объявлений: write ---

    async def add_adgroups(self, groups: list[dict]) -> dict:
        """Создать группы объявлений (до 1000 за вызов).

        Элемент: `{Name, CampaignId, RegionIds, NegativeKeywords?: {Items}, NegativeKeywordSharedSetIds?,
        TrackingParams?, <блок типа>?}`. У текстовой группы блока нет; иначе один из
        `core.ads.ADGROUP_TYPE_BLOCKS` (MobileAppAdGroup, DynamicTextAdGroup, SmartAdGroup, UnifiedAdGroup…).
        """
        validate_adgroups(groups)
        return await self.call("adgroups", "add", {"AdGroups": groups})

    async def update_adgroups(self, groups: list[dict]) -> dict:
        """Изменить группы объявлений. Каждый элемент содержит `Id`."""
        validate_adgroups(groups, update=True)
        return await self.call("adgroups", "update", {"AdGroups": groups})

    async def get_adgroup(self, adgroup_id: int) -> dict | None:
        """Одна группа со всеми полями, включая блок её типа."""
        result = await self.call(
            "adgroups",
            "get",
            {"SelectionCriteria": {"Ids": [adgroup_id]}, "FieldNames": ADGROUP_FIELDS, **ADGROUP_TYPE_FIELDS},
        )
        items = result.get("AdGroups", [])
        return items[0] if items else None

    async def delete_adgroups(self, ids: list[int]) -> dict:
        return await self.call("adgroups", "delete", {"SelectionCriteria": {"Ids": ids}})

    # --- Write: общие минус-слова ---

    async def add_negative_keyword_shared_sets(self, sets: list[dict]) -> dict:
        """Создать наборы общих минус-слов (до 30 за вызов, 30 на аккаунт).

        Каждый элемент: `{"Name": "...", "NegativeKeywords": ["фраза1", "фраза2"]}`.
        Фразы без минуса в начале, до 7 слов, до 35 символов на слово, общая
        длина всех фраз в наборе — до 4096 символов (без пробелов и операторов).

        `NegativeKeywords` — плоский массив строк (и в add, и в update).
        """
        if not sets:
            raise ValueError("sets пустой")
        if len(sets) > 30:
            raise ValueError("negativekeywordsharedsets.add — не более 30 за вызов")
        return await self.call(
            "negativekeywordsharedsets",
            "add",
            {
                "NegativeKeywordSharedSets": sets,
            },
        )

    async def delete_negative_keyword_shared_sets(self, ids: list[int]) -> dict:
        """Удалить наборы общих минус-слов (до 30 за вызов).

        Не удалятся наборы, которые привязаны к группам объявлений —
        API вернёт Warning с перечислением adgroup_id.
        """
        return await self.call(
            "negativekeywordsharedsets",
            "delete",
            {
                "SelectionCriteria": {"Ids": ids},
            },
        )

    async def update_negative_keyword_shared_set(
        self,
        set_id: int,
        name: str | None = None,
        negative_keywords: list[str] | None = None,
    ) -> dict:
        """Обновить набор минус-слов. Минимум один параметр должен быть задан.

        Args:
            negative_keywords: полный список фраз (заменяет текущий).
                Для добавления фраз — сначала получи текущие через
                `list_negative_keyword_shared_sets`, добавь новые и передай
                объединённый список.
        """
        if name is None and negative_keywords is None:
            raise ValueError("укажи name или negative_keywords")
        item: dict[str, Any] = {"Id": set_id}
        if name is not None:
            item["Name"] = name
        if negative_keywords is not None:
            item["NegativeKeywords"] = negative_keywords
        return await self.call(
            "negativekeywordsharedsets",
            "update",
            {
                "NegativeKeywordSharedSets": [item],
            },
        )

    # --- Корректировки ставок ---

    async def list_bid_modifiers(
        self,
        campaign_ids: list[int] | None = None,
        adgroup_ids: list[int] | None = None,
        ids: list[int] | None = None,
        types: list[str] | None = None,
        field_names: list[str] | None = None,
        *,
        levels: list[str] | None = None,
    ) -> list[dict]:
        """Корректировки ставок (bidmodifiers.get) со всеми полями каждого типа.

        levels — CAMPAIGN и/или AD_GROUP (в API поле обязательное; по умолчанию оба).
        Нужен хотя бы один из campaign_ids / adgroup_ids / ids.
        """
        criteria: dict[str, Any] = {"Levels": levels or ["CAMPAIGN", "AD_GROUP"]}
        if ids:
            criteria["Ids"] = ids
        if campaign_ids:
            criteria["CampaignIds"] = campaign_ids
        if adgroup_ids:
            criteria["AdGroupIds"] = adgroup_ids
        if types:
            criteria["Types"] = types
        params: dict[str, Any] = {
            "SelectionCriteria": criteria,
            "FieldNames": field_names or ["Id", "CampaignId", "AdGroupId", "Level", "Type"],
        }
        for block, sub in BID_MODIFIER_SUBFIELDS.items():
            params[f"{block}FieldNames"] = sub
        return await self._paginated_get("bidmodifiers", "BidModifiers", params, page_limit=10000)

    async def add_bid_modifiers(self, modifiers: list[dict]) -> dict:
        """Добавить корректировки ставок.

        Элемент — объект с привязкой (`CampaignId` **или** `AdGroupId`) и
        одним блоком типа. Одиночные: `MobileAdjustment {BidModifier, OperatingSystemType?}`,
        `DesktopAdjustment`, `SmartTvAdjustment`, `TabletAdjustment`, `DesktopOnlyAdjustment`,
        `VideoAdjustment`, `SmartAdAdjustment`, `AdGroupAdjustment` — `{BidModifier}`.
        Массивы: `DemographicsAdjustments [{Gender?, Age?, BidModifier}]`,
        `RetargetingAdjustments [{RetargetingConditionId, BidModifier}]`,
        `RegionalAdjustments [{RegionId, BidModifier}]`, `SerpLayoutAdjustments [{SerpLayout, BidModifier}]`,
        `IncomeGradeAdjustments [{Grade, BidModifier}]`.
        BidModifier — процент (0 = отключить показы, 100 = без корректировки).
        """
        if not modifiers:
            raise ValueError("modifiers пустой")
        return await self.call("bidmodifiers", "add", {"BidModifiers": modifiers})

    async def set_bid_modifiers(self, modifiers: list[dict]) -> dict:
        """Обновить значение существующих корректировок.

        Элемент: `{"Id": <id>, "BidModifier": <0..1200>}`.
        Нельзя менять `Adjustment`/`Level` — только само значение процента.
        """
        if not modifiers:
            raise ValueError("modifiers пустой")
        return await self.call("bidmodifiers", "set", {"BidModifiers": modifiers})

    async def delete_bid_modifiers(self, ids: list[int]) -> dict:
        return await self.call("bidmodifiers", "delete", {"SelectionCriteria": {"Ids": ids}})

    # --- Ретаргетинг и аудитории ---

    async def list_retargeting_lists(
        self,
        ids: list[int] | None = None,
        types: list[str] | None = None,
        field_names: list[str] | None = None,
    ) -> list[dict]:
        """Списки ретаргетинга.

        types: RETARGETING (цели Метрики) или AUDIENCE (аудитории Метрики).
        """
        criteria: dict[str, Any] = {}
        if ids:
            criteria["Ids"] = ids
        if types:
            criteria["Types"] = types
        return await self._paginated_get(
            "retargetinglists",
            "RetargetingLists",
            {
                "SelectionCriteria": criteria,
                "FieldNames": field_names
                or [
                    "Id",
                    "Name",
                    "Description",
                    "Type",
                    "Rules",
                    "IsAvailable",
                    "Scope",
                ],
            },
            page_limit=1000,
        )

    async def add_retargeting_lists(self, lists: list[dict]) -> dict:
        """Создать списки ретаргетинга (до 1000 за вызов, до 2000 на аккаунт).

        Каждый элемент:
            {"Name": "...", "Type": "RETARGETING"|"AUDIENCE" (по умолч. RETARGETING),
             "Description": "...",
             "Rules": [{"Operator": "ALL"|"ANY"|"NONE",
                        "Arguments": [{"ExternalId": <goal/segment id>,
                                       "MembershipLifeSpan": <1..540 дней, только для целей Метрики>}]}]}

        Для интересов мобильных приложений `ExternalId` с префиксом
        10/20/30 (short/long/any term).
        """
        if not lists:
            raise ValueError("lists пустой")
        if len(lists) > 1000:
            raise ValueError("retargetinglists.add — не более 1000 за вызов")
        return await self.call("retargetinglists", "add", {"RetargetingLists": lists})

    async def update_retargeting_lists(self, lists: list[dict]) -> dict:
        """Обновить списки ретаргетинга.

        Каждый элемент: {"Id": ..., "Name"?, "Description"?, "Rules"?}.
        Любое из полей опционально, но хотя бы одно должно быть задано.
        """
        if not lists:
            raise ValueError("lists пустой")
        return await self.call("retargetinglists", "update", {"RetargetingLists": lists})

    async def delete_retargeting_lists(self, ids: list[int]) -> dict:
        return await self.call("retargetinglists", "delete", {"SelectionCriteria": {"Ids": ids}})

    async def add_audience_targets(self, targets: list[dict]) -> dict:
        """Привязать аудитории к группам объявлений.

        Каждый элемент:
            {"AdGroupId": ..., "RetargetingListId": ... | "InterestId": ...,
             "ContextBid": <микро>, "StrategyPriority": "LOW"|"NORMAL"|"HIGH"}
        `InterestId` только для групп типа MOBILE_APP_AD_GROUP.
        """
        if not targets:
            raise ValueError("targets пустой")
        return await self.call("audiencetargets", "add", {"AudienceTargets": targets})

    async def suspend_audience_targets(self, ids: list[int]) -> dict:
        return await self.call("audiencetargets", "suspend", {"SelectionCriteria": {"Ids": ids}})

    async def resume_audience_targets(self, ids: list[int]) -> dict:
        return await self.call("audiencetargets", "resume", {"SelectionCriteria": {"Ids": ids}})

    async def delete_audience_targets(self, ids: list[int]) -> dict:
        return await self.call("audiencetargets", "delete", {"SelectionCriteria": {"Ids": ids}})

    async def set_audience_target_bids(self, bids: list[dict]) -> dict:
        """Установить ставки/приоритет для привязок аудиторий (до 10000 за вызов).

        Элемент: `{"Id"|"AdGroupId"|"CampaignId": ..., "ContextBid": <микро>,
                   "StrategyPriority": "LOW"|"NORMAL"|"HIGH"}`
        `Id`/`AdGroupId`/`CampaignId` — **взаимоисключающие в одном элементе**:
        для конкретной привязки передай `Id`, для всех в группе/кампании —
        `AdGroupId`/`CampaignId`.
        ContextBid — ставка × 1_000_000 (ручная стратегия).
        StrategyPriority — только для авто-стратегий (default NORMAL).
        """
        if not bids:
            raise ValueError("bids пустой")
        if len(bids) > 10000:
            raise ValueError("audiencetargets.setBids — не более 10000 за вызов")
        scope_keys = {"Id", "AdGroupId", "CampaignId"}
        for i, item in enumerate(bids):
            keys = scope_keys & item.keys()
            if len(keys) != 1:
                raise ValueError(
                    f"bids[{i}]: нужен ровно один из Id/AdGroupId/CampaignId, нашёл {sorted(keys) or 'ни одного'}"
                )
        return await self.call("audiencetargets", "setBids", {"Bids": bids})

    async def list_audience_targets(
        self,
        adgroup_ids: list[int] | None = None,
        campaign_ids: list[int] | None = None,
        ids: list[int] | None = None,
        states: list[str] | None = None,
        field_names: list[str] | None = None,
        *,
        retargeting_list_ids: list[int] | None = None,
        interest_ids: list[int] | None = None,
    ) -> list[dict]:
        """Привязки аудиторий (retargeting/interest) к группам объявлений."""
        criteria: dict[str, Any] = {}
        if ids:
            criteria["Ids"] = ids
        if adgroup_ids:
            criteria["AdGroupIds"] = adgroup_ids
        if campaign_ids:
            criteria["CampaignIds"] = campaign_ids
        if retargeting_list_ids:
            criteria["RetargetingListIds"] = retargeting_list_ids
        if interest_ids:
            criteria["InterestIds"] = interest_ids
        if states:
            criteria["States"] = states
        return await self._paginated_get(
            "audiencetargets",
            "AudienceTargets",
            {
                "SelectionCriteria": criteria,
                "FieldNames": field_names
                or [
                    "Id",
                    "AdGroupId",
                    "CampaignId",
                    "RetargetingListId",
                    "InterestId",
                    "State",
                    "ContextBid",
                    "StrategyPriority",
                ],
            },
            page_limit=10000,
        )

    # --- Исследование ключей ---

    async def keywords_has_search_volume(
        self,
        keywords: list[str],
        region_ids: list[int] | None = None,
        field_names: list[str] | None = None,
    ) -> list[dict]:
        """Есть ли у фраз поисковый спрос (keywordsresearch.hasSearchVolume), по типам устройств.

        region_ids — регионы Яндекса (213 — Москва, 225 — Россия); API требует хотя бы один,
        по умолчанию — Россия. Ответ: [{Keyword, RegionIds, AllDevices, MobilePhones, Tablets, Desktops}],
        значения YES/NO.
        """
        result = await self.call(
            "keywordsresearch",
            "hasSearchVolume",
            {
                "SelectionCriteria": {"Keywords": keywords, "RegionIds": region_ids or [225]},
                "FieldNames": field_names
                or ["Keyword", "RegionIds", "AllDevices", "MobilePhones", "Tablets", "Desktops"],
            },
        )
        return result.get("HasSearchVolumeResults", [])

    async def keywords_deduplicate(self, keywords: list[dict], operations: list[str] | None = None) -> dict:
        """Подсказки по дублям фраз (keywordsresearch.deduplicate) — только расчёт, кабинет не меняется.

        keywords — [{"Keyword": "...", "Id"?: id существующей фразы, "Weight"?: вес}].
        operations — MERGE_DUPLICATES (склеить дубли), ELIMINATE_OVERLAPPING (минусовать
        пересечения); по умолчанию API делает обе. Ответ: {Add, Update, Delete: {Ids}, Failure}.
        """
        params: dict[str, Any] = {"Keywords": keywords}
        if operations:
            params["Operation"] = operations
        return await self.call("keywordsresearch", "deduplicate", params)

    # --- Write: создание/удаление кампаний (P3) ---

    # Валидные type-specific блоки для campaigns.add.
    # https://yandex.ru/dev/direct/doc/ref-v5/campaigns/add.html
    _CAMPAIGN_TYPE_KEYS = frozenset(
        [
            "TextCampaign",
            "DynamicTextCampaign",
            "MobileAppCampaign",
            "CpmBannerCampaign",
            "CpmVideoCampaign",
            "SmartCampaign",
            "UnifiedCampaign",
            "CpmPriceCampaign",
            "ContentPromotionCampaign",
            "McBannerCampaign",
        ]
    )

    async def add_campaigns(self, campaigns: list[dict]) -> dict:
        """Создать кампании (до 10 за вызов — лимит API жёстче других методов).

        Каждый элемент:
            {Name, StartDate, EndDate?, DailyBudget?: {Amount, Mode},
             <TypeBlock>: {BiddingStrategy, ...}}
        TypeBlock — один из: TextCampaign, DynamicTextCampaign, MobileAppCampaign,
        CpmBannerCampaign, CpmVideoCampaign, SmartCampaign, UnifiedCampaign,
        CpmPriceCampaign, ContentPromotionCampaign, McBannerCampaign.

        Структура BiddingStrategy объёмная — сверяйся со справочником
        `campaigns.add` в доке Яндекса. Цены (Amount, BidCeiling, AverageCpc,
        AverageCpa и т.д.) задаются в **микро** (рубли × 1_000_000).
        """
        if not campaigns:
            raise ValueError("campaigns пустой")
        for i, c in enumerate(campaigns):
            if "Name" not in c or "StartDate" not in c:
                raise ValueError(f"campaigns[{i}]: обязательны Name и StartDate")
            type_keys = self._CAMPAIGN_TYPE_KEYS & c.keys()
            if len(type_keys) != 1:
                raise ValueError(
                    f"campaigns[{i}]: нужен ровно один type-specific блок, нашёл {sorted(type_keys) or 'ни одного'}"
                )
        return await self.call("campaigns", "add", {"Campaigns": campaigns})

    async def delete_campaigns(self, ids: list[int]) -> dict:
        """Удалить кампании безвозвратно. Кампания должна быть archived."""
        return await self.call("campaigns", "delete", {"SelectionCriteria": {"Ids": ids}})

    # --- Агентство и клиенты (P3) ---

    async def update_client(self, fields: dict) -> dict:
        """Изменить настройки клиента (НДС, уведомления, контактная информация).

        fields: словарь с полями клиента, которые нужно обновить.
        """
        return await self.call("clients", "update", fields)

    async def update_agency_client(self, fields: dict) -> dict:
        """Изменить настройки агентского доступа к клиенту."""
        return await self.call("agencyclients", "update", fields)

    # --- Фиды, бизнес-данные, лиды (P3) ---

    async def list_feeds(
        self,
        ids: list[int] | None = None,
        field_names: list[str] | None = None,
    ) -> list[dict]:
        """Товарные фиды клиента."""
        criteria: dict[str, Any] = {}
        if ids:
            criteria["Ids"] = ids
        return await self._paginated_get(
            "feeds",
            "Feeds",
            {
                "SelectionCriteria": criteria,
                "FieldNames": field_names
                or [
                    "Id",
                    "Name",
                    "BusinessType",
                    "SourceType",
                    "FilterQuantity",
                    "UpdatedTime",
                    "FilenameSource",
                    "UrlSource",
                ],
            },
            page_limit=1000,
        )

    async def add_feeds(self, feeds: list[dict]) -> dict:
        """Создать фиды (через URL или FilenameSource/FileContent)."""
        if not feeds:
            raise ValueError("feeds пустой")
        return await self.call("feeds", "add", {"Feeds": feeds})

    async def update_feeds(self, feeds: list[dict]) -> dict:
        if not feeds:
            raise ValueError("feeds пустой")
        return await self.call("feeds", "update", {"Feeds": feeds})

    async def delete_feeds(self, ids: list[int]) -> dict:
        return await self.call("feeds", "delete", {"SelectionCriteria": {"Ids": ids}})

    async def list_businesses(
        self,
        ids: list[int] | None = None,
        field_names: list[str] | None = None,
    ) -> list[dict]:
        """Организации из Яндекс Бизнеса, доступные кабинету (для привязки к объявлениям)."""
        params: dict[str, Any] = {
            "FieldNames": field_names or ["Id", "Name", "Address", "Phone", "ProfileUrl", "IsPublished"]
        }
        if ids:
            params["SelectionCriteria"] = {"Ids": ids}
        return await self._paginated_get("businesses", "Businesses", params, page_limit=1000)

    async def list_leads(
        self,
        turbo_page_ids: list[int],
        date_from: str | None = None,
        date_to: str | None = None,
        field_names: list[str] | None = None,
    ) -> list[dict]:
        """Лиды с форм Турбо-страниц. `turbo_page_ids` обязателен (так в API).

        date_from/date_to — `YYYY-MM-DDThh:mm:ssZ` или `YYYY-MM-DD` (UTC).
        """
        if not turbo_page_ids:
            raise InvalidArguments("leads.get требует хотя бы одну турбо-страницу (TurboPageIds).")
        criteria: dict[str, Any] = {"TurboPageIds": turbo_page_ids}
        if date_from:
            criteria["DateTimeFrom"] = date_from
        if date_to:
            criteria["DateTimeTo"] = date_to
        return await self._paginated_get(
            "leads",
            "Leads",
            {
                "SelectionCriteria": criteria,
                "FieldNames": field_names or ["Id", "SubmittedAt", "TurboPageId", "TurboPageName", "Data"],
            },
            page_limit=10000,
        )

    # --- Динамический и смарт-таргетинг (P3) ---

    async def list_dynamic_text_ad_targets(
        self,
        adgroup_ids: list[int] | None = None,
        campaign_ids: list[int] | None = None,
        ids: list[int] | None = None,
        states: list[str] | None = None,
        field_names: list[str] | None = None,
    ) -> list[dict]:
        """Условия нацеливания динамических объявлений по страницам сайта (dynamictextadtargets.get)."""
        return await self._paginated_get(
            "dynamictextadtargets",
            "Webpages",
            {
                "SelectionCriteria": _ad_targets_criteria(ids, adgroup_ids, campaign_ids, states),
                "FieldNames": field_names
                or [
                    "Id",
                    "AdGroupId",
                    "CampaignId",
                    "Name",
                    "State",
                    "Bid",
                    "ContextBid",
                    "StrategyPriority",
                    "Conditions",
                    "ConditionType",
                ],
            },
            page_limit=10000,
        )

    async def add_dynamic_text_ad_targets(self, targets: list[dict]) -> dict:
        """Добавить условия таргетинга для DynamicTextAd."""
        if not targets:
            raise ValueError("targets пустой")
        return await self.call("dynamictextadtargets", "add", {"Webpages": targets})

    async def delete_dynamic_text_ad_targets(self, ids: list[int]) -> dict:
        return await self.call("dynamictextadtargets", "delete", {"SelectionCriteria": {"Ids": ids}})

    async def suspend_dynamic_text_ad_targets(self, ids: list[int]) -> dict:
        return await self.call("dynamictextadtargets", "suspend", {"SelectionCriteria": {"Ids": ids}})

    async def resume_dynamic_text_ad_targets(self, ids: list[int]) -> dict:
        return await self.call("dynamictextadtargets", "resume", {"SelectionCriteria": {"Ids": ids}})

    async def set_dynamic_text_ad_target_bids(self, bids: list[dict]) -> dict:
        """Установить ставки для условий таргетинга dynamic-ads.

        Элемент: {Id | AdGroupId | CampaignId, Bid (микро)?, ContextBid?, StrategyPriority?}
        """
        if not bids:
            raise ValueError("bids пустой")
        return await self.call("dynamictextadtargets", "setBids", {"Bids": bids})

    async def list_dynamic_feed_ad_targets(
        self,
        adgroup_ids: list[int] | None = None,
        campaign_ids: list[int] | None = None,
        ids: list[int] | None = None,
        states: list[str] | None = None,
        field_names: list[str] | None = None,
    ) -> list[dict]:
        """Фильтры динамических объявлений по фиду (dynamicfeedadtargets.get)."""
        return await self._paginated_get(
            "dynamicfeedadtargets",
            "DynamicFeedAdTargets",
            {
                "SelectionCriteria": _ad_targets_criteria(ids, adgroup_ids, campaign_ids, states),
                "FieldNames": field_names
                or [
                    "Id",
                    "AdGroupId",
                    "CampaignId",
                    "Name",
                    "State",
                    "Bid",
                    "ContextBid",
                    "Conditions",
                    "ConditionType",
                    "AvailableItemsOnly",
                ],
            },
            page_limit=10000,
        )

    async def list_smart_ad_targets(
        self,
        adgroup_ids: list[int] | None = None,
        campaign_ids: list[int] | None = None,
        ids: list[int] | None = None,
        states: list[str] | None = None,
        field_names: list[str] | None = None,
    ) -> list[dict]:
        """Фильтры смарт-баннеров (smartadtargets.get)."""
        return await self._paginated_get(
            "smartadtargets",
            "SmartAdTargets",
            {
                "SelectionCriteria": _ad_targets_criteria(ids, adgroup_ids, campaign_ids, states),
                "FieldNames": field_names
                or [
                    "Id",
                    "AdGroupId",
                    "CampaignId",
                    "Name",
                    "State",
                    "Audience",
                    "AverageCpc",
                    "AverageCpa",
                    "StrategyPriority",
                    "Conditions",
                    "ConditionType",
                    "AvailableItemsOnly",
                ],
            },
            page_limit=10000,
        )

    async def add_smart_ad_targets(self, targets: list[dict]) -> dict:
        if not targets:
            raise ValueError("targets пустой")
        return await self.call("smartadtargets", "add", {"SmartAdTargets": targets})

    async def delete_smart_ad_targets(self, ids: list[int]) -> dict:
        return await self.call("smartadtargets", "delete", {"SelectionCriteria": {"Ids": ids}})

    async def suspend_smart_ad_targets(self, ids: list[int]) -> dict:
        return await self.call("smartadtargets", "suspend", {"SelectionCriteria": {"Ids": ids}})

    async def resume_smart_ad_targets(self, ids: list[int]) -> dict:
        return await self.call("smartadtargets", "resume", {"SelectionCriteria": {"Ids": ids}})

    async def set_smart_ad_target_bids(self, bids: list[dict]) -> dict:
        """Элемент: {Id | AdGroupId | CampaignId, AverageCpc (микро)?, AverageCpa (микро)?, StrategyPriority?}"""
        if not bids:
            raise ValueError("bids пустой")
        return await self.call("smartadtargets", "setBids", {"Bids": bids})

    # --- Расширения объявлений: sitelinks / vcards / adextensions ---

    async def list_sitelinks(
        self,
        ids: list[int] | None = None,
        field_names: list[str] | None = None,
    ) -> list[dict]:
        params: dict[str, Any] = {"FieldNames": field_names or ["Id", "Sitelinks"]}
        if ids:
            params["SelectionCriteria"] = {"Ids": ids}
        return await self._paginated_get("sitelinks", "SitelinksSets", params, page_limit=1000)

    async def add_sitelinks(self, sitelinks_sets: list[dict]) -> dict:
        """Создать наборы быстрых ссылок (до 1000 за вызов).

        Каждый элемент: `{"Sitelinks": [{"Title": "...", "Href": "...",
                                          "Description"?, "TurboPageId"?}]}`.
        От 1 до 8 ссылок в наборе. Title ≤ 30 симв.
        Редактирование невозможно — создай новый набор и переподключи к объявлениям.
        """
        if not sitelinks_sets:
            raise InvalidArguments("Список наборов быстрых ссылок пуст.")
        return await self.call("sitelinks", "add", {"SitelinksSets": sitelinks_sets})

    async def delete_sitelinks(self, ids: list[int]) -> dict:
        """Удалить наборы быстрых ссылок. Нельзя удалить привязанные к объявлениям."""
        return await self.call("sitelinks", "delete", {"SelectionCriteria": {"Ids": ids}})

    async def list_vcards(
        self,
        ids: list[int] | None = None,
        campaign_ids: list[int] | None = None,
        field_names: list[str] | None = None,
    ) -> list[dict]:
        """Визитки. API фильтрует только по Id; `campaign_ids` отбирает по CampaignId уже после ответа."""
        default = ["Id", "CampaignId", "Country", "City", "CompanyName", "WorkTime", "Phone", "Street", "House"]
        params: dict[str, Any] = {"FieldNames": field_names or [*default, "ContactEmail"]}
        if ids:
            params["SelectionCriteria"] = {"Ids": ids}
        items = await self._paginated_get("vcards", "VCards", params, page_limit=1000)
        if campaign_ids:
            wanted = set(campaign_ids)
            items = [v for v in items if v.get("CampaignId") in wanted]
        return items

    async def add_vcards(self, vcards: list[dict]) -> dict:
        """Создать визитки (до 1000 за вызов).

        Обязательные поля: `CampaignId`, `Country`, `City`, `CompanyName`,
        `WorkTime`, `Phone: {CountryCode, CityCode, PhoneNumber, Extension?}`.
        """
        if not vcards:
            raise InvalidArguments("Список визиток пуст.")
        return await self.call("vcards", "add", {"VCards": vcards})

    async def delete_vcards(self, ids: list[int]) -> dict:
        return await self.call("vcards", "delete", {"SelectionCriteria": {"Ids": ids}})

    async def list_ad_extensions(
        self,
        ids: list[int] | None = None,
        types: list[str] | None = None,
        states: list[str] | None = None,
        statuses: list[str] | None = None,
        modified_since: str | None = None,
        field_names: list[str] | None = None,
        callout_field_names: list[str] | None = None,
    ) -> list[dict]:
        """Расширения объявлений — сейчас это уточнения (CALLOUT).

        states: ON | DELETED; statuses: DRAFT, MODERATION, ACCEPTED, REJECTED.
        """
        criteria: dict[str, Any] = {}
        if ids:
            criteria["Ids"] = ids
        if types:
            criteria["Types"] = types
        if states:
            criteria["States"] = states
        if statuses:
            criteria["Statuses"] = statuses
        if modified_since:
            criteria["ModifiedSince"] = modified_since
        params: dict[str, Any] = {
            "SelectionCriteria": criteria,
            "FieldNames": field_names or ["Id", "Type", "State", "Status", "StatusClarification", "Associated"],
            "CalloutFieldNames": callout_field_names or ["CalloutText"],
        }
        return await self._paginated_get("adextensions", "AdExtensions", params, page_limit=10000)

    async def add_ad_extensions(self, extensions: list[dict]) -> dict:
        """Создать уточнения (до 1000 за вызов).

        Сейчас API поддерживает только Callout:
            `[{"Callout": {"CalloutText": "..."}}]`. Текст ≤ 25 символов.
        """
        if not extensions:
            raise InvalidArguments("Список уточнений пуст.")
        return await self.call("adextensions", "add", {"AdExtensions": extensions})

    async def delete_ad_extensions(self, ids: list[int]) -> dict:
        return await self.call("adextensions", "delete", {"SelectionCriteria": {"Ids": ids}})

    # --- Креативы: adimages / creatives / turbopages ---

    async def list_ad_images(
        self,
        hashes: list[str] | None = None,
        associated: str | None = None,
        field_names: list[str] | None = None,
    ) -> list[dict]:
        """Список изображений.

        associated: "YES" (привязанные к объявлениям) | "NO" (свободные).
        """
        criteria: dict[str, Any] = {}
        if hashes:
            criteria["AdImageHashes"] = hashes
        if associated:
            criteria["Associated"] = associated
        return await self._paginated_get(
            "adimages",
            "AdImages",
            {
                "SelectionCriteria": criteria,
                "FieldNames": field_names
                or [
                    "AdImageHash",
                    "OriginalUrl",
                    "PreviewUrl",
                    "Name",
                    "Type",
                    "Subtype",
                    "Associated",
                ],
            },
            page_limit=1000,
        )

    async def add_ad_images(self, images: list[dict]) -> dict:
        """Загрузить изображения (до 100 за вызов, рекомендуется ≤3).

        Каждый элемент:
            {"ImageData": "<base64>", "Name": "photo.jpg",
             "Type"?: "REGULAR|WIDE|FIXED_IMAGE|AUTO"}
        В ответе — `AdImageHash`, по нему потом привязывай к объявлениям.
        """
        if not images:
            raise InvalidArguments("Список изображений пуст.")
        if len(images) > 100:
            raise InvalidArguments("adimages.add — не более 100 изображений за вызов.")
        return await self.call("adimages", "add", {"AdImages": images})

    async def delete_ad_images(self, hashes: list[str]) -> dict:
        """Удалить изображения по хэшам (до 10000). Нельзя удалить привязанные."""
        return await self.call(
            "adimages",
            "delete",
            {
                "SelectionCriteria": {"AdImageHashes": hashes},
            },
        )

    async def list_creatives(
        self,
        ids: list[int] | None = None,
        types: list[str] | None = None,
        field_names: list[str] | None = None,
    ) -> list[dict]:
        """Креативы: HTML5, видео, смарт-баннеры.

        types: IMAGE_CREATIVE, HTML5_CREATIVE, VIDEO_EXTENSION_CREATIVE,
        CPC_VIDEO_CREATIVE, CPM_VIDEO_CREATIVE, SMART_CREATIVE.
        """
        criteria: dict[str, Any] = {}
        if ids:
            criteria["Ids"] = ids
        if types:
            criteria["Types"] = types
        params: dict[str, Any] = {
            "SelectionCriteria": criteria,
            "FieldNames": field_names
            or [
                "Id",
                "Type",
                "Name",
                "PreviewUrl",
                "Width",
                "Height",
                "ThumbnailUrl",
                "Associated",
                "IsAdaptive",
            ],
            "VideoExtensionCreativeFieldNames": ["Duration"],
            "CpcVideoCreativeFieldNames": ["Duration"],
            "CpmVideoCreativeFieldNames": ["Duration"],
            "SmartCreativeFieldNames": ["CreativeGroupId", "CreativeGroupName", "BusinessType"],
        }
        return await self._paginated_get("creatives", "Creatives", params, page_limit=1000)

    async def add_creatives(self, creatives: list[dict]) -> dict:
        """Создать креативы (до 10 за вызов).

        Сейчас в API поддерживается только тип VideoExtensionCreative:
            `[{"VideoExtensionCreative": {"VideoId": "<id>"}}]`
        VideoId предварительно получается из AdVideos (загрузка видео).
        """
        if not creatives:
            raise InvalidArguments("Список креативов пуст.")
        if len(creatives) > 10:
            raise InvalidArguments("creatives.add — не более 10 креативов за вызов.")
        return await self.call("creatives", "add", {"Creatives": creatives})

    async def list_turbopages(
        self,
        ids: list[int] | None = None,
        bound_with_hrefs: list[str] | None = None,
        field_names: list[str] | None = None,
    ) -> list[dict]:
        """Турбо-страницы клиента; `bound_with_hrefs` — только привязанные к этим адресам сайта."""
        criteria: dict[str, Any] = {}
        if ids:
            criteria["Ids"] = ids
        if bound_with_hrefs:
            criteria["BoundWithHrefs"] = bound_with_hrefs
        return await self._paginated_get(
            "turbopages",
            "TurboPages",
            {
                "SelectionCriteria": criteria,
                "FieldNames": field_names or ["Id", "Name", "Href", "PreviewHref", "TurboSiteHref", "BoundWithHref"],
            },
            page_limit=1000,
        )

    # --- Видео: advideos ---

    async def list_ad_videos(self, ids: list[str], field_names: list[str] | None = None) -> list[dict]:
        """Видео по Id (API не отдаёт список всех видео — Ids обязательны)."""
        if not ids:
            raise InvalidArguments("advideos.get требует хотя бы один Id видео.")
        return await self._paginated_get(
            "advideos",
            "AdVideos",
            {"SelectionCriteria": {"Ids": ids}, "FieldNames": field_names or ["Id", "Status"]},
            page_limit=1000,
        )

    async def add_ad_videos(self, videos: list[dict]) -> dict:
        """Загрузить видео: элемент `{Url | VideoData (base64), Name?}`; в ответе — Id видео для creatives.add."""
        if not videos:
            raise InvalidArguments("Список видео пуст.")
        for i, video in enumerate(videos):
            if not (video.get("Url") or video.get("VideoData")):
                raise InvalidArguments(f"advideos[{i}]: нужен Url или VideoData.")
        return await self.call("advideos", "add", {"AdVideos": videos})

    # --- Справочники ---

    async def get_dictionaries(self, dictionary_names: list[str]) -> dict:
        """Получить справочники: Currencies, TimeZones, GeoRegions,
        AdCategories, OperationSystemVersions, ProductivityIndicators,
        SupplyChainStages, AutoBusinesses.
        """
        return await self.call(
            "dictionaries",
            "get",
            {
                "DictionaryNames": dictionary_names,
            },
        )


def _bids_criteria(
    keyword_ids: list[int] | None,
    adgroup_ids: list[int] | None,
    campaign_ids: list[int] | None,
    serving_statuses: list[str] | None,
) -> dict[str, Any]:
    """SelectionCriteria для keywordbids.get / bids.get: API требует хотя бы один из трёх фильтров."""
    criteria: dict[str, Any] = {}
    if keyword_ids:
        criteria["KeywordIds"] = keyword_ids
    if adgroup_ids:
        criteria["AdGroupIds"] = adgroup_ids
    if campaign_ids:
        criteria["CampaignIds"] = campaign_ids
    if not criteria:
        raise ValueError("нужен хотя бы один фильтр: keyword_ids / adgroup_ids / campaign_ids")
    if serving_statuses:
        criteria["ServingStatuses"] = serving_statuses
    return criteria


def _ad_targets_criteria(
    ids: list[int] | None,
    adgroup_ids: list[int] | None,
    campaign_ids: list[int] | None,
    states: list[str] | None,
) -> dict[str, Any]:
    """AdTargetsSelectionCriteria — общая для dynamictextadtargets, dynamicfeedadtargets, smartadtargets."""
    criteria: dict[str, Any] = {}
    if ids:
        criteria["Ids"] = ids
    if adgroup_ids:
        criteria["AdGroupIds"] = adgroup_ids
    if campaign_ids:
        criteria["CampaignIds"] = campaign_ids
    if states:
        criteria["States"] = states
    return criteria


class DirectProvider(Provider):
    """Директ API v5 для `auth status --check` и `doctor`: один дешёвый `clients.get`.

    Токен читает `core.auth` (rb-yandex-oauth), поэтому своих полей в credentials нет.
    """

    abstract = False
    name = "direct"
    credential_fields = ()

    def health_check(self) -> Health:
        from ..core.auth import resolve_token

        client = DirectClient(token=resolve_token(), timeout=10.0)
        client.retries = 0
        asyncio.run(client.call("clients", "get", {"FieldNames": ["Login"]}))
        return Health(quota=units_quota(client.last_units))


def units_quota(units: str | None) -> Quota | None:
    """Заголовок `Units: израсходовано/остаток/суточный лимит` → Quota."""
    parts = (units or "").split("/")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return Quota(remaining=int(parts[1]), limit=int(parts[2]), unit="points")
