# ADR 0012: What the M6 packaging milestone decided

**Status:** Accepted (2026-09-07, M6)

## Context

M6 makes amicus installable and migratable.
It adds both host manifests with `env_vars` generated from the declarations, a router skill and seven per-verb commands, a test-asserted `docs/MIGRATION.md`, a third-party backend proven to load from a real out-of-tree wheel, install smoke captured from both target hosts, and the agent-friendly-mcp review walk answered with real cold-start and first-repair probe evidence.
No new runtime subsystem: everything either generates from an existing declaration or exercises an existing seam from outside for the first time.
The maintainer approved decisions 1–5 in the 2026-09-07 planning session; 6–10 are the planner's rulings on questions the spec leaves open.
The maintainer separately authorized a spend of six paid calls — one per enabled backend per host — after a Codex review showed that three could not cover both hosts.

## Decisions

- **Packaging goes as far as release automation, unpublished, and the publish workflow is a separate plan.**
  Manifests, wheel and install smoke land in M6.
  The publish workflow and its TestPyPI dry run are `docs/superpowers/plans/2026-09-07-amicus-publish-workflow.md`, executed after M6 merges, because the execution model's rule 5 (one plan, one draft PR) and rule 6 (`.github/workflows/**` changes are their own reviewed PR) together forbid a milestone plan producing that change.
  Neither plan publishes to PyPI; the trademark clearance the README names is still open and is maintainer-only.
- **Commands are per-verb with the backend as an argument** — `/amicus:consult`, not `/amicus:codex:consult`.
  The tool surface's premise is that the backend is a parameter; the command surface says the same thing and stays fixed-size as backends are added.
- **Eval fixtures are a scenario file plus a harness protocol, with a subset hand-run.**
  Scenarios that are specified but not executed are marked unrun in `skills/collaborating-with-amicus/tests/scenarios.md`, never quietly counted as passing.
- **`docs/MIGRATION.md` carries three things per sibling:** the env-var mapping (generated, test-asserted), the tool-name map, and the behavior deltas a migrating user actually hits.
- **The cold-start and first-repair probes are captured from the real host installs, not simulated.**
  `review-workflow.md:31` permits simulated evidence; the maintainer chose captured.
- **The cold-start probe and the authorized paid consult are the same event.**
  A fresh host context meeting the installed server, asked a natural-language task, choosing a tool and calling it, is simultaneously the install smoke and the cold-start evidence.
  A cold-start probe measures a specific host's agent, so the two hosts cannot share calls.
  Each run enables exactly one backend via `AMICUS_BACKENDS`, which is what makes the routing assertion gradable.
- **Task 2's manifest smoke is a hard precondition for Task 8.**
  The precondition is the subprocess smoke of the manifest's own command line, not the in-process boot check: an in-process `create_app()` reads no manifest and so cannot fail for a bad command, a missing console script or malformed JSON.
- **The annotation-friction capture is a probe inside the install smoke, not a separate exercise.**
  ADR 0001's consequence — Claude enabled means codex-only calls carry mutation-grade annotations — is observable as host approval behavior in the same session that runs the other probes.
- **The wheel fixture lives in `tests/fixtures/fakebackend/` and is built at test time**, not committed as a `.whl`.
  A committed binary would rot against the `hatchling` config and could not prove the current build path works.
- **The wheel test asserts a negative control.**
  A wrong `api_version` in the installed wheel must produce `UnavailableBackend(reason="api_version")`.
  Without it, an entry-point group that silently scanned nothing would look exactly like success.
- **One surface bump (`amicus/0.1/schema-6` → `schema-7`), from the review walk's fix wave only.**
  `amicus_capabilities` gains `result_format`, the persisted job-result version this release reads, because `job_result_incompatible` was a published error code about a number that appeared on no agent-visible surface.
  Every pin moved with it in a dedicated commit (rule 10): three manifest snapshots and their hashes, the three per-profile surface digests, the wire-shape and result-format snapshots, and `test_discovery_cost`'s `MEASURED`.
  `RESULT_FORMAT` stays `2`: no stored job result changes shape, so rule 11 does not fire.
