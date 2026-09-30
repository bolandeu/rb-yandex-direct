"""ReportsClient — асинхронные TSV-отчёты (сервис Reports).

Алгоритм по оф. доке:
- POST JSON {"params": ReportDefinition} на /json/v5/reports
- 200 — отчёт готов, тело = TSV
- 201 / 202 — отчёт в очереди или формируется; читать заголовок retryIn и
  повторить через указанное число секунд
- 400 — ошибка параметров или переполнение очереди; 5xx — сбой сервиса

Отчёт с тем же ReportName, но другими параметрами API отвергает, поэтому имя
по умолчанию — хэш параметров: одинаковый запрос попадает в тот же отчёт в очереди.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from ..core.errors import DirectAPIError
from .direct import PROD_BASE, SANDBOX_BASE

log = logging.getLogger(__name__)


# Столбцы с текстом пользователя: «2024» в поисковом запросе — строка, а не число.
_TEXT_COLUMN_MARKERS = ("Name", "Query", "Criterion", "Keyword", "Title", "Text", "Placement", "Url", "Label")


def _value(column: str, raw: str) -> Any:
    """Ячейка TSV → число, где это число; `--` (нет данных) → None; текстовые столбцы — строки."""
    if raw == "--":
        return None
    if any(marker in column for marker in _TEXT_COLUMN_MARKERS):
        return raw
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


@dataclass
class Report:
    tsv: str
    request_id: str | None
    rows: int | None

    def parse(self) -> list[dict[str, Any]]:
        """Строки отчёта как dict по заголовку столбцов; заголовок отчёта и итог пропускаются."""
        lines = [ln for ln in self.tsv.splitlines() if ln and not ln.startswith('"')]
        if not lines:
            return []
        header = lines[0].split("\t")
        out = []
        for ln in lines[1:]:
            if ln.lower().startswith("total rows"):
                continue
            parts = ln.split("\t")
            if len(parts) != len(header):
                continue
            out.append({k: _value(k, v) for k, v in zip(header, parts, strict=True)})
        return out


def report_name(params: dict[str, Any], prefix: str = "yd") -> str:
    """Имя отчёта из хэша параметров: одинаковые запросы — одно имя, разные — разные."""
    digest = hashlib.sha1(json.dumps(params, sort_keys=True, ensure_ascii=False).encode(), usedforsecurity=False)
    return f"{prefix}-{digest.hexdigest()[:16]}"


# Пресеты популярных отчётов: тип и минимально достаточный для медиабайера набор полей.
PRESETS: dict[str, tuple[str, list[str]]] = {
    "campaigns": (
        "CAMPAIGN_PERFORMANCE_REPORT",
        [
            "Date", "CampaignId", "CampaignName", "CampaignType", "Impressions", "Clicks", "Cost", "Ctr",
            "AvgCpc", "Conversions", "CostPerConversion", "Bounces", "AvgImpressionPosition",
        ],
    ),
    "ads": (
        "AD_PERFORMANCE_REPORT",
        ["Date", "CampaignId", "AdGroupId", "AdId", "Impressions", "Clicks", "Cost", "Ctr", "AvgCpc", "Conversions"],
    ),
    "queries": (
        "SEARCH_QUERY_PERFORMANCE_REPORT",
        [
            "Date", "CampaignId", "AdGroupId", "CriterionId", "Criterion", "Query", "MatchType", "Impressions",
            "Clicks", "Cost", "Ctr", "AvgCpc", "Conversions",
        ],
    ),
    "account": (
        "ACCOUNT_PERFORMANCE_REPORT",
        ["Date", "Impressions", "Clicks", "Cost", "Ctr", "AvgCpc", "Conversions", "CostPerConversion"],
    ),
}  # fmt: skip


class ReportsClient:
    """Сервис Reports: TSV-отчёты с ожиданием готовности (201/202 + retryIn). Не Provider — без health_check."""

    def __init__(
        self,
        token: str,
        client_login: str | None = None,
        sandbox: bool = False,
        use_operator_units: bool = False,
        language: str = "ru",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.token = token
        self.transport = transport  # для тестов (httpx.MockTransport)
        self.client_login = client_login
        self.base_url = SANDBOX_BASE if sandbox else PROD_BASE
        self.use_operator_units = use_operator_units
        self.language = language

    def headers(
        self,
        *,
        processing_mode: str = "auto",
        money_in_micros: bool = False,
        skip_report_header: bool = True,
        skip_column_header: bool = False,
        skip_report_summary: bool = True,
        language: str | None = None,
    ) -> dict[str, str]:
        """Заголовки запроса отчёта (без токена — его добавляет `fetch`)."""
        h = {
            "Accept-Language": language or self.language,
            "processingMode": processing_mode,
            "returnMoneyInMicros": "true" if money_in_micros else "false",
            "skipReportHeader": "true" if skip_report_header else "false",
            "skipColumnHeader": "true" if skip_column_header else "false",
            "skipReportSummary": "true" if skip_report_summary else "false",
        }
        if self.client_login:
            h["Client-Login"] = self.client_login
        if self.use_operator_units:
            h["Use-Operator-Units"] = "true"
        return h

    async def fetch(self, params: dict[str, Any], headers: dict[str, str], *, max_wait_sec: int = 1200) -> Report:
        """Отправить ReportDefinition и дождаться TSV (200), повторяя по retryIn на 201/202."""
        payload = json.dumps({"params": params}, ensure_ascii=False).encode("utf-8")
        url = f"{self.base_url}/reports"
        all_headers = {
            **headers,
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        elapsed = 0
        async with httpx.AsyncClient(timeout=120, transport=self.transport) as client:
            while elapsed < max_wait_sec:
                resp = await client.post(url, content=payload, headers=all_headers)
                request_id = resp.headers.get("RequestId")
                if resp.status_code == 200:
                    return Report(tsv=resp.text, request_id=request_id, rows=None)
                if resp.status_code in (201, 202):
                    retry_in = int(resp.headers.get("retryIn", "10"))
                    log.info("Отчёт готовится, retryIn=%ss", retry_in)
                    await asyncio.sleep(retry_in)
                    elapsed += retry_in
                    continue
                try:
                    err = resp.json().get("error", {})
                except ValueError:
                    err = {}
                raise DirectAPIError(
                    error_code=int(err.get("error_code", resp.status_code)),
                    error_string=err.get("error_string", f"HTTP {resp.status_code}"),
                    error_detail=err.get("error_detail", resp.text[:500]),
                    request_id=request_id,
                )
        raise DirectAPIError(
            error_code=408,
            error_string="Report timeout",
            error_detail=f"Отчёт не готов за {max_wait_sec} с; повторите тот же запрос позже — он уже в очереди.",
            request_id=None,
        )

    async def run(
        self,
        report_type: str,
        field_names: list[str],
        date_from: str | None = None,
        date_to: str | None = None,
        date_range_type: str = "CUSTOM_DATE",
        report_name: str | None = None,
        filters: list[dict] | None = None,
        processing_mode: str = "auto",
        include_vat: str = "NO",
        goals: list[str] | None = None,
        max_wait_sec: int = 1200,
    ) -> Report:
        """Библиотечный вызов: собрать ReportDefinition из аргументов и получить отчёт."""
        criteria: dict[str, Any] = {}
        if date_range_type == "CUSTOM_DATE":
            if not (date_from and date_to):
                raise ValueError("CUSTOM_DATE требует date_from и date_to")
            criteria["DateFrom"] = date_from
            criteria["DateTo"] = date_to
        if filters:
            criteria["Filter"] = filters
        params: dict[str, Any] = {
            "SelectionCriteria": criteria,
            "FieldNames": field_names,
            "ReportType": report_type,
            "DateRangeType": date_range_type,
            "Format": "TSV",
            "IncludeVAT": include_vat,
        }
        if goals:
            params["Goals"] = goals
        params["ReportName"] = report_name or _named(params)
        return await self.fetch(params, self.headers(processing_mode=processing_mode), max_wait_sec=max_wait_sec)

    async def preset(
        self,
        name: str,
        date_from: str,
        date_to: str,
        campaign_ids: list[int] | None = None,
        extra_fields: list[str] | None = None,
    ) -> Report:
        """Пресет из PRESETS за период, с фильтром по кампаниям."""
        report_type, fields = PRESETS[name]
        filters = (
            [{"Field": "CampaignId", "Operator": "IN", "Values": [str(x) for x in campaign_ids]}]
            if campaign_ids
            else None
        )
        return await self.run(report_type, fields + (extra_fields or []), date_from, date_to, filters=filters)

    async def campaign_performance(self, date_from: str, date_to: str, extra_fields: list[str] | None = None) -> Report:
        return await self.preset("campaigns", date_from, date_to, extra_fields=extra_fields)

    async def ad_performance(self, date_from: str, date_to: str, extra_fields: list[str] | None = None) -> Report:
        return await self.preset("ads", date_from, date_to, extra_fields=extra_fields)

    async def search_query_performance(
        self,
        date_from: str,
        date_to: str,
        campaign_ids: list[int] | None = None,
        extra_fields: list[str] | None = None,
    ) -> Report:
        return await self.preset("queries", date_from, date_to, campaign_ids, extra_fields)

    async def account_performance(self, date_from: str, date_to: str, extra_fields: list[str] | None = None) -> Report:
        return await self.preset("account", date_from, date_to, extra_fields=extra_fields)


def _named(params: dict[str, Any]) -> str:
    return report_name(params)
