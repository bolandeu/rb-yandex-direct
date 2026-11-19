"""Consumer contracts: what other tools, Windmill flows and the platform rely on in this CLI.

The contracts are written by the consumers (through dev), not by this tool:
`tests/contracts/<consumer>/<provider>.yaml`, format `contract: 1`
(`tests/contracts/schema.json`; the Standard, Consumer contracts). The source of
truth is the consumer's repo; this repo keeps a copy and runs it in its gate.

- `static` — against `describe --json`: commands (path, arguments, options), root
  options, documented exit codes, env var names (`x-rb-env`);
- `run` — the CLI in-process with `argv`, offline: no network (a case that tries
  fails, even when the CLI catches the error), no real keys (every `x-rb-env` var
  unset, the OS keychain disabled); `{placeholders}` in argv and the offline data
  come from this repo's `tests/contracts/fixtures.yaml`; then the exit code and
  `stdout_json_schema` (extra fields fine, missing required ones not) or `stdout_regex`;
- `view` — a `v1` view's columns and type families, in `describe --json` and on
  the migrated test database (SQLite; PostgreSQL too under scripts/pg_test.sh).

`provider_range` limits a contract to those versions of this tool. One test per
case, id `<consumer>:<section>:<name>`. The gate runs this file as its own step
(`gate check`: "contracts"); a failing case stops the release. Never edit
a consumer's contract to make it pass — that's the point.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import socket
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import typer
import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version
from typer.testing import CliRunner

from rb_yandex_direct.cli import app as cli_app
from rb_yandex_direct.core import opencli
from rb_yandex_direct.core.version import DEV_VERSION, cli_name, installed_version

CONTRACTS = Path(__file__).parent / "contracts"
SCHEMA = json.loads((CONTRACTS / "schema.json").read_text())
FIXTURES = CONTRACTS / "fixtures.yaml"
# The version the gate is building, when set, else the installed one.
VERSION_ENV = "RB_PROVIDER_VERSION"
PG_URL = os.environ.get("TEST_DATABASE_URL")
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
FAMILIES = (  # (substring of the SQL type, family); first match wins
    ("timestamp", "datetime"),
    ("datetime", "datetime"),
    ("date", "date"),
    ("int", "integer"),
    ("bool", "boolean"),
    ("json", "json"),
    ("char", "text"),
    ("text", "text"),
    ("string", "text"),
    ("uuid", "text"),
    ("float", "number"),
    ("double", "number"),
    ("real", "number"),
    ("numeric", "number"),
    ("decimal", "number"),
)


class ContractError(Exception):
    """A consumer's expectation this CLI doesn't meet, or a contract file that can't be read."""


@dataclass(frozen=True)
class Contract:
    consumer: str
    file: str
    data: dict[str, Any]


def _validate(content: Any, definition: str, name: str) -> None:
    validator = jsonschema.Draft202012Validator({**SCHEMA, "$ref": f"#/$defs/{definition}"})
    if errors := sorted(validator.iter_errors(content), key=lambda e: list(map(str, e.absolute_path))):
        where = "/".join(str(part) for part in errors[0].absolute_path) or "(top)"
        raise ContractError(f"{name}: {where}: {errors[0].message} (format: tests/contracts/schema.json)")


def _read(path: Path, name: str) -> Any:
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ContractError(f"{name}: not valid YAML: {exc}") from exc


def load_contracts(root: Path = CONTRACTS, provider: str | None = None) -> list[Contract]:
    """Every contract under `root` for `provider` (this CLI), validated against schema.json."""
    provider = provider or cli_name()
    contracts: list[Contract] = []
    for path in sorted(root.glob("*/*.yaml")):
        name = f"{path.parent.name}/{path.name}"
        content = _read(path, name)
        _validate(content, "contract", name)
        if content["provider"] != provider:
            raise ContractError(f"{name}: a contract for provider '{content['provider']}', this is '{provider}'")
        contracts.append(Contract(content["consumer"], name, content))
    return contracts


def load_fixtures(path: Path = FIXTURES) -> dict[str, Any]:
    """This repo's side of the `run` cases: placeholder values and the fixtures preparing offline data."""
    if not path.is_file():
        return {}
    content = _read(path, "fixtures.yaml") or {}
    _validate(content, "fixtures", "fixtures.yaml")
    return content


def cases(contract: Contract) -> list[tuple[str, str, Any]]:
    """(test id, kind, spec) for every check in the contract."""
    prefix = contract.consumer
    static = contract.data.get("static") or {}
    found = [
        (f"{prefix}:static:command:{' '.join(spec['path'])}", "command", spec) for spec in static.get("commands", [])
    ]
    found += [
        (f"{prefix}:static:{key}", key, static[key]) for key in ("root_options", "exit_codes", "env") if key in static
    ]
    found += [(f"{prefix}:run:{spec['name']}", "run", spec) for spec in contract.data.get("run") or []]
    found += [(f"{prefix}:view:{spec['name']}", "view", spec) for spec in contract.data.get("view") or []]
    return found


