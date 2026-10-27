#!/usr/bin/env python
"""Capture the tool catalog two `codex` binaries send the model, and diff it, at zero spend.

`--help` and `features list` stop at what the CLI accepts; neither shows the tools codex
offers the model. codex 0.152.0 dropped `update_plan` and added a gated `clock.sleep` while
every help surface stayed byte-identical (#380). This reads the catalog off the wire instead:

    * a fake Responses server listens on 127.0.0.1 on an ephemeral port, and every run points
      codex at it with a `model_providers` entry passed as `-c` overrides. The provider has no
      `env_key` and no credential exists anywhere in the run's environment;
    * the same server is the run's HTTP(S) proxy (`HTTPS_PROXY` and friends, loopback
      exempted through `NO_PROXY`). Anything codex tries to reach beyond loopback arrives as a
      proxy request, is refused, and its host is reported under OUTBOUND. A client that
      ignored the proxy settings would not show up there, so OUTBOUND is what codex tried
      through the proxy, not a proof that nothing else was attempted;
    * every run happens in its own scratch HOME and CODEX_HOME under an environment that
      keeps PATH and nothing else (no OPENAI_API_KEY, CODEX_API_KEY or CODEX_ACCESS_TOKEN),
      and `login status` there must report logged out first, or the run is not made;
    * the server answers the first `responses` request with a completed one-word turn, so
      codex exits 0 promptly. No request ever leaves the machine for a model, and the only
      prompt is a literal of this script, sent over stdin (AGENTS.md rule 18).

The server keeps only normalized metadata from each request: every tool's qualified name and
a short sha256 of its definition (a namespace gets an entry of its own, `namespace:<name>`,
hashing its description and metadata apart from its members). It never stores or prints a
raw request, a header or any instructions text, and `--out` writes that metadata and nothing
else.

Each model in KNOWN_MODEL_SLUGS is captured on both binaries twice, with amicus's
MODEL_RUN_DISABLED_FEATURES disabled and without, through the argv amicus itself builds for a
read-only run (`codex_cli.build_exec_command`). A disable the binary's `features list` does not
list is classified "unsupported on this binary" and left out, because codex rejects an unknown
`--disable` at startup, and a startup failure is never read as an empty catalog.

Model metadata. Which tools codex offers depends on the model's metadata (`tool_mode`,
`experimental_supported_tools`), which a logged-in codex reads from the served catalog. A
scratch home has no login, so by default (`--catalog new`) both binaries get the new binary's
bundled catalog (`codex debug models --bundled`) through `-c model_catalog_json`, which holds
the metadata constant so a difference is the binary's. `--catalog own` lets each binary use
its own bundled catalog instead, and `--catalog-bin PATH` takes the shared catalog from a third
binary, so two old binaries can be replayed against metadata that carries today's models.
A model absent from the catalog in use runs on codex's fallback metadata, and the report says
so.

Positive control. A capture that cannot see a tool proves nothing by its absence, so the
disables are checked against the baseline, tool by tool: `clock.sleep` (sleep_tool) and each
of `create_goal`, `get_goal` and `update_goal` (goals) must be offered by some model's baseline
on an authoritative carrier (the top-level `tools` or an `additional_tools` item) and be gone
from that model's disabled run. A name read only from exec's description does not count as a
baseline, because it may be missing merely because it was deferred; a tool still offered after
its disable, on any carrier, fails the control. A control with any tool lacking an
authoritative baseline is "unobserved", and then the probe is not declared validated.
`--omit-disables` is the negative control for the control itself: the "disabled" runs then
send no `--disable`, so every applicable control must FAIL.

Blind spots, reported as unobserved: the plugin-tool family never appears in a scratch home,
so the remote_plugin disable has no control; a `code_mode_only` model's nested tools are read
from the `declare const tools` lines in its `exec` tool's description, which codex says may
omit deferred tools, so a nested absence is not evidence of removal (any nested change still
moves `exec`'s own hash); and the served catalog is never read.

Usage:
    uv run python scripts/capture_codex_wire_tools.py --old-bin PATH --new-bin PATH
        [--catalog new|own] [--catalog-bin PATH] [--model SLUG ...] [--out FILE]
        [--omit-disables]

Exit codes:
    0  every capture succeeded, no control failed, and every control was applied on both
       binaries (validated)
    1  at least one FAIL: a run that captured nothing or an empty catalog, a run that did not
       exit 0 after exactly one request, a control that failed (a controlled tool still
       offered after its disable, on any carrier), or an attempt to reach api.openai.com
    2  stopped before capturing: a binary's version, `features list` or the catalog in use
       could not be read
    3  no FAIL, but at least one control was unobserved, so the probe is not validated
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import hashlib
import importlib.util
import json
import re
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from amicus.backends.codex import cli as codex_cli
from amicus.backends.codex import contract as codex_contract
from amicus.sdk.conventions.preflight import FlagSupport

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable
    from types import ModuleType


def _load_compat() -> ModuleType:
    """`check_backend_compat.py`, for its scratch-home isolation, process-group handling and
    login guard, loaded by path because `scripts/` is not a package."""
    if "check_backend_compat" in sys.modules:
        return sys.modules["check_backend_compat"]
    path = Path(__file__).with_name("check_backend_compat.py")
    spec = importlib.util.spec_from_file_location("check_backend_compat", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_backend_compat"] = module
    spec.loader.exec_module(module)
    return module


compat = _load_compat()

LOOPBACK = "127.0.0.1"
PROVIDER_ID = "amicus_wire_probe"
# The only prompt a run carries: a literal of this script, over stdin (AGENTS.md rule 18).
SYNTHETIC_PROMPT = compat.SYNTHETIC_PROMPT
FALLBACK_WARNING = re.compile(r"Model metadata for `([^`]+)` not found")
UNKNOWN_FEATURE = "Unknown feature flag"
# The host a model turn would go to if the provider override did not hold.
MODEL_HOST = "api.openai.com"
# A code-mode `exec` tool declares each nested tool on a line of this form.
_NESTED = re.compile(r"declare const tools: \{ (\w+)\(")
NESTED_PREFIX = "exec/"
# A namespace's own entry, beside its members': `namespace:clock`.
NAMESPACE_PREFIX = "namespace:"
HASH_CHARS = 16

# The tools each controlled disable must remove, by leaf name (see `leaf`).
CONTROLLED: dict[str, frozenset[str]] = {
    codex_contract.SLEEP_TOOL_FEATURE: frozenset({"clock.sleep"}),
    codex_contract.GOALS_FEATURE: frozenset({"create_goal", "get_goal", "update_goal"}),
}
UNCONTROLLED: dict[str, str] = {
    codex_contract.REMOTE_PLUGIN_FEATURE: (
        "the plugin-tool family never appears in a scratch home with no login, so this "
        "disable has no tool to remove there"
    ),
}
BLIND_SPOTS = ("the served model catalog: it needs a login; a bundled catalog stands in for it",)
BASELINE, DISABLED = "baseline", "disabled"


def leaf(name: str) -> str:
    """A tool's name with code mode's spelling undone: `exec/clock__sleep` -> `clock.sleep`."""
    return name.removeprefix(NESTED_PREFIX).replace("__", ".")


def _digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()[:HASH_CHARS]


def _walk(tool: Any, prefix: str, out: dict[str, str | None]) -> None:
    if not isinstance(tool, dict):
        out[f"{prefix}<unparsed {type(tool).__name__}>"] = _digest(tool)
        return
    kind, name = tool.get("type"), tool.get("name")
    if kind == "namespace" and isinstance(tool.get("tools"), list):
        # `functions` is the Responses API's default namespace; its members read bare.
        inner = "" if name == "functions" else f"{prefix}{name}."
        # The namespace's own description and metadata, apart from its members.
        own = {k: v for k, v in tool.items() if k != "tools"}
        out[f"{NAMESPACE_PREFIX}{prefix}{name}"] = _digest(own)
        for child in tool["tools"]:
            _walk(child, inner, out)
        return
    qualified = f"{prefix}{name or kind}"
    out[qualified] = _digest(tool)
    if kind == "custom" and name == "exec":
        for nested in _NESTED.findall(str(tool.get("description", ""))):
            out.setdefault(f"{NESTED_PREFIX}{nested}", None)


def catalog_of(body: Any) -> dict[str, str | None] | None:
    """The normalized tool catalog of one Responses request: {qualified name: short hash},
    from the top-level `tools` and from any `additional_tools` input item (code mode). A
    nested code-mode tool maps to None: its declaration is part of `exec`'s hash. None when
    the body is not a request at all."""
    if not isinstance(body, dict):
        return None
    out: dict[str, str | None] = {}
    for tool in body.get("tools") or []:
        _walk(tool, "", out)
    for item in body.get("input") or []:
        if isinstance(item, dict) and item.get("type") == "additional_tools":
            for tool in item.get("tools") or []:
                _walk(tool, "", out)
    return dict(sorted(out.items()))


# --- the fake Responses server, which is also each run's proxy -----------------------------


def _completed_turn() -> bytes:
    events = (
        {"type": "response.created", "response": {"id": "resp_amicus_probe"}},
        {
            "type": "response.output_item.done",
            "item": {
                "type": "message",
                "role": "assistant",
                "id": "msg_amicus_probe",
                "content": [{"type": "output_text", "text": "OK"}],
            },
        },
        {
            "type": "response.completed",
            "response": {
                "id": "resp_amicus_probe",
                "usage": {
                    "input_tokens": 0,
                    "input_tokens_details": None,
                    "output_tokens": 0,
                    "output_tokens_details": None,
                    "total_tokens": 0,
                },
            },
        },
    )
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


@dataclass
class Observed:
    """What one run's server saw, as metadata only."""

    catalogs: list[dict[str, str | None] | None] = field(default_factory=list)
    model: str | None = None
    outbound: set[str] = field(default_factory=set)
    other: list[str] = field(default_factory=list)  # loopback requests that were not a turn


