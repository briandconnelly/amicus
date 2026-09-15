"""Relativizing a throwaway worktree's paths out of prose, and redacting what is left."""

from __future__ import annotations

import pytest

from amicus.sdk.core import pathalias

# --- Worktree-path relativization in returned prose (#412) --------------------------
#
# Kimi runs with cwd = the throwaway worktree, so it writes absolute paths into its
# prose; the worktree is torn down before the caller reads the result, leaving every
# such path dead. `path_aliases` + `relativize` rewrite them to repo-relative form.


def test_path_aliases_includes_realpath_and_file_uri_forms(tmp_path):
    # A symlinked ancestor (macOS: /tmp -> /private/tmp, /var -> /private/var) means the
    # path mkdtemp handed us and the one Kimi reports can differ. Build the symlink here
    # rather than relying on the host's /tmp, so this covers both aliases on Linux CI too.
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    wt = str(link / "tree")

    aliases = pathalias.path_aliases(wt)

    assert wt in aliases
    assert str(real / "tree") in aliases
    assert f"file://{wt}" in aliases
    assert f"file://{real / 'tree'}" in aliases
    # Longest-first, so a containing alias (file:// form, or the longer of the two roots)
    # is always tried before an alias it contains.
    assert list(aliases) == sorted(aliases, key=len, reverse=True)
    assert len(set(aliases)) == len(aliases)


def test_path_aliases_dedupes_when_realpath_matches(tmp_path):
    wt = str(tmp_path / "tree")
    aliases = pathalias.path_aliases(wt)
    assert len(set(aliases)) == len(aliases)
    assert aliases == (f"file://{wt}", wt)


def test_path_aliases_strips_trailing_separator(tmp_path):
    # A trailing slash would make every alias fail to match `<root>/file` (the text has one
    # separator, the alias two), silently disabling the rewrite.
    wt = str(tmp_path / "tree")
    assert pathalias.path_aliases(wt + "/") == pathalias.path_aliases(wt)


def test_path_aliases_on_removed_path(tmp_path):
    # Aliases are captured while the worktree exists, but must not depend on it: realpath
    # resolves the surviving ancestors and passes the missing leaf through unchanged.
    wt = tmp_path / "tree"
    wt.mkdir()
    before = pathalias.path_aliases(str(wt))
    wt.rmdir()
    assert pathalias.path_aliases(str(wt)) == before


ROOT = "/private/tmp/pontonier-worktree-__g9bg1q/tree"
ALIASES = (f"file://{ROOT}", ROOT)


def test_relativize_rewrites_the_observed_bug_shapes():
    # The two forms the live reproduction produced: a markdown link target and a code span.
    text = f"Created [REPRO.md]({ROOT}/REPRO.md).\n\nFull path: `{ROOT}/REPRO.md`."
    out = pathalias.relativize(text, ALIASES)
    assert out == "Created [REPRO.md](./REPRO.md).\n\nFull path: `./REPRO.md`."
    assert ROOT not in out


def test_relativize_rewrites_nested_path():
    out = pathalias.relativize(f"see {ROOT}/src/pkg/mod.py now", ALIASES)
    assert out == "see ./src/pkg/mod.py now"


def test_relativize_rewrites_bare_root():
    assert pathalias.relativize(f"I worked in {ROOT} today", ALIASES) == "I worked in . today"


def test_relativize_rewrites_file_uri_without_leaving_a_host():
    # Stripping only the root from `file://<root>/f.py` would yield `file://./f.py`, where
    # `.` parses as the URI HOST — a malformed link, worse than the dead path.
    out = pathalias.relativize(f"open file://{ROOT}/f.py", ALIASES)
    assert out == "open ./f.py"
    assert "file://" not in out


def test_relativize_prefixes_dot_slash_so_no_uri_scheme_can_be_exposed():
    # Bare-relative output would leave `javascript:a` as a live markdown link target.
    out = pathalias.relativize(f"[x]({ROOT}/javascript:a)", ALIASES)
    assert out == "[x](./javascript:a)"


