---
description: Check which backends amicus has enabled, installed, and authenticated
argument-hint: "[backend]"
---

Call the `amicus_backends` MCP tool from the amicus server (free — no model call) to
list backends. Pass `backend` only if the request names one; omit it to list every backend amicus
knows about — disabled ones are listed too, marked `enabled: false`.

Request: $ARGUMENTS

For each backend, report `enabled`, `available` (the plugin loaded),
`status.installed`, `status.authenticated`, and which features it supports
(`amicus_delegate` works on `codex` and `kimi` only; `amicus_adversarial_review` is
`claude`-only). A backend can be enabled but not ready — check `status`, not just
`enabled`, before recommending it. `AMICUS_BACKENDS` controls which backends are
*enabled* in this deployment; it is not a default to fall back to, and this command
never picks a backend for you.

To see a backend's model slugs and reasoning-effort sets before overriding `model`
or `reasoning_effort` on a paid call, call `amicus_models` with that `backend`.

To see the full tool inventory, fingerprint, and error catalog, call
`amicus_capabilities`.
