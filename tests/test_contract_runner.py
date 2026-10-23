"""The consumer-contract runner itself (tests/test_contracts.py): what each section checks, and how it fails.

Consumers' contracts live in tests/contracts/<consumer>/<provider>.yaml (format
`contract: 1`, written by the consumer); these tests feed the runner synthetic ones.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
import typer

from tests.test_contracts import (
    ContractError,
    applies,
    case_ids,
    check_env,
    check_exit_codes,
    check_output,
    check_root_options,
    check_static_command,
    check_view_columns,
    expand_argv,
    load_contracts,
    run_case,
    type_family,
)

DOCUMENT = {
    "opencli": "0.1",
    "info": {"title": "yd", "version": "0.7.0"},
    "command": {
        "name": "yd",
        "options": [{"name": "--version"}, {"name": "--json"}],
        "commands": [
            {
                "name": "search",
                "arguments": [{"name": "queries"}],
                "options": [{"name": "--engine", "aliases": ["-e"]}, {"name": "--json"}],
            },
            {"name": "cache", "commands": [{"name": "info", "options": [{"name": "--json"}]}]},
        ],
        "exitCodes": [{"code": 0}, {"code": 2}, {"code": 5}],
        "metadata": [
            {
                "name": "x-rb-env",
                "value": [
                    {"name": "X_XMLRIVER_USER", "purpose": "credential", "fallbacks": ["XMLRIVER_USER"]},
                    {"name": "X_DATABASE_URL", "purpose": "database"},
                ],
            },
            {
                "name": "x-rb-data",
                "value": {
                    "views": [
                        {
                            "name": "x_v1_calls",
                            "columns": [{"name": "model", "type": "TEXT"}, {"name": "n", "type": "INTEGER"}],
                        }
                    ]
                },
            },
        ],
    },
}

CONTRACT = """
contract: 1
consumer: windmill
provider: yd
provider_range: ">=0.6,<1.0"
contact: dev
static:
  commands:
    - path: [search]
      arguments: [queries]
      options: [--engine, --json]
  root_options: [--version]
  exit_codes: [0, 2]
  env: [X_XMLRIVER_USER]
run:
  - name: version
    argv: [--version]
    exit: 0
    stdout_regex: '^\\d'