def test_relativize_rewrites_every_occurrence():
    out = pathalias.relativize(f"{ROOT}/a and {ROOT}/b and {ROOT}", ALIASES)
    assert out == "./a and ./b and ."


def test_relativize_rewrites_at_string_start_and_end():
    assert pathalias.relativize(f"{ROOT}/a.py", ALIASES) == "./a.py"
    assert pathalias.relativize(f"in {ROOT}", ALIASES) == "in ."


def test_relativize_leaves_partial_component_match_alone():
    # `<parent>/treex/f` merely starts with the root; rewriting it would invent a path.
    text = f"{ROOT}x/f.py"
    assert pathalias.relativize(text, ALIASES) == text


def test_relativize_leaves_root_as_suffix_of_longer_path_alone():
    text = f"/other{ROOT}/f.py"
    assert pathalias.relativize(text, ALIASES) == text


def test_relativize_replaces_sentence_final_bare_root_with_a_safe_marker():
    # #420 review round 3: this used to be a KNOWN LIMITATION that left the text fully
    # UNCHANGED (rewriting `<root>.` to `..` would misleadingly read as the parent
    # directory) — but leaving it alone leaked the complete absolute path instead, which
    # is strictly worse and is exactly the shape a raw git diagnostic takes
    # (`fatal: failed in <wt>.`). The ambiguous case now gets an unambiguous marker
    # instead of a bare `.`, so the path never survives either way.
    text = f"the root is {ROOT}."
    out = pathalias.relativize(text, ALIASES)
    assert out == "the root is [worktree]."
    assert ROOT not in out


def test_relativize_replaces_mid_sentence_root_with_marker_before_the_next_clause():
    # The ambiguous case is not only string-final: `<root>.` followed by whitespace (a new
    # sentence) is the same shape.
    text = f"See {ROOT}. Done."
    out = pathalias.relativize(text, ALIASES)
    assert out == "See [worktree]. Done."
    assert ROOT not in out


def test_relativize_replaces_root_followed_by_period_then_closing_delimiter():
    # A period immediately followed by another right-delimiter (not just whitespace/EOF)
    # is the same "clause-final" shape, e.g. a parenthetical.
    text = f"(see {ROOT}.)"
    out = pathalias.relativize(text, ALIASES)
    assert out == "(see [worktree].)"
    assert ROOT not in out


def test_relativize_leaves_a_period_suffixed_sibling_alone():
    # `<root>.bak` names a DIFFERENT file/extension, not a clause ending — the marker only
    # applies when the period is followed by a right-delimiter or end of string, so this
    # stays a missed rewrite (safe) rather than a wrong one (misleading).
    text = f"{ROOT}.bak"
    assert pathalias.relativize(text, ALIASES) == text


def test_relativize_preserves_none_and_empty():
    assert pathalias.relativize(None, ALIASES) is None
    assert pathalias.relativize("", ALIASES) == ""


def test_relativize_with_no_aliases_is_identity():
    text = f"{ROOT}/a.py"
    assert pathalias.relativize(text, ()) == text


def test_relativize_escapes_regex_metacharacters_in_the_root(tmp_path):
    # mkdtemp roots are tame, but a caller-supplied one is not: an unescaped `.` or `+`
    # would match characters it should not.
    root = "/tmp/a+b(c)/t.ee"
    out = pathalias.relativize(f"{root}/f.py and /tmp/aab(c)/txee/f.py", (root,))
    assert out == "./f.py and /tmp/aab(c)/txee/f.py"


def test_path_aliases_rejects_empty_and_relative_paths():
    # An empty path resolves to the CWD and yields a bare `file://` alias, which would
    # rewrite any unrelated file URI (`file:///etc/passwd` -> `./etc/passwd`). A relative
    # path cannot anchor an absolute one. Both are programming errors, not inputs to
    # tolerate — `_core` is written for callers that do not exist yet.
    for bad in ("", "   ", "relative/tree", "./tree"):
        with pytest.raises(ValueError):
            pathalias.path_aliases(bad)


