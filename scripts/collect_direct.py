"""Скрипт для /direct-report, этап 1 — собрать данные в JSON.

ЧЕРНОВИК. Пишет JSON-срез одного клиента в cache-директорию:
  clients.json, campaigns.json, balance.json,
  reports/{campaigns,queries,ads,account}.tsv

Использование:
  uv run python scripts/collect_direct.py \\
      --login client@yandex.ru \\
      --date-from 2026-04-14 --date-to 2026-04-20 \\
      --out .cache/direct/2026-04-20/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from rb_yandex_direct.core.auth import resolve_token
from rb_yandex_direct.providers.direct import DirectClient
from rb_yandex_direct.providers.reports import ReportsClient


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


async def collect(login: str | None, date_from: str, date_to: str, out_dir: Path) -> None:
    token = resolve_token()
    sandbox = os.getenv("YANDEX_DIRECT_SANDBOX", "").lower() == "true"

    client = DirectClient(token=token, client_login=login, sandbox=sandbox)
    reports = ReportsClient(token=token, client_login=login, sandbox=sandbox)

    _dump(out_dir / "clients.json", await client.list_clients())
    _dump(out_dir / "campaigns.json", await client.list_campaigns())
    _dump(out_dir / "adgroups.json", await client.list_adgroups())

    # 4 базовых отчёта
    for name, coro in [
        ("campaigns", reports.campaign_performance(date_from, date_to)),
        ("ads", reports.ad_performance(date_from, date_to)),
        ("queries", reports.search_query_performance(date_from, date_to)),
        ("account", reports.account_performance(date_from, date_to)),
    ]:
        rep = await coro
        path = out_dir / "reports" / f"{name}.tsv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rep.tsv)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--login", help="Client-Login (если агентский доступ)")
    p.add_argument("--date-from", required=True, help="YYYY-MM-DD")
    p.add_argument("--date-to", required=True)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    asyncio.run(collect(args.login, args.date_from, args.date_to, args.out))
    print(f"Собрано в {args.out}")


if __name__ == "__main__":
    main()