def case_ids(contract: Contract) -> list[str]:
    return [case_id for case_id, _kind, _spec in cases(contract)]


def applies(data: dict, version: str) -> bool:
    """Whether the contract's `provider_range` (if any) contains `version` (a dev build of X counts as X)."""
    if "provider_range" not in data:
        return True
    try:
        wanted = SpecifierSet(data["provider_range"])
    except InvalidSpecifier as exc:
        raise ContractError(f"provider_range {data['provider_range']!r} is not a version range") from exc
    return Version(Version(version).base_version) in wanted


# --- static ----------------------------------------------------------------------


def _metadata(document: dict, name: str) -> Any:
    return next((item.get("value") for item in document["command"].get("metadata", []) if item["name"] == name), None)


def _option_names(command: dict) -> set[str]:
    return {name for option in command.get("options", []) for name in (option["name"], *option.get("aliases", []))}


def check_static_command(spec: dict, document: dict) -> None:
    command = document["command"]
    path = " ".join(spec["path"])
    for part in spec["path"]:
        command = next((c for c in command.get("commands", []) if c["name"] == part), None)
        if command is None:
            raise ContractError(f"no command '{path}' (at '{part}') in describe --json")
    arguments = [argument["name"] for argument in command.get("arguments", [])]
    for argument in spec.get("arguments", []):
        if argument not in arguments:
            raise ContractError(f"'{path}' has no argument '{argument}' (it has: {', '.join(arguments) or 'none'})")
    names = _option_names(command)
    for option in spec.get("options", []):
        if option not in names:
            raise ContractError(f"'{path}' has no option '{option}' (it has: {', '.join(sorted(names)) or 'none'})")


def check_root_options(options: list[str], document: dict) -> None:
    names = _option_names(document["command"])
    for option in options:
        if option not in names:
            raise ContractError(f"no root option '{option}' (root options: {', '.join(sorted(names))})")


def check_exit_codes(codes: list[int], document: dict) -> None:
    documented = {entry["code"] for entry in document["command"].get("exitCodes", [])}
    for code in codes:
        if code not in documented:
            raise ContractError(f"exit code {code} is not documented (exitCodes: {sorted(documented)})")


def _env_names(document: dict) -> set[str]:
    return {
        name for entry in _metadata(document, "x-rb-env") or [] for name in (entry["name"], *entry.get("fallbacks", []))
    }


def check_env(names: list[str], document: dict) -> None:
    known = _env_names(document)
    for name in names:
        if name not in known:
            raise ContractError(
                f"env '{name}' is not one this CLI reads (x-rb-env: {', '.join(sorted(known)) or 'none'})"
            )


# --- run -------------------------------------------------------------------------


def expand_argv(argv: list[str], placeholders: dict[str, str]) -> list[str]:
    def value(match: re.Match[str]) -> str:
        if match[1] not in placeholders:
            name = "{" + match[1] + "}"
            raise ContractError(f"placeholder {name} is not defined in tests/contracts/fixtures.yaml (placeholders:)")
        return str(placeholders[match[1]])

    return [re.sub(r"\{(\w+)\}", value, arg) for arg in argv]


def check_output(spec: dict, exit_code: int, stdout: str) -> None:
    if exit_code != spec["exit"]:
        raise ContractError(f"exit code {exit_code}, the consumer expects {spec['exit']}; output: {stdout[:500]}")
    if "stdout_regex" in spec and not re.search(spec["stdout_regex"], stdout):
        raise ContractError(f"output doesn't match {spec['stdout_regex']!r}: {stdout[:500]}")
    if "stdout_json_schema" not in spec:
        return
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ContractError(f"output is not JSON ({exc}): {stdout[:500]}") from exc
    errors = sorted(jsonschema.Draft202012Validator(spec["stdout_json_schema"]).iter_errors(payload), key=str)
    if errors:
        where = "/".join(str(part) for part in errors[0].absolute_path) or "(top)"
        raise ContractError(f"output at {where}: {errors[0].message}")


def resolve_fixture(request: pytest.FixtureRequest, name: str) -> Any:
    """The provider's fixture by name — a clear error when this repo has none."""
    try:
        return request.getfixturevalue(name)
    except pytest.FixtureLookupError as exc:
        raise ContractError(
            f"fixture '{name}' doesn't exist in this repo's tests (define it in tests/conftest.py)"
        ) from exc


def _local(host: Any) -> bool:
    return isinstance(host, str) and (host in LOCAL_HOSTS or host.startswith("127."))


