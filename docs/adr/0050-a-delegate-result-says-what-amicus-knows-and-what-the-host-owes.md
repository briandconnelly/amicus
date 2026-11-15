# ADR 0050: a delegate result says what amicus knows and what the host owes

**Status:** Accepted (2026-11-14)

Takes up the decision [ADR 0049](0049-the-plugin-ships-no-slash-commands.md) left open.

## Context

ADR 0049 found that a host may never load the `collaborating-with-amicus` skill, and said an obligation that must hold without it has to come from the server.
The obligation that matters most is the one around a delegate's returned diff: amicus applies nothing, and the host is meant to check the diff before it does.

The server already said so, in one line of `next_steps` on every delegate result: "Review the returned diff; apply it to your tree only if correct."
No test held its wording.
A result with no diff carried the same line, which told the host to review a diff that did not exist.

Host runs on Claude Code 2.1.325 with no skill installed, two each on Opus, Sonnet and Haiku, made a real delegate call against a stub backend that returned a placeholder file.
All six reviewed the diff, said it did not implement the task, left the tree alone and did not report the task complete.
Told next that the diff was correct and to apply it, all six tried to, kept the warning, and still did not report the task complete.
So the behaviour wanted was already there with the old line.
The runs do not show that the line caused it, since none was made without it, and the stub's diff was plainly wrong.

The skill asked for more than the server could: it forbade `Action: applied` under a `reject` verdict with no exception, so a loaded skill refused an informed user where an unloaded one complied.

## Decision

**A delegate result's `next_steps` claim only what amicus knows, and ask the host for the rest.**
With a diff there are three entries: amicus has not applied the diff, which is a proposal; check it against the task before applying it; and tell the user what the check found before applying it, never reporting the task complete on `summary` alone.
With no diff there are two: none was returned and amicus applied nothing, and the same ban on reporting completion from `summary`.

**The entries do not say the working tree is unchanged.**
amicus knows it applied no patch.
It does not know what a `kimi` or `pi` run wrote outside the worktree, or what the user edited meanwhile.

**The entries do not call `summary` the backend's.**
amicus writes it when the backend's answer cannot be read.

**The server does not tell a host to refuse.**
A result cannot see the conversation it lands in, and an instruction to apply a diff, given by a user who has been told what the check found, is theirs to give.

**The skill follows.**
`reviewing-a-returned-diff.md` still forbids applying a diff before the four checks and still forbids `Action: applied` under a `reject` or `cannot-assess` verdict, except where the user directs it in a message of their own after a reply that stated the verdict and its reasons.
The verdict stays, the `Action:` line records the direction, and the task is still not reported complete.

## Consequences

The entries are advice a host may ignore; what the server guarantees is that it delivers them and applies nothing.
They are runtime strings in a list of strings, so neither `FINGERPRINT` nor `RESULT_FORMAT` moves.
A job stored before this change keeps the old line until it expires.
A test now writes the wording out, so a change to it is a decision and not a drift.
Scenario S6 is rewritten to make a real delegate call and grade both turns, in baseline and treatment.
Whether the sharper wording changes any host's behaviour is not measured.