def test_relativize_sorts_aliases_longest_first_itself():
    # Correctness must not depend on the caller's ordering: with `/root` tried first, the
    # longer `/root/sub` never gets a chance and the result names the wrong file.
    assert pathalias.relativize("/root/sub/file", ("/root", "/root/sub")) == "./file"
    assert pathalias.relativize("/root/sub/file", ("/root/sub", "/root")) == "./file"


def test_relativize_ignores_blank_aliases():
    assert pathalias.relativize("open file:///etc/passwd", ("", "   ")) == "open file:///etc/passwd"


@pytest.mark.parametrize(
    "suffix",
    ["+suffix", "@v2/f.py", "%20x", "x/f.py", ".bak/f.py", "~1/f.py", "-old/f.py", "=v"],
)
def test_relativize_leaves_sibling_paths_alone(suffix):
    # A POSIX path component may contain nearly any byte, so `<root>+suffix`, `<root>@v2`
    # and friends are DIFFERENT directories. Rewriting them would invent a path and point
    # the caller at the wrong file. Only a `/` or prose punctuation ends the root.
    text = f"{ROOT}{suffix}"
    assert pathalias.relativize(text, ALIASES) == text


@pytest.mark.parametrize("prefix", ["/pré", "/other", "x", "9", "_", "-", "~", "+", "@", "%"])
def test_relativize_leaves_enclosing_paths_alone(prefix):
    # The alias appearing mid-path means it is the tail of some longer, unrelated path.
    text = f"{prefix}{ROOT}/f.py"
    assert pathalias.relativize(text, ALIASES) == text


@pytest.mark.parametrize(
    ("left", "right"),
    [("(", ")"), ("[", "]"), ("`", "`"), ('"', '"'), ("'", "'"), ("<", ">"), (" ", " ")],
)
def test_relativize_matches_inside_common_prose_delimiters(left, right):
    out = pathalias.relativize(f"x{left}{ROOT}/f.py{right}y", ALIASES)
    assert out == f"x{left}./f.py{right}y"


@pytest.mark.parametrize("punct", [":", ",", ";", "!", "?", ")", "]", "`", '"', ">"])
def test_relativize_treats_ambiguous_punctuation_as_prose(punct):
    # `:`/`,`/`;` (and the closers) are all LEGAL bytes in a POSIX path component, so
    # `<root>:8080` could in principle name a sibling directory. They are treated as prose
    # punctuation anyway: a trailing colon or comma after a path is overwhelmingly more
    # common in a sentence than a sibling whose name embeds one. This is a deliberate
    # ambiguity call, not an oversight — `.` is the one that goes the other way, because
    # its wrong answer (`..`) actively names a real, different directory.
    assert pathalias.relativize(f"in {ROOT}{punct} ok", ALIASES) == f"in .{punct} ok"


# --- sanitize_prose: the redaction/relativization interaction (#412 review) ---------
#
# Neither plain order is safe. Relativizing first shortens `api_key=<root>/secret` below
# the redactor's length floor, so the secret escapes. Redacting first lets the redactor
# CONSUME PART of an alias (its value charset covers `=` but stops at `:`, so a crafted
# `api_key=<16 chars>=file://<root>/secret` eats `...=file` and leaves `://<root>/secret`
# un-relativizable, surfacing the dead path AND the secret). Staging each alias behind an
# all-charset placeholder makes the alias atomic to the redactor, so both hold.


def test_sanitize_prose_relativizes_ordinary_paths():
    out = pathalias.sanitize_prose(f"Created [f.md]({ROOT}/f.md).", ALIASES)
    assert out == "Created [f.md](./f.md)."


