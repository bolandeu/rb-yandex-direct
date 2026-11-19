"""`describe --json`: this CLI as an OpenCLI document (https://opencli.org, spec 0.1).

The machine-readable contract of the tool for the architect, Windmill and the
tools catalog. Commands, options and arguments come from the Click tree Typer
builds — nothing is written twice. Read by duck typing (`param_type_name`,
`commands`): recent Typer ships its own copy of Click, so `isinstance` checks
against the `click` package would match nothing. OpenCLI has no fields for a parameter's type
or default, nor metadata on the document itself, so ours go into `metadata`
entries named `x-rb-*`: per option/argument `x-rb-type`, `x-rb-default`
(always present, null when there is no default or it is computed at run time),
`x-rb-multiple`; on the root command the tool's env vars, data, external
programs and template version.

The output is a cross-tool contract like `auth status`: tests/test_describe.py
validates it against the OpenCLI schema and snapshots it. Changing or removing
anything in it is a breaking change.
"""

from __future__ import annotations

import enum
import importlib
import inspect
import json
import os
from dataclasses import asdict
from pathlib import PurePath
from typing import Any

import platformdirs

from .._distribution import DIST_NAME, TEMPLATE_VERSION, TOOL
from . import data_files, deps
from .errors import EXIT_CODES
from .version import DEV_VERSION, cli_name, installed_version, module_exists, optional_module, package_summary

OPENCLI_VERSION = "0.1"
_PACKAGE_NAME = __name__.split(".")[0]


def document(root: Any) -> dict:
    """The OpenCLI document for the CLI whose root command is `root`."""
    command = _command(cli_name(), root)
    # The root's help carries the version ("<cli> 1.2.3 — ..."); it is in `info` already.
    command.pop("description", None)
    command["exitCodes"] = [{"code": code, "description": meaning} for code, meaning in EXIT_CODES.items()]
    command["metadata"] = _meta(
        {
            # Shared-database namespace, `uv tool install` name, import package.
            "x-rb-tool": {"tool": TOOL, "dist": DIST_NAME, "package": _PACKAGE_NAME},
            "x-rb-template-version": TEMPLATE_VERSION,
            "x-rb-env": env_vars(),
            "x-rb-data": data(),
            "x-rb-external": [asdict(spec) for spec in deps.declared().values()],
            "x-rb-skills": _bundled_skills(),
        }
    )
    return {"opencli": OPENCLI_VERSION, "info": info(), "command": command}


def _bundled_skills() -> list[dict]:
    """The agent skills the package ships (the package skill part, copier's include_skill); none without it.

    Each entry names the skill, describes it and carries the path of the directory that holds its
    SKILL.md, so a consumer reads the text with no second process. A zip import has no such
    directory: `path` is left out rather than invented.
    """
    skills = optional_module(f"{_PACKAGE_NAME}.core.skills")
    if not skills:
        return []
    return [
        {"name": s.name, "description": s.description, **({"path": s.path} if getattr(s, "path", None) else {})}
        for s in skills.bundled()
    ]


def info() -> dict:
    """The `info` of the document: the name of the CLI, its version and its summary."""
    found = {"title": cli_name(), "version": installed_version() or DEV_VERSION}
    if summary := package_summary():
        found["summary"] = summary
    return found


def _command(name: str, cmd: Any) -> dict:
    out: dict[str, Any] = {"name": name}
    if description := cleaned(cmd.help):
        out["description"] = description
    if cmd.hidden:
        out["hidden"] = True
    options = [option(p) for p in cmd.params if p.param_type_name == "option"]
    arguments = [argument(p) for p in cmd.params if p.param_type_name == "argument"]
    if options:
        out["options"] = options
    if arguments:
        out["arguments"] = arguments
    if (subcommands := getattr(cmd, "commands", None)) is not None:  # a group
        # Registration order (Typer keeps it): the order `--help` shows.
        out["commands"] = [_command(sub_name, sub) for sub_name, sub in subcommands.items()]
    return out


def option(param: Any) -> dict:
    """The OpenCLI entry of a Click option."""
    names = sorted(param.opts, key=len, reverse=True)  # the long form is the name
    out: dict[str, Any] = {"name": names[0]}
    if aliases := [*names[1:], *param.secondary_opts]:
        out["aliases"] = aliases
    if param.required:
        out["required"] = True
    if not param.is_flag and not param.count:
        value: dict[str, Any] = {"name": param.metavar or (param.name or "value").upper(), "required": True}
        if not param.multiple:
            value["arity"] = {"maximum": 1}
        if choices := _choices(param.type):
            value["acceptedValues"] = choices
        out["arguments"] = [value]
    if description := cleaned(param.help):
        out["description"] = description
    if param.hidden:
        out["hidden"] = True
    out["metadata"] = _param_meta(param, multiple=param.multiple)
    return out


def argument(param: Any) -> dict:
    """The OpenCLI entry of a Click argument."""
    out: dict[str, Any] = {"name": param.name or "argument"}
    out["required"] = param.required
    maximum = None if param.nargs == -1 else param.nargs
    out["arity"] = {"minimum": param.nargs if param.required and param.nargs > 0 else int(param.required)}
    if maximum is not None:
        out["arity"]["maximum"] = maximum
    if choices := _choices(param.type):
        out["acceptedValues"] = choices
    if description := cleaned(getattr(param, "help", None)):  # Typer's arguments carry help
        out["description"] = description
    if getattr(param, "hidden", False):
        out["hidden"] = True
    out["metadata"] = _param_meta(param, multiple=param.nargs == -1)
    return out


