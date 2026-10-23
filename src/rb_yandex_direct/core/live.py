"""v4 Live: клиент для команды и финансовый доступ (мастер-токен, финансовый токен, номер операции).

Финансовый токен (dg-v4/concepts/finance-token) — SHA-256 от конкатенации: мастер-токен +
номер операции + имя метода + [операция AccountManagement] + логин, от имени которого запрос
(точки → дефисы, строчные буквы). Номер операции — целое 1…9223372036854775807, строго больше,
чем в любом прошлом финансовом вызове этого логина (с любой машины).

- мастер-токен и логин — секрет в keychain `yandex-oauth:direct_finance` (`yd finance setup`)
  или env YANDEX_OAUTH_DIRECT_FINANCE_MASTER_TOKEN / YANDEX_OAUTH_DIRECT_FINANCE_LOGIN;
- номер операции — `platformdirs.user_data_dir("yd")/finance.json`; следующий номер —
  max(прошлый + 1, текущее время в мс), поэтому растёт и при вызовах с разных машин.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import platformdirs

from ..credentials import manager as credentials
from ..providers.live import Finance, LiveClient
from . import services
from .auth import resolve_token
from .errors import CliError, InvalidArguments
from .version import cli_name

FINANCE_PROVIDER = "direct_finance"
FINANCE_FIELDS = ("master_token", "login")
MAX_OPERATION_NUM = 9_223_372_036_854_775_807


def live(ctx_obj: dict) -> LiveClient:
    """LiveClient с тем же кабинетом и песочницей, что у v5-команд (`services.connection`)."""
    conn = services.connection(ctx_obj)
    return LiveClient(token=resolve_token(), client_login=conn["client_login"], sandbox=conn["sandbox"])


def normalize_login(login: str) -> str:
    """Логин для финансового токена: без пробелов по краям, строчные, точки → дефисы."""
    normalized = login.strip().lower().replace(".", "-")
    if not normalized:
        raise InvalidArguments("Пустой логин для финансового токена.")
    return normalized


def finance_token(master_token: str, operation_num: int, method: str, login: str, action: str = "") -> str:
    """SHA-256(мастер-токен + номер операции + метод + операция AccountManagement + логин)."""
    payload = f"{master_token.strip()}{operation_num}{method}{action}{normalize_login(login)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class FinanceNotConfigured(CliError):
    def __init__(self) -> None:
        env = ", ".join(credentials.store.env_var_name(FINANCE_PROVIDER, f) for f in FINANCE_FIELDS)
        super().__init__(
            "AUTH_REQUIRED",
            "Нет мастер-токена для финансовых операций Директа.",
            action=f"Выполните '{cli_name()} finance setup' или задайте {env}.",
            exit_code=3,
        )


def finance_credential() -> dict[str, str]:
    """{"master_token", "login"} из keychain/env; чего-то нет — FinanceNotConfigured."""
    bag = credentials.get_credential(FINANCE_PROVIDER, env_fields=list(FINANCE_FIELDS)) or {}
    if not bag.get("master_token") or not bag.get("login"):
        raise FinanceNotConfigured()
    return bag


def store_finance_credential(master_token: str, login: str) -> None:
    credentials.store_credential(FINANCE_PROVIDER, {"master_token": master_token.strip(), "login": login.strip()})


def delete_finance_credential() -> None:
    credentials.delete_credential(FINANCE_PROVIDER)


def state_path() -> Path:
    return Path(platformdirs.user_data_dir(cli_name())) / "finance.json"


def last_operation_num() -> int:
    try:
        return int(json.loads(state_path().read_text(encoding="utf-8")).get("last_operation_num", 0))
    except OSError, ValueError:
        return 0


def next_operation_num() -> int:
    """Следующий номер (без записи): больше прошлого и не меньше текущего времени в мс."""
    return max(last_operation_num() + 1, int(time.time() * 1000))


def commit_operation_num(num: int) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_operation_num": num}), encoding="utf-8")


def finance(method: str, action: str = "") -> Finance:
    """Финансовые поля для вызова: номер операции фиксируется сразу — до запроса, чтобы не повториться."""
    cred = finance_credential()
    num = next_operation_num()
    if num > MAX_OPERATION_NUM:
        raise InvalidArguments("Номер финансовой операции вышел за предел API; сбросьте счётчик в Директе.")
    commit_operation_num(num)
    return Finance(finance_token(cred["master_token"], num, method, cred["login"], action), num)