def test_sanitize_prose_redacts_a_secret_riding_on_a_worktree_path():
    out = pathalias.sanitize_prose(f"api_key={ROOT}/abcdefgh", ALIASES)
    assert out == "api_key=[redacted: secret value]"
    assert "abcdefgh" not in out


def test_sanitize_prose_survives_a_crafted_partial_alias_consumption():
    crafted = f"api_key={'A' * 16}=file://{ROOT}/abcdefgh"
    out = pathalias.sanitize_prose(crafted, ALIASES)
    assert "abcdefgh" not in out
    assert ROOT not in out
    assert "pontonier-worktree-" not in out


def test_sanitize_prose_replaces_sentence_final_bare_root_with_a_safe_marker():
    """#420 review round 3: sanitize_prose's alias-staging shares the ambiguous-period
    carve-out with `relativize` (both go through `_replace_aliases`), so the same leak
    applied there too — a raw diagnostic ending in a bare worktree root plus a period (a
    common git-stderr shape, e.g. `fatal: failed in <wt>.`) passed through completely
    unrewritten. RED before the `_replace_aliases` fix."""
    text = f"fatal: failed in {ROOT}."
    out = pathalias.sanitize_prose(text, ALIASES)
    assert out == "fatal: failed in [worktree]."
    assert ROOT not in out
    assert "pontonier-worktree-" not in out


def test_sanitize_prose_ambiguous_marker_does_not_reopen_ordering_attack_b():
    """#420 review round 4: the round-3 fix substituted `_AMBIGUOUS_SUFFIX_MARKER`
    (`[worktree]`, containing `[`/`]`) directly in the ambiguous branch — but during
    `sanitize_prose`'s staging pass that breaks the labelled-value run right where the
    marker starts: `api_key=<root>./<16-char secret>` staged as
    `api_key=[worktree]./<16-char secret>` never reads as one long value, so the 16-char
    tail ships completely unredacted — ordering attack (b) reopened for exactly the
    ambiguous shape. The ambiguous branch must stage behind an equally-alphanumeric,
    equally-verified-absent placeholder during redaction, exactly like the ordinary branch,
    and only become the literal marker in the final unstaging step. RED before the fix."""
    secret_tail = "abcdefghijklmnop"  # 16 chars, exactly the redaction floor
    attack = f"api_key={ROOT}./{secret_tail}"
    out = pathalias.sanitize_prose(attack, ALIASES) or ""
    assert secret_tail not in out
    assert ROOT not in out
    assert "pontonier-worktree-" not in out
    assert "[redacted: secret value]" in out
    # Idempotency: re-running sanitize_prose on the already-sanitized output must be a
    # no-op — no staged token should ever survive into the emitted text for a second pass
    # to find and mangle.
    assert pathalias.sanitize_prose(out, ALIASES) == out


def test_sanitize_prose_never_leaks_either_placeholder():
    # Sibling of the placeholder-leak guard below, covering the ambiguous-branch token too.
    for text in (f"{ROOT}.", f"api_key={ROOT}./abcdefghijklmnop", f"see {ROOT}. here"):
        out = pathalias.sanitize_prose(text, ALIASES) or ""
        assert pathalias._AMBIGUOUS_PLACEHOLDER_PREFIX not in out


def test_sanitize_prose_never_leaks_the_placeholder():
    # The staged token is derived per input, so assert on its fixed prefix: any surviving
    # token — whole or fragment — carries it.
    for text in (f"{ROOT}/a", f"api_key={ROOT}/a", f"see {ROOT} here", "nothing to do"):
        out = pathalias.sanitize_prose(text, ALIASES) or ""
        assert pathalias._PLACEHOLDER_PREFIX not in out
        assert pathalias._staged_placeholder(text) not in out


def test_sanitize_prose_still_redacts_ordinary_secrets():
    out = pathalias.sanitize_prose("token=" + "z" * 40, ALIASES)
    assert "[redacted: secret value]" in out


