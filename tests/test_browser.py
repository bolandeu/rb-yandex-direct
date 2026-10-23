"""Команды веб-интерфейса (`masters`, `history`, `browser`) поверх подменённого браузерного слоя."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from rb_yandex_direct.cli import app
from rb_yandex_direct.core.errors import CliError
from rb_yandex_direct.providers import browser
from rb_yandex_direct.providers.direct import PROD_BASE

from .fake_browser import PAGE, BrowserAuthError, BrowserCaptchaError, FakeBrowser
from .test_cli import plain


def run(*args: str, input: str | None = None):
    result = CliRunner().invoke(app, list(args), prog_name="yd", input=input)
    return result


def run_json(*args: str) -> tuple[int, dict]:
    result = run(*args, "--json")
    return result.exit_code, json.loads(result.stdout)


# --- чтение ------------------------------------------------------------------------------------


def test_masters_list(fake_browser: FakeBrowser) -> None:
    code, payload = run_json("masters", "list", "--status", "active")
    assert code == 0
    assert payload["count"] == 1
    assert payload["masters"][0]["CampaignId"] == 72349978
    assert fake_browser.last("fetch_masters_list") == ((), {"status": "active"})
    assert fake_browser.state["opened"] == ["chrome"]  # сохранённой сессии нет — куки Chrome


def test_masters_list_human_table() -> None:
    result = run("masters", "list")
    assert result.exit_code == 0
    assert "72349978" in result.stdout


def test_masters_get_with_extras(fake_browser: FakeBrowser) -> None:
    code, payload = run_json("masters", "get", "72349978", "--moderation", "--tracking-params")
    assert code == 0
    assert payload["master"]["TrackingParams"] == "utm=1"
    assert "Moderation" in payload["master"]


@pytest.mark.parametrize(
    ("command", "function", "key"),
    [
        ("audience", "fetch_master_audience", "audience"),
        ("counters", "fetch_master_metrika_counters", "counters"),
        ("target-actions", "fetch_master_target_actions", "target_actions"),
    ],
)
def test_masters_readers(command: str, function: str, key: str, fake_browser: FakeBrowser) -> None:
    code, payload = run_json("masters", command, "5")
    assert code == 0
    assert key in payload
    assert fake_browser.last(function) == ((5,), {})


def test_masters_images_list(fake_browser: FakeBrowser) -> None:
    code, payload = run_json("masters", "images", "list", "5")
    assert code == 0
    assert payload["images"] == {"Images": []}


def test_history_expands_dates(fake_browser: FakeBrowser) -> None:
    code, payload = run_json(
        "history", "get", "--campaign", "1", "--date-from", "2026-09-01", "--date-to", "2026-09-02T12:00:00"
    )
    assert code == 0
    assert payload["count"] == 1
    _, kwargs = fake_browser.last("fetch_change_history")
    assert kwargs["date_from"] == "2026-09-01T00:00:00"
    assert kwargs["date_to"] == "2026-09-02T12:00:00"
    assert kwargs["campaign_ids"] == [1]
    assert kwargs["categories"] is None


def test_history_rejects_bad_limit() -> None:
    assert run("history", "get", "--limit", "0").exit_code == 2


# --- изменения: dry-run и подтверждение --------------------------------------------------------


def test_suspend_dry_run_does_not_open_browser(fake_browser: FakeBrowser) -> None:
    code, payload = run_json("masters", "suspend", "7", "--dry-run")
    assert code == 0
    assert payload["dry_run"] is True
    assert payload["action"] == "suspend_master"
    assert fake_browser.state["opened"] == []


def test_suspend_non_interactive_requires_confirm(fake_browser: FakeBrowser) -> None:
    result = run("masters", "suspend", "7", "--non-interactive")
    assert result.exit_code == 2
    assert fake_browser.calls == []


def test_suspend_prompt_declined_is_aborted(fake_browser: FakeBrowser) -> None:
    result = run("masters", "suspend", "7", input="n\n")
    assert result.exit_code == 1
    assert fake_browser.calls == []


@pytest.mark.parametrize("command", ["suspend", "resume", "archive", "delete", "launch"])
def test_status_actions(command: str, fake_browser: FakeBrowser) -> None:
    code, payload = run_json("masters", command, "7", "--confirm")
    assert code == 0
    assert fake_browser.last(f"{command}_master") == ((7,), {})
    assert payload["result"] == {"CampaignId": 72349978}


def test_copy_passes_launch(fake_browser: FakeBrowser) -> None:
    assert run("masters", "copy", "7", "--launch", "--confirm").exit_code == 0
    assert fake_browser.last("copy_master") == ((7,), {"launch": True})


def test_update_maps_cli_values_to_library(fake_browser: FakeBrowser, tmp_path) -> None:
    image = tmp_path / "a.png"
    image.write_bytes(b"\x89PNG")
    code, _ = run_json(
        "masters", "update", "7", "--confirm",
        "--weekly-budget", "9500",
        "--headline", "2=Новый",
        "--text", "1=Текст",
        "--clear-headline", "5",
        "--image", f"1={image}",
        "--age-from", "25", "--age-to", "unlimited",
        "--device", "mobile", "--device", "desktop",
        "--remove-audience-tag", "1",
        "--add-sitelink", "О нас|https://example.com/about",
        "--add-target-action", "236386933=150",
        "--no-directs-helps",
    )  # fmt: skip
    assert code == 0
    (campaign_id,), kwargs = fake_browser.last("update_master")
    assert campaign_id == 7
    assert kwargs["weekly_budget"] == 9500
    assert kwargs["headlines"] == {1: "Новый"}
    assert kwargs["texts"] == {0: "Текст"}
    assert kwargs["clear_headlines"] == [4]
    assert kwargs["images"] == {0: str(image)}
    assert (kwargs["age_from"], kwargs["age_from_requested"]) == (25, True)
    assert (kwargs["age_to"], kwargs["age_to_requested"]) == (None, True)
    assert kwargs["devices"] == {"mobile", "desktop"}
    assert kwargs["remove_audience_tags"] == [0]
    assert kwargs["add_sitelinks"] == [{"Title": "О нас", "Href": "https://example.com/about", "Description": ""}]
    assert kwargs["add_target_actions"] == {236386933: 150.0}
    assert kwargs["directs_helps"] is False
    assert kwargs["launch"] is False
    assert "gender" not in kwargs  # не переданное поле не трогаем


def test_update_dry_run_shows_plan_with_sorted_devices(fake_browser: FakeBrowser) -> None:
    code, payload = run_json("masters", "update", "7", "--device", "tablet", "--device", "mobile", "--dry-run")
    assert code == 0
    assert payload["params"]["devices"] == ["mobile", "tablet"]
    assert fake_browser.calls == []


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--headline", "9=x"],
        ["--headline", "x"],
        ["--headline", "1="],
        ["--headline", "1=a", "--headline", "1=b"],
        ["--age-from", "20"],
        ["--age-to", "99"],
        ["--add-sitelink", "без ссылки"],
        ["--add-target-action", "abc"],
        ["--add-target-action", "1=abc"],
        ["--image", "1=/нет/такого.png"],
        ["--remove-sitelink", "0"],
    ],
)
def test_update_rejects_bad_arguments_before_browser(args: list[str], fake_browser: FakeBrowser) -> None:
    assert run("masters", "update", "7", "--confirm", *args).exit_code == 2
    assert fake_browser.state["opened"] == []


def test_update_rejects_wrong_image_type(tmp_path) -> None:
    doc = tmp_path / "a.txt"
    doc.write_text("x")
    assert run("masters", "update", "7", "--image", f"1={doc}", "--confirm").exit_code == 2


def test_add_dry_run_needs_no_api() -> None:
    code, payload = run_json(
        "masters", "add", "https://example.com/", "--headline", "H", "--text", "T",
        "--region-id", "213", "--target-action", "1=10", "--weekly-budget", "5000", "--draft", "--dry-run",
    )  # fmt: skip
    assert code == 0
    assert payload["params"]["launch"] is False
    assert payload["params"]["region_ids"] == [213]


@respx.mock
def test_add_resolves_region_ids_via_api(fake_browser: FakeBrowser, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = respx.post(f"{PROD_BASE}/dictionaries").mock(
        return_value=httpx.Response(
            200, json={"result": {"GeoRegions": [{"GeoRegionId": 213, "GeoRegionName": "Москва"}]}}
        )
    )
    code, _ = run_json(
        "masters", "add", "https://example.com/", "--headline", "H", "--text", "T", "--region", "Казань",
        "--region-id", "213", "--target-action", "1=10", "--weekly-budget", "5000", "--confirm",
    )  # fmt: skip
    assert code == 0
    assert json.loads(route.calls.last.request.content)["method"] == "getGeoRegions"
    (url,), kwargs = fake_browser.last("create_master")
    assert url == "https://example.com/"
    assert kwargs["regions"] == [("Казань", None), ("Москва", 213)]
    assert kwargs["target_actions"] == {1: 10.0}
    assert kwargs["launch"] is True


@respx.mock
def test_add_unknown_region_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    respx.post(f"{PROD_BASE}/dictionaries").mock(return_value=httpx.Response(200, json={"result": {"GeoRegions": []}}))
    result = run(
        "masters", "add", "https://example.com/", "--headline", "H", "--text", "T",
        "--region-id", "999999", "--target-action", "1=10", "--weekly-budget", "5000", "--confirm",
    )  # fmt: skip
    assert result.exit_code == 2


@pytest.mark.parametrize(
    "args",
    [
        ["--target-action", "1=10"],  # нет региона
        ["--region", "Москва", "--target-action", "1=10", *[a for n in "23456" for a in ("--headline", n)]],
    ],
)
def test_add_rejects(args: list[str]) -> None:
    base = ["masters", "add", "https://example.com/", "--headline", "H", "--text", "T", "--weekly-budget", "1"]
    assert run(*base, *args, "--confirm").exit_code == 2


def test_images_mutations(fake_browser: FakeBrowser, tmp_path) -> None:
    image = tmp_path / "b.jpg"
    image.write_bytes(b"x")
    assert run("masters", "images", "add", "7", "--file", str(image), "--confirm").exit_code == 0
    assert fake_browser.last("add_master_images") == ((7,), {"paths": [str(image)], "launch": False})
    assert run("masters", "images", "set", "7", "--file", str(image), "--launch", "--confirm").exit_code == 0
    assert fake_browser.last("set_master_images")[1]["launch"] is True
    assert run("masters", "images", "delete", "7", "--position", "2", "--confirm").exit_code == 0
    assert fake_browser.last("delete_master_images")[1]["positions"] == [1]
    assert run("masters", "images", "delete", "7", "--confirm").exit_code == 2
    too_many = [arg for _ in range(6) for arg in ("--file", str(image))]
    assert run("masters", "images", "set", "7", *too_many, "--confirm").exit_code == 2


# --- сессия и ошибки ---------------------------------------------------------------------------


def test_stale_saved_session_falls_back_to_chrome(fake_browser: FakeBrowser) -> None:
    fake_browser.state["saved"] = True
    fake_browser.state["auth_failures"] = 1
    code, _ = run_json("masters", "list")
    assert code == 0
    assert fake_browser.state["opened"] == ["saved", "chrome"]


def test_expired_chrome_cookies_are_auth_required(fake_browser: FakeBrowser) -> None:
    fake_browser.state["auth_failures"] = 1
    code, payload = run_json("masters", "list")
    assert code == 3
    assert payload["error"]["code"] == "AUTH_REQUIRED"
    assert "yd browser login" in payload["error"]["action"]


def test_explicit_chrome_dir_skips_saved_session(fake_browser: FakeBrowser, tmp_path) -> None:
    fake_browser.state["profile_usable"] = True
    assert run("masters", "list", "--chrome-dir", str(tmp_path)).exit_code == 0
    assert fake_browser.state["opened"] == ["chrome"]


def test_profile_session_is_preferred(fake_browser: FakeBrowser) -> None:
    fake_browser.state["profile_usable"] = True
    assert run("masters", "list").exit_code == 0
    assert fake_browser.state["opened"] == ["profile"]


@pytest.mark.parametrize(
    ("error", "code", "error_code"),
    [
        (BrowserCaptchaError("captcha"), 5, "PROVIDER_ERROR"),
        (ValueError("bad status"), 2, "INVALID_ARGUMENTS"),
    ],
)
def test_library_errors_are_mapped(error, code, error_code, fake_browser: FakeBrowser) -> None:
    def boom(*args, **kwargs):
        raise error

    fake_browser.masters.fetch_masters_list = boom
    result_code, payload = run_json("masters", "list")
    assert result_code == code
    assert payload["error"]["code"] == error_code


def test_network_and_generic_errors(fake_browser: FakeBrowser) -> None:
    session = fake_browser.session
    for error in (session.BrowserNetworkError("net::ERR"), session.BrowserSessionError("?"), session.PlaywrightError()):

        def boom(*args, error=error, **kwargs):
            raise error

        fake_browser.masters.fetch_masters_list = boom
        code, payload = run_json("masters", "list")
        assert (code, payload["error"]["code"]) == (5, "PROVIDER_ERROR")


def test_library_stdout_goes_to_stderr(fake_browser: FakeBrowser) -> None:
    def noisy(page, status):
        print("⚠ предупреждение библиотеки")
        return []

    fake_browser.masters.fetch_masters_list = noisy
    result = run("masters", "list", "--json")
    assert json.loads(result.stdout)["count"] == 0
    assert "предупреждение" in result.stderr


def test_missing_extra_is_dependency_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser, "_lib", None)

    def missing(name: str):
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(browser.importlib, "import_module", missing)
    code, payload = run_json("masters", "list")
    assert code == 1
    assert payload["error"]["code"] == "DEPENDENCY_TOO_OLD"
    assert "rb-yandex-direct[browser]" in payload["error"]["action"]
    human = run("browser", "status")
    assert "rb-yandex-direct[browser]" in plain(human.stderr).replace("\n", "")  # скобки не съедены rich


# --- yd browser ---------------------------------------------------------------------------------


def test_login_from_chrome_saves_snapshot(fake_browser: FakeBrowser) -> None:
    code, payload = run_json("browser", "login", "--from-chrome", "--no-verify")
    assert code == 0
    assert payload["source"] == "saved"
    assert fake_browser.last("capture_storage_state")[1]["verify"] is False
    assert fake_browser.last("save_session")[1]["path"] == browser.paths().session
    assert browser.paths().pointer == fake_browser.session.PROFILE_POINTER_PATH


def test_login_profile_then_status_and_logout(fake_browser: FakeBrowser) -> None:
    code, payload = run_json("browser", "login", "--timeout", "5")
    assert code == 0
    assert payload["source"] == "profile"
    assert fake_browser.last("login_persistent_session")[1]["timeout_ms"] == 5000
    code, status = run_json("browser", "status")
    assert status["active"] == "profile"
    browser.paths().pointer.write_text("x")
    code, payload = run_json("browser", "logout")
    assert code == 0
    assert str(browser.paths().profile) in payload["removed"]
    assert not browser.paths().profile.exists()
    assert run_json("browser", "logout")[1]["removed"] == []


def test_logout_keeps_foreign_directory(fake_browser: FakeBrowser) -> None:
    browser.paths().profile.mkdir(parents=True)
    assert run_json("browser", "logout")[1]["removed"] == []
    assert browser.paths().profile.exists()


def test_login_window_is_refused_non_interactive() -> None:
    assert run("--non-interactive", "browser", "login").exit_code == 2


def test_login_errors_are_mapped(fake_browser: FakeBrowser) -> None:
    def boom(**kwargs):
        raise BrowserAuthError("timeout")

    fake_browser.session.login_persistent_session = boom
    assert run("browser", "login").exit_code == 3


def test_status_human(fake_browser: FakeBrowser) -> None:
    fake_browser.state["saved"] = True
    result = run("browser", "status")
    assert result.exit_code == 0
    assert "saved" in result.stdout


def test_doctor_rewrites_library_hints() -> None:
    code, payload = run_json("browser", "doctor")
    assert code == 0
    assert payload["healthy"] is False
    hint = next(c["hint"] for c in payload["checks"] if c["name"] == "saved_session")
    assert hint == "Run: yd browser login"
    assert run("browser", "doctor").exit_code == 0


def test_provider_health(fake_browser: FakeBrowser) -> None:
    provider = browser.DirectWebProvider()
    with pytest.raises(CliError) as excinfo:
        provider.health_check()
    assert "browser login" in (excinfo.value.action or "")
    fake_browser.state["saved"] = True
    assert provider.health_check().status == "ok"


def test_provider_health_without_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser, "_lib", None)
    monkeypatch.setattr(browser.importlib, "import_module", lambda name: (_ for _ in ()).throw(ImportError(name)))
    assert browser.DirectWebProvider().health_check().status == "unreachable"


def test_page_sentinel_is_passed_to_library(fake_browser: FakeBrowser) -> None:
    seen = []
    fake_browser.masters.fetch_master = lambda page, campaign_id: seen.append(page) or {}
    assert run("masters", "get", "1").exit_code == 0
    assert seen == [PAGE]