def _param_meta(param: Any, *, multiple: bool) -> list[dict]:
    default = param.default
    # x-rb-default is always there: the value, or null when there is none or it is computed at run time.
    no_default = default is None or callable(default) or default == ()
    meta: dict[str, Any] = {"x-rb-type": param.type.name, "x-rb-default": None if no_default else jsonable(default)}
    if multiple:
        meta["x-rb-multiple"] = True
    return _meta(meta, keep_null=("x-rb-default",))


def _choices(param_type: Any) -> list[str] | None:
    choices = getattr(param_type, "choices", None)  # a Choice (or an Enum Typer turned into one)
    return [str(jsonable(choice)) for choice in choices] if choices else None


def jsonable(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, PurePath):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def cleaned(text: str | None) -> str:
    """A help text as the docstring wrote it."""
    # output.guard escaped `[` for Typer's rich markup; the document wants the docstring itself.
    return inspect.cleandoc(text or "").replace("\\[", "[").strip()


def _meta(values: dict[str, Any], keep_null: tuple[str, ...] = ()) -> list[dict]:
    """Metadata entries; a null value is dropped unless `keep_null` names its key."""
    return [{"name": name, "value": value} for name, value in values.items() if value is not None or name in keep_null]


def env_vars() -> list[dict]:
    """Every env var the tool reads: provider credentials, then the database's."""
    found: list[dict] = []
    manager_module = f"{_PACKAGE_NAME}.credentials.manager"
    providers_module = f"{_PACKAGE_NAME}.providers.base"
    if module_exists(manager_module) and module_exists(providers_module):
        manager = importlib.import_module(manager_module)
        for provider in importlib.import_module(providers_module).all_providers():
            # A per-target credential's name holds the target: <NS>_<PROVIDER>_<TARGET>_<FIELD>.
            key = f"{provider.name}:TARGET" if provider.per_target else provider.name
            for field in provider.credential_fields:
                entry: dict[str, Any] = {
                    "name": manager.env_var_name(key, field).replace("_TARGET_", "_<TARGET>_"),
                    "purpose": "credential",
                    "provider": provider.name,
                    "field": field,
                    "required": provider.required,
                }
                fallbacks = [manager.env_var_name(key, field, ns) for ns in provider.shared_namespaces]
                if field in provider.legacy_env:
                    fallbacks.append(provider.legacy_env[field])
                if fallbacks:
                    entry["fallbacks"] = [name.replace("_TARGET_", "_<TARGET>_") for name in fallbacks]
                found.append(entry)
    if module_exists(f"{_PACKAGE_NAME}.core.db"):
        db = importlib.import_module(f"{_PACKAGE_NAME}.core.db")
        found += [
            {"name": name, "purpose": "database", "description": description, "required": False}
            for name, description in db.ENV_VARS.items()
        ]
    return found


def data() -> dict:
    """The tool's tables, `<tool>_v1_*` views and files in the user data dir."""
    files = [asdict(entry) for entry in data_files.DATA_FILES]
    out: dict[str, Any] = {}
    if module_exists(f"{_PACKAGE_NAME}.core.tables"):
        tables = importlib.import_module(f"{_PACKAGE_NAME}.core.tables")
        out["tables"] = [
            {
                "name": table.name,
                "schema": table.schema or "public",
                "kind": table.info.get("kind"),
                **({"description": table.comment} if table.comment else {}),
                "columns": [
                    {
                        "name": column.name,
                        "type": str(column.type),
                        "nullable": bool(column.nullable),
                        **({"primary_key": True} if column.primary_key else {}),
                    }
                    for column in table.columns
                ],
                **({"push": True} if "push" in table.info else {}),
            }
            for table in tables.metadata.tables.values()
        ]
        out["views"] = [
            {
                "name": view.name,
                **({"description": view.comment} if view.comment else {}),
                "columns": [
                    {
                        "name": column.name,
                        "type": str(column.type),
                        **({"description": column.comment} if column.comment else {}),
                    }
                    for column in view.columns
                ],
            }
            for view in tables.views.tables.values()
        ]
        files.insert(
            0,
            {
                "path": _sqlite_file(),
                "kind": "data",
                "description": "The local SQLite database, used when the shared database URL is unset",
            },
        )
    out["user_data_dir"] = {"appname": TOOL, "files": files}
    return out


def _sqlite_file() -> str:
    """Where `db.sqlite_path()` puts the local database by default: relative to the user data dir.

    A tool may name the file its own way (serp: `serp.sqlite`), so it is asked, with
    `<TOOL>_DB_PATH` hidden — the contract is the default, not this machine's override.
    """
    db = importlib.import_module(f"{_PACKAGE_NAME}.core.db")
    override = os.environ.pop(db.PATH_ENV_VAR, None)
    try:
        path = db.sqlite_path()
    finally:
        if override is not None:
            os.environ[db.PATH_ENV_VAR] = override
    try:
        return path.relative_to(platformdirs.user_data_path(TOOL)).as_posix()
    except ValueError:  # the tool keeps it outside the data dir
        return path.as_posix()
