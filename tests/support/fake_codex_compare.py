#!/usr/bin/env python3
"""A stand-in `codex` for `check_backend_compat.py compare` (#376), stdlib only.

`compare` runs every probe under an environment that keeps PATH and nothing else, so this
fake cannot be steered by environment variables. It reads its behavior from a JSON file
beside itself instead (`codex` reads `codex.json`), which a test writes:

    version          what `--version` reports (default 0.163.0)
    commands         subcommand names `--help` lists
    exec_flags       extra option rows for `exec --help`
    features         {name: [stage, default]} for `features list`
    logged_in        `login status` reports a ChatGPT login (default false)
    login_status     replaces `login status` outright: {"stdout", "stderr", "exit"}, or
                     {"signal": N} to die by that signal
    exec_help_exit   `exec --help` prints nothing and exits with this status
    override_wording replaces the strict-config override rejection's wording
    accept_unknown_feature   an unknown `--disable` name is not rejected
    reject_keys      `-c` keys rejected as unknown under `--strict-config`
    exec_exit        how a run that gets past config loading exits (default 1, the 401)
    exec_end         replaces that run's ending outright: {"stdout", "stderr", "exit"}
    models           what `debug models` prints
    log              a file that gets one JSON line per invocation: argv, the environment's
                     keys and CODEX_HOME, and what arrived on stdin

`exec --help` pads its blank lines with spaces, as codex does, so a committed capture only
matches it under the whitespace policy. An `exec` run checks its arguments, then its
features, then its configuration, the order codex reports them in, and a run that gets past
all three ends the way an unauthenticated codex does: a 401 on stderr."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_SPEC = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
_VALUE_FLAGS = {
    "--sandbox",
    "--cd",
    "--output-last-message",
    "--output-schema",
    "--add-dir",
    "--model",
    "-c",
    "--config",
    "--disable",
    "--enable",
}
_BOOL_FLAGS = {
    "--json",
    "--skip-git-repo-check",
    "--ephemeral",
    "--ignore-user-config",
    "--ignore-rules",
    "--strict-config",
}
_SANDBOXES = ("read-only", "workspace-write", "danger-full-access")
_KNOWN_KEYS = {
    "model_reasoning_effort",
    "sandbox_workspace_write.network_access",
    "sandbox_workspace_write.writable_roots",
    "developer_instructions",
    "sandbox_mode",
    "approval_policy",
}
_FEATURES = {
    "goals": ["stable", "true"],
    "remote_plugin": ["stable", "true"],
    "sleep_tool": ["stable", "true"],
    "some_feature": ["under development", "false"],
}


def _exec_help() -> str:
    flags = sorted(_VALUE_FLAGS | _BOOL_FLAGS - {"-c", "--config"}) + _SPEC.get("exec_flags", [])
    rows = "\n".join(f"      {flag}\n          (fake)\n          " for flag in flags)
    return (
        f"Run Codex non-interactively\n\nUsage: codex exec [OPTIONS] [PROMPT]\n\nOptions:\n{rows}\n"
    )


def _help() -> str:
    names = _SPEC.get("commands", ["exec", "login", "features", "debug"])
    rows = "\n".join(f"  {name:<16}  The {name} command" for name in names)
    head = "Codex CLI\n\nUsage: codex [OPTIONS] <COMMAND>\n\n"
    return f"{head}Commands:\n{rows}\n\nOptions:\n  -h, --help\n"


def _fail(text: str, code: int = 1) -> int:
    sys.stderr.write(text)
    return code


def _exec(args: list[str]) -> int:
    strict = ignore_user_config = False
    overrides: list[tuple[str, str]] = []
    disabled: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "-":
            i += 1
            continue
        if arg in _BOOL_FLAGS:
            strict |= arg == "--strict-config"
            ignore_user_config |= arg == "--ignore-user-config"
            i += 1
            continue
        if arg not in _VALUE_FLAGS:
            return _fail(f"error: unexpected argument '{arg}' found\n\nUsage: codex exec\n", 2)
        value = args[i + 1]
        if arg == "--sandbox" and value not in _SANDBOXES:
            return _fail(
                f"error: invalid value '{value}' for '--sandbox <SANDBOX_MODE>'\n"
                f"  [possible values: {', '.join(_SANDBOXES)}]\n",
                2,
            )
        if arg in ("-c", "--config"):
            key, _, raw = value.partition("=")
            overrides.append((key, raw))
        if arg == "--disable":
            disabled.append(value)
        i += 2
    features = _SPEC.get("features", _FEATURES)
    for name in disabled:
        if name not in features and not _SPEC.get("accept_unknown_feature"):
            return _fail(f"Error: Unknown feature flag: {name}\n")
    for key, raw in overrides:
        variant = raw.strip('"')
        if key == "sandbox_mode" and variant not in _SANDBOXES:
            choices = ", ".join(f"`{s}`" for s in _SANDBOXES)
            return _fail(
                f"Error loading config.toml: unknown variant `{variant}`, expected one of "
                f"{choices}\nin `sandbox_mode`\n"
            )
        if key == "approval_policy" and raw == '"untrusted"':
            return _fail(
                f"Error: approval_policy = {raw} is no longer supported; remove this setting\n"
            )
        if strict and (key not in _KNOWN_KEYS or key in _SPEC.get("reject_keys", [])):
            wording = _SPEC.get("override_wording", "in -c/--config override")
            return _fail(
                f"Error loading config.toml: unknown configuration field `{key}` {wording}\n"
            )
    config = Path(os.environ.get("CODEX_HOME", "/nonexistent")) / "config.toml"
    if strict and not ignore_user_config and config.is_file():
        key = config.read_text(encoding="utf-8").split("=")[0].strip()
        if key not in _KNOWN_KEYS:
            return _fail(
                f"Error loading config.toml:\n{config}:1:1: unknown configuration field `{key}`\n"
            )
    end = _SPEC.get("exec_end")
    if end is not None:
        sys.stdout.write(end.get("stdout", ""))
        sys.stderr.write(end.get("stderr", ""))
        return int(end.get("exit", 1))
    sys.stderr.write(
        "ERROR: unexpected status 401 Unauthorized: Missing bearer or basic authentication "
        "in header, url: https://api.example.invalid/v1/responses\n"
    )
    return int(_SPEC.get("exec_exit", 1))


def main() -> int:
    argv = sys.argv[1:]
    stdin = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
    log = _SPEC.get("log")
    if log:
        with Path(log).open("a", encoding="utf-8") as out:
            entry = {
                "argv": argv,
                "env": sorted(os.environ),
                "codex_home": os.environ.get("CODEX_HOME"),
                "stdin": stdin,
            }
            out.write(json.dumps(entry) + "\n")
    if argv == ["--version"]:
        print(f"codex-cli {_SPEC.get('version', '0.163.0')}")
        return 0
    if argv == ["--help"]:
        sys.stdout.write(_help())
        return 0
    if argv == ["exec", "--help"]:
        if "exec_help_exit" in _SPEC:
            return int(_SPEC["exec_help_exit"])
        sys.stdout.write(_exec_help())
        return 0
    if argv == ["exec", "review", "--help"]:
        print("Run a code review\n\nOptions:\n      --uncommitted\n          (fake)")
        return 0
    if argv == ["login", "--help"]:
        print("Manage login\n\nCommands:\n  status  Show login status")
        return 0
    if argv == ["login", "status"]:
        override = _SPEC.get("login_status")
        if override is not None:
            if "signal" in override:
                os.kill(os.getpid(), int(override["signal"]))
            sys.stdout.write(override.get("stdout", ""))
            sys.stderr.write(override.get("stderr", ""))
            return int(override.get("exit", 1))
        if _SPEC.get("logged_in"):
            print("Logged in using ChatGPT")
            return 0
        return _fail("Not logged in\n")
    if argv == ["features", "list"]:
        for name, (stage, default) in sorted(_SPEC.get("features", _FEATURES).items()):
            print(f"{name:<40} {stage:<18} {default}")
        return 0
    if argv == ["debug", "models"]:
        sys.stdout.write(_SPEC.get("models", "fake-model\n"))
        return 0
    if argv[:1] == ["exec"]:
        return _exec(argv[1:])
    return _fail(f"fake codex: unhandled {argv}\n", 2)


if __name__ == "__main__":
    sys.exit(main())
