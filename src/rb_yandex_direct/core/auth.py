"""Токен Директа — общая библиотека rb-yandex-oauth (keychain ОС + переменные окружения).

- keychain: `yandex-oauth:direct`;
- env: `YANDEX_OAUTH_DIRECT_<FIELD>` (TOKEN, REFRESH_TOKEN, CLIENT_ID, CLIENT_SECRET, EXPIRES_AT);
  задан `YANDEX_OAUTH_DIRECT_REFRESH_TOKEN` — keychain не читается, токен обновляется в памяти;
- `YANDEX_DIRECT_TOKEN` — готовый access-токен без автообновления (разовые запуски, тесты).

`.env`-файлы не читаются. Client-Login (`--login`, конфиг проекта, `YANDEX_DIRECT_LOGIN`) —
не секрет и не часть токена.
"""

from __future__ import annotations

from rb_yandex_oauth import TokenStore

from ..constants import PROFILE
from ..credentials import manager as credentials
from .errors import AuthRequired

store = TokenStore(PROFILE, credentials.store)


def resolve_token() -> str:
    """Действующий access-токен (обновляется сам по refresh_token); нет токена — AuthRequired."""
    token, _refreshable = store.resolve()
    if not token:
        raise AuthRequired(PROFILE)
    return token
