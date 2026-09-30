"""DirectClient: повторы временных сбоев, разбор ответа, проверки методов структуры объявлений."""

from __future__ import annotations

import httpx
import pytest

from rb_yandex_direct.core.errors import DirectAPIError, InvalidArguments
from rb_yandex_direct.providers.direct import DirectClient


def _client(handler) -> DirectClient:
    client = DirectClient(token="t", transport=httpx.MockTransport(handler))
    client.backoff = 0
    return client


@pytest.mark.asyncio
async def test_retries_transport_errors_then_succeeds() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 3:
            raise httpx.ConnectError("нет сети")
        return httpx.Response(200, json={"result": {"ok": 1}}, headers={"Units": "1/2/3", "RequestId": "r"})

    client = _client(handler)
    assert await client.call("clients", "get") == {"ok": 1}
    assert len(calls) == 3
    assert (client.last_units, client.last_request_id) == ("1/2/3", "r")


@pytest.mark.asyncio
async def test_network_failure_after_retries_is_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("долго")

    with pytest.raises(DirectAPIError) as info:
        await _client(handler).call("clients", "get")
    assert (info.value.code, info.value.exit_code) == ("PROVIDER_ERROR", 5)


@pytest.mark.asyncio
async def test_retries_temporary_api_code_and_5xx() -> None:
    responses = iter(
        [
            httpx.Response(200, json={"error": {"error_code": 1000, "error_string": "Недоступно"}}),
            httpx.Response(503, text="busy"),
            httpx.Response(200, json={"result": {"Clients": []}}),
        ]
    )
    assert await _client(lambda r: next(responses)).call("clients", "get") == {"Clients": []}


@pytest.mark.asyncio
async def test_5xx_without_body_after_retries() -> None:
    with pytest.raises(DirectAPIError) as info:
        await _client(lambda r: httpx.Response(502, text="bad gateway")).call("clients", "get")
    assert info.value.error_code == 502


@pytest.mark.asyncio
async def test_invalid_json_on_4xx() -> None:
    with pytest.raises(DirectAPIError, match="Invalid JSON"):
        await _client(lambda r: httpx.Response(400, text="<html>")).call("clients", "get")


@pytest.mark.asyncio
async def test_non_dict_json_is_empty_result() -> None:
    assert await _client(lambda r: httpx.Response(200, json=[1, 2])).call("clients", "get") == {}


@pytest.mark.asyncio
async def test_structure_methods_validate_before_request() -> None:
    client = _client(lambda r: pytest.fail("запроса быть не должно"))
    checks = [
        client.list_ad_videos([]),
        client.add_ad_videos([]),
        client.add_ad_videos([{"Name": "без источника"}]),
        client.list_leads([]),
        client.add_ad_images([]),
        client.add_ad_images([{"ImageData": "x", "Name": "a"}] * 101),
        client.add_sitelinks([]),
        client.add_vcards([]),
        client.add_ad_extensions([]),
        client.add_creatives([]),
        client.update_ads([{"TextAd": {}}]),
        client.update_adgroups([{"Name": "без Id"}]),
    ]
    for coro in checks:
        with pytest.raises(InvalidArguments):
            await coro


@pytest.mark.asyncio
async def test_get_ad_and_adgroup_none_when_missing() -> None:
    client = _client(lambda r: httpx.Response(200, json={"result": {}}))
    assert await client.get_ad(1) is None
    assert await client.get_adgroup(1) is None
