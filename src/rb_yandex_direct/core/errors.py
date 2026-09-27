"""Исключения. Код 1002 — неверный/истёкший токен (из оф. документации)."""


class DirectError(Exception):
    pass


class DirectAuthError(DirectError):
    pass


class DirectAPIError(DirectError):
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
        super().__init__(f"[{error_code}] {error_string}: {error_detail} (RequestId={request_id})")

    @property
    def is_auth_error(self) -> bool:
        return self.error_code == 1002
