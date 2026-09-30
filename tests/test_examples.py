"""Каждая строка `Example:` из справки выполняется против замоканного API Директа.

Примеры — то, что копируют агенты; тест держит каждый рабочим от начала до конца
(CLI → сервис → клиент → HTTP) без настоящего токена и сети. Изменяющим командам
без `--dry-run`/`--confirm` в примере добавляется `--confirm --non-interactive`.
"""

from __future__ import annotations

import inspect
import json
import shlex
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from rb_yandex_direct.cli import app

from .test_help import CLI, COMMANDS, _slug

# Файлы, на которые ссылаются примеры, с содержимым, которое команды принимают.
FILES = {
    "client.json": {"ClientInfo": "ООО Ромашка"},
    "campaigns.json": [{"Name": "Весна", "StartDate": "2026-10-01", "TextCampaign": {"BiddingStrategy": {}}}],
    "update.json": [{"Id": 12345, "Name": "Весна"}],
    "ads.json": [{"AdGroupId": 555, "TextAd": {"Title": "Диваны", "Text": "Доставка", "Href": "https://example.com"}}],
    "feeds.json": [{"Id": 7001, "Name": "Каталог", "UrlFeed": {"Url": "https://example.com/feed.xml"}}],
    "targets.json": [{"AdGroupId": 555, "Name": "Все страницы"}],
    "sitelinks.json": [{"Title": "Доставка", "Href": "https://example.com/d"}],
    "vcards.json": [
        {
            "CampaignId": 12345,
            "Country": "Россия",
            "City": "Москва",
            "CompanyName": "Ромашка",
            "WorkTime": "0#4#9#00#18#00",
            "Phone": {"CountryCode": "+7", "CityCode": "495", "PhoneNumber": "1234567"},
        }
    ],
    "adgroups.json": [{"Name": "Диваны", "CampaignId": 12345, "RegionIds": [213]}],
    "adgroups-update.json": [{"Id": 555, "Name": "Диваны Москва"}],
    "ads-update.json": [{"Id": 777, "TextAd": {"Title": "Диваны от 8990 ₽"}}],
}
TEXT_FILES = {"minus.txt": "бесплатно\nскачать\n", "keywords.txt": "купить диван\nдиван недорого\n"}
# Ответы `get`, без которых пример законно падает (объект не найден).
RESULTS = {
    "campaigns": {"Campaigns": [{"Id": 12345, "Name": "Весна"}]},
    "adgroups": {"AdGroups": [{"Id": 555, "Name": "Диваны"}]},
    "ads": {"Ads": [{"Id": 777, "TextAd": {"Title": "Диваны"}}]},
}
REPORT_TSV = "Date\tClicks\tCost\n2026-09-01\t10\t1000000\nTotal rows: 1\n"
# auth — браузер и keychain, покрыт в test_auth.py.
SKIP = {("auth", "login"), ("auth", "refresh"), ("auth", "logout")}


def _example(path: tuple[str, ...]) -> list[str]:
    doc = inspect.getdoc(COMMANDS[path]) or ""
    line = next(ln.strip() for ln in doc.splitlines() if ln.strip().startswith("Example:"))
    args = shlex.split(line.removeprefix("Example:").split(" # ")[0])[1:]  # без имени CLI
    params = inspect.signature(inspect.unwrap(COMMANDS[path])).parameters
    if "confirm" in params and not {"--dry-run", "--confirm"} & set(args):
        args += ["--confirm", "--non-interactive"]
    return args


def _api(request: httpx.Request) -> httpx.Response:
    headers = {"RequestId": "r1", "Units": "10/20000/64000"}
    if request.url.path.endswith("/reports"):
        return httpx.Response(200, text=REPORT_TSV, headers=headers)
    service = request.url.path.rsplit("/", 1)[-1]
    method = json.loads(request.content).get("method")
    result = RESULTS.get(service, {}) if method == "get" else {}
    return httpx.Response(200, json={"result": result}, headers=headers)


@pytest.mark.parametrize("path", sorted(set(COMMANDS) - SKIP), ids=_slug)
def test_example_runs(path: tuple[str, ...], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    monkeypatch.chdir(tmp_path)
    for name, content in FILES.items():
        (tmp_path / name).write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    for name, text in TEXT_FILES.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    (tmp_path / "banner.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    # Проект нужен примерам status/config; кабинет по умолчанию — свой.
    assert CliRunner().invoke(app, ["init", "--name", "demo"], prog_name=CLI).exit_code == 0
    args = _example(path)
    with respx.mock(assert_all_called=False) as router:
        router.post(url__startswith="https://api.direct.yandex.com").mock(side_effect=_api)
        router.post(url__startswith="https://api-sandbox.direct.yandex.com").mock(side_effect=_api)
        router.post(url__startswith="https://oauth.yandex.ru").mock(
            return_value=httpx.Response(200, json={"access_token": "a2", "refresh_token": "r2", "expires_in": 3600})
        )
        result = CliRunner().invoke(app, args, prog_name=CLI)
    assert result.exit_code == 0, f"{shlex.join([CLI, *args])}\n{result.output}\n{result.exception!r}"