def test_sanitize_prose_preserves_none_and_empty():
    assert pathalias.sanitize_prose(None, ALIASES) is None
    assert pathalias.sanitize_prose("", ALIASES) == ""


@pytest.mark.parametrize("bad", ["\n/tmp/tree", "/tmp/tree\n", " /tmp/tree", "/tmp/tree ", "/"])
def test_path_aliases_rejects_whitespace_bearing_and_root_paths(bad):
    # Stripping silently ACCEPTED a relative path ("\n/tmp/tree") and silently CHANGED a
    # legal absolute one ("/tmp/tree\n" is a different path). `/` is never a worktree and
    # yields aliases that cannot rewrite anything. All are programming errors.
    with pytest.raises(ValueError):
        pathalias.path_aliases(bad)


# The published fixed sentinel this module used before the collision was found. Kept here as
# a literal so the regression test reproduces the original attack exactly.
_FORMER_FIXED_PLACEHOLDER = "cicwt0worktree0alias0placeholder0"


def test_sanitize_prose_cannot_synthesize_a_jwt_via_placeholder_collision():
    """A fixed sentinel let model output ENCODE structural characters. `.` separates a JWT's
    segments, so `eyJ<8>` + sentinel + `<8>` + sentinel + `<8>` carried no dots while the
    redactor looked at it, then the final sentinel -> `.` replacement reconstructed a valid
    JWT in the output — a secret the redactor covers, smuggled past it. The staged sentinel
    is now derived per input and verified absent from it, so no pre-existing text can be
    turned into `.`."""
    attack = (
        "eyJ" + "a" * 8 + _FORMER_FIXED_PLACEHOLDER + "b" * 8 + _FORMER_FIXED_PLACEHOLDER + "c" * 8
    )
    out = pathalias.sanitize_prose(attack, ALIASES)
    assert out is not None
    # The give-away is a reconstructed `eyJ….….…` shape that was not in the input.
    assert not (out.startswith("eyJ") and out.count(".") == 2), f"JWT reconstructed: {out}"
    # Sanity: the same payload with literal dots IS redacted, so this test guards a real gap.
    literal = "eyJ" + "a" * 8 + "." + "b" * 8 + "." + "c" * 8
    assert "[redacted: secret value]" in (pathalias.sanitize_prose(literal, ALIASES) or "")


def test_staged_placeholder_is_verified_absent_from_the_input():
    # White-box: the guarantee is absence CHECKED against this input, not an unlikely
    # constant. Text that already contains the derived token forces a different token.
    text = "some prose"
    token = pathalias._staged_placeholder(text)
    assert token not in text
    assert token.isalnum()  # every char inside the redactor's value class
    assert len(token) > 16  # clears the labelled-secret length floor
    assert pathalias._staged_placeholder(token) != token


def test_sanitize_prose_leaves_a_literal_token_lookalike_untouched():
    text = f"the build wrote {_FORMER_FIXED_PLACEHOLDER} to the log"
    assert pathalias.sanitize_prose(text, ALIASES) == text


def test_path_aliases_includes_percent_encoded_file_uri(tmp_path):
    # `Path.as_uri()` percent-encodes spaces and `%`, so a canonical file URI Kimi emits for
    # a TMPDIR containing either would not match a naively concatenated `file://` alias.
    root = tmp_path / "a%b c" / "tree"
    root.mkdir(parents=True)
    aliases = pathalias.path_aliases(str(root))
    encoded = root.as_uri()
    assert encoded in aliases
    assert "%25b%20c" in encoded  # the encoding really differs from the raw form
    assert pathalias.relativize(f"open {encoded}/f.py", aliases) == "open ./f.py"
    # The raw, unencoded spelling still works too.
    assert pathalias.relativize(f"open file://{root}/f.py", aliases) == "open ./f.py"


