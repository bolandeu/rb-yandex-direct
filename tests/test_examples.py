"""Every `Example:` line from the --help pages runs against a mocked Direct API.

The examples are what agents copy; this keeps each of them runnable end to end
(CLI → DirectClient/ReportsClient → HTTP) without a real token or network.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import click
import httpx
import pytest
import respx
from click.testing import CliRunner

from rb_yandex_direct.cli import cli
from rb_yandex_direct.core.client import PROD_BASE

from .test_help import CLI, COMMANDS, _slug

# Files the examples refer to, with content the commands accept.
FILES = {
    "client.json": {"ClientInfo": "ООО Ромашка"},
    "campaigns.json": [{"Name": "Весна", "StartDate": "2026-10-01", "TextCampaign": {"BiddingStrategy": {}}}],
    "ads.json": [{"AdGroupId": 555, "TextAd": {"Title": "Диваны", "Text": "Доставка", "Href": "https://example.com"}}],
    "feeds.json": [{"Id": 7001, "Name": "Каталог", "UrlFeed": {"Url": "https://example.com/feed.xml"}}],
    "targets.json": [{"AdGroupId": 555, "Name": "Все страницы"}],
    "sitelinks.json": [{"Title": "Доставка", "Href": "https://example.com/d"}],
    "vcards.json": [{"CampaignId": 12345, "Country": "Россия", "City": "Москва", "CompanyName": "Ромашка"}],
}
REPORT_TSV = "Date\tClicks\tCost\n2026-09-01\t10\t1000000\nTotal rows: 1\n"
# auth commands (browser, keychain) are covered in test_auth.py.
SKIP = {("auth", "login"), ("auth", "refresh"), ("auth", "logout"), ("auth", "status")}


def _example(path: tuple[str, ...]) -> list[str]:
    doc = COMMANDS[path].help or ""
    line = next(ln.strip() for ln in doc.splitlines() if ln.strip().startswith("Example:"))
    args = shlex.split(line.removeprefix("Example:").split("#")[0])[1:]  # drop the CLI name
    if any(isinstance(p, click.Option) and "--yes" in p.opts for p in COMMANDS[path].params):
        args.append("--yes")
    return args


def _api(request: httpx.Request) -> httpx.Response:
    headers = {"RequestId": "r1", "Units": "10/20000/64000"}
    if request.url.path.endswith("/reports"):
        return httpx.Response(200, text=REPORT_TSV, headers=headers)
    return httpx.Response(200, json={"result": {}}, headers=headers)


@pytest.mark.parametrize("path", sorted(set(COMMANDS) - SKIP), ids=_slug)
def test_example_runs(path: tuple[str, ...], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    monkeypatch.chdir(tmp_path)
    for name, content in FILES.items():
        (tmp_path / name).write_text(json.dumps(content, ensure_ascii=False))
    (tmp_path / "minus.txt").write_text("бесплатно\nскачать\n")
    (tmp_path / "banner.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    with respx.mock(assert_all_called=False) as router:
        router.post(url__startswith=PROD_BASE).mock(side_effect=_api)
        router.post(url__startswith="https://oauth.yandex.ru").mock(
            return_value=httpx.Response(200, json={"access_token": "a2", "refresh_token": "r2", "expires_in": 3600})
        )
        result = CliRunner().invoke(cli, _example(path), obj={}, prog_name=CLI)
    assert result.exit_code == 0, f"{shlex.join([CLI, *_example(path)])}\n{result.output}\n{result.exception!r}"
