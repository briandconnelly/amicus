"""Behavior contract for scripts/check_sentence_per_line.py (AGENTS.md rule 16).

The script lives under scripts/ (not the package), so coverage doesn't track it;
these tests pin its segmentation and 0/1/2 exit behavior directly, and run it over
the committed docs/ tree, which is what puts rule 16 in the gate. It is loaded by
path, mirroring tests/test_check_github_actions_pinning.py."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_sentence_per_line.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("check_sentence_per_line", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load_script()


# --- sentence_breaks: segmenting one line -------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "Two sentences share this line. This is the second.",
        "Is this a question? Yes.",
        "It worked! Then it stopped.",
        "It ends in a code span. `amicus.sdk` opens the next.",
        "It ends before a link. [ADR 0013](adr/0013.md) opens the next.",
        "It ends before emphasis. *Then* the next.",
        "It ends in emphasis, *like this.* The next follows.",
        "It ends in a parenthesis (like this.) The next follows.",
        "It was released as 0.2.0. Then 0.3.0 followed.",
        "- A list item. With a second sentence.",
        "1. A numbered item. With a second sentence.",
        "- **Label.** One sentence. And another.",
        'A quotation can end the sentence it sits in, "like this." Then the next.',
        "A curly one can too, \u201clike this.\u201d Then the next.",
        'He asked "why?" Then he left.',
    ],
)
def test_sentence_breaks_finds_a_second_sentence(line):
    assert len(check.sentence_breaks(line)) == 1


@pytest.mark.parametrize(
    "line",
    [
        "One sentence, ending here.",
        "A clause; another clause joined by a semicolon.",
        "A lead-in: Then what it introduces, in one sentence.",
        "A version like v0.9.0 or 0.2.0 does not end a sentence.",
        "Abbreviations such as e.g. `this` and i.e. That do not end one.",
        "Neither does vs. Codex, cf. The spec, or etc. And so on.",
        "A code span `amicus.sdk.core. Runtime` hides its periods.",
        "A double-backtick span ``a. `B` c`` hides its periods too.",
        'A quotation "Ends here. Then more." is reproduced as written.',
        "A curly quotation “Ends here. Then more.” is too.",
        'A quotation closing on its own period, "like this." is still one sentence.',
        'A link [text](a.md "Its title. Two sentences.") hides its target.',
        "A bare URL https://example.com/v1.2/A.B hides its dots.",
        "An ellipsis ... Does not end a sentence.",
        "1. A numbered item holding one sentence.",
        "### 3. A numbered heading",
        "**Bold run-in label.** Then one sentence.",
        "- [x] A done task. ",
    ],
)
def test_sentence_breaks_finds_one_sentence(line):
    assert check.sentence_breaks(line) == []


def test_sentence_breaks_returns_offsets_into_the_original_line():
    # Masking is length-preserving, so an offset indexes the unmasked line.
    line = "See `a.b` and [x](y.z). Then `c.d` here. Last."
    assert [line[offset:] for offset in check.sentence_breaks(line)] == [
        "Then `c.d` here. Last.",
        "Last.",
    ]


# --- iter_violations: what is and is not prose ---------------------------------


def test_iter_violations_reports_the_line_number():
    text = "# Title\n\nOne sentence.\nTwo here. And three.\n"
    assert check.iter_violations(text) == [(4, "Two here. And three.")]


def test_iter_violations_accepts_a_sentence_wrapped_across_lines():
    assert check.iter_violations("One sentence wrapped\nacross two lines.\n") == []


@pytest.mark.parametrize(
    "text",
    [
        "```\nOne. Two.\n```\n",
        "~~~python\nOne. Two.\n~~~\n",
        "- item\n\n  ```sh\n  One. Two.\n  ```\n",
        "<!--\nOne. Two.\n-->\n",
        "<!-- One. Two. -->\n",
        "---\ntitle: One. Two.\n---\n",
        "| a | One. Two. |\n",
        "> One. Two.\n",
        "  > One. Two.\n",
        "[ref]: https://example.com One. Two.\n",
    ],
)
def test_iter_violations_skips_what_is_not_prose(text):
    assert check.iter_violations(text) == []


def test_iter_violations_resumes_after_a_fence_closes():
    text = "```\nOne. Two.\n```\nThree. Four.\n"
    assert check.iter_violations(text) == [(4, "Three. Four.")]


def test_iter_violations_resumes_after_a_comment_closes():
    text = "<!--\nOne. Two.\n-->\nThree. Four.\n"
    assert check.iter_violations(text) == [(4, "Three. Four.")]


def test_a_fence_closes_only_on_its_own_character_and_length():
    # A ~~~ or shorter ``` line inside a ```` block is content, not a close.
    text = "````\n~~~\n```\nOne. Two.\n````\nThree. Four.\n"
    assert check.iter_violations(text) == [(6, "Three. Four.")]


@pytest.mark.parametrize(
    ("text", "lineno"),
    [
        # A backtick fence's info string cannot hold a backtick, so these are code spans.
        ("```a``` is inline code.\n\nOne. Two.\n", 3),
        ("```` ``` ```` is inline code.\n\nOne. Two.\n", 3),
        ("  ```a``` in a list item.\n\nOne. Two.\n", 3),
    ],
)
def test_a_backtick_run_with_a_backtick_after_it_opens_no_fence(text, lineno):
    assert [n for n, _ in check.iter_violations(text)] == [lineno]


@pytest.mark.parametrize(
    "text",
    [
        "```sh\nOne. Two.\n```\nThree. Four.\n",
        # A tilde fence's info string may hold a backtick.
        "~~~ `x`\nOne. Two.\n~~~\nThree. Four.\n",
    ],
)
def test_a_fence_with_an_allowed_info_string_still_opens(text):
    assert check.iter_violations(text) == [(4, "Three. Four.")]


@pytest.mark.parametrize(
    ("text", "lineno"),
    [
        ("<!-- note --> One. Two.\n", 1),
        ("One. Two. <!-- note -->\n", 1),
        ("<!--\nHidden. Hidden.\n--> One. Two.\n", 3),
        ("<!-- a --> One. <!-- b --> Two.\n", 1),
    ],
)
def test_prose_beside_a_comment_is_still_checked(text, lineno):
    assert [n for n, _ in check.iter_violations(text)] == [lineno]


def test_a_fence_inside_a_comment_does_not_open_a_code_block():
    text = "<!-- ``` -->\nOne. Two.\n"
    assert check.iter_violations(text) == [(2, "One. Two.")]


@pytest.mark.parametrize(
    ("text", "lineno"),
    [
        ("A comment opens with `<!--`.\nThen it closes.\n\nOne. Two.\n", 4),
        ("Write `<!--` here. Then this.\n", 1),
        ("Use ``a `<!--` b`` here.\n\nOne. Two.\n", 3),
        # An escaped backslash leaves the backtick after it free to open a span.
        ("A path ends in \\\\`<!--` here.\n\nOne. Two.\n", 3),
        # An escaped backtick is literal, and the backtick after it still opens a span.
        ("Use \\``<!--` and ``.\n\nOne. Two.\n", 3),
        # An escaped ``<`` is literal, so it opens no comment either.
        ("Write \\<!-- literally.\n\nOne. Two.\n", 3),
    ],
)
def test_a_comment_opener_in_a_code_span_opens_no_comment(text, lineno):
    assert [n for n, _ in check.iter_violations(text)] == [lineno]


def test_a_backtick_inside_a_comment_does_not_hide_its_close():
    # Whichever opens first wins, so a backtick after ``<!--`` is comment text.
    text = "<!-- a ` --> One. Two. `\n"
    assert [n for n, _ in check.iter_violations(text)] == [1]


def test_an_escaped_backtick_opens_no_code_span_before_a_comment():
    text = "Literal \\`<!-- hidden ` One. Two. -->\n"
    assert check.iter_violations(text) == []


def test_a_backtick_inside_an_html_tag_opens_no_code_span():
    # The tag is one inline token, so its backtick cannot pair with one past ``<!--``.
    text = '<span title="`"> <!-- ` Hidden. Hidden. -->\n'
    assert check.iter_violations(text) == []


@pytest.mark.parametrize(
    ("text", "lineno"),
    [
        ("Intro.\n<!-- never closed\nOne. Two.\n", 2),
        # A span closing on a later line is not followed, so its ``<!--`` opens one.
        ("Start `code <!-- still\ncode end`.\n\nOne. Two.\n", 1),
        ("<!-- a -->\n\nText <!-- b\n", 3),
    ],
)
def test_unclosed_comment_names_the_line_that_opened_it(text, lineno):
    assert check.unclosed_comment(text) == lineno


@pytest.mark.parametrize("text", ["Fine.\n", "<!--\nHidden.\n-->\n", "`<!--` is code.\n"])
def test_unclosed_comment_is_none_when_every_comment_closes(text):
    assert check.unclosed_comment(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "| A | B |\n| --- | --- |\n| One. Two. | Three |\n",
        "A | B\n--- | ---\nOne. Two. | Three\n",
        "One. Two. | B\n:-- | --:\nC | D\n",
    ],
)
def test_iter_violations_skips_a_table_with_or_without_leading_pipes(text):
    assert check.iter_violations(text) == []


def test_a_table_ends_at_the_next_blank_line():
    text = "A | B\n--- | ---\nC | D\n\nOne. Two.\n"
    assert check.iter_violations(text) == [(5, "One. Two.")]


def test_a_pipe_above_a_thematic_break_is_not_a_table():
    # A delimiter row needs a pipe; a bare ``---`` makes a setext heading instead.
    text = "One. Two | x\n---\n"
    assert check.iter_violations(text) == [(1, "One. Two | x")]


def test_front_matter_is_skipped_only_at_the_top_of_a_file():
    text = "Intro.\n\n---\n\nOne. Two.\n"
    assert check.iter_violations(text) == [(5, "One. Two.")]


# --- main: exit codes -----------------------------------------------------------


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_main_exits_0_when_every_line_holds_one_sentence(tmp_path, capsys):
    _write(tmp_path, "docs/a.md", "# A\n\nOne sentence.\nAnother.\n")
    assert check.main([str(tmp_path)]) == 0
    assert "1 docs/ Markdown file(s)" in capsys.readouterr().out


def test_main_exits_1_and_names_each_violation(tmp_path, capsys):
    _write(tmp_path, "docs/a.md", "Fine.\n")
    _write(tmp_path, "docs/sub/b.md", "Fine.\nOne. Two.\n")
    assert check.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "FAIL: docs/sub/b.md:2: One. Two." in out
    assert "1 line(s)" in out


def test_main_exits_1_when_a_file_ends_inside_a_comment(tmp_path, capsys):
    # Everything after the opener went unchecked, so the run must not pass.
    _write(tmp_path, "docs/a.md", "Fine.\nIt opens with <!-- here.\n\nOne. Two.\n")
    assert check.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "FAIL: docs/a.md:2: an HTML comment opens here and never closes" in out
    assert "1 file(s)" in out
    assert "line(s) under docs/ hold" not in out


def test_main_exits_2_when_there_is_nothing_to_scan(tmp_path, capsys):
    assert check.main([str(tmp_path)]) == 2
    assert "nothing to verify" in capsys.readouterr().out


def test_main_scans_only_markdown_under_docs(tmp_path):
    _write(tmp_path, "docs/a.md", "Fine.\n")
    _write(tmp_path, "docs/notes.txt", "One. Two.\n")
    _write(tmp_path, "README.md", "One. Two.\n")
    assert check.main([str(tmp_path)]) == 0


# --- the committed tree ----------------------------------------------------------


def test_committed_docs_hold_one_sentence_per_line(capsys):
    """Rule 16 over the real tree: this is the gate half of the check."""
    assert check.main([str(_REPO_ROOT)]) == 0, capsys.readouterr().out
    scanned = len(list((_REPO_ROOT / "docs").rglob("*.md")))
    assert scanned > 0
    assert f"across {scanned} docs/ Markdown file(s)" in capsys.readouterr().out


def test_a_violation_planted_in_the_committed_docs_is_caught(tmp_path, capsys):
    """Control: the real-tree pass above is not vacuous on this corpus."""
    shutil.copytree(_REPO_ROOT / "docs", tmp_path / "docs")
    target = tmp_path / "docs" / "RELEASING.md"
    target.write_text(
        target.read_text(encoding="utf-8") + "\nA planted sentence. And a second one.\n",
        encoding="utf-8",
    )
    assert check.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "FAIL: docs/RELEASING.md:" in out
    assert "1 line(s)" in out