def test_staged_placeholder_extends_on_a_forced_collision(monkeypatch):
    """The absence CHECK, not just the derivation, is the guarantee. A digest that appears
    inside its own input is not constructible, so the seed is stubbed to force the collision
    the loop exists for — otherwise the loop is unfalsifiable and its removal goes unnoticed
    (a mutation probe caught exactly that)."""
    monkeypatch.setattr(pathalias, "_placeholder_seed", lambda _text: "deadbeef")
    base = pathalias._PLACEHOLDER_PREFIX + "deadbeef"
    text = f"log line mentioning {base} inline"

    token = pathalias._staged_placeholder(text)

    assert token not in text
    assert token.startswith(base)
    assert len(token) > len(base)  # the loop extended it
    # And the collision cannot survive into output: nothing pre-existing becomes `.`.
    assert pathalias.sanitize_prose(text, ALIASES) == text


def test_staged_placeholder_rechecks_each_extension(monkeypatch):
    """A single `if` is not enough — the recheck must loop. Text holding both the base token
    and base+"0" forces two extensions; a one-shot check would return base+"0", which is
    still present."""
    monkeypatch.setattr(pathalias, "_placeholder_seed", lambda _text: "deadbeef")
    base = pathalias._PLACEHOLDER_PREFIX + "deadbeef"
    text = f"{base} and {base}0 both appear"

    token = pathalias._staged_placeholder(text)

    assert token not in text
    assert token == base + "00"


def _call_with_timeout(fn, seconds):
    """Run `fn()` under a SIGALRM deadline so a regression in a loop's termination argument
    FAILS this test rather than hanging the whole suite (#420 review round 5)."""
    import signal

    def _handler(signum, frame):
        raise TimeoutError(f"did not terminate within {seconds}s")

    old_handler = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def test_staged_ambiguous_placeholder_terminates_when_other_is_a_prefix_of_token(monkeypatch):
    """#420 review round 5 (NEW-2): the loop's `other in token` clause cannot be fixed by
    appending -- once `other` occurs anywhere in `token`, every further extension only adds
    characters AFTER the existing match, so a loop that only appends there never terminates.
    Forced via the same seam `_staged_placeholder`'s own collision tests use
    (`_placeholder_seed` stubbed to a fixed value): choose `other` to equal `token`'s
    un-extended form exactly (a prefix match -- the realistic shape, since both derive from
    the same `_placeholder_seed(text)` and differ only in their fixed literal prefix).
    Wrapped in a SIGALRM deadline so a reintroduced regression fails loudly instead of
    hanging the suite."""
    monkeypatch.setattr(pathalias, "_placeholder_seed", lambda _text: "deadbeef")
    other = pathalias._AMBIGUOUS_PLACEHOLDER_PREFIX + "deadbeef"  # == token's initial form
    text = "some prose that never mentions the forced token"

    token = _call_with_timeout(
        lambda: pathalias._staged_ambiguous_placeholder(text, other), seconds=5
    )

    assert token not in text
    assert token not in other
    assert other not in token
    assert token != other
    assert len(token) > 16  # clears the labelled-secret length floor


def test_staged_ambiguous_placeholder_rejects_empty_other():
    # The empty string is a substring of everything, which would make `other in token`
    # permanently, unfixably true -- `_staged_placeholder`'s own output is never empty, so
    # this is a caller-contract check, not a real-world case.
    with pytest.raises(ValueError, match="non-empty"):
        pathalias._staged_ambiguous_placeholder("text", "")


