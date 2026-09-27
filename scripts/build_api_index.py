# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
"""Сгенерировать docs/api_links.json — индекс методов API Яндекс.Директа.

Берёт sitemap.xml (не требует JS, не триггерит капчу), парсит URL вида
`/dev/direct/doc/<lang>/<service>/<method>` и группирует по сервисам.

Запуск:
    uv run scripts/build_api_index.py --out docs/api_links.json

Итоговый JSON:
    {
      "generated_from": "https://yandex.ru/dev/direct/doc/sitemap.xml",
      "lang": "en",
      "base_url": "https://yandex.com/dev/direct/doc/en/",
      "services": {
        "audiencetargets": {
          "overview": "https://yandex.com/dev/direct/doc/en/audiencetargets/audiencetargets",
          "methods": {
            "add": "https://yandex.com/dev/direct/doc/en/audiencetargets/add",
            "setBids": "https://yandex.com/dev/direct/doc/en/audiencetargets/setBids",
            ...
          }
        },
        ...
      }
    }
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import httpx

SITEMAP_URL = "https://yandex.ru/dev/direct/doc/sitemap.xml"
DOC_ROOT = "/dev/direct/doc/"
NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
# Хост для вывода ссылок: .com читается лучше из-за английской локали.
OUTPUT_HOST = "https://yandex.com"

# Реальные API-сервисы (из client.py + типовые v5-сервисы).
API_SERVICES = frozenset([
    "adextensions", "adgroups", "adimages", "ads", "advideos", "agencyclients",
    "audiencetargets", "bidmodifiers", "businesses", "campaigns", "changes",
    "clients", "creatives", "dictionaries", "dynamictextadtargets", "feeds",
    "keywords", "keywordbids", "keywordsresearch", "leads",
    "negativekeywordsharedsets", "reports", "retargetinglists",
    "sitelinks", "smartadtargets", "turbopages", "vcards",
])

# Методы, которых нет в sitemap, но URL рабочий (проверено через WebFetch).
# service → list[method]. URL собирается как <base>/<service>/<method>.
KNOWN_EXTRA_METHODS: dict[str, list[str]] = {
    "adextensions": ["moderate"],
    "ads": ["suspend", "resume", "archive", "unarchive", "moderate", "update"],
    "adimages": ["update"],
    "audiencetargets": ["setBids", "suspend", "resume"],
    "bidmodifiers": ["toggle", "set"],
    "campaigns": [
        "archive", "unarchive", "suspend", "resume", "delete", "update",
        "add", "get",
    ],
    "dynamictextadtargets": ["get", "add", "delete", "suspend", "resume", "setBids"],
    "feeds": ["get", "add", "update", "delete"],
    "keywordsresearch": ["deduplicate", "hasSearchVolume"],
    "reports": ["reports"],  # docs/reports/reports
    "smartadtargets": ["get", "add", "delete", "suspend", "resume", "setBids"],
    "vcards": ["get", "add", "delete"],
}


def build(lang: str) -> dict:
    resp = httpx.get(SITEMAP_URL, timeout=30.0, follow_redirects=True)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)

    services: dict[str, dict] = {}
    guides: dict[str, str] = {}
    prefix = f"{DOC_ROOT}{lang}/"

    for loc in root.findall("sm:url/sm:loc", NS):
        if not loc.text:
            continue
        path = urlparse(loc.text).path
        if not path.startswith(prefix):
            continue
        rel = path[len(prefix):].rstrip("/")
        url = f"{OUTPUT_HOST}{path}"

        parts = rel.split("/")
        head = parts[0]

        if head in API_SERVICES:
            svc = services.setdefault(head, {"overview": None, "methods": {}})
            if len(parts) == 1 or (len(parts) == 2 and parts[1] == head):
                svc["overview"] = url
            elif len(parts) == 2:
                svc["methods"][parts[1]] = url
            else:
                # Вложенные страницы (notebooks/examples сервиса) — в methods с ключом-путём.
                svc["methods"]["/".join(parts[1:])] = url
        else:
            # Всё остальное — гайды/объекты/примеры. Складываем по ключу-пути.
            guides[rel or "_index"] = url

    # Дополняем недостающие (URL строим по шаблону).
    for service, extra in KNOWN_EXTRA_METHODS.items():
        svc = services.setdefault(service, {"overview": None, "methods": {}})
        if svc["overview"] is None:
            svc["overview"] = f"{OUTPUT_HOST}{DOC_ROOT}{lang}/{service}/{service}"
        for method in extra:
            svc["methods"].setdefault(
                method, f"{OUTPUT_HOST}{DOC_ROOT}{lang}/{service}/{method}"
            )

    services_sorted = {
        name: {
            "overview": svc["overview"],
            "methods": dict(sorted(svc["methods"].items())),
        }
        for name, svc in sorted(services.items())
    }
    guides_sorted = dict(sorted(guides.items()))

    return {
        "generated_from": SITEMAP_URL,
        "lang": lang,
        "base_url": f"{OUTPUT_HOST}{DOC_ROOT}{lang}/",
        "services": services_sorted,
        "guides": guides_sorted,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--lang", choices=["en", "ru"], default="en")
    p.add_argument("--out", type=Path, default=Path("docs/api_links.json"))
    args = p.parse_args()

    index = build(args.lang)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")

    total_methods = sum(len(s["methods"]) for s in index["services"].values())
    print(f"[ok] {len(index['services'])} API-сервисов, {total_methods} методов, "
          f"{len(index['guides'])} гайдов → {args.out}")


if __name__ == "__main__":
    main()
