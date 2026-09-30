"""ReportsClient — асинхронные TSV-отчёты.

Алгоритм по оф. доке (подтверждён примерами в context7):
- POST JSON на /json/v5/reports
- 200 — отчёт готов, тело = TSV
- 201 / 202 — отчёт в очереди или формируется; читать заголовок retryIn и
  повторить через указанное число секунд
- 400 — ошибка параметров или переполнение очереди
- 500 — внутренняя ошибка

processingMode: ONLINE | OFFLINE | AUTO (default AUTO).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from ..core.errors import DirectAPIError
from .direct import PROD_BASE, SANDBOX_BASE

log = logging.getLogger(__name__)


@dataclass
class Report:
    tsv: str
    request_id: str | None
    rows: int | None

    def parse(self) -> list[dict[str, str]]:
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
            out.append(dict(zip(header, parts, strict=True)))
        return out


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

    def _headers(self, processing_mode: str = "auto", skip_report_summary: bool = False) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.token}",
            "Accept-Language": self.language,
            "processingMode": processing_mode,
            "returnMoneyInMicros": "false",
            "Content-Type": "application/json; charset=utf-8",
        }
        if self.client_login:
            h["Client-Login"] = self.client_login
        if self.use_operator_units:
            h["Use-Operator-Units"] = "true"
        if skip_report_summary:
            h["skipReportSummary"] = "true"
        return h

    async def run(
        self,
        report_type: str,
        field_names: list[str],
        date_from: str | None = None,
        date_to: str | None = None,
        date_range_type: str = "CUSTOM_DATE",
        report_name: str = "yd",
        filters: list[dict] | None = None,
        processing_mode: str = "auto",
        include_vat: str = "NO",
        goals: list[str] | None = None,
        max_wait_sec: int = 1200,
    ) -> Report:
        criteria: dict[str, Any] = {}
        if date_range_type == "CUSTOM_DATE":
            if not (date_from and date_to):
                raise ValueError("CUSTOM_DATE требует date_from и date_to")
            criteria["DateFrom"] = date_from
            criteria["DateTo"] = date_to
        if filters:
            criteria["Filter"] = filters

        body = {
            "params": {
                "SelectionCriteria": criteria,
                "FieldNames": field_names,
                "ReportName": report_name,
                "ReportType": report_type,
                "DateRangeType": date_range_type,
                "Format": "TSV",
                "IncludeVAT": include_vat,
            }
        }
        if goals:
            body["params"]["Goals"] = goals

        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        url = f"{self.base_url}/reports"
        headers = self._headers(processing_mode)

        elapsed = 0
        async with httpx.AsyncClient(timeout=120, transport=self.transport) as client:
            while elapsed < max_wait_sec:
                resp = await client.post(url, content=payload, headers=headers)
                request_id = resp.headers.get("RequestId")
                if resp.status_code == 200:
                    return Report(tsv=resp.text, request_id=request_id, rows=None)
                if resp.status_code in (201, 202):
                    retry_in = int(resp.headers.get("retryIn", "10"))
                    log.info("Отчёт готовится, retryIn=%ss", retry_in)
                    await asyncio.sleep(retry_in)
                    elapsed += retry_in
                    continue
                if resp.status_code == 400:
                    try:
                        err = resp.json().get("error", {})
                    except Exception:
                        err = {}
                    raise DirectAPIError(
                        error_code=int(err.get("error_code", 400)),
                        error_string=err.get("error_string", "Bad Request"),
                        error_detail=err.get("error_detail", resp.text[:500]),
                        request_id=request_id,
                    )
                raise DirectAPIError(
                    error_code=resp.status_code,
                    error_string=f"HTTP {resp.status_code}",
                    error_detail=resp.text[:500],
                    request_id=request_id,
                )
        raise DirectAPIError(
            error_code=408,
            error_string="Report timeout",
            error_detail=f"Отчёт не готов за {max_wait_sec}s",
            request_id=None,
        )

    # ---- Пресеты популярных отчётов ----
    # Поля — минимально достаточный набор для медиабайера. Можно расширять
    # параметром extra_fields.

    async def campaign_performance(
        self,
        date_from: str,
        date_to: str,
        extra_fields: list[str] | None = None,
    ) -> Report:
        fields = [
            "Date",
            "CampaignId",
            "CampaignName",
            "CampaignType",
            "Impressions",
            "Clicks",
            "Cost",
            "Ctr",
            "AvgCpc",
            "Conversions",
            "CostPerConversion",
            "Bounces",
            "AvgImpressionPosition",
        ] + (extra_fields or [])
        return await self.run(
            report_type="CAMPAIGN_PERFORMANCE_REPORT",
            field_names=fields,
            date_from=date_from,
            date_to=date_to,
            report_name=f"cpr-{date_from}-{date_to}",
        )

    async def ad_performance(
        self,
        date_from: str,
        date_to: str,
        extra_fields: list[str] | None = None,
    ) -> Report:
        fields = [
            "Date",
            "CampaignId",
            "AdGroupId",
            "AdId",
            "Impressions",
            "Clicks",
            "Cost",
            "Ctr",
            "AvgCpc",
            "Conversions",
        ] + (extra_fields or [])
        return await self.run(
            report_type="AD_PERFORMANCE_REPORT",
            field_names=fields,
            date_from=date_from,
            date_to=date_to,
            report_name=f"adpr-{date_from}-{date_to}",
        )

    async def search_query_performance(
        self,
        date_from: str,
        date_to: str,
        campaign_ids: list[int] | None = None,
        extra_fields: list[str] | None = None,
    ) -> Report:
        fields = [
            "Date",
            "CampaignId",
            "AdGroupId",
            "CriterionId",
            "Criterion",
            "Query",
            "MatchType",
            "Impressions",
            "Clicks",
            "Cost",
            "Ctr",
            "AvgCpc",
            "Conversions",
        ] + (extra_fields or [])
        filters: list[dict] = []
        if campaign_ids:
            filters.append(
                {
                    "Field": "CampaignId",
                    "Operator": "IN",
                    "Values": [str(x) for x in campaign_ids],
                }
            )
        return await self.run(
            report_type="SEARCH_QUERY_PERFORMANCE_REPORT",
            field_names=fields,
            date_from=date_from,
            date_to=date_to,
            filters=filters or None,
            report_name=f"sqpr-{date_from}-{date_to}",
        )

    async def account_performance(
        self,
        date_from: str,
        date_to: str,
        extra_fields: list[str] | None = None,
    ) -> Report:
        fields = [
            "Date",
            "Impressions",
            "Clicks",
            "Cost",
            "Ctr",
            "AvgCpc",
            "Conversions",
            "CostPerConversion",
        ] + (extra_fields or [])
        return await self.run(
            report_type="ACCOUNT_PERFORMANCE_REPORT",
            field_names=fields,
            date_from=date_from,
            date_to=date_to,
            report_name=f"accpr-{date_from}-{date_to}",
        )