def test_alias_replacement_cannot_abut_an_alphanumeric():
    """Why alias -> `.` cannot synthesize a covered secret, stated as a test rather than left
    to a comment. Every shape the redactor covers needs its structural characters flanked by
    alphanumerics (a JWT's `eyJ<seg>.<seg>.<seg>`), but a match requires a prose DELIMITER
    immediately before the alias — so a substitution never lands directly after an
    alphanumeric, and the reconstructed dots always carry the delimiters with them."""
    # Aliases jammed against alnum text: no delimiter, so no substitution at all.
    jammed = f"eyJ{'a' * 8}{ROOT}{'b' * 8}{ROOT}{'c' * 8}"
    assert pathalias.sanitize_prose(jammed, ALIASES) == jammed
    # Delimited: substitution happens, but the delimiters survive, so it is not a JWT.
    spaced = f"eyJ{'a' * 8} {ROOT} {'b' * 8} {ROOT} {'c' * 8}"
    out = pathalias.sanitize_prose(spaced, ALIASES)
    assert out == f"eyJ{'a' * 8} . {'b' * 8} . {'c' * 8}"
    assert ".." not in out


# --- sanitize_echo_prose: control characters ahead of the alias staging -------------
#
# A control character defeats relativization for the same reason it defeats redaction:
# alias matching is an exact string match, so `\x1b` wedged into the printed path means
# no alias matches and the dead absolute worktree path rides out whole. Stripping AFTER
# `sanitize_prose` cannot fix that — the miss already happened. So the strip belongs
# ahead of the staging pass, inside one function, not composed by a caller.


@pytest.mark.parametrize("ch", ["\x1b", "\x00", "\x07", "\x7f", "\x85"])
def test_sanitize_echo_prose_relativizes_a_control_split_path(ch):
    """The #420 guarantee under attack: a bare control character inside the printed
    worktree path must not smuggle the dead absolute path into an error envelope."""
    head, tail = ROOT[:6], ROOT[6:]
    out = pathalias.sanitize_echo_prose(f"failed at {head}{ch}{tail}/src/x.py", ALIASES)
    assert ROOT not in out
    assert out == "failed at ./src/x.py"


@pytest.mark.parametrize("ch", ["\x1b", "\x00", "\x07", "\x7f", "\x85"])
def test_sanitize_prose_alone_leaks_the_control_split_path(ch):
    """Positive control for the test above: the un-stripped helper really does leak, so
    that assertion measures the new behavior rather than an attack that never worked."""
    head, tail = ROOT[:6], ROOT[6:]
    attacked = f"failed at {head}{ch}{tail}/src/x.py"
    assert f"{head}{ch}{tail}" in (pathalias.sanitize_prose(attacked, ALIASES) or "")


def test_a_printable_escape_payload_still_defeats_relativization():
    """The honest bound on the guarantee. Deleting the ESC from `\\x1b[0m` leaves the
    printable `[0m` behind, so the alias STILL does not match and the dead path survives.
    Stripping buys terminal-rendering safety and closes the bare-control split; it is not
    a claim that any interpolation can be undone — nothing short of not echoing the text
    could promise that. Pinned so a future reader does not over-read the docstring."""
    head, tail = ROOT[:6], ROOT[6:]
    out = pathalias.sanitize_echo_prose(f"failed at {head}\x1b[0m{tail}/src/x.py", ALIASES) or ""
    assert f"{head}[0m{tail}" in out  # path survives, mangled — but no control character
    assert "\x1b" not in out


def test_sanitize_echo_prose_still_redacts_a_secret_riding_on_a_worktree_path():
    """The #412 interaction guarantee survives the added strip."""
    out = pathalias.sanitize_echo_prose(f"api_key={ROOT}/abcdefgh", ALIASES)
    assert "abcdefgh" not in out


def test_sanitize_echo_prose_deletes_non_newline_controls():
    out = pathalias.sanitize_echo_prose("a\x1b[31mb\nc\x07d", ALIASES)
    assert out == "a[31mb\ncd"


@pytest.mark.parametrize("value", [None, ""])
def test_sanitize_echo_prose_passes_empty_through(value):
    assert pathalias.sanitize_echo_prose(value, ALIASES) == value


