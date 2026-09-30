"""`yd finance` и `yd shared-account` — ДЕНЬГИ: финансовые методы API Директа v4 Live.

Нужен мастер-токен (Директ → Настройки API → Финансовые операции → «Выдать новый мастер-токен»):
`yd finance setup` кладёт его в keychain. Финансовый токен и номер операции CLI считает сам
(`core.live`). Все переводы, оплаты, пополнения и счета — только через --dry-run → --confirm.
"""

from __future__ import annotations

import sys
from enum import StrEnum
from typing import Any

import typer

from .. import output
from ..core import live as core_live
from ..core import services
from ..core.errors import InvalidArguments
from ..credentials import manager as credentials
from . import _live
from ._common import emit_list, emit_object

app = output.group(
    "ДЕНЬГИ: финансы API Директа v4 — мастер-токен, баллы, кредитные лимиты, счета, оплата и перевод между кампаниями."
)

PayOption = typer.Option(..., "--pay", help="Кампания и сумма в валюте: CAMPAIGN_ID=СУММА (повторяемая).")


# --- доступ ---------------------------------------------------------------------------------


@app.command("setup")
@output.guard
def setup(
    ctx: typer.Context,
    finance_login: str = typer.Option(
        None, "--finance-login", help="Логин, от имени которого идут финансовые вызовы (владелец OAuth-токена)."
    ),
    master_token_stdin: bool = typer.Option(
        False, "--master-token-stdin", help="Прочитать мастер-токен из stdin (скрипты); иначе — скрытый ввод."
    ),
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Сохранить мастер-токен финансовых операций и логин в keychain (yandex-oauth:direct_finance).

    Мастер-токен выдаётся один раз: Директ → Настройки API → Финансовые операции →
    «Разрешить финансовые операции» → «Выдать новый мастер-токен» (подтверждение по SMS).
    Без keychain (сервер) — env YANDEX_OAUTH_DIRECT_FINANCE_MASTER_TOKEN и
    YANDEX_OAUTH_DIRECT_FINANCE_LOGIN, setup не нужен. Токен в аргументах не принимается.

    Example: {cli} finance setup --finance-login agency-login
    """
    interactive = not ctx.obj.get("non_interactive")
    if master_token_stdin:
        token = sys.stdin.readline().strip()
    elif interactive:
        token = typer.prompt("Мастер-токен", hide_input=True, err=True).strip()
    else:
        raise InvalidArguments("С --non-interactive передайте мастер-токен через --master-token-stdin.")
    if not finance_login:
        if not interactive:
            raise InvalidArguments("Укажите --finance-login.")
        finance_login = typer.prompt("Логин для финансовых операций", err=True).strip()
    if not token or not finance_login:
        raise InvalidArguments("Нужны и мастер-токен, и логин.")
    core_live.store_finance_credential(token, finance_login)
    output.emit_success(
        ctx,
        {"login": finance_login, "stored": "keychain"},
        lambda d: output.human.echo(f"Мастер-токен для {d['login']} сохранён в keychain."),
    )


@app.command("forget")
@output.guard
def forget(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить мастер-токен и логин из keychain (переменные окружения не трогает).

    Example: {cli} finance forget
    """
    core_live.delete_finance_credential()
    output.emit_success(ctx, {"deleted": True}, lambda _: output.human.echo("Мастер-токен удалён из keychain."))


@app.command("status")
@output.guard
def status(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Готовность финансовых операций: есть ли мастер-токен (откуда), логин, последний номер операции.

    Значений секретов не печатает и в сеть не ходит.
    --json: {"ok": true, "configured": bool, "source": "env"|"keychain"|null, "login", "last_operation_num", "state_file"}.

    Example: {cli} finance status --json
    """
    env = credentials.read_fields_from_env(core_live.FINANCE_PROVIDER, list(core_live.FINANCE_FIELDS))
    bag = credentials.get_credential(core_live.FINANCE_PROVIDER, env_fields=list(core_live.FINANCE_FIELDS)) or {}
    configured = bool(bag.get("master_token") and bag.get("login"))
    payload = {
        "configured": configured,
        "source": ("env" if env.get("master_token") else "keychain") if configured else None,
        "login": bag.get("login"),
        "last_operation_num": core_live.last_operation_num() or None,
        "state_file": str(core_live.state_path()),
    }
    output.emit_success(ctx, payload, lambda d: output.human.key_values("Финансовые операции", d))


# --- чтение ---------------------------------------------------------------------------------


@app.command("units")
@output.guard
def units(
    ctx: typer.Context,
    clients: list[str] = typer.Option(..., "--client", help="Логин (повторяемая)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Остаток баллов API по логинам (GetClientsUnits).

    --json: {"ok": true, "count": N, "units": [{Login, UnitsRest}]}.

    Example: {cli} finance units --client shop@yandex.ru --json
    """
    items = _live.call(ctx, "GetClientsUnits", clients) or []
    emit_list(ctx, "units", items, [("Логин", "Login"), ("Баллы", "UnitsRest")], title="Баллы API")


@app.command("credit-limits")
@output.guard
def credit_limits(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Кредитные лимиты агентства по договорам (GetCreditLimits). Нужен мастер-токен.

    Расходует номер финансовой операции. --json: {"ok": true, "limits": {Currency, Limits: [{ContractID,
    Limit, LimitSpent}]}}.

    Example: {cli} finance credit-limits --json
    """
    fin = core_live.finance("GetCreditLimits")
    data = services.run(core_live.live(ctx.obj).call("GetCreditLimits", finance=fin)) or {}
    emit_object(ctx, "limits", data, title="Кредитные лимиты")


@app.command("check-payment")
@output.guard
def check_payment(
    ctx: typer.Context,
    transaction_id: str = typer.Argument(..., help="CustomTransactionID платежа (32 символа)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Статус платежа по его CustomTransactionID (CheckPayment).

    Example: {cli} finance check-payment A123456789012345678901234567890B --json
    """
    data = _live.call(ctx, "CheckPayment", {"CustomTransactionID": transaction_id})
    emit_object(ctx, "payment", data, title=f"Платёж {transaction_id}")


# --- деньги ---------------------------------------------------------------------------------


def _camp_payments(pairs: list[str], option: str, currency: str) -> list[dict]:
    return [
        {"CampaignID": ident, "Sum": total, "Currency": currency.upper()}
        for ident, total in _live.parse_pairs(pairs, option)
    ]


@app.command("invoice")
@output.guard
def invoice(
    ctx: typer.Context,
    pays: list[str] = PayOption,
    currency: str = _live.CurrencyOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """ДЕНЬГИ: выставить счёт на оплату кампаний (CreateInvoice); вернуть ссылку на счёт.

    Суммы — в валюте, с НДС клиента. Нужен мастер-токен.

    Example: {cli} finance invoice --pay 12345=5000 --dry-run
    """
    param = {"Payments": _camp_payments(pays, "--pay", currency)}
    _live.mutate(
        ctx, title="Счёт на оплату кампаний", method="CreateInvoice", param=param, confirm=confirm, finance=True
    )


class PayMethod(StrEnum):
    Bank = "Bank"
    Overdraft = "Overdraft"


@app.command("pay")
@output.guard
def pay(
    ctx: typer.Context,
    pays: list[str] = PayOption,
    method: PayMethod = typer.Option(
        ..., "--method", help="Bank — из кредитного лимита агентства (нужен --contract), Overdraft — овердрафт."
    ),
    contract: str = typer.Option(None, "--contract", help="Номер договора (для --method Bank)."),
    currency: str = _live.CurrencyOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """ДЕНЬГИ: оплатить кампании из кредита агентства или овердрафта (PayCampaigns).

    Сразу пополняет баланс кампаний и создаёт обязательство оплатить счёт. Нужен мастер-токен.

    Example: {cli} finance pay --pay 12345=5000 --method Overdraft --dry-run
    """
    if method is PayMethod.Bank and not contract:
        raise InvalidArguments("Для --method Bank укажите --contract.")
    param: dict[str, Any] = {"Payments": _camp_payments(pays, "--pay", currency), "PayMethod": method.value}
    if contract:
        param["ContractID"] = contract
    _live.mutate(ctx, title="Оплатить кампании", method="PayCampaigns", param=param, confirm=confirm, finance=True)


@app.command("transfer")
@output.guard
def transfer(
    ctx: typer.Context,
    sources: list[str] = typer.Option(..., "--from", help="Откуда: CAMPAIGN_ID=СУММА (повторяемая)."),
    targets: list[str] = typer.Option(..., "--to", help="Куда: CAMPAIGN_ID=СУММА (повторяемая)."),
    currency: str = _live.CurrencyOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """ДЕНЬГИ: перевести деньги между кампаниями (TransferMoney); суммы «откуда» и «куда» равны.

    Доступную сумму кампании показывает Директ (SumAvailableForTransfer). Нужен мастер-токен.

    Example: {cli} finance transfer --from 111=1000 --to 222=1000 --dry-run
    """
    src = _camp_payments(sources, "--from", currency)
    dst = _camp_payments(targets, "--to", currency)
    if round(sum(p["Sum"] for p in src), 2) != round(sum(p["Sum"] for p in dst), 2):
        raise InvalidArguments("Сумма --from должна быть равна сумме --to.")
    _live.mutate(
        ctx,
        title="Перевести деньги между кампаниями",
        method="TransferMoney",
        param={"FromCampaigns": src, "ToCampaigns": dst},
        confirm=confirm,
        finance=True,
    )


# --- общий счёт -----------------------------------------------------------------------------

shared_app = output.group(
    "ДЕНЬГИ: общий счёт (API v4 AccountManagement): список, настройки, пополнение, счёт, перевод."
)

ACCOUNT_COLUMNS = [
    ("Счёт", "AccountID"),
    ("Логин", "Login"),
    ("Остаток", "Amount"),
    ("Можно перевести", "AmountAvailableForTransfer"),
    ("Валюта", "Currency"),
    ("Бюджет/день", "AccountDayBudget.Amount"),
]


@shared_app.command("list")
@output.guard
def shared_list(
    ctx: typer.Context,
    clients: list[str] = typer.Option(None, "--client", help="Логин клиента агентства (повторяемая, до 50)."),
    account_ids: list[int] = typer.Option(None, "--account", help="Id общего счёта (повторяемая, до 100)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Общие счета: остаток, доступно к переводу, дневной бюджет, уведомления (AccountManagement Get).

    Агентству нужен --client или --account. Суммы — в валюте счёта.
    --json: {"ok": true, "count": N, "accounts": [{AccountID, Login, Amount, AmountAvailableForTransfer,
    Currency, AccountDayBudget, SmsNotification, EmailNotification, …}]}.

    Example: {cli} shared-account list --json
    """
    criteria: dict[str, Any] = {}
    if clients:
        criteria["Logins"] = clients
    if account_ids:
        criteria["AccountIDS"] = account_ids
    param: dict[str, Any] = {"Action": "Get"}
    if criteria:
        param["SelectionCriteria"] = criteria
    data = _live.call(ctx, "AccountManagement", param) or {}
    emit_list(ctx, "accounts", data.get("Accounts") or [], ACCOUNT_COLUMNS, title="Общие счета")


@shared_app.command("update")
@output.guard
def shared_update(
    ctx: typer.Context,
    account_id: int = typer.Argument(..., help="Id общего счёта."),
    day_budget: float = typer.Option(None, "--day-budget", help="Дневной бюджет в валюте счёта; 0 — снять."),
    email: str = typer.Option(None, "--email", help="Почта для уведомлений."),
    money_warning: int = typer.Option(None, "--money-warning", help="Порог уведомления об остатке, % (1–50)."),
    notify_paused: bool = typer.Option(
        None, "--notify-paused/--no-notify-paused", help="Письмо при остановке по дневному бюджету."
    ),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить настройки общего счёта: дневной бюджет и почтовые уведомления (AccountManagement Update).

    Дневной бюджет можно менять не чаще 3 раз в сутки. Не указанное не меняется.

    Example: {cli} shared-account update 555 --day-budget 3000 --dry-run
    """
    account: dict[str, Any] = {"AccountID": account_id}
    if day_budget is not None:
        # SpendMode устарел, но остаётся обязательным полем AccountDayBudgetInfo.
        account["AccountDayBudget"] = {"Amount": day_budget, "SpendMode": "Default"}
    mail: dict[str, Any] = {}
    if email:
        mail["Email"] = email
    if money_warning is not None:
        mail["MoneyWarningValue"] = money_warning
    if notify_paused is not None:
        mail["PausedByDayBudget"] = "Yes" if notify_paused else "No"
    if mail:
        account["EmailNotification"] = mail
    if len(account) == 1:
        raise InvalidArguments("Нечего менять: --day-budget, --email, --money-warning или --notify-paused.")
    _live.mutate(
        ctx,
        title=f"Настройки общего счёта {account_id}",
        method="AccountManagement",
        param={"Action": "Update", "Accounts": [account]},
        confirm=confirm,
    )


def _account_payments(pairs: list[str], currency: str) -> list[dict]:
    return [
        {"AccountID": ident, "Amount": total, "Currency": currency.upper()}
        for ident, total in _live.parse_pairs(pairs, "--pay")
    ]


@shared_app.command("deposit")
@output.guard
def shared_deposit(
    ctx: typer.Context,
    pays: list[str] = typer.Option(..., "--pay", help="Счёт и сумма: ACCOUNT_ID=СУММА (повторяемая, до 50)."),
    contract: str = typer.Option(None, "--contract", help="Договор кредита агентства; нет — овердрафт рекламодателя."),
    currency: str = _live.CurrencyOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """ДЕНЬГИ: пополнить общие счета из кредита агентства или овердрафта (AccountManagement Deposit).

    Суммы — с НДС клиента. Нужен мастер-токен.

    Example: {cli} shared-account deposit --pay 555=10000 --dry-run
    """
    payments = _account_payments(pays, currency)
    for p in payments:
        p |= {"Contract": contract} if contract else {"Origin": "Overdraft"}
    _live.mutate(
        ctx,
        title="Пополнить общие счета",
        method="AccountManagement",
        param={"Action": "Deposit", "Payments": payments},
        confirm=confirm,
        finance=True,
        finance_action="Deposit",
    )


@shared_app.command("invoice")
@output.guard
def shared_invoice(
    ctx: typer.Context,
    pays: list[str] = typer.Option(..., "--pay", help="Счёт и сумма: ACCOUNT_ID=СУММА (повторяемая)."),
    currency: str = _live.CurrencyOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """ДЕНЬГИ: выставить счёт на пополнение общих счетов (AccountManagement Invoice); ссылки — в ActionsResult.

    Нужен мастер-токен.

    Example: {cli} shared-account invoice --pay 555=10000 --dry-run
    """
    _live.mutate(
        ctx,
        title="Счёт на пополнение общих счетов",
        method="AccountManagement",
        param={"Action": "Invoice", "Payments": _account_payments(pays, currency)},
        confirm=confirm,
        finance=True,
        finance_action="Invoice",
    )


@shared_app.command("transfer")
@output.guard
def shared_transfer(
    ctx: typer.Context,
    from_account: int = typer.Option(..., "--from", help="Id общего счёта-источника."),
    to_account: int = typer.Option(..., "--to", help="Id общего счёта-получателя."),
    amount: float = typer.Option(..., "--amount", help="Сумма в валюте счёта."),
    currency: str = _live.CurrencyOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """ДЕНЬГИ: перевести деньги между общими счетами (AccountManagement TransferMoney).

    Не больше 3 переводов в сутки с одного счёта. Нужен мастер-токен.

    Example: {cli} shared-account transfer --from 555 --to 556 --amount 1000 --dry-run
    """
    if amount <= 0 or round(amount, 2) != amount:
        raise InvalidArguments("--amount: сумма > 0, до копеек.")
    transfer_item = {
        "FromAccountID": from_account,
        "ToAccountID": to_account,
        "Amount": amount,
        "Currency": currency.upper(),
    }
    _live.mutate(
        ctx,
        title=f"Перевести {amount:g} {currency.upper()} со счёта {from_account} на {to_account}",
        method="AccountManagement",
        param={"Action": "TransferMoney", "Transfers": [transfer_item]},
        confirm=confirm,
        finance=True,
        finance_action="TransferMoney",
    )


@shared_app.command("enable")
@output.guard
def shared_enable(
    ctx: typer.Context,
    client_login: str = typer.Argument(..., help="Логин клиента агентства."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """ДЕНЬГИ: подключить клиенту общий счёт — деньги всех кампаний переносятся на него (EnableSharedAccount).

    Только для агентств; необратимо; у клиента должна быть хотя бы одна кампания.

    Example: {cli} shared-account enable shop-login --dry-run
    """
    _live.mutate(
        ctx,
        title=f"Подключить общий счёт клиенту {client_login}",
        method="EnableSharedAccount",
        param={"Login": client_login},
        confirm=confirm,
    )