- **The walk's other eight findings are fixed without moving the surface**, four of them in the router skill's text.
  The graded failures are left recorded as failures; the remedy is skill text a future run would pass on, never an edited assertion.
- **S1 is 4 of 6, with two runs unscored — not 6 of 6 "passing on intent".**
  Branch A of S1 permits `amicus_backends` before the paid call and nothing else; runs 4 and 5 opened with `amicus_capabilities`.
  An earlier ruling in this milestone scored them as passing on intent with the deviation named.
  The maintainer overrode that on 2026-09-07: amending an assertion after the run it would grade is the failure mode the scenario file exists to prevent, so those two runs are unscored — neither pass nor fail — and branch A is not widened.
  Both rows and their full ordered call lists stay in the Run log so any reader can re-grade them against either wording.
  Widening branch A remains available to a future round, taken before the runs it would grade.
- **S2 is `partial`, not `pass`.**
  Its one run used an unsupported `backend_options` key rather than either invalid call its Setup declares, so the repair was by key removal.
  That leaves the "corrected value drawn from `error.repair.arguments` or `invalid_arguments[].allowed_values`" half of its second assertion never exercised, because a removal repair carries no `allowed_values` list.
  The declared invalid-backend case (`backend="chatgpt"`) is rejected before dispatch and is therefore runnable for free; it is left to a future round rather than claimed as covered.

## Known gaps

These are stated rather than hidden, and carried to M7.

- **The standing cold-start regression gate is NOT built.**
  `design-workflow.md` Step 9 describes a gate that measures cold-start behavior on every change.
  M6 captured the evidence and pinned no baseline against which a future change is measured.
  A later change could regress first-call success and nothing in CI would notice.
- **`tests/test_discovery_cost.py` ratchets the TOKEN COST of discovery, which is a different measure from first-call success.**
  It is not coverage of the latter, and a green run there is no evidence that an agent picks the right tool.
  Its own docstring now says so, and names the captured host evidence that scopes it: Codex CLI 0.153.4 preloads the catalog and pays the tax the budget assumes, while Claude Code 2.1.263 defers MCP tool definitions behind a `ToolSearch` lookup and does not.
  The budget stays the worst-case ceiling for clients that do preload.
- **Tag resolvability is unproven.**
  The committed `.mcp.json` names `git+https://github.com/briandconnelly/amicus.git@v0.1.0`, a tag that will not exist until release.
  Task 2's manifest smoke and every host capture substituted a locally built wheel for that one `--from` argument, leaving every other field of the committed command line unchanged.
  What the tag itself resolves to is therefore not proven by M6; it is the publish workflow's gate.
- **The review walk is a checklist review, not a behavioral gate.**
  Its findings are pinned only insofar as `tests/test_review_artifact.py` enforces the artifact's shape — every §1–§9 section accounted for, both mandatory probes carrying captured evidence, every finding carrying its five labeled lines.
  That instrument checks the walk was performed and recorded in the required shape; it cannot check that the walk's judgments were correct.
- **`tests/test_review_artifact.py`'s own guarantees are narrower than they look, and one known hole is left open.**
  This is the previous gap sharpened, not a second one: the file verifies that a finding's five labels are PRESENT, not that they say anything.
  A finding whose severity, section, summary, evidence and remediation values are all blank still passes `test_every_finding_carries_all_five_labeled_lines`, confirmed by mutation.
  The hole is recorded rather than fixed, deliberately: four other holes in this same file were found and closed during M6 — two by tracing the briefed parser before it was committed, two by mutating the walk document afterwards — and unbounded mutation-testing of every remaining assertion was judged past the point of diminishing returns for this milestone.
  Four holes in one file is also the reason to treat its guarantees as narrow rather than as a proxy for the walk's quality: read a green run as "the artifact has the required shape", never as "the artifact is any good".
  A future reviewer tightening this file should start by mutating the assertions that were never mutated.
- **An un-migrated host may still prefer a sibling server.**
  The walk's one Major finding is that a cold start with the maintainer's real MCP fleet loaded reached a rival second-opinion server and never called amicus.
  `docs/MIGRATION.md` now tells a migrating user to remove the siblings; naming the superseded servers inside `CAPABILITY_SUMMARY` would put the signal on the surface itself and is deferred to M7, because it costs another fingerprint bump.