@contextlib.contextmanager
def offline(mp: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """No network but loopback: every attempt is refused and recorded (a caught error still counts)."""
    attempts: list[str] = []
    real_getaddrinfo, real_connect = socket.getaddrinfo, socket.socket.connect

    def getaddrinfo(host, port, *args, **kwargs):
        if not _local(host):
            attempts.append(f"{host}:{port}")
            raise OSError(f"contract run: network blocked ({host})")
        return real_getaddrinfo(host, port, *args, **kwargs)

    def connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _local(address[0]):
            attempts.append(f"{address[0]}:{address[1]}")
            raise OSError(f"contract run: network blocked ({address[0]})")
        return real_connect(self, address)

    mp.setattr(socket, "getaddrinfo", getaddrinfo)
    mp.setattr(socket.socket, "connect", connect)
    yield attempts


@contextlib.contextmanager
def _no_keychain() -> Iterator[None]:
    import keyring
    from keyring.backends import fail

    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    try:
        yield
    finally:
        keyring.set_keyring(previous)


def run_case(
    spec: dict,
    request: pytest.FixtureRequest,
    fixtures: dict[str, Any],
    *,
    app: typer.Typer = cli_app,
    document: dict | None = None,
) -> None:
    """A `run` case: offline, no real keys, the provider's offline data in place; then its result."""
    document = document or opencli.document(typer.main.get_command(app))
    argv = expand_argv(spec["argv"], fixtures.get("placeholders") or {})
    with pytest.MonkeyPatch.context() as mp, _no_keychain():
        for name in _env_names(document) | set(spec.get("env_unset", [])):
            mp.delenv(name, raising=False)
        prepare = fixtures.get("offline_cache" if spec.get("offline_cache", True) else "no_cache")
        if prepare:
            resolve_fixture(request, prepare)
        with offline(mp) as attempts:
            result = CliRunner().invoke(app, argv)
    if attempts:
        raise ContractError(
            f"the case tried the network: {', '.join(sorted(set(attempts)))} — a contract run is offline "
            "(offline data from fixtures.yaml `offline_cache`; `offline_cache: false` must fail before the provider)"
        )
    check_output(spec, result.exit_code, result.stdout)


# --- view ------------------------------------------------------------------------


def type_family(sql_type: str) -> str:
    """'TIMESTAMP WITH TIME ZONE' -> 'datetime', 'BIGINT' -> 'integer', ... ('other' when unknown)."""
    lowered = sql_type.lower()
    return next((family for marker, family in FAMILIES if marker in lowered), "other")


def check_view_columns(view: str, expected: dict[str, str], actual: dict[str, str]) -> None:
    """`expected` (column -> family, "any" for any) against the view's `actual` columns (name -> SQL type)."""
    for column, family in expected.items():
        if column not in actual:
            raise ContractError(f"view '{view}' has no column '{column}' (it has: {', '.join(actual) or 'none'})")
        found = type_family(actual[column])
        if family != "any" and found != family:
            raise ContractError(f"view '{view}': column '{column}' is {found}, the consumer expects {family}")


def described_view_columns(view: str, document: dict) -> dict[str, str]:
    views = {entry["name"]: entry for entry in (_metadata(document, "x-rb-data") or {}).get("views", [])}
    if view not in views:
        raise ContractError(f"no view '{view}' in describe --json (views: {', '.join(views) or 'none'})")
    return {column["name"]: column["type"] for column in views[view]["columns"]}


def database_view_columns(view: str) -> dict[str, str]:
    """The view's columns (name -> SQL type) on the test database: tests' SQLite, or PostgreSQL under pg_test.sh."""
    raise ContractError(f"this tool has no database, so no view '{view}'")


# --- the tests ---------------------------------------------------------------------


def _version() -> str:
    return os.environ.get(VERSION_ENV) or installed_version() or DEV_VERSION.split("-")[0]


try:
    CONTRACT_LIST = load_contracts()
    FIXTURE_SPEC = load_fixtures()
except ContractError as exc:  # a broken file fails the run, naming the file
    CONTRACT_LIST, FIXTURE_SPEC = [], {}
    LOAD_ERROR: str | None = str(exc)
else:
    LOAD_ERROR = None
CASES = [(contract, case_id, kind, spec) for contract in CONTRACT_LIST for case_id, kind, spec in cases(contract)]


def test_contract_files_are_valid() -> None:
    assert LOAD_ERROR is None, LOAD_ERROR


@pytest.mark.parametrize(("contract", "case_id", "kind", "spec"), CASES, ids=[case[1] for case in CASES])
def test_contract(
    contract: Contract,
    case_id: str,
    kind: str,
    spec: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version = _version()
    if not applies(contract.data, version):
        pytest.skip(f"{case_id}: provider_range {contract.data['provider_range']}, this is {version}")
    document = opencli.document(typer.main.get_command(cli_app))
    try:
        if kind == "command":
            check_static_command(spec, document)
        elif kind == "root_options":
            check_root_options(spec, document)
        elif kind == "exit_codes":
            check_exit_codes(spec, document)
        elif kind == "env":
            check_env(spec, document)
        elif kind == "run":
            run_case(spec, request, FIXTURE_SPEC, document=document)
        else:
            check_view_columns(spec["name"], spec["columns"], described_view_columns(spec["name"], document))
            check_view_columns(spec["name"], spec["columns"], database_view_columns(spec["name"]))
    except ContractError as exc:
        pytest.fail(f"{case_id} ({contract.file}): {exc}", pytrace=False)
