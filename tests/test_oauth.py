"""Тесты OAuth — без реальных запросов к Яндексу."""

import pytest
import respx
from httpx import Response

from rb_yandex_direct.core.errors import DirectAuthError
from rb_yandex_direct.core.oauth import TOKEN_URL, OAuthToken, YandexOAuth


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_ok() -> None:
    respx.post(TOKEN_URL).mock(
        return_value=Response(200, json={
            "access_token": "y0_AA",
            "refresh_token": "y0_RR",
            "expires_in": 31536000,
            "token_type": "bearer",
        })
    )
    oauth = YandexOAuth("id", "secret")
    tok = await oauth.exchange_code("code123")
    assert tok.access_token == "y0_AA"
    assert tok.refresh_token == "y0_RR"
    assert tok.expires_at is not None
    assert tok.is_expired is False


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_error() -> None:
    respx.post(TOKEN_URL).mock(return_value=Response(400, text="bad code"))
    oauth = YandexOAuth("id", "secret")
    with pytest.raises(DirectAuthError):
        await oauth.exchange_code("bad")


def test_build_authorize_url() -> None:
    oauth = YandexOAuth("APP", "SEC")
    url = oauth.build_authorize_url("http://localhost:1234/", "ST")
    assert "client_id=APP" in url
    assert "scope=direct%3Aapi+passport%3Abusiness" in url
    assert "state=ST" in url
    assert "response_type=code" in url


def test_token_empty_credentials() -> None:
    with pytest.raises(DirectAuthError):
        YandexOAuth("", "secret")


def test_token_to_env_dict() -> None:
    tok = OAuthToken(access_token="AA", refresh_token="RR")
    env = tok.to_env_dict()
    assert env["YANDEX_DIRECT_TOKEN"] == "AA"
    assert env["YANDEX_DIRECT_REFRESH_TOKEN"] == "RR"
