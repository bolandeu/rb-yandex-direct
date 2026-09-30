"""Имена, от которых зависят пути и ключи хранилищ. Держим в одном месте:
Python-пакет называется rb_yandex_direct, дистрибутив — rb-yandex-direct, команда — yd."""

from __future__ import annotations

from yandex_oauth import Profile

from ._distribution import DIST_NAME

# У Директа свой слот keychain `yandex-oauth:direct`, а не общий `yandex-oauth:yandex` ym/ywm:
# API Директа принимает токен только от приложения с подтверждённой заявкой на доступ
# (иначе код 58) и правами `direct:api passport:business`.
PROFILE = Profile(
    cli_name="yd",
    token_env="YANDEX_DIRECT_TOKEN",  # noqa: S106 — это ИМЯ переменной окружения, не секрет
    scopes="direct:api passport:business",
    service="Яндекс.Директ",
    provider="direct",
)
CLI_NAME = PROFILE.cli_name

__all__ = ["CLI_NAME", "DIST_NAME", "PROFILE"]
