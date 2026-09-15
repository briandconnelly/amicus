"""Rewrite a throwaway worktree's paths out of prose, then redact what is left.

A delegate's worktree is torn down before its caller reads the result, so every absolute
path into it is dead on arrival. These helpers relativize those paths and compose that with
secret redaction for text bound for a caller. They are text-only and know nothing about
creating or removing a worktree, which is why they live here in ``amicus.sdk.core`` rather
than beside the worktree lifecycle in ``amicus.orchestration``: a backend sanitizes its own
diagnostics with them, and a backend never imports the orchestration layer (ADR 0030)."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from amicus.sdk.core.redaction import (
    _CONTROL_CHARS_KEEPING_LF_RE,
    _CONTROL_CHARS_RE,
    _preserving_key_block_failure,
    redact_text,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

# An alias is rewritten only where prose punctuation (or a string edge) brackets it, so it
# is the WHOLE leading portion of a path and never a fragment of a longer name. This is an
# ALLOWLIST of delimiters, deliberately not a denylist of "path characters": a POSIX
# component may contain nearly any byte, so `<root>+suffix`, `<root>@v2` and `/pré<root>`
# name DIFFERENT paths, and a denylist that forgot `+`/`@`/`%`/non-ASCII silently rewrote
# them into the wrong file. Erring toward a missed rewrite is safe; erring toward a wrong
# one points the caller at the wrong content.
#
# `/` is asymmetric on purpose. On the RIGHT it is what separates the root from the path we
# want to keep (`<root>/src/f.py`), so it must be allowed — an earlier draft forbade it on
# both sides and was a silent no-op on every real case. On the LEFT it would mean the alias
# is the tail of a longer path (`/other<root>/f.py`), a different file, so it is excluded.
#
# `.` is absent from the right-hand set deliberately: allowing it as an ordinary
# right-delimiter would rewrite a sentence-final `<root>.` to `..`, the parent directory —
# more misleading than the dead path it replaced. That is NOT the same as leaving it
# unmatched, though (#420 review round 3): a `.` immediately followed by a right-delimiter
# or end of string is unambiguously the end of THIS path reference (a clause/sentence
# boundary), never a continuation like `<root>.bak` (a genuinely different file, where the
# `.` is followed by more path characters) — so `_replace_aliases` below matches that case
# too, through a distinct ambiguous-suffix branch, and substitutes an unambiguous marker
# instead of a bare `.`. Leaving it fully unmatched (the original design) let the complete
# absolute path leak instead, which is strictly worse than the `..` ambiguity this was
# meant to avoid, and is exactly the shape a raw git diagnostic takes
# (`fatal: … in <wt>.`). See `relativize`'s docstring and `_AMBIGUOUS_SUFFIX_MARKER`.
_LEFT_DELIMS = r"\s(\[{`\"'<=,;:|"
_RIGHT_DELIMS = r"/\s)\]}`\"'<>,;:!?*|"

# What an alias becomes when it is followed by the ambiguous `.` case above: unlike a bare
# `.`, concatenating this with the literal period that follows in the source text can never
# read as `..` (or anything else path-like), so the worktree path is removed without
# introducing a new misleading path. Never emitted by the normal (non-ambiguous) branch,
# which keeps using `replacement` (`.` for `relativize`, the staging placeholder for
# `sanitize_prose`) exactly as before.
_AMBIGUOUS_SUFFIX_MARKER = "[worktree]"


def path_aliases(path: str) -> tuple[str, ...]:
    """Every textual spelling of ``path`` an agent's prose might use, longest first.

    Covers the symlinked-ancestor case (macOS resolves ``/tmp`` -> ``/private/tmp`` and
    ``/var/folders`` -> ``/private/var/folders``, so the path ``mkdtemp`` returned and the
    one the agent reports can differ) and the ``file://`` URI spelling of each. Sorted
    longest-first so a containing alias is always tried before an alias it contains.

    Capture these while the worktree still EXISTS. ``realpath`` happens to resolve a
    deleted path correctly today — only the surviving ancestors carry the symlinks — but
    relying on that would make a rename of this call site silently degrade the alias set.

    Raises ``ValueError`` unless ``path`` is absolute, free of surrounding whitespace, and
    below the filesystem root. Each rejection is a programming error a ``_core`` caller
    would rather hear loudly than have silently reinterpreted:

    - blank resolves to the process CWD and yields a bare ``file://`` alias that would
      rewrite any unrelated URI (``file:///etc/passwd`` -> ``./etc/passwd``);
    - surrounding whitespace cannot be trimmed away, because trimming would ACCEPT the
      relative ``"\\n/tmp/tree"`` and would silently retarget the legal absolute
      ``"/tmp/tree\\n"`` (a different file) onto ``/tmp/tree``;
    - ``/`` is never a worktree, and its aliases cannot rewrite anything anyway (nothing
      follows the root to supply the required delimiter)."""
    if path != path.strip() or not path:
        raise ValueError(f"path_aliases needs a path without surrounding whitespace, got {path!r}")
    root = path.rstrip("/")
    if not root or not Path(root).is_absolute():
        raise ValueError(f"path_aliases needs an absolute path below the root, got {path!r}")
    forms = {root, os.path.realpath(root)}
    # Both file-URI spellings: the raw concatenation an agent typically writes, and the
    # canonical percent-encoded one `Path.as_uri()` produces. They differ as soon as an
    # ancestor holds a space or `%` (`/tmp/a%b c` -> `file:///tmp/a%25b%20c`), so covering
    # only the raw form would leave a valid URI pointing into the deleted worktree.
    aliases = forms | {f"file://{form}" for form in forms}
    for form in forms:
        with contextlib.suppress(ValueError):
            aliases.add(Path(form).as_uri())
    return tuple(sorted(aliases, key=len, reverse=True))


def relativize(text: str | None, aliases: Iterable[str]) -> str | None:
    """Rewrite absolute paths under a throwaway worktree to repo-relative form.

    The worktree is torn down before the caller reads a delegate result, so every
    absolute path the agent wrote into its prose is dead on arrival (#412). Each alias is
    replaced by a single ``.``, which leaves the rest of the path to follow on its own:
    ``<root>/src/f.py`` -> ``./src/f.py``, ``file://<root>/f.py`` -> ``./f.py``, and a
    bare ``<root>`` -> ``.``.

    The paths stay RELATIVE rather than being re-rooted at the live repo: the diff is not
    applied, so a live absolute path would be equally dead for a new file and, worse,
    would point at a real file whose content differs from what the agent described.

    The ``./`` prefix is load-bearing, not cosmetic: bare-relative output would turn
    ``[x](<root>/javascript:a)`` into a link target with a live URI scheme, and stripping
    only the root from a ``file://`` URI would leave ``file://./f.py``, where ``.`` parses
    as the HOST. Prefixing sidesteps both without teaching this function to parse Markdown.

    A match needs prose punctuation (or a string edge) on both sides — see ``_LEFT_DELIMS``
    / ``_RIGHT_DELIMS`` for why that is an allowlist rather than a denylist of path
    characters, and why ``/`` is allowed on only one side.

    A sentence-final bare root (``... in <root>.``) is a special case: replacing it with a
    bare ``.`` would emit ``..``, the parent directory, more misleading than the dead path
    it replaced — so this one shape gets ``_AMBIGUOUS_SUFFIX_MARKER`` (``[worktree]``)
    instead of ``.``, never a fragment of the original path either way.

    Aliases are sorted longest-first HERE rather than trusting the caller's order: with a
    containing alias tried second, a shorter one it contains would match first and name
    the wrong file. Blank entries are dropped — an empty alias matches everywhere.

    ``None`` passes through unchanged, mirroring ``redaction.redact_text``.

    Prefer ``sanitize_prose`` for text that is also being secret-redacted — the two
    operations interact, and it is the only combination that is safe for both."""
    return _replace_aliases(text, aliases, ".")


def _replace_aliases(
    text: str | None,
    aliases: Iterable[str],
    replacement: str,
    *,
    ambiguous_replacement: str = _AMBIGUOUS_SUFFIX_MARKER,
) -> str | None:
    if not text:
        return text
    usable = sorted({alias for alias in aliases if alias.strip()}, key=len, reverse=True)
    if not usable:
        return text
    alternation = "|".join(re.escape(alias) for alias in usable)
    # The lookahead has two branches: the ordinary right-delimiter set (unambiguous --
    # `replacement` applies), and a named `ambiguous` branch for a `.` immediately followed
    # by a right-delimiter or end of string (a clause/sentence boundary -- see
    # `_AMBIGUOUS_SUFFIX_MARKER`; `<root>.bak`, where more path characters follow the `.`,
    # matches NEITHER branch and stays unmatched, same as before). Both are lookaheads, so
    # neither consumes the `.` itself -- it survives untouched in the output either way.
    #
    # `ambiguous_replacement` defaults to the literal marker (what `relativize` wants, since
    # it never redacts). `sanitize_prose` overrides it with a STAGED alphanumeric stand-in
    # instead -- substituting the bracketed marker directly here, during the staging pass,
    # would break the labelled-value character run right at the `[`, letting an adjacent
    # secret ship unredacted (#420 review round 4). See `_staged_ambiguous_placeholder`.
    pattern = re.compile(
        rf"(?<![^{_LEFT_DELIMS}])(?:{alternation})"
        rf"(?=(?P<ambiguous>\.(?=[{_RIGHT_DELIMS}]|$))|[{_RIGHT_DELIMS}]|$)"
    )
    return pattern.sub(
        lambda m: ambiguous_replacement if m.group("ambiguous") else replacement, text
    )


# The stand-in an alias wears while the secret redactor runs. Three properties are required,
# and the third is why this is derived per input rather than being a module constant:
#
# 1. EVERY character is alphanumeric, hence inside the redactor's inline-value character
#    class (`redaction.SECRET_VALUE_PATTERNS`), so the redactor can only swallow the token
#    WHOLE or not at all. Its value match is anchored at a label and runs greedily until a
#    character outside that class; there is no such character inside the token, so it can
#    never stop part-way through and leave a fragment.
# 2. It is comfortably longer than the labelled pattern's 16-character minimum, so a
#    labelled path still reads as a long value and stays redacted no matter how short the
#    real root is (erring toward redaction).
# 3. It is ABSENT from the text being sanitized, verified rather than assumed. A fixed
#    sentinel let model output smuggle a covered secret straight through: the final
#    token -> `.` replacement also hit sentinels ALREADY in the text, and `.` is structural
#    in secret shapes. `eyJ<8 chars><sentinel><8 chars><sentinel><8 chars>` carries no dots
#    while the redactor inspects it, so the JWT pattern misses — and the replacement then
#    reconstructs a valid JWT in the output. Deriving the token from the text and checking
#    membership closes that: nothing pre-existing can be turned into `.`.
_PLACEHOLDER_PREFIX = "cicwt0alias0"


def _placeholder_seed(text: str) -> str:
    """The hex tail that makes a staged placeholder text-specific. A seam: overriding it is
    the only way a test can force the collision that ``_staged_placeholder``'s loop exists
    to handle, since deriving a digest that appears inside its own input is not
    constructible."""
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:24]


def _staged_placeholder(text: str) -> str:
    """An alphanumeric token, longer than the redactor's length floor, guaranteed absent
    from ``text``. Derived from the text's own digest so it is deterministic, then extended
    until it does not occur — absence is CHECKED, which is the property that matters;
    unpredictability is not relied upon. The loop terminates because each pass lengthens the
    token while ``text`` is finite."""
    token = _PLACEHOLDER_PREFIX + _placeholder_seed(text)
    while token in text:
        token += "0"
    return token


# Sibling of `_PLACEHOLDER_PREFIX` for `_replace_aliases`'s ambiguous-suffix branch (#420
# review round 4): that branch cannot stage behind `_AMBIGUOUS_SUFFIX_MARKER` (`[worktree]`)
# directly during `sanitize_prose`'s redaction pass -- `[`/`]` sit outside the redactor's
# inline-value character class, so `api_key=<root>./<16-char secret>` would stage as
# `api_key=[worktree]./<16-char secret>`, breaking the labelled-value run right at the `[`
# and shipping the secret tail unredacted (reopening ordering attack (b) for exactly this
# shape). This prefix stages that branch behind an EQUALLY alphanumeric, equally
# verified-absent token instead, carrying the same "swallowed whole or not at all"
# guarantee as the ordinary placeholder; only the final unstaging step in `sanitize_prose`
# tells the two branches apart, mapping survivors of this one to `_AMBIGUOUS_SUFFIX_MARKER`
# instead of `.`.
_AMBIGUOUS_PLACEHOLDER_PREFIX = "cicwt0ambig0"

# Every character _guard_char_absent_from can hand out, in a fixed search order. Spelled out
# literally (not `string.ascii_letters + string.digits`) so this file adds no new import for
# it. Uppercase first: legitimate placeholder content here is always lowercase-hex-and-prefix
# (see `_placeholder_seed`/`_PLACEHOLDER_PREFIX`/`_AMBIGUOUS_PLACEHOLDER_PREFIX`), so the
# common case resolves on the very first candidate.
_GUARD_CHAR_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _guard_char_absent_from(other: str) -> str:
    """A single alphanumeric character verified absent from ``other``. Exists so
    ``_staged_ambiguous_placeholder`` can build a token structurally incapable of
    containing ``other`` as a substring (see there) instead of trying to fix that by
    appending, which cannot work once ``other`` already occurs in the token. Searches the
    full 62-character alphanumeric alphabet in a fixed order, so it terminates even in the
    pathological case a test constructs ``other`` to contain most of it — this module's own
    callers only ever pass a prefixed hex digest, so this returns on one of the first few
    candidates in practice."""
    for candidate in _GUARD_CHAR_ALPHABET:
        if candidate not in other:
            return candidate
    # Every alphanumeric character appears in `other` -- unreachable through this module's
    # own callers, only through a test deliberately constructing such a string. Fail loudly
    # rather than loop forever with nothing left to try.
    raise AssertionError("_guard_char_absent_from: `other` exhausts the alphanumeric alphabet")


def _staged_ambiguous_placeholder(text: str, other: str) -> str:
    """Sibling of ``_staged_placeholder`` for the ambiguous-suffix branch: alphanumeric,
    longer than the redaction floor, and disjoint from BOTH ``text`` and ``other`` (the
    ordinary placeholder already staged for this same call) in both directions — the two
    tokens coexist in the same staged text and are unstaged by two separate literal
    ``.replace()`` calls, so one containing the other as a substring would corrupt both.

    Three termination arguments, one per ``while`` clause, because they are NOT
    interchangeable:

    - ``token in text``: ``text`` is fixed and finite, so appending a character each pass
      eventually makes ``token`` longer than ``text`` — at most ``len(text)`` iterations.
    - ``token in other``: same argument, bounded by ``len(other)``.
    - ``other in token``: appending CANNOT fix this. Once ``other`` occurs anywhere in
      ``token``, every further extension only adds characters AFTER the existing (already
      matching) content, so the match survives no matter how long ``token`` grows — a loop
      that only appends here never terminates (#420 review round 5's NEW-2 finding). Fixed
      structurally instead of loop-repaired: ``token`` is rebuilt from a single character
      chosen to be absent from ``other`` (``_guard_char_absent_from``) and repeated. A
      string built entirely from a character that ``other`` does not itself contain CANNOT
      have ``other`` as a substring — a property of the CONTENT, not the length — so this
      clause cannot re-trigger for the rebuilt token, and any further extension (for the
      ``token in text`` clause) keeps appending that same guard character to preserve the
      guarantee rather than reverting to ``"0"``.

    ``other`` must be non-empty: the empty string is a substring of every string, which
    would make the ``other in token`` clause permanently, unfixably true no matter what
    ``token`` becomes — ``_staged_placeholder``'s own output is never empty, so this is a
    caller-contract check on a case that cannot arise from this module's own callers, not a
    real-world scenario."""
    if not other:
        raise ValueError("_staged_ambiguous_placeholder needs a non-empty `other`")
    token = _AMBIGUOUS_PLACEHOLDER_PREFIX + _placeholder_seed(text)
    guard: str | None = None
    while token in text or token in other or other in token:
        if guard is None and other in token:
            guard = _guard_char_absent_from(other)
            token = guard * max(len(token), 32)
        elif guard is not None:
            token += guard
        else:
            token += "0"
    return token


def sanitize_prose(text: str | None, aliases: Iterable[str]) -> str | None:
    """Relativize worktree paths AND redact secrets — the one order safe for both (#412).

    Doing these in sequence is not safe in either direction, which is why they are one
    function rather than two calls a caller has to order correctly:

    - **Relativize, then redact** shortens a labelled worktree-prefixed value below the
      redactor's 16-character floor, so ``api_key=<root>/abcdefgh`` becomes
      ``api_key=./abcdefgh`` and the secret escapes. The agent sees the worktree path, so an
      injected task can aim for that shape deliberately.
    - **Redact, then relativize** lets the redactor consume PART of an alias. Its value
      class covers ``=`` but stops at ``:``, so a crafted
      ``api_key=<16 chars>=file://<root>/abcdefgh`` has ``...=file`` eaten, leaving
      ``://<root>/abcdefgh`` — whose bare root is now preceded by ``/`` and so fails the
      left-hand delimiter check. Both the dead path and the secret survive.

    So each alias is first staged behind a token from ``_staged_placeholder`` — which the
    redactor can neither partially consume nor confuse with pre-existing text (see there for
    all three required properties); redaction runs against that; then any token that survived
    — i.e. was not part of a redacted secret — becomes ``.``. The sentence-final ambiguous
    case (see ``_replace_aliases``) is staged behind a SEPARATE token
    (``_staged_ambiguous_placeholder``) with the same properties, so it carries the same
    redaction guarantee; a survivor there becomes ``_AMBIGUOUS_SUFFIX_MARKER`` instead of
    ``.`` — never the bracketed marker directly, which would break the labelled-value run
    the redactor needs to see (#420 review round 4).

    Redaction remains best-effort by contract (see ``redaction``): an adversarial model can
    always emit an unlabelled secret that no pattern matches. This closes the interaction
    between the two passes, not that broader gap."""
    return _sanitize_prose(text, aliases)


def _sanitize_prose(
    text: str | None, aliases: Iterable[str], transform: Callable[[str], str] | None = None
) -> str | None:
    """:func:`sanitize_prose`, with an optional pass applied to the STAGED text.

    ``transform`` runs after alias staging and before redaction — the only window where a
    text rewrite can neither break alias matching nor be undone by it. Aliases are already
    behind alphanumeric placeholders, so a transform that deletes characters cannot damage
    them; and the transform still runs ahead of the redactor, which is where control-
    character stripping has to be (see ``redaction.sanitize_echo``).

    Staging runs AGAIN after the transform, against the same placeholders. The two passes
    catch different aliases and the result is their union: the first sees the delimiters
    the transform is about to delete, the second sees an alias the transform REPAIRED — a
    path that carried a control character inside it matches nothing until the character is
    gone. Running only one of them loses whichever set the other covers, and both sets are
    real. The second pass cannot disturb the first's work, since a placeholder is not an
    alias.

    ``None`` (the default) is the plain :func:`sanitize_prose` path, byte-identical to
    before this parameter existed — one staging pass, no transform."""
    if not text:
        return text
    placeholder = _staged_placeholder(text)
    ambiguous_placeholder = _staged_ambiguous_placeholder(text, placeholder)

    def stage(value: str) -> str:
        # `_replace_aliases` is None-tolerant for callers that pass optional text; `value`
        # is never None here (the empty guard above ran), so coalesce for the type checker.
        return (
            _replace_aliases(
                value, aliases, placeholder, ambiguous_replacement=ambiguous_placeholder
            )
            or ""
        )

    staged = stage(text)
    if transform is not None:
        staged = stage(transform(staged))
    redacted = redact_text(staged)
    if not redacted:
        return redacted
    return redacted.replace(placeholder, ".").replace(
        ambiguous_placeholder, _AMBIGUOUS_SUFFIX_MARKER
    )


def sanitize_echo_prose(text: str | None, aliases: Iterable[str]) -> str | None:
    """:func:`sanitize_prose` for text bound for an ERROR envelope: control characters are
    deleted between the alias staging and the redaction.

    Use this instead of :func:`sanitize_prose` wherever the text is a diagnostic being
    echoed back to a caller. A control character defeats BOTH passes this function
    composes, and for the same reason: each is a match over contiguous text. The redaction
    half is documented on ``redaction.sanitize_echo``. The relativization half is the
    mirror image — alias matching is an exact string match, so ``\\x1b`` wedged into the
    printed worktree path means no alias matches and the dead absolute path rides out
    whole.

    Stripping the OUTPUT of :func:`sanitize_prose` does not fix either half: by then both
    misses have already happened, and removing the control character merely produces a
    clean-looking message that still carries the path and the secret.

    WHERE the strip goes is the subtle part, and BOTH ends are wrong. Stripping before the
    staging destroys alias matching from the other side: ``_replace_aliases`` needs a
    delimiter beside an alias, and a control character is often the delimiter it has —
    ``"prefix\\t<root>/f.py"`` relativizes correctly until the tab is deleted, after which
    the alias inherits ``x`` on its left, stops matching, and the dead absolute path is
    disclosed. Line feed, tab, and carriage return all behave this way. So the strip runs
    in the one window where neither failure is reachable: AFTER staging (aliases are behind
    alphanumeric placeholders that deleting characters cannot damage) and BEFORE redaction
    (where the strip has to be). See :func:`_sanitize_prose`.

    That window is also why this helper can share ``redaction.sanitize_echo_prose``'s
    newline policy rather than needing one of its own: with aliases already staged,
    collapsing line feeds can no longer cost a relativization.

    ``aliases`` are the real worktree paths and so contain no control characters (this
    library creates them under a temp root it names itself), so they are matched as given.

    The key-block guard applies here for the same reason it applies to
    ``redaction.sanitize_echo``: a control character damaging an END marker makes a block
    look unterminated, so deleting it would terminate the block and uncover everything the
    fail-closed blanket covered."""
    if not text:
        return text

    def view(pattern: re.Pattern[str]) -> str:
        def transform(staged: str) -> str:
            return _preserving_key_block_failure(pattern.sub("", staged), staged)

        return _sanitize_prose(text, aliases, transform) or ""

    collapsed = view(_CONTROL_CHARS_RE)
    keeping_lf = view(_CONTROL_CHARS_KEEPING_LF_RE)
    return keeping_lf if keeping_lf.replace("\n", "") == collapsed else collapsed
