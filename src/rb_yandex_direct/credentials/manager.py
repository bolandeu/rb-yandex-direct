"""Keychain ОС + переменные окружения — общая реализация из yandex-oauth.

Слот Директа — `yandex-oauth:direct`; env — `YANDEX_OAUTH_DIRECT_<FIELD>`.
`keyring` реэкспортирован намеренно: тесты подменяют его in-memory-хранилищем.
"""

from __future__ import annotations

from rb_yandex_oauth import CredentialStore
from rb_yandex_oauth.credentials import keyring  # noqa: F401 — патч-цель тестов

from ..constants import PROFILE

store = CredentialStore(PROFILE)

read_fields_from_env = store.read_fields_from_env
get_credential = store.get_credential
store_credential = store.store_credential
delete_credential = store.delete_credential
get_secret = store.get_secret
store_secret = store.store_secret
read_secret_from_env = store.read_secret_from_env
delete_secret = store.delete_secret
