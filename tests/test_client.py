"""Тесты DirectClient — мокаем httpx через respx."""

import pytest
import respx
from httpx import Response

from rb_yandex_direct.core.errors import DirectAPIError
from rb_yandex_direct.providers.direct import PROD_BASE, SANDBOX_BASE, DirectClient


def test_sandbox_switch() -> None:
    assert DirectClient(token="t", sandbox=True).base_url == SANDBOX_BASE
    assert DirectClient(token="t").base_url == PROD_BASE


@pytest.mark.asyncio
@respx.mock
async def test_call_ok_and_headers() -> None:
    route = respx.post(f"{PROD_BASE}/campaigns").mock(
        return_value=Response(
            200,
            json={"result": {"Campaigns": [{"Id": 1, "Name": "Test"}]}},
            headers={"Units": "10/100/1000", "RequestId": "abc-1"},
        )
    )
    c = DirectClient(token="t", client_login="user", use_operator_units=True)
    result = await c.call("campaigns", "get", {"FieldNames": ["Id"]})

    assert result == {"Campaigns": [{"Id": 1, "Name": "Test"}]}
    assert c.last_units == "10/100/1000"
    assert c.last_request_id == "abc-1"

    req = route.calls.last.request
    assert req.headers["Authorization"] == "Bearer t"
    assert req.headers["Client-Login"] == "user"
    assert req.headers["Use-Operator-Units"] == "true"
    assert req.headers["Accept-Language"] == "ru"


@pytest.mark.asyncio
@respx.mock
async def test_call_error_1002() -> None:
    respx.post(f"{PROD_BASE}/campaigns").mock(
        return_value=Response(
            200, json={"error": {"error_code": 1002, "error_string": "Invalid token", "error_detail": "expired"}}
        )
    )
    c = DirectClient(token="t")
    with pytest.raises(DirectAPIError) as exc:
        await c.call("campaigns", "get")
    assert exc.value.error_code == 1002
    assert exc.value.is_auth_error
