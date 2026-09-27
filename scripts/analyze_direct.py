"""Скрипт для /direct-report, этап 2 — построить markdown-отчёт.

ЧЕРНОВИК. Читает JSON/TSV срез из cache-директории, печатает отчёт:
  — баланс API-баллов и остаток бюджета;
  — ТОП-5 кампаний по расходу и по CTR;
  — ТОП-20 поисковых запросов без конверсий (кандидаты в минус-слова);
  — объявления на модерации/отклонённые.

Использование:
  uv run python scripts/analyze_direct.py --cache .cache/direct/2026-04-20/ > report.md
"""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path


def _read_tsv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    text = path.read_text()
    # Формат отчётов Яндекса: первая строка — служебная (имя отчёта),
    # вторая — заголовки, последняя — Total rows. Режем по факту.
    lines = text.splitlines()
    header_idx = 1 if lines and not lines[0].startswith("Date") else 0
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])), delimiter="\t")
    return [row for row in reader if not any(str(row.get(k, "")).startswith("Total") for k in row)]


def _rub(micros: str | int | None) -> str:
    try:
        return f"{int(micros) / 1_000_000:.2f} ₽"
    except (TypeError, ValueError):
        return str(micros or "")


def analyze(cache: Path) -> str:
    out: list[str] = []
    clients = json.loads((cache / "clients.json").read_text()) if (cache / "clients.json").exists() else []
    balance = json.loads((cache / "balance.json").read_text()) if (cache / "balance.json").exists() else []
    campaigns = json.loads((cache / "campaigns.json").read_text()) if (cache / "campaigns.json").exists() else []

    out.append(f"# Отчёт по Яндекс.Директу — {cache.name}\n")

    if clients:
        c = clients[0]
        out.append(
            f"**Клиент:** `{c.get('Login')}` · валюта: {c.get('Currency')} · качество: {c.get('AccountQuality')}\n"
        )
    if balance:
        b = balance[0]
        out.append(
            f"**API баллы:** rate={b.get('RateLimit')}/{b.get('RateLimitInHours')}ч · daily={b.get('DailyLimit')}\n"
        )

    on = [c for c in campaigns if c.get("State") == "ON"]
    out.append(f"\n**Кампании:** всего {len(campaigns)}, активных {len(on)}\n")

    # ТОП по расходу из campaign_performance.tsv
    perf = _read_tsv(cache / "reports" / "campaigns.tsv")
    if perf:
        for row in perf:
            row["_cost"] = float(row.get("Cost", "0") or 0)
            row["_clicks"] = int(row.get("Clicks", "0") or 0)
            row["_impr"] = int(row.get("Impressions", "0") or 0)
        top_cost = sorted(perf, key=lambda r: r["_cost"], reverse=True)[:5]
        out.append("\n## ТОП-5 кампаний по расходу\n")
        out.append("| Кампания | Показы | Клики | Расход | CTR |")
        out.append("|---|---:|---:|---:|---:|")
        for r in top_cost:
            ctr = (r["_clicks"] / r["_impr"] * 100) if r["_impr"] else 0
            out.append(
                f"| {r.get('CampaignName', '—')[:40]} | {r['_impr']} | {r['_clicks']}"
                f" | {_rub(r['_cost'] * 1_000_000)} | {ctr:.2f}% |"
            )

    # ТОП поисковых запросов без конверсий
    queries = _read_tsv(cache / "reports" / "queries.tsv")
    if queries:
        no_conv = [
            q for q in queries if int(q.get("Clicks", "0") or 0) >= 5 and int(q.get("Conversions", "0") or 0) == 0
        ]
        no_conv.sort(key=lambda q: float(q.get("Cost", "0") or 0), reverse=True)
        if no_conv:
            out.append("\n## Кандидаты в минус-слова (≥5 кликов, 0 конверсий)\n")
            out.append("| Запрос | Клики | Расход |")
            out.append("|---|---:|---:|")
            for q in no_conv[:20]:
                out.append(
                    f"| {q.get('Query', '—')[:60]} | {q.get('Clicks')}"
                    f" | {_rub(float(q.get('Cost', '0') or 0) * 1_000_000)} |"
                )

    return "\n".join(out) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cache", required=True, type=Path)
    args = p.parse_args()
    print(analyze(args.cache))


if __name__ == "__main__":
    main()