view: []
"""


def _write(root: Path, consumer: str, name: str, text: str) -> None:
    (root / consumer).mkdir(parents=True, exist_ok=True)
    (root / consumer / name).write_text(text)


def test_contracts_load_per_consumer_and_expand_to_cases(tmp_path: Path) -> None:
    _write(tmp_path, "windmill", "yd.yaml", CONTRACT)
    [contract] = load_contracts(tmp_path, provider="yd")
    assert contract.consumer == "windmill"
    assert case_ids(contract) == [
        "windmill:static:command:search",
        "windmill:static:root_options",
        "windmill:static:exit_codes",
        "windmill:static:env",
        "windmill:run:version",
    ]


def test_a_malformed_contract_names_its_file(tmp_path: Path) -> None:
    _write(tmp_path, "windmill", "yd.yaml", CONTRACT.replace("contract: 1", "contract: 2"))
    with pytest.raises(ContractError, match=r"windmill/yd\.yaml"):
        load_contracts(tmp_path, provider="yd")
    _write(tmp_path, "windmill", "yd.yaml", CONTRACT.replace("    exit: 0\n", ""))
    with pytest.raises(ContractError, match="exit"):
        load_contracts(tmp_path, provider="yd")


def test_a_contract_for_another_provider_is_an_error(tmp_path: Path) -> None:
    _write(tmp_path, "windmill", "other.yaml", CONTRACT.replace("provider: yd", "provider: other"))
    with pytest.raises(ContractError, match="provider 'other'"):
        load_contracts(tmp_path, provider="yd")


def test_provider_range() -> None:
    assert applies({"provider_range": ">=0.6,<1.0"}, "0.6.0")
    assert not applies({"provider_range": ">=0.6,<1.0"}, "1.0.0")
    assert not applies({"provider_range": ">=0.6,<1.0"}, "1.0.0.dev3")  # building 1.0.0
    assert not applies({"provider_range": ">=0.6,<1.0"}, "0.5.9")
    assert applies({}, "0.1.0")


def test_static_sections() -> None:
    check_static_command({"path": ["search"], "arguments": ["queries"], "options": ["--engine", "-e"]}, DOCUMENT)
    check_static_command({"path": ["cache", "info"], "options": ["--json"]}, DOCUMENT)
    check_root_options(["--version", "--json"], DOCUMENT)
    check_exit_codes([0, 2, 5], DOCUMENT)
    check_env(["X_XMLRIVER_USER", "XMLRIVER_USER", "X_DATABASE_URL"], DOCUMENT)
    for check, what in [
        (lambda: check_static_command({"path": ["serach"]}, DOCUMENT), "command 'serach'"),
        (lambda: check_static_command({"path": ["search"], "options": ["--top"]}, DOCUMENT), "option '--top'"),
        (lambda: check_static_command({"path": ["search"], "arguments": ["query"]}, DOCUMENT), "argument 'query'"),
        (lambda: check_root_options(["--ai"], DOCUMENT), "root option '--ai'"),
        (lambda: check_exit_codes([3], DOCUMENT), "exit code 3"),
        (lambda: check_env(["X_XMLSTOCK_TOKEN"], DOCUMENT), "env 'X_XMLSTOCK_TOKEN'"),
    ]:
        with pytest.raises(ContractError, match=what):
            check()


def test_placeholders_come_from_the_providers_fixtures() -> None:
    placeholders = {"fixture_query": "купить ёлку"}
    assert expand_argv(["search", "{fixture_query}", "--json"], placeholders) == ["search", "купить ёлку", "--json"]
    with pytest.raises(ContractError, match=r"placeholder \{fixture_empty_query\}.*tests/contracts/fixtures\.yaml"):
        expand_argv(["search", "{fixture_empty_query}"], placeholders)


def test_output_checks() -> None:
    schema = {"type": "object", "required": ["ok", "results"], "properties": {"results": {"type": "array"}}}
    check_output({"exit": 0, "stdout_json_schema": schema}, 0, '{"ok": true, "results": [], "extra": 1}')
    check_output({"exit": 0, "stdout_regex": r"^\d+\.\d+\.\d+"}, 0, "0.7.0\n")
    with pytest.raises(ContractError, match="'results' is a required property"):
        check_output({"exit": 0, "stdout_json_schema": schema}, 0, '{"ok": true}')
    with pytest.raises(ContractError, match="exit code 5, the consumer expects 0"):
        check_output({"exit": 0}, 5, "")
    with pytest.raises(ContractError, match="not JSON"):
        check_output({"exit": 0, "stdout_json_schema": schema}, 0, "Done.")
    with pytest.raises(ContractError, match="doesn't match"):
        check_output({"exit": 0, "stdout_regex": r"^\d"}, 0, "v0.7")


def _probe() -> typer.Typer:
    probe = typer.Typer()

    @probe.command()
    def fetch(swallow: bool = typer.Option(False, help="Catch the network error like a provider would.")) -> None:
        """Talk to the network."""
        try:
            socket.create_connection(("example.com", 80), timeout=1)
        except OSError:
            if not swallow:
                raise
            raise typer.Exit(5) from None

    @probe.command()
    def env() -> None:
        """Print an env var."""
        import os

        typer.echo(os.environ.get("X_XMLRIVER_USER", "unset"))

    return probe


def test_a_case_that_reaches_the_network_fails_even_if_the_cli_catches_it(request: pytest.FixtureRequest) -> None:
    for argv in (["fetch"], ["fetch", "--swallow"]):
        with pytest.raises(ContractError, match=r"tried the network: example\.com"):
            run_case({"argv": argv, "exit": 5}, request, {}, app=_probe(), document=DOCUMENT)


def test_run_env_has_no_real_keys_and_env_unset_applies(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("X_XMLRIVER_USER", "real-key")
    case = {"argv": ["env"], "exit": 0, "stdout_regex": "^unset$"}
    run_case(case, request, {}, app=_probe(), document=DOCUMENT)  # credentials from x-rb-env are never passed in
    run_case({**case, "env_unset": ["X_XMLRIVER_USER"]}, request, {}, app=_probe(), document=DOCUMENT)


def test_offline_cache_uses_the_providers_fixture(request: pytest.FixtureRequest) -> None:
    case = {"argv": ["env"], "exit": 0}
    with pytest.raises(ContractError, match="fixture 'no_such_cache_fixture'"):
        run_case(case, request, {"offline_cache": "no_such_cache_fixture"}, app=_probe(), document=DOCUMENT)
    run_case(case, request, {"offline_cache": "tmp_path"}, app=_probe(), document=DOCUMENT)
    run_case(
        {**case, "offline_cache": False},
        request,
        {"offline_cache": "no_such_cache_fixture", "no_cache": "tmp_path"},
        app=_probe(),
        document=DOCUMENT,
    )


def test_view_columns_by_type_family() -> None:
    actual = {"model": "VARCHAR", "at": "TIMESTAMP", "x": "INTEGER"}
    check_view_columns("x_v1_calls", {"model": "text", "at": "datetime"}, actual)
    with pytest.raises(ContractError, match="column 'at'"):
        check_view_columns("x_v1_calls", {"at": "datetime"}, {"model": "TEXT"})
    assert type_family("TIMESTAMP WITH TIME ZONE") == "datetime"
    assert type_family("BIGINT") == "integer"
    assert type_family("JSONB") == "json"


WINDMILL = Path(__file__).parent / "data" / "contracts" / "windmill-serp.yaml"  # the first real contract, verbatim


def test_the_windmill_contract_is_accepted_as_is(tmp_path: Path) -> None:
    """~/Work/dev/windmill/tests/contracts/serp/windmill.yaml validates unchanged and expands into its cases."""
    (tmp_path / "windmill").mkdir()
    (tmp_path / "windmill" / "serp.yaml").write_text(WINDMILL.read_text())
    [contract] = load_contracts(tmp_path, provider="serp")
    assert (contract.consumer, contract.data["provider_range"]) == ("windmill", ">=0.6,<1.0")
    assert case_ids(contract) == [
        "windmill:static:command:search",
        "windmill:static:command:cache info",
        "windmill:static:command:describe",
        "windmill:static:root_options",
        "windmill:static:exit_codes",
        "windmill:static:env",
        "windmill:run:version",
        "windmill:run:search_json_envelope",
        "windmill:run:empty_result_is_success",
        "windmill:run:error_is_json_under_json",
        "windmill:run:auth_missing_is_exit_3",
        "windmill:run:cache_info_json",
        "windmill:run:describe_json",
    ]
