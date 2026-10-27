#!/usr/bin/env python3
"""A stand-in `codex` for `scripts/capture_codex_wire_tools.py` (#380), stdlib only.

The capture script runs codex under an environment that keeps PATH, the scratch homes and
the probe's proxy settings and nothing else, so this fake reads its behavior from a JSON file
beside itself (`codex` reads `codex.json`), which a test writes:

    version          what `--version` reports (default 0.164.0)
    features         feature names `features list` lists (each stable, true)
    reject_features  feature names an `exec` run rejects as unknown even though listed
    bundled          the models `debug models --bundled` prints; absent: it fails
    tools            {model: [tool, ...]} the top-level `tools` a request carries; a model
                     with no entry gets `default_tools`
    additional       {model: [tool, ...]} carried as an `additional_tools` input item
    default_tools    the tools of any model `tools` does not name
    gated            {feature: [name, ...]} tools (top-level, or a namespace's members) that
                     `--disable <feature>` removes
    ignore_disables  `--disable` removes nothing
    no_request       exit 1 before sending any request
    connect          hosts to CONNECT to through the proxy before the request
    fallback         print codex's fallback-metadata warning for the run's model
    log              a file that gets one JSON line per invocation: argv, the environment's
                     keys and what arrived on stdin

An `exec` run rejects an unknown `--disable` the way codex does, then POSTs one request to the
`base_url` of the provider named in its `-c` overrides, straight to loopback, and exits 0 once
the answer holds a completed turn."""

from __future__ import annotations

import http.client
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

_SPEC = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))


def _log(argv: list[str], stdin: str) -> None:
    if _SPEC.get("log"):
        with Path(_SPEC["log"]).open("a", encoding="utf-8") as fh:
            entry = {"argv": argv, "env": sorted(os.environ), "stdin": stdin}
            fh.write(json.dumps(entry) + "\n")


def _values(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, token in enumerate(argv[:-1]) if token == flag]


def _undeclare(tool: dict, gone: set[str]) -> dict:
    """A code-mode `exec` with the declaration lines of `gone` tools cut from its description."""
    if tool.get("type") != "custom":
        return tool
    lines = str(tool.get("description", "")).splitlines()
    kept = [line for line in lines if not any(f"{{ {n}(" in line for n in gone)]
    return {**tool, "description": "\n".join(kept)}


def _strip(tools: list[dict], gone: set[str]) -> list[dict]:
    kept = []
    for tool in tools:
        if tool.get("name") in gone:
            continue
        if tool.get("type") == "namespace":
            members = [
                _undeclare(t, gone) for t in tool.get("tools", []) if t.get("name") not in gone
            ]
            kept.append({**tool, "tools": members})
            continue
        kept.append(_undeclare(tool, gone))
    return kept


def _connect(host: str) -> None:
    proxy = urllib.parse.urlsplit(os.environ["HTTPS_PROXY"])
    conn = http.client.HTTPConnection(proxy.hostname, proxy.port, timeout=10)
    conn.set_tunnel(host, 443)
    try:
        conn.connect()
    except OSError:
        pass  # the probe's proxy refuses every tunnel
    finally:
        conn.close()


def _exec(argv: list[str], stdin: str) -> int:
    features = set(_SPEC.get("features", []))
    disabled = _values(argv, "--disable")
    rejected = set(_SPEC.get("reject_features", []))
    for feature in disabled:
        if feature not in features or feature in rejected:
            print(f"Error: Unknown feature flag: {feature}", file=sys.stderr)
            return 1
    if _SPEC.get("no_request"):
        print("Error: could not start the session", file=sys.stderr)
        return 1
    model = (_values(argv, "--model") or ["gpt-5.5"])[0]
    overrides = " ".join(_values(argv, "-c"))
    base = re.search(r'base_url="([^"]+)"', overrides)
    if base is None:
        print("Error: no provider", file=sys.stderr)
        return 1
    for host in _SPEC.get("connect", []):
        _connect(host)
    gone: set[str] = set()
    if not _SPEC.get("ignore_disables"):
        for feature in disabled:
            gone |= set(_SPEC.get("gated", {}).get(feature, []))
    tools = _SPEC.get("tools", {}).get(model, _SPEC.get("default_tools", []))
    body: dict = {
        "model": model,
        "instructions": "fake instructions",
        "tools": _strip(tools, gone),
        "input": [{"type": "message", "role": "user", "content": stdin}],
    }
    additional = _SPEC.get("additional", {}).get(model)
    if additional:
        item = {"type": "additional_tools", "role": "developer", "tools": _strip(additional, gone)}
        body["input"].insert(0, item)
    if _SPEC.get("fallback"):
        print(json.dumps({"type": "error", "message": f"Model metadata for `{model}` not found."}))
    request = urllib.request.Request(
        base[1] + "/responses",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer must-not-leak"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10) as answer:
        text = answer.read().decode()
    if "response.completed" not in text:
        print("Error: stream ended early", file=sys.stderr)
        return 1
    print("OK")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    stdin = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
    _log(argv, stdin)
    if argv == ["--version"]:
        print(f"codex-cli {_SPEC.get('version', '0.164.0')}")
        return 0
    if argv[:2] == ["login", "status"]:
        print("Not logged in", file=sys.stderr)
        return 1
    if argv[:2] == ["features", "list"]:
        for name in _SPEC.get("features", []):
            print(f"{name:<40} stable             true")
        return 0
    if argv[:3] == ["debug", "models", "--bundled"]:
        if "bundled" not in _SPEC:
            print("error: unrecognized subcommand", file=sys.stderr)
            return 2
        print(json.dumps({"models": _SPEC["bundled"]}))
        return 0
    if argv[:1] == ["exec"]:
        return _exec(argv, stdin)
    print(f"error: unexpected argv {argv}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
