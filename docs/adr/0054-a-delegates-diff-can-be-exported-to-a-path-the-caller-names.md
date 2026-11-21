# ADR 0054: a delegate's diff can be exported to a path the caller names

**Status:** Accepted (2026-11-21)

Adds one tool, `amicus_job_export_diff`, and narrows the "no other file" clause of [ADR 0035](0035-a-backend-answer-is-kept-on-the-job-record.md) by exactly one file.
AGENTS.md rule 18 was amended first, in a governance PR of its own (#561), to admit it.

## Context

The skill's diff-review recipe applies `$RETURNED_DIFF`, a file holding a delegate's `diff`, but amicus offered no way to produce that file (issue #556).
Agents worked around it in two ways.
Some told the backend to write its patch to a side file and waited on that file, never fetching or consuming the job, which left the result filling the per-workspace cap.
Others fetched the result, and a diff near the 200,000-byte cap overflowed the host's tool-output limit: Claude Code spilled results of about 157,000 and 208,000 characters into its own files, and retyping a large diff by hand is error-prone.

ADR 0035 and rule 18 kept a delegate's diff only on the job record, so writing it anywhere else was a decision for the maintainer rather than a skill rule.

## Decision

**A new free tool writes the stored diff to one new file at a path the caller names.**
`amicus_job_export_diff(job_id, path, workspace_root)` reads the job exactly as `amicus_job_result` does at its default detail, so a workspace, lookup, running, corrupt or incompatible outcome is that tool's own.
For a delegate it writes the success's `diff`, or a stopped run's `partial.diff` on a stored `timeout` or `budget_exceeded`, and returns the same envelope with that diff null and `meta.diff_export` naming the file, its byte count, its SHA-256 and its `source` (`diff` or `partial`).
`diffstat`, `meta.truncated` and `meta.redacted_paths` are returned as stored, so a caller can tell whether the file is the whole change.
A delegate with no diff is returned unchanged and nothing is written; a job of any other kind is `invalid_arguments` on `job_id`.

**The file's properties are fixed.**
`path` must be absolute and name nothing that exists yet, a symlink included, in a directory that exists.
The directory is resolved and opened, and the file is created relative to that open directory with `O_CREAT | O_EXCL | O_NOFOLLOW` and mode `0o600`, so it is never an overwrite and never follows a link.
A directory that is the job store or lies under it is refused, also when it is reached through a symlinked parent.
The file holds the stored diff's UTF-8 bytes exactly.
A refused path is `invalid_arguments` on `path` with `details.reason` one of `not_absolute`, `exists`, `parent_missing`, `inside_job_store` or `not_writable`, and nothing is created.
A file the call created and could not finish, a full disk for example, is removed by that same call, which fails as `export_failed`, temporary, with a repair naming this tool.

**A successful export counts as delivery; a failed one does not.**
The job is stamped delivered, as `amicus_job_result` stamps it, only after the file is whole.
A refused or failed export leaves the record undelivered and unchanged, so it keeps its cap slot and a later `amicus_job_result` still returns the whole diff.
The export never changes `result.json`, and `meta.diff_export` is delivery-only like `meta.consume`, so `RESULT_FORMAT` does not move.

**Ownership passes to the caller when the call returns.**
The file is outside the job retention the tool surface discloses: `AMICUS_JOB_TTL`, the per-workspace cap and `amicus_job_consume_result` never touch it, and the caller deletes it.
A crash while the file is being written can leave a partial file at the caller's path, since only the call that created it can remove it; its byte count and digest will not match a later successful export's.
The path, like the diff, goes to no log and into no error message.

**The path is not bound to the MCP roots.**
A scratch directory is the natural place for a file to review and apply, and it usually lies outside the workspace, so binding the path to the client's roots would refuse the common case.

**The tool is a new one, annotated as an additive write.**
It is `readOnlyHint: false`, `destructiveHint: false` and `idempotentHint: false`, because each call can create a new file and never removes or replaces one.
`amicus_job_result` stays `readOnlyHint: true`, which is why the export is not a parameter on it.

**The skill's recipe exports first.**
A delegate's result is retrieved by exporting it before any `amicus_job_result`, because a fetch returns the whole diff into the host's context; the recipe checks the file's digest against `meta.diff_export.sha256` before applying it.

## Alternatives

**Base64 pages through `amicus_job_result`.**
Each page fits a host's output limit, but the host must reassemble and decode the pages into a file itself, which is the error-prone step the issue reports, and every page still passes through its context.

**An MCP resource for the diff.**
Whether a host saves a resource to disk, and where, is the host's choice, and the resource's bytes would still reach the context of a host that reads it inline.

**A stdin-only recipe.**
Feeding `git apply` from the host still needs the diff in the host's context first, so it does not help a diff that overflows the output limit.

**A parameter on `amicus_job_result` and `amicus_job_consume_result`.**
It would make two read tools write files, so they could no longer be annotated read-only, and `effects.job_reads_read_only` would stop being true.

**An operator-approved export root.**
Codex's critique proposed restricting `path` to a directory the operator names, so a prompt-injected host could not be steered into writing elsewhere.
It is not adopted here: the file is new, never an overwrite, mode `0o600` and outside the job store, and the host can already write files with its own tools.
It remains the alternative the maintainer may still choose, as a server setting that narrows the accepted paths without changing the tool.

## Consequences

The tool surface gains one tool and one error code, `export_failed`, and `Meta` gains the delivery-only `diff_export`.
The diff can exist in a second place the caller chose, for as long as the caller keeps it, which is the one exception rule 18 now names.
A host without the skill learns of the export from the delegate's `_async` description, the server instructions and the tool's own description.
