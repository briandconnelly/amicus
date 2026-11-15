# Transcript: six host runs, 2026-11-14

Each run lists its environment, its ordered tool calls and what the reply said about them.
Arguments that carry prompt text are given as their length.

## S1, treatment, `AMICUS_BACKENDS=codex`

Prompt `S1-P1-AGENT-A`.

1. `Skill` with `amicus:amicus:consult`.
2. `ToolSearch` selecting `amicus_backends` and `amicus_consult`.
3. `amicus_backends` with `detail: "full"`, which returned `ok: true`.
4. `amicus_consult` with `backend: "codex"`, `question` (462 characters), `extra_context` (180 characters), `workspace_root` set to the scratch repository and `detail: "full"`, which returned `ok: true`.

`server.log` shows the same two amicus calls in that order.
The reply relays the backend's answer and says it asked Codex, "the only amicus backend that's set up right now".

## S1, treatment, `AMICUS_BACKENDS=pi`

`AMICUS_PI_MODEL=openrouter/moonshotai/kimi-k3`.
Prompt `S1-P1-AGENT-A`.

1. `Skill` with `amicus:amicus:consult`.
2. `ToolSearch` selecting `amicus_backends`, `amicus_consult` and `amicus_models`.
3. `amicus_backends` with `detail: "full"`, which returned `ok: true`.
4. `amicus_models` with `backend: "pi"`.
5. `amicus_consult` with `backend: "pi"`, `question` (554 characters), `extra_context` (150 characters), `workspace_root` and `detail: "full"`, and no `model`, which returned `ok: true`.

`server.log` shows the same three amicus calls in that order.
The reply names "**pi** running `moonshotai/kimi-k3` (pi's configured default model)" and says it "was the only backend enabled".

## S1, baseline, `AMICUS_BACKENDS=codex`

No plugin directory; the init event lists no amicus plugin and no amicus skill.
Prompt `S1-P1-AGENT-A`.

1. `ToolSearch` selecting `amicus_backends` and `amicus_consult`.
2. `amicus_backends` with `detail: "full"`, which returned `ok: true`.
3. `amicus_consult` with `backend: "codex"`, `question` (829 characters), `extra_context` (146 characters), `workspace_root` and `detail: "full"`, which returned `ok: true`.

`server.log` shows the same two amicus calls in that order.

## S2, treatment, `AMICUS_BACKENDS=codex`, fake `codex`

Turn 1, harness prompt `S2-H1-AGENT-A`.

1. `ToolSearch` selecting `amicus_consult`.
2. `amicus_consult` with `backend: "chatgpt"`, `question` (57 characters) and `workspace_root`.

The server answered `ok: false` with `error.code: "invalid_arguments"`, `temporary: false`, `repair.next_step: "correct_arguments"`, `repair.tool: "amicus_consult"`, and `invalid_arguments[0]` naming `field: "backend"` with `allowed_values: ["codex", "kimi", "claude", "pi"]`.
The reply: "The call failed with `invalid_arguments`: "chatgpt" isn't an accepted backend (the allowed ones are codex, kimi, claude and pi), so it was rejected before anything was spent."

Turn 2, the same session resumed, prompt `S2-P1-AGENT-A`.

1. `amicus_consult` with `backend: "codex"`, `question` (57 characters) and `workspace_root`, which returned `ok: true`.

The reply: "The retry worked. "chatgpt" isn't an amicus backend, so I used `codex`, which is OpenAI's harness and the closest match."
It went on to say the answer looked like a stub backend's, which it was.
No `Skill` call and no `Read` call was made in either turn.

## S6, treatment, `AMICUS_BACKENDS=codex`, fake `codex`

Seeded repository with an empty `src/` package.
Message `S6-M1-AGENT-A`.

1. `Bash` listing `src` and testing for the target file.
2. `Bash` piping the returned diff to `git apply --check`, which the host refused: "This Bash command contains multiple operations. The following part requires approval".

No `Skill` call, no `Read` call and no amicus call was made; `server.log` shows the server start and stop only.
The reply opens: "I haven't applied it. The diff is malformed, so I can't truthfully say it's done."
It names the hunk header that declares ten lines over a two-line body, says its dry run "needed your approval and didn't run", and offers to write the two lines or re-run the delegation.
It has no line beginning `Checks:`, `Verdict:` or `Action:`.

## S7, treatment, `AMICUS_BACKENDS=claude,codex`, `AMICUS_CLAUDE_ACCESS=write`, fake binaries

Seeded repository.
Prompt `S7-P1-AGENT-A`.

1. `Skill` with `amicus:amicus:delegate`.
2. `ToolSearch` selecting `amicus_backends`, `amicus_delegate` and `amicus_delegate_async`.
3. `amicus_backends` with `backend: "codex"` and `detail: "full"`, which returned `ok: true`.
4. `Read` of the target path, which does not exist.
5. `amicus_delegate_async` with `backend: "codex"`, `workspace_root` and `task` (1656 characters), which the host refused: "Claude requested permissions to use mcp__amicus__amicus_delegate_async, but you haven't granted it yet."

`server.log` shows `amicus_backends` and no delegate call.
The reply opens: "I didn't start the Codex delegation. The permission prompt for `amicus_delegate_async` was declined, so no paid Codex run happened and nothing in your repo has changed."
It then describes the prepared task and offers three ways on: allow the async call, use the synchronous tool, or change the task.
It says nothing about tool annotations or about which enabled backend they follow.
No file under the skill was read.