- **The review walk's F3 remedy passed one run and is not confirmed; F2's is untested.**
  S6's first remedy — an ordering directive in prose — failed three runs on the same assertion.
  A Codex review of the whole branch then found the grader was also implicated: the assertion was applied to the entire harness transcript, so the `LOAD` line the harness itself demands could supply the deciding "apply" token.
  Both were changed for the fourth run: the remedy became a required output SHAPE (a `Checks:` block over `fidelity`, `scope`, `checks-run`, `consistency`, then a labelled `Verdict:` line) and the grader was scoped to a defined `RESPONSE` section.
  That run passed (`docs/host-captures/s6-response-contract/claude-code/2.1.263/`), and the capture records the control: graded the old way the same response would have been a fourth failure.
  Two variables moved together in one run, so this is a direction, not a settled result, and the finding is carried to M7 rather than closed.
  S7's remedy (SKILL.md rule 5) could not be tested at all, because it needs a real host approval gate and the paid budget is gone.
- **S8's pass rests on a call the server would reject.**
  The described `amicus_consult` call put the log text in a `prompt` field, which is not one of that tool's parameters.
  The secret-absence assertion is a substring check and held regardless, so the verdict stands, but a call that could not have been made is weaker evidence of what the model would have put in `question` than a schema-valid one.
  S8 gained a schema-validity assertion binding future runs; the logged run is on record as not meeting it.
- **Rule 6 names seven prompt carriers and one scenario covers three of them.**
  SKILL.md rule 6 now enumerates `question`, `task`, `target`, `evidence`, `extra_context`, `instructions_append` and `focus`, matching AGENTS.md rule 18 plus the two carriers `amicus_adversarial_review` requires.
  S8 exercises the three `amicus_consult` carries.
  `task`, `focus`, `target` and `evidence` have no scenario; the adversarial pair is the gap most worth closing, since its prompt text is required rather than optional.
- **`.codex-plugin/plugin.json` declares `"skills": "./skills/"` and no capture ever loaded a skill on the Codex host.**
  Every Codex CLI run in this milestone was baseline mode — no amicus skill staged — so the Codex host's skill-loading path is declared and unexercised, exactly as the git tag is declared and unresolved.
  Whether that host discovers, loads, and acts on `collaborating-with-amicus` is unproven by M6.
  A free treatment-mode run on the Codex host would settle it and is carried to M7.
- **The paid budget is exhausted.**
  Six calls were spent, all on cold start, three per host.
  No later probe in this milestone could re-run a paid path, which is why the long-running-operation probe and a live redaction trace are both recorded as skipped.

## Open questions

- **AGENTS.md rule 18 does not say whether it binds test fixtures as well as runtime prompt handling.**
  Rule 18 reads "Never write a prompt input (`question`, `task`, `extra_context`, `instructions_append`, `focus`) to disk, to a worker's argv or to a log; it travels over the worker's stdin."
  `skills/collaborating-with-amicus/tests/scenarios.md` commits synthetic prompt text, including S8's fabricated credential strings, and every host capture quotes scenario prompts.
  Read literally the rule covers those; read as a runtime egress rule — which is what its second clause is about — it does not.
  The milestone proceeded on the second reading and the scenario fixtures stay committed, which is the maintainer's 2026-09-07 ruling.
  The defect is the ambiguity, not the fixtures.
  The fix is a governance PR narrowing rule 18's wording to runtime prompt handling, and rule 9 forces that into a PR of its own, so it is recorded here rather than done inside this milestone.

## Consequences

- amicus installs from both host manifests, and a third-party backend distribution loads through the `amicus.backends` entry-point group without living in this tree.
- A migrating user has a generated, test-asserted env mapping that cannot drift from the declarations, and a tool map for all three siblings.
- The surface identity moved once and deliberately, and a client cached at `amicus/0.1/schema-6` can detect it from `amicus_capabilities` alone.
- The next milestone inherits two measurement gaps that are recorded rather than closed: no standing cold-start gate, and no proof that the release tag resolves.
