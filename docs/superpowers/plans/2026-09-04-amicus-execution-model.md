# amicus execution model: one plan per milestone, executed by Opus/Sonnet agents

The spec above is not executable as written: it names interfaces and gates, not steps.
Each milestone gets its own implementation plan in the `superpowers:writing-plans` format
(bite-sized TDD steps with the actual test and implementation code in every step), and
an agent executes that plan with `superpowers:subagent-driven-development` or
`superpowers:executing-plans`. Part 3 is the first such plan and the template for the rest.

**Rules for whoever writes a milestone plan (Opus recommended; Sonnet executes):**

1. Write it from this spec plus the sibling source it ports; store it at
   `~/projects/amicus/docs/superpowers/plans/YYYY-MM-DD-amicus-M<n>-<slug>.md` — in the
   amicus repo only, including the plan for any pontonier work (pontonier's AGENTS.md
   forbids restating rules that have a home, and its sdist would ship a tracked plan;
   the M-1 review established this). Until the amicus repo exists (M0 Task 1 creates
   it and copies this spec to `docs/superpowers/specs/2026-09-04-amicus-design.md`),
   the plan lives in this file. Every plan's header links the spec.
2. Every port task names the sibling file and line range being ported, writes the
   differential test **first** from the sibling's current behaviour, then copies and
   adapts the code. No task may reference a type or function that is not defined in the
   spec's interface blocks or in an earlier task's "Produces" block.
3. Every task ends with an independently runnable test command and a commit.
   Snapshot or fingerprint regeneration is always its own commit.
4. The plan's last task runs the milestone gate from the table above, including the
   perturbation check, and records the result in the PR description.
5. One plan produces one draft PR (`gh pr create --draft`); the human reviews and merges.
6. Plans may not touch `.github/workflows/**`, `CODEOWNERS`, or `AGENTS.md` as a side
   effect; those are separate reviewed PRs.
7. Before handing a plan to Sonnet, run the writing-plans self-review: spec coverage,
   placeholder scan, type consistency.

**Definition of done for a milestone:** the gate is green in CI on the draft PR, the
perturbation check is recorded, and the human has merged.

**A plan is deleted once it has been executed and merged.** Git history keeps every
line. A finished plan left in the tree reads as live instructions: in M7 a reviewer
found the plan still teaching a release sequence that had been superseded within the
same PR, which an agent reading it top-down would have followed. The durable record of
what was decided is the ADRs under `docs/adr/`; the durable record of what was built is
the code and the git log.

---