def test_sanitize_echo_prose_is_idempotent():
    text = f"boom \x1b[31mRED\x1b[0m at {ROOT}/x.py\napi_key=" + "Z" * 32
    once = pathalias.sanitize_echo_prose(text, ALIASES)
    assert pathalias.sanitize_echo_prose(once, ALIASES) == once


@pytest.mark.parametrize("delim", ["\n", "\t", "\r", "\x0b", "\x0c"])
def test_sanitize_echo_prose_relativizes_when_a_control_char_is_the_alias_delimiter(delim):
    """Regression: stripping BEFORE the staging disclosed a dead absolute worktree path.

    `_replace_aliases` needs a delimiter beside an alias, and a control character is often
    the delimiter it has — a tab, a carriage return, the line feed that starts the line.
    Delete it first and the alias inherits the previous character on its left, stops
    matching, and the absolute path rides out: the #420 failure this helper exists to
    prevent. Plain `sanitize_prose` handles all of these, so the helper was strictly worse
    than the function it wraps.
    """
    text = f"prefix{delim}{ROOT}/file"
    out = pathalias.sanitize_echo_prose(text, ALIASES) or ""
    assert ROOT not in out, out
    # Positive control: deleting the delimiter really is what breaks it, so this measures
    # the staging order rather than a path that was never at risk.
    assert ROOT in (pathalias.sanitize_prose(text.replace(delim, ""), ALIASES) or "")


def test_sanitize_echo_prose_relativizes_an_alias_the_strip_repairs():
    """The other half of the union, which a single staging pass would lose.

    A path with a control character INSIDE it matches no alias until the character is
    gone — the mirror of the delimiter case, and the reason staging runs both before and
    after the strip. Covering only one of the two would trade one disclosure for another.
    """
    head, tail = ROOT[:6], ROOT[6:]
    out = pathalias.sanitize_echo_prose(f"failed at {head}\x1b{tail}/f.py", ALIASES) or ""
    assert ROOT not in out
    assert out == "failed at ./f.py"


def test_sanitize_echo_prose_redacts_a_secret_split_by_a_line_feed():
    """With aliases staged first, collapsing line feeds can no longer cost a
    relativization — so this helper shares `redaction.sanitize_echo_prose`'s newline
    policy instead of needing a weaker one of its own, and a secret split at a line feed
    is caught rather than accepted as a miss."""
    secret = "sk-ant-api03-" + "A" * 40
    out = pathalias.sanitize_echo_prose("sk-\nant-api03-" + "A" * 40, ALIASES) or ""
    assert secret not in out
    assert "A" * 40 not in out


def test_sanitize_echo_prose_keeps_line_feeds_in_an_untouched_diagnostic():
    out = pathalias.sanitize_echo_prose(f"line one\nfailed at {ROOT}/x.py\nline three", ALIASES)
    assert out == "line one\nfailed at ./x.py\nline three"


@pytest.mark.parametrize("ch", ["\x00", "\x1b", "\x7f", "\x85"])
def test_sanitize_echo_prose_never_cancels_a_key_blocks_fail_closed_blanket(ch):
    """Keeping line feeds does not exempt this helper from the key-block guard.

    A control character OTHER than a line feed damages an END marker just as well, so
    stripping it would terminate a block that was failing closed and uncover everything the
    blanket covered. Caught only because the redaction-side guard prompted the question
    here too — the LF policy differs between the helpers, the key-block rule does not.
    """
    body = "MIIEowIBAAKCAQEA" + "b" * 40
    text = (
        f"-----BEGIN RSA PRIVATE KEY-----\n{body}\n"
        f"-----END RSA PRIVATE KEY---{ch}--\ntrailing secret area"
    )
    # Positive control: unstripped, the damaged END really does leave the block open.
    assert "trailing secret area" not in (pathalias.sanitize_prose(text, ALIASES) or "")
    assert "trailing secret area" not in (pathalias.sanitize_echo_prose(text, ALIASES) or "")
    assert body not in (pathalias.sanitize_echo_prose(text, ALIASES) or "")