class FakeResponses:
    """A loopback Responses endpoint and refusing proxy for one run."""

    def __init__(self) -> None:
        self.seen = Observed()
        seen, lock, turn = self.seen, threading.Lock(), _completed_turn()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                pass

            def _outbound(self, host: str) -> None:
                with lock:
                    seen.outbound.add(host)
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_CONNECT(self) -> None:
                self._outbound(self.path.rsplit(":", 1)[0])

            def _proxied(self) -> bool:
                if self.path.startswith(("http://", "https://")):
                    self._outbound(urlsplit(self.path).hostname or "?")
                    return True
                return False

            def do_GET(self) -> None:
                if self._proxied():
                    return
                with lock:
                    seen.other.append(f"GET {urlsplit(self.path).path}")
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self) -> None:
                if self._proxied():
                    return
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                path = urlsplit(self.path).path
                if not path.endswith("/responses"):
                    with lock:
                        seen.other.append(f"POST {path}")
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                encoding = (self.headers.get("Content-Encoding") or "identity").lower()
                try:
                    body = json.loads(raw) if encoding == "identity" else None
                except ValueError:
                    body = None
                with lock:
                    seen.catalogs.append(catalog_of(body))
                    if isinstance(body, dict) and isinstance(body.get("model"), str):
                        seen.model = seen.model or body["model"]
                del raw, body  # nothing of the request outlives its normalization
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(turn)))
                self.end_headers()
                self.wfile.write(turn)

        self._server = ThreadingHTTPServer((LOOPBACK, 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> FakeResponses:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()

    @property
    def url(self) -> str:
        return f"http://{LOOPBACK}:{self.port}"

    def provider_overrides(self) -> tuple[str, ...]:
        entry = (
            f'{{name="amicus wire probe",base_url="{self.url}/v1",wire_api="responses",'
            "request_max_retries=0,stream_max_retries=0}"
        )
        return (
            "-c",
            f"model_providers.{PROVIDER_ID}={entry}",
            "-c",
            f'model_provider="{PROVIDER_ID}"',
        )

    def proxy_env(self) -> dict[str, str]:
        loopback = f"{LOOPBACK},localhost"
        env = {name: self.url for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY")}
        env |= {name.lower(): value for name, value in env.items()}
        return env | {"NO_PROXY": loopback, "no_proxy": loopback}


# --- one run ---------------------------------------------------------------------------------


@dataclass
class Capture:
    # captured | empty | unclean | no-request | unsupported | not-run | timed-out
    status: str
    tools: dict[str, str | None] = field(default_factory=dict)
    detail: str = ""
    fallback: bool = False
    requests: int = 0
    outbound: tuple[str, ...] = ()
    exit_code: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == "captured"


def run_argv(
    binary: str,
    model: str,
    scratch: Any,
    overrides: tuple[str, ...],
    disables: tuple[str, ...],
) -> list[str]:
    """The argv amicus builds for a read-only run, with the probe's provider overrides as
    operator extra args, and its `--disable` pairs cut down to `disables`."""
    argv, _dropped = codex_cli.build_exec_command(
        codex_bin=binary,
        cwd=str(scratch.work),
        sandbox=codex_contract.SANDBOX_READ_ONLY,
        isolation="inherit",
        output_last_message_path=str(scratch.tmp / "last-message.txt"),
        model=model,
        skip_git_repo_check=True,
        extra_args=overrides,
        flag_support=FlagSupport(supported=frozenset(), help_parsed=False),
    )
    out: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == codex_contract.DISABLE_FEATURE_FLAG and i + 1 < len(argv):
            if argv[i + 1] in disables:
                out += argv[i : i + 2]
            i += 2
            continue
        out.append(argv[i])
        i += 1
    return out


def capture(
    binary: str, model: str, disables: tuple[str, ...], catalog_path: str | None
) -> Capture:
    with compat.Scratch() as scratch, FakeResponses() as server:
        guard = scratch.run([binary, *codex_contract.LOGIN_STATUS_ARGS])
        if not compat.logged_out(guard):
            return Capture(
                "not-run",
                detail="`login status` in its scratch home did not report logged out ("
                + scratch.scrub(compat.login_diagnostic(guard))
                + ")",
            )
        overrides = server.provider_overrides()
        if catalog_path is not None:
            overrides += ("-c", f"model_catalog_json={json.dumps(catalog_path)}")
        scratch.env |= server.proxy_env()
        run = scratch.run(
            run_argv(binary, model, scratch, overrides, disables), stdin_text=SYNTHETIC_PROMPT
        )
        seen = server.seen
    # Under `--json` codex reports the warning as an event on stdout.
    fallback = model in FALLBACK_WARNING.findall(run.stdout + run.stderr)
    common = {
        "fallback": fallback,
        "requests": len(seen.catalogs),
        "outbound": tuple(sorted(seen.outbound)),
        "exit_code": run.exit_code,
    }
    if seen.catalogs:
        first = seen.catalogs[0]
        if first is None:
            return Capture("no-request", detail="the request body was not readable JSON", **common)
        # A run that did not end cleanly after exactly one request may have shown codex more
        # than one catalog, or failed after it; none of it is evidence.
        if len(seen.catalogs) != 1:
            return Capture("unclean", detail=f"sent {len(seen.catalogs)} requests", **common)
        if run.timed_out:
            return Capture("unclean", detail="timed out after its request", **common)
        if run.exit_code != 0:
            return Capture(
                "unclean",
                detail=f"exited {run.exit_code} after its request: {_tail(scratch, run.stderr)}",
                **common,
            )
        if not first:
            return Capture(
                "empty",
                detail="the request carried no tools at all; an empty capture is never read "
                "as an empty catalog",
                **common,
            )
        return Capture("captured", first, **common)
    if UNKNOWN_FEATURE in run.stderr:
        return Capture("unsupported", detail=_tail(scratch, run.stderr), **common)
    if run.timed_out:
        return Capture("timed-out", detail="it timed out before any request", **common)
    return Capture(
        "no-request",
        detail=f"exit {run.exit_code} before any request: {_tail(scratch, run.stderr)}",
        **common,
    )


def _tail(scratch: Any, stderr: str) -> str:
    lines = [line for line in scratch.scrub(stderr).strip().splitlines() if line.strip()]
    return " | ".join(lines[-3:])[:400]


# --- one binary --------------------------------------------------------------------------------


@dataclass
class Side:
    label: str
    binary: str
    version: str | None = None
    supported: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()
    captures: dict[tuple[str, str], Capture] = field(default_factory=dict)
    controls: dict[str, str] = field(default_factory=dict)  # feature -> verdict
    # The model metadata this binary ran on; None when its bundled catalog was unreadable.
    facts: dict[str, dict[str, Any]] | None = None
    control_lines: list[str] = field(default_factory=list)


def read_features(binary: str) -> dict[str, tuple[str, str]] | None:
    with compat.Scratch() as scratch:
        run = scratch.run([binary, "features", "list"])
    rows = compat.feature_rows(run.stdout) if compat.surface_ok(run) else {}
    return rows or None


def read_bundled(binary: str) -> list[dict[str, Any]] | None:
    """`codex debug models --bundled`: the catalog shipped with the binary. No login."""
    with compat.Scratch() as scratch:
        run = scratch.run([binary, "debug", "models", "--bundled"])
    if not compat.surface_ok(run):
        return None
    try:
        data = json.loads(run.stdout)
    except ValueError:
        return None
    models = data.get("models") if isinstance(data, dict) else data
    if not isinstance(models, list) or not all(isinstance(m, dict) for m in models):
        return None
    return models


def model_facts(models: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The metadata that shapes a catalog, per slug; base instructions are left out."""
    return {
        str(m.get("slug")): {
            "tool_mode": m.get("tool_mode"),
            "experimental_supported_tools": m.get("experimental_supported_tools"),
        }
        for m in models
    }


def judge_controls(side: Side, models: tuple[str, ...], omitted: bool) -> None:
    """Each controlled tool needs its own observed removal. A baseline counts only when an
    authoritative carrier (top-level `tools` or an `additional_tools` item) offers the tool:
    a name read from exec's description may be missing merely because it was deferred, so
    its disappearance there proves nothing. A tool still offered after its disable, on any
    carrier, fails the control."""
    for feature, tools in CONTROLLED.items():
        if feature in side.unsupported:
            side.controls[feature] = "unsupported"
            side.control_lines.append(f"{feature}: unsupported on this binary, no control")
            continue
        removed: dict[str, list[str]] = {tool: [] for tool in tools}
        failed: list[tuple[str, list[str]]] = []
        for model in models:
            base, off = side.captures[model, BASELINE], side.captures[model, DISABLED]
            if not off.ok:
                continue
            # A survivor fails the control whatever this model's baseline showed.
            kept = sorted(n for n in off.tools if leaf(n) in tools)
            if kept:
                failed.append((model, kept))
                continue
            if not base.ok:
                continue
            for name in base.tools:
                if leaf(name) in tools and not name.startswith(NESTED_PREFIX):
                    removed[leaf(name)].append(model)
        if failed:
            side.controls[feature] = "failed"
            why = " (--omit-disables: the disable was not sent)" if omitted else ""
            side.control_lines += [
                f"{feature}: FAILED on {model}: the disabled run still offers "
                f"{', '.join(kept)}{why}"
                for model, kept in failed
            ]
            continue
        missing = sorted(tool for tool, seen in removed.items() if not seen)
        if missing:
            side.controls[feature] = "unobserved"
            side.control_lines.append(
                f"{feature}: unobserved: no authoritative baseline offers {', '.join(missing)} "
                "(top-level tools or additional_tools; a name read from exec's description "
                "does not count), so this control proves nothing here"
            )
            continue
        side.controls[feature] = "passed"
        side.control_lines.append(
            f"{feature}: passed: "
            + "; ".join(f"{tool} offered by {', '.join(removed[tool])}" for tool in sorted(removed))
            + ", each removed by the disable"
        )


# --- the comparison ----------------------------------------------------------------------------


@dataclass
class Report:
    old: Side
    new: Side
    models: tuple[str, ...]
    catalog: str
    catalog_bin: str | None = None
    catalog_facts: dict[str, dict[str, Any]] = field(default_factory=dict)
    omitted: bool = False
    stopped: str | None = None
    problems: list[str] = field(default_factory=list)
    unobserved: list[str] = field(default_factory=list)

    @property
    def validated(self) -> bool:
        return not self.problems and all(
            side.controls.get(feature) in {"passed", "unsupported"}
            and any(v == "passed" for v in side.controls.values())
            for side in (self.old, self.new)
            for feature in CONTROLLED
        )


def run_all(
    old_bin: str,
    new_bin: str,
    models: tuple[str, ...],
    *,
    catalog: str = "new",
    catalog_bin: str | None = None,
    omit_disables: bool = False,
    workers: int = 6,
) -> Report:
    report = Report(Side("old", old_bin), Side("new", new_bin), models, catalog, catalog_bin)
    report.omitted = omit_disables
    for side in (report.old, report.new):
        side.version = compat.read_version(side.binary)
        if side.version is None:
            report.stopped = f"the {side.label} binary ({side.binary}) printed no release"
            return report
        rows = read_features(side.binary)
        if rows is None:
            report.stopped = f"`features list` could not be read from the {side.label} binary"
            return report
        wanted = codex_contract.MODEL_RUN_DISABLED_FEATURES
        side.supported = tuple(f for f in wanted if f in rows)
        side.unsupported = tuple(f for f in wanted if f not in rows)
    with tempfile.TemporaryDirectory(prefix="amicus-wire-") as folder:
        catalog_path: str | None = None
        if catalog == "new":
            source = catalog_bin or new_bin
            bundled = read_bundled(source)
            if bundled is None:
                report.stopped = (
                    f"`debug models --bundled` could not be read from {source}; "
                    "rerun with --catalog own to let each binary use its own"
                )
                return report
            path = Path(folder).resolve() / "catalog.json"
            path.write_text(json.dumps({"models": bundled}), encoding="utf-8")
            catalog_path = str(path)
            report.catalog_facts = model_facts(bundled)
            report.old.facts = report.new.facts = report.catalog_facts
        else:
            for side in (report.old, report.new):
                own = read_bundled(side.binary)
                side.facts = None if own is None else model_facts(own)
        jobs = [
            (side, model, variant)
            for side in (report.old, report.new)
            for model in models
            for variant in (BASELINE, DISABLED)
        ]

        def one(job: tuple[Side, str, str]) -> Capture:
            side, model, variant = job
            disables = () if variant == BASELINE or omit_disables else side.supported
            return capture(side.binary, model, disables, catalog_path)

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for job, result in zip(jobs, pool.map(one, jobs), strict=True):
                job[0].captures[job[1], job[2]] = result
    for side in (report.old, report.new):
        judge_controls(side, models, omit_disables)
    _collect_problems(report)
    return report


def _collect_problems(report: Report) -> None:
    for side in (report.old, report.new):
        for (model, variant), cap in sorted(side.captures.items()):
            if not cap.ok:
                report.problems.append(
                    f"{side.label} {side.version} {model} {variant}: {cap.status}: {cap.detail}"
                )
            if MODEL_HOST in cap.outbound:
                report.problems.append(
                    f"{side.label} {side.version} {model} {variant}: tried to reach "
                    f"{MODEL_HOST} through the proxy (refused)"
                )
        for feature, verdict in side.controls.items():
            if verdict == "failed":
                report.problems.append(
                    f"positive control {feature} failed on the {side.label} binary "
                    f"({side.version}): the probe cannot tell a removed tool from a blind one"
                )
            elif verdict == "unobserved":
                report.unobserved.append(
                    f"positive control {feature} on the {side.label} binary ({side.version}): "
                    "not every controlled tool had an authoritative baseline, so the probe is "
                    "not validated"
                )
    for feature, why in UNCONTROLLED.items():
        report.unobserved.append(f"{feature}: {why}")
    report.unobserved += list(BLIND_SPOTS)
    if report.catalog == "new":
        _annotate(report, report.catalog_facts, "in the catalog in use")
    else:
        for side in (report.old, report.new):
            where = f"on the {side.label} binary ({side.version}), in its own bundled catalog"
            if side.facts is None:
                report.unobserved.append(
                    f"on the {side.label} binary ({side.version}): `debug models --bundled` "
                    "could not be read, so which models ran on fallback metadata is unknown"
                )
            else:
                _annotate(report, side.facts, where)


def _annotate(report: Report, facts: dict[str, dict[str, Any]], where: str) -> None:
    mode_only = [m for m in report.models if facts.get(m, {}).get("tool_mode") == "code_mode_only"]
    report.unobserved.append(
        "code_mode_only models' nested tools are read from exec's description, which may omit "
        f"deferred tools, so a nested absence is not evidence of removal; {where}: "
        f"{', '.join(mode_only) or 'none'}"
    )
    absent = [m for m in report.models if m not in facts]
    if absent:
        where = where.replace(", in its own", ", not in its own").replace(
            "in the catalog in use", "not in the catalog in use"
        )
        report.unobserved.append(
            f"{where}, so captured on codex's fallback metadata, not the model's own: "
            + ", ".join(absent)
        )


def catalog_diff(before: dict[str, str | None], after: dict[str, str | None]) -> list[str]:
    lines = [f"+ {n}" for n in sorted(after.keys() - before.keys())]
    lines += [
        f"- {n}" + (" (nested; may only be deferred)" if n.startswith(NESTED_PREFIX) else "")
        for n in sorted(before.keys() - after.keys())
    ]
    lines += [
        f"~ {n} (definition hash {before[n]} -> {after[n]})"
        for n in sorted(before.keys() & after.keys())
        if before[n] != after[n]
    ]
    return lines


def describe(report: Report) -> list[str]:
    old, new = report.old, report.new
    lines = [
        f"codex wire tools: old {old.version or 'unknown'} ({old.binary}), "
        f"new {new.version or 'unknown'} ({new.binary})"
    ]
    if report.stopped:
        return [*lines, f"STOPPED: {report.stopped}"]
    if report.catalog == "own":
        source = "each binary's own bundled catalog"
    elif report.catalog_bin:
        source = f"the bundled catalog of {report.catalog_bin}, applied to both"
    else:
        source = "the new binary's bundled catalog, applied to both"
    lines.append(f"model metadata: {source}")
    if report.omitted:
        lines.append("NEGATIVE CONTROL: --omit-disables, so no disabled run sent a --disable")
    for side in (old, new):
        if side.unsupported:
            lines.append(
                f"{side.label} {side.version}: unsupported on this binary, not sent: "
                + ", ".join(side.unsupported)
            )
    lines.append("CAPTURED")
    for model in report.models:
        for variant in (BASELINE, DISABLED):
            caps = [side.captures[model, variant] for side in (old, new)]
            notes = [
                f"{side.label} {side.version} ran on fallback metadata"
                for side, cap in zip((old, new), caps, strict=True)
                if cap.fallback
            ]
            counts = ", ".join(
                f"{side.label} {len(cap.tools) if cap.ok else cap.status}"
                for side, cap in zip((old, new), caps, strict=True)
            )
            lines.append(
                f"  {model} {variant}: {counts}" + (f" ({'; '.join(notes)})" if notes else "")
            )
    caps = [c for side in (old, new) for c in side.captures.values()]
    clean = [c for c in caps if c.ok and c.requests == 1 and c.exit_code == 0]
    lines.append(
        f"  {len(clean)} of {len(caps)} runs: exactly one request, answered with a "
        "completed turn by the fake, then exit 0"
    )
    lines.append("CONTROLS")
    for side in (old, new):
        lines += [f"  {side.label} {side.version}: {line}" for line in side.control_lines]
    differed = []
    for model in report.models:
        for variant in (BASELINE, DISABLED):
            a, b = old.captures[model, variant], new.captures[model, variant]
            if a.ok and b.ok:
                change = catalog_diff(a.tools, b.tools)
                if change:
                    differed.append(f"  {model} {variant}:")
                    differed += [f"    {line}" for line in change]
    lines.append("DIFFERED" + ("" if differed else " (nothing)"))
    lines += differed
    hosts = sorted({h for s in (old, new) for c in s.captures.values() for h in c.outbound})
    lines.append(
        "OUTBOUND (refused by the probe's proxy): " + (", ".join(hosts) if hosts else "none")
    )
    lines.append("UNOBSERVED")
    lines += [f"  {item}" for item in report.unobserved]
    lines += [f"FAIL {problem}" for problem in report.problems]
    lines.append(
        "VALIDATED: every control was applied and passed on both binaries"
        if report.validated
        else "NOT VALIDATED: an absence in this report proves nothing"
    )
    return lines


def to_json(report: Report) -> dict[str, Any]:
    """The normalized record `--out` writes: names, hashes and verdicts, nothing raw."""
    return {
        "catalog": report.catalog,
        "catalog_bin_version": compat.read_version(report.catalog_bin)
        if report.catalog_bin
        else None,
        "omit_disables": report.omitted,
        "validated": report.validated,
        "sides": {
            side.label: {
                "version": side.version,
                "catalog_facts": None
                if side.facts is None
                else {m: side.facts.get(m) for m in report.models},
                "disables_supported": list(side.supported),
                "disables_sent": [] if report.omitted else list(side.supported),
                "unsupported": list(side.unsupported),
                "controls": side.controls,
                "captures": {
                    f"{model} {variant}": {
                        "status": cap.status,
                        "fallback_metadata": cap.fallback,
                        "requests": cap.requests,
                        "exit_code": cap.exit_code,
                        "outbound": list(cap.outbound),
                        "tools": cap.tools,
                    }
                    for (model, variant), cap in sorted(side.captures.items())
                },
            }
            for side in (report.old, report.new)
        },
        "problems": report.problems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture and diff the model-facing tool catalog of two codex binaries, "
        "at zero spend (#380)."
    )
    parser.add_argument("--old-bin", required=True, type=Path)
    parser.add_argument("--new-bin", required=True, type=Path)
    parser.add_argument("--catalog", choices=("new", "own"), default="new")
    parser.add_argument(
        "--catalog-bin",
        type=Path,
        help="with --catalog new, read the shared bundled catalog from this codex binary "
        "instead of the new one (to replay old binaries against a catalog that carries "
        "today's models)",
    )
    parser.add_argument(
        "--model",
        action="append",
        default=None,
        help="capture only this slug (repeatable); default: every slug in KNOWN_MODEL_SLUGS",
    )
    parser.add_argument("--out", type=Path, help="write the normalized record here as JSON")
    parser.add_argument(
        "--omit-disables",
        action="store_true",
        help="negative control: send no --disable on the disabled runs; every applicable "
        "control must then fail",
    )
    args = parser.parse_args(argv)
    models = tuple(args.model or codex_contract.KNOWN_MODEL_SLUGS)
    report = run_all(
        str(args.old_bin.absolute()),
        str(args.new_bin.absolute()),
        models,
        catalog=args.catalog,
        catalog_bin=str(args.catalog_bin.absolute()) if args.catalog_bin else None,
        omit_disables=args.omit_disables,
    )
    print("\n".join(describe(report)))
    if report.stopped:
        return 2
    if args.out:
        args.out.write_text(json.dumps(to_json(report), indent=2) + "\n", encoding="utf-8")
    if report.problems:
        return 1
    return 0 if report.validated else 3


if __name__ == "__main__":
    with contextlib.suppress(BrokenPipeError):
        sys.exit(main())
