---
description: Preview a review or delegate call amicus would assemble — free, no model call
argument-hint: "<backend> review|delegate [working_tree|branch <base>|commit <sha>]"
---

Preview what an `amicus_review_changes` or `amicus_delegate` call would send,
without spending quota.

Request: $ARGUMENTS

Both preview tools still take `backend` as a required argument — a dry run reports
what amicus would assemble *for that backend's resolved options*, not whether the
backend itself is ready or authenticated; use `amicus_backends` for that, and if the
request does not name a backend ask which one to preview against.

For a review preview, call `amicus_dry_run` (free — no model call). Map the scope
request to `scope`/`base`/`commit` as for `/amicus:review`, and pass the absolute
repo path as `workspace_root`. Report the context summary (files/lines changed), the
prompt size, whether the diff would be truncated, and any redacted secret paths.

For a delegate preview, call `amicus_delegate_dry_run` (free — no model call) with
the same `task` and `workspace_root` you would pass to `amicus_delegate`, and report
the resolved options it would use.

Say what the preview does not cover: it reports metadata about the input amicus
would assemble, not what the backend itself reads and sends once the paid call runs.
Do not present a clean preview as evidence that nothing sensitive will be sent.
