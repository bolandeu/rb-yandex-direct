from __future__ import annotations

# Базовый класс и ошибки авторизации — общие с yandex-oauth, чтобы output.guard
# ловил и ошибки общего кода (OAuth, keychain) как свои.
from yandex_oauth.errors import (
    AuthRequired,
    CliError,
    CredentialStoreUnavailable,
    CredentialsUnhealthy,
    InvalidArguments,
)

from .._distribution import DIST_NAME
from .version import cli_name

__all__ = [
    "Aborted",
    "AuthRequired",
    "CliError",
    "CliTooOld",
    "CredentialStoreUnavailable",
    "CredentialsUnhealthy",
    "DependencyTooOld",
    "DirectAPIError",
    "InvalidArguments",
    "ProjectNotInitialized",
    "ProviderError",
]

# The real command (may differ from the package name) for `action` hints;
# `uv tool upgrade` takes the distribution name, which is the package's.
_CLI = cli_name()
_DIST = DIST_NAME


class ProjectNotInitialized(CliError):
    def __init__(self, path: str) -> None:
        super().__init__(
            "PROJECT_NOT_INITIALIZED",
            f"Проект не найден в '{path}' и выше по дереву каталогов.",
            action=f"Выполните '{_CLI} init' в каталоге проекта.",
            exit_code=4,
        )


class DependencyTooOld(CliError):
    """Another CLI this one calls is missing or older than required (core/deps.py).

    `dist` is its distribution name — what `uv tool` knows it by (`rb-serp`
    for the `serp` command, standard §10). With `install_url` the action is a
    pinned, runnable install; without it, what to install and no fake URL.
    """

    def __init__(
        self,
        name: str,
        installed: str | None,
        required: str | None,
        *,
        install_url: str | None = None,
        dist: str | None = None,
    ) -> None:
        dist = dist or name
        found = "is not installed" if installed is None else f"is {installed}"
        need = f"{name} >= {required}" if required else name
        if install_url:
            repo = install_url.removesuffix(".git")
            tag = f"v{required}" if required else "<latest release tag>"
            action = f"Run 'uv tool install \"{dist} @ git+{repo}.git@{tag}\" --force', then retry."
        elif installed is not None:
            action = f"Run 'uv tool upgrade {dist}', then retry."
        else:
            action = f"Install {need} (distribution {dist}; see its README for the install command), then retry."
        super().__init__(
            "DEPENDENCY_TOO_OLD",
            f"'{name}' {found}; {_CLI} needs {need}.",
            action=action,
            exit_code=1,
        )


class ProviderError(CliError):
    """An external service failed: network, timeout, HTTP 5xx/429, malformed response.

    `status` is the HTTP status when there was one. Raised by
    `providers.HttpProvider` after its retries are exhausted — commands and
    services normally don't construct this themselves.
    """

    def __init__(self, provider: str, message: str, *, status: int | None = None, action: str | None = None) -> None:
        super().__init__(
            "PROVIDER_ERROR",
            f"Provider '{provider}': {message}",
            action=action or "Retry later; if it keeps failing, check the provider's status page.",
            exit_code=5,
        )
        self.provider = provider
        self.status = status

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["provider"] = self.provider
        if self.status is not None:
            payload["status"] = self.status
        return payload


class CliTooOld(CliError):
    def __init__(self, installed: str, required: str) -> None:
        super().__init__(
            "CLI_TOO_OLD",
            f"This project requires {_CLI} >= {required}, but {installed} is installed.",
            action=f"Run 'uv tool upgrade {_DIST}' (or lower cli.min_version in the project's config.toml).",
            exit_code=6,
        )


class Aborted(CliError):
    def __init__(self, description: str) -> None:
        super().__init__("ABORTED", f"{description}: отменено пользователем.", exit_code=1)


# Коды ошибок API, означающие «токен, приложение или доступ к кабинету не годятся», а не сбой
# сервиса: 53 — ошибка авторизации, 54 — нет прав, 58 — заявка на доступ к API не подтверждена,
# 513 — логин не подключён к Директу, 1002 — токен недействителен.
CREDENTIAL_ERROR_CODES = frozenset({53, 54, 58, 513, 1002})


class DirectAPIError(CliError):
    """Ошибка из ответа Директа (`{"error": {error_code, error_string, error_detail}}`) или HTTP-сбой.

    Учётные данные (CREDENTIAL_ERROR_CODES) → AUTH_REQUIRED, exit 3, с подсказкой войти заново;
    всё остальное → PROVIDER_ERROR, exit 5. `api_code` и `request_id` попадают в JSON-конверт:
    по RequestId поддержка Директа находит запрос.
    """

    def __init__(
        self,
        error_code: int,
        error_string: str,
        error_detail: str = "",
        request_id: str | None = None,
    ) -> None:
        self.error_code = error_code
        self.error_string = error_string
        self.error_detail = error_detail
        self.request_id = request_id
        text = f"[{error_code}] {error_string}" + (f": {error_detail}" if error_detail else "")
        if self.is_auth_error:
            super().__init__(
                "AUTH_REQUIRED",
                f"Директ не принял учётные данные: {text}",
                action=f"Проверьте заявку на доступ к API и выполните '{_CLI} auth login'.",
                exit_code=3,
            )
        else:
            super().__init__("PROVIDER_ERROR", f"Директ: {text}", exit_code=5)

    @property
    def is_auth_error(self) -> bool:
        return self.error_code in CREDENTIAL_ERROR_CODES

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["provider"] = "direct"
        payload["api_code"] = self.error_code
        if self.request_id:
            payload["request_id"] = self.request_id
        return payload
