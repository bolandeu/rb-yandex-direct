"""Команды v4 Live без денег: wordstat, forecast, events, goals, tags, suggest, v4."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from rb_yandex_direct.cli import app
from rb_yandex_direct.providers.live import LIVE_PROD

Handler = Callable[[str, object], object]


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Замоканный v4 Live: `live(handler)` — handler(method, param) → data или httpx.Response."""
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("rb_yandex_direct.commands._live.POLL_INTERVAL", 0)
    calls: list[dict] = []

    def install(handler: Handler) -> list[dict]:
        def respond(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            calls.append(body)
            data = handler(body["method"], body.get("param"))
            return data if isinstance(data, httpx.Response) else httpx.Response(200, json={"data": data})

        respx.post(LIVE_PROD).mock(side_effect=respond)
        return calls

    with respx.mock:
        yield install


def run(*args: str) -> tuple[int, dict]:
    result = CliRunner().invoke(app, [*args, "--json"], prog_name="yd")
    return result.exit_code, json.loads(result.stdout)


def test_wordstat_run_creates_waits_gets_deletes(live) -> None:
    statuses = iter(["Pending", "Done"])

    def handler(method: str, param: object) -> object:
        if method == "GetWordstatReportList":
            return [{"ReportID": 7, "StatusReport": next(statuses)}]
        return {
            "CreateNewWordstatReport": 7,
            "GetWordstatReport": [{"Phrase": "диван", "SearchedWith": [{"Phrase": "диван", "Shows": 10}]}],
            "DeleteWordstatReport": 1,
        }[method]

    calls = live(handler)
    code, payload = run("wordstat", "run", "диван", "-r", "213", "-r", "-219")
    assert code == 0
    assert payload["report_id"] == 7
    assert payload["report"][0]["SearchedWith"][0]["Shows"] == 10
    assert calls[0]["param"] == {"Phrases": ["диван"], "GeoID": [213, -219]}
    assert [c["method"] for c in calls][-1] == "DeleteWordstatReport"


def test_wordstat_run_failed_report_is_provider_error(live) -> None:
    live(lambda m, p: 7 if m == "CreateNewWordstatReport" else [{"ReportID": 7, "StatusReport": "Failed"}])
    code, payload = run("wordstat", "run", "диван")
    assert code == 5
    assert payload["error"]["code"] == "PROVIDER_ERROR"


def test_wordstat_run_timeout(live) -> None:
    live(lambda m, p: 7 if m == "CreateNewWordstatReport" else [{"ReportID": 7, "StatusReport": "Pending"}])
    code, payload = run("wordstat", "run", "диван", "--timeout", "0")
    assert code == 5
    assert "не готов" in payload["error"]["message"]


def test_wordstat_too_many_phrases(live) -> None:
    live(lambda m, p: None)
    code, _ = run("wordstat", "create", *[f"f{i}" for i in range(11)])
    assert code == 2


def test_wordstat_get_human_table(live) -> None:
    live(
        lambda m, p: [
            {
                "Phrase": "диван",
                "SearchedWith": [{"Phrase": "диван купить", "Shows": 5}],
                "SearchedAlso": [{"Phrase": "кресло", "Shows": 3}],
            }
        ]
    )
    result = CliRunner().invoke(app, ["wordstat", "get", "7"], prog_name="yd")
    assert result.exit_code == 0
    assert "диван купить" in result.stdout
    assert "кресло" in result.stdout


def test_wordstat_delete_dry_run_sends_nothing(live) -> None:
    calls = live(lambda m, p: 1)
    code, payload = run("wordstat", "delete", "7", "--dry-run")
    assert code == 0
    assert payload["body"] == {"method": "DeleteWordstatReport", "param": 7, "locale": "ru"}
    assert calls == []


def test_forecast_create_param(live) -> None:
    calls = live(lambda m, p: 9)
    code, payload = run("forecast", "create", "диван", "-m", "бу", "--auction-bids", "--currency", "usd")
    assert code == 0
    assert payload["forecast_id"] == 9
    assert calls[0]["param"] == {
        "Phrases": ["диван"],
        "Currency": "USD",
        "AuctionBids": "Yes",
        "CommonMinusWords": ["бу"],
    }


def test_forecast_run_and_human_get(live) -> None:
    forecast = {"Phrases": [{"Phrase": "диван", "Shows": 100}], "Common": {"Shows": 100}}

    def handler(method: str, param: object) -> object:
        return {
            "CreateNewForecast": 9,
            "GetForecastList": [{"ForecastID": 9, "StatusForecast": "Done"}],
            "GetForecast": forecast,
            "DeleteForecastReport": 1,
        }[method]

    calls = live(handler)
    code, payload = run("forecast", "run", "диван", "--keep")
    assert code == 0
    assert payload["forecast"] == forecast
    assert "DeleteForecastReport" not in [c["method"] for c in calls]
    human = CliRunner().invoke(app, ["forecast", "get", "9"], prog_name="yd")
    assert "Итого" in human.stdout


def test_events_list_filter(live) -> None:
    calls = live(lambda m, p: [{"EventName": "x", "CampaignID": 1}])
    code, payload = run(
        "events", "list", "--from", "2026-09-01", "--to", "2026-09-02T10:00:00Z", "--campaign", "1",
        "--type", "MoneyIn", "--client", "shop", "--last-only", "--limit", "10", "--offset", "5",
    )  # fmt: skip
    assert code == 0
    assert payload["count"] == 1
    param = calls[0]["param"]
    assert param["TimestampFrom"] == "2026-09-01T00:00:00Z"
    assert param["TimestampTo"] == "2026-09-02T10:00:00Z"
    assert param["Filter"] == {"CampaignIDS": [1], "EventType": ["MoneyIn"]}
    assert (param["Logins"], param["LastEventOnly"], param["Limit"], param["Offset"]) == (["shop"], "Yes", 10, 5)


def test_goals(live) -> None:
    calls = live(lambda m, p: [{"GoalID": 1, "Name": "Заказ"}])
    assert run("goals", "stat", "--campaign", "5")[1]["goals"][0]["GoalID"] == 1
    assert calls[-1]["param"] == {"CampaignIDS": [5]}
    run("goals", "retargeting", "--client", "shop")
    assert calls[-1]["param"] == {"Logins": ["shop"]}
    run("goals", "retargeting")
    assert calls[-1]["param"] == {}


def test_tags_set_campaign_keeps_existing_ids(live) -> None:
    def handler(method: str, param: object) -> object:
        if method == "GetCampaignsTags":
            return [{"CampaignID": 5, "Tags": [{"TagID": 11, "Tag": "зима"}, {"TagID": 12, "Tag": "старое"}]}]
        return [{"CampaignID": 5, "Tags": []}]

    calls = live(handler)
    code, payload = run("tags", "set-campaign", "5", "-t", "зима", "-t", "новое", "--confirm")
    assert code == 0
    assert calls[-1]["param"] == [
        {"CampaignID": 5, "Tags": [{"TagID": 11, "Tag": "зима"}, {"TagID": 0, "Tag": "новое"}]}
    ]
    assert payload["failed"] == 0


def test_tags_banners_needs_one_selector(live) -> None:
    calls = live(lambda m, p: [{"BannerID": 7, "TagIDS": [1]}])
    assert run("tags", "banners")[0] == 2
    assert run("tags", "banners", "--campaign", "5")[1]["banners"][0]["BannerID"] == 7
    assert calls[-1]["param"] == {"CampaignIDS": [5]}
    assert run("tags", "campaigns", "--campaign", "5")[0] == 0
    code, _ = run("tags", "set-banners", "--banner", "7", "--confirm")
    assert code == 0
    assert calls[-1]["param"] == [{"BannerID": 7, "TagIDS": []}]


def test_suggest_and_meta(live) -> None:
    live(lambda m, p: {"GetKeywordsSuggestion": ["диван купить"], "PingAPI": 1, "GetVersion": 4}.get(m, [4, 104]))
    assert run("suggest", "диван")[1]["keywords"] == ["диван купить"]
    assert run("v4", "ping")[1]["result"] == 1
    assert run("v4", "version")[1]["version"] == 4
    assert run("v4", "version", "--available")[1]["version"] == [4, 104]
    human = CliRunner().invoke(app, ["suggest", "диван"], prog_name="yd")
    assert "диван купить" in human.stdout


def test_api_error_is_json_envelope(live) -> None:
    live(
        lambda m, p: httpx.Response(200, json={"error_code": 53, "error_str": "Ошибка авторизации", "error_detail": ""})
    )
    code, payload = run("v4", "ping")
    assert code == 3
    assert payload["error"]["api_code"] == 53
