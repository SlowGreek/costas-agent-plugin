# Prompt template — outdated-closure batch (backlog cleanup with proof)

Closes `OUTDATED` backlog items the RIGHT way: not by asserting "this looks already-fixed," but by
**proving** it with a repro test that PASSES on the target branch — then batching the proofs into one
draft PR that links + auto-resolves the work items. Runs as a **mode of the Implement loop**, fed by
Triage's `OUTDATED-candidate` dispositions. The payoff: a stale backlog gets cleaned *with evidence*,
and the proof tests stay behind as regression guards.

The discipline: an `OUTDATED` disposition is a **claim** until a test proves it. This mode turns
claims into proof — and catches the claims that are wrong (the bug is still live → re-route, don't
close).

**GOAL GUARD note:** unlike the other prompt templates in this directory, this file has no fenced
dispatch block of its own — it is an orchestrator-run, multi-stage recipe (the EM/orchestrator itself
runs STAGE 2 onward, one build at a time, per §8). It never needs its own GOAL GUARD text because it
never hands a raw sub-agent prompt to anyone: STAGE 1's only dispatched workers are `engineer-charter.md`
makers, which already carry the GOAL GUARD. Only the root orchestrator (the session that acquired the
repository lease) may run `/goal` for this workflow.

---

## The workflow (one Workflow run)

INPUT: the set of `OUTDATED-candidate` items (id + the bug's repro / expected behavior). TARGET =
`{TARGET_REMOTE}/{TARGET_BRANCH}` loaded from the codebase adapter, via the pinned target worktree
(refresh that exact target first).

**STAGE 1 — parallel (the thinking):** one code-only maker per candidate writes a repro test for its
item — a test asserting the bug's *expected (fixed)* behavior on the **real** path. Makers fan out
concurrently in isolated worktrees (`engineer-charter.md`); they do NOT run builds.

**STAGE 2 — ONE batched classification run (the scarce resource):** collect every test onto
ONE branch (`ai/outdated-closure-<date>-<digest>`, the documented batch exception
to the normal `ai/wi-<id>-*` convention) off the target. Dedup existing closure
PRs by the complete linked-WI set plus the `outdated-closure` label/title. The EM
runs a **single** build/test invocation over all
of them — never N concurrent builds (they deadlock on the daemon/restore; §8). This is a
**classification run, not a green gate**: mixed exit status is expected. Record a durable per-test
outcome (pass / still-reproducing failure / compile-or-unprovable), even when the aggregate command is
nonzero. If output is piped, preserve the raw status and results; never let a nominal zero hide a test
failure or a nonzero prevent classification.

**STAGE 2b — bounded SERIAL diagnostic passes when the batch won't even run:** an **aggregate compile
error** (as opposed to an individual test failing) can hide every candidate's per-test outcome at once —
none of them classify because the batch never produced a test binary. When that happens, do NOT fan out
concurrent builds to diagnose it. Instead run bounded, SERIAL diagnostic passes, one build at a time:
read the compiler's own file/line error locations, identify which candidate test addition(s) they point
at, remove or mark those specific additions as `compile-or-unprovable` (return their WIs to normal
triage per STAGE 3), then rerun the shrinking classification batch. Repeat one pass at a time, capped at
**one diagnostic pass per remaining candidate** (never unbounded retries), until the batch build is
runnable (produces real per-test outcomes) or no candidates remain.
**UNATTRIBUTABLE ERROR (the loop-forever hazard):** the compiler's file/line location does not always
resolve to one specific candidate — an ambiguous, cross-cutting, or shared-file error can leave the
diagnostic pass unable to name which addition(s) are at fault. Do NOT guess, and do NOT retry the same
unattributable error hoping the next pass clarifies it: the moment one diagnostic pass cannot attribute
the error to a specific subset of the still-remaining candidates, mark **every** remaining candidate in
that batch `compile-or-unprovable` in that same pass, return all of their WIs to normal triage, and STOP
the diagnostic loop immediately — even though the batch was never confirmed runnable. This still
terminates within the existing per-candidate pass cap (an unattributable pass consumes the rest of the
budget at once instead of leaving it to spin), and it guarantees STAGE 2b always terminates in bounded
passes: it never loops forever, and it never opens a PR from an ambiguous or partially-diagnosed batch.
Once the shrinking batch is runnable, proceed to STAGE 3 classification as normal. A whole-batch
unattributable exit instead leaves an empty candidate set and skips STAGE 3 — STAGE 3 never sees an
unrunnable batch.

**STAGE 3 — partition by result:**
- Test **PASSES** on target → the bug is genuinely gone → **CONFIRMED OUTDATED** → keep the test (now
  a regression guard) + queue its WI for closure.
- Test **FAILS** on target → the bug is **still live** → the "outdated" claim was wrong → remove that
  test addition from the candidate branch and **return the item to normal triage** as `VERIFIABLE`.
  This is the load-bearing safety check — it stops you closing a still-broken bug.
- Test **won't compile / can't be asserted headlessly** → `NEEDS-QA` or `NOT-ACTIONABLE` per the
  taxonomy; remove its test addition from the candidate branch, return it to normal triage, and
  disposition honestly. Never count an unprovable item as outdated.

**STAGE 4 — confirmed-only green gate + draft PR:** after removing every non-confirmed test addition,
rerun **only the confirmed-outdated passing tests** and require that rerun to exit 0. If no confirmed
tests remain, do not open a PR. Then run the **style review + security review** on the closure branch
(yes, even a test-only PR — §5 steps 5–6; this was an explicit requirement). Every confirmed-outdated
item already carries a **live, submitted WI** from Triage — that WI-existence bar is a precondition for
this stage, not a substitute for authority. Invoke the global two-phase canonical `branch-ownership`
procedure for the closure PR: the pending reservation records the target source repository, exact
absent head ref/class, every live submitted WI, evidence, and BOTH persisted `initial_push` and
`open_draft_pr` grants. A lone `open_draft_pr` grant never supplies push authority. Preflight all
prerequisites, perform exactly one initial push, immediately open ONE **DRAFT** PR, and bind immutable
identity/URL; freeze all mutation and escalate on bind failure. Later mutation requires the bound live
source/head match and applicable push/update authority:
- Title: `chore(outdated): close N already-fixed bugs with regression proofs`.
- **Links every CONFIRMED-OUTDATED work item**; on merge they auto-resolve via the tracker's PR→WI
  transition (Fixed / By Design as appropriate).
- Body, per item: the WI id + its proof test + "passes on `<target>@<sha>` → already fixed."
If either transport grant or any live WI is missing, do not push or open: persist a complete drainable
`outdated-closure-escalated` prepared handoff (the PR title, full per-item body, confirmed-outdated WI
list, missing prerequisite, escalation target/status/time) on the canonical backlog under a valid
lease and escalate it; never claim the closure PR was opened. Confirmed closure WIs already exist, so
this mode never substitutes a new unrelated WI for one.

**TRIGGER:** put the PR up as soon as there is **≥1 confirmed-outdated** item — the goal is to *drain*
the stale backlog, not to batch for batching's sake — but DO bundle everything that validated together
in the same round into the one PR. Cap a single PR at **~10–15 WIs** so review stays manageable; spill
the rest to the next PR.

OUTPUT: honest counts — confirmed-outdated (→ which closure PR), re-routed-to-`VERIFIABLE`, and
un-provable (with each one's disposition). **Never report an item closed without its passing-on-target
test.**

---

## Why prove instead of assert
- A reasoned "this is probably fixed" closes real bugs that only *look* fixed (the data path changed,
  not the bug). The passing-on-target test is the only thing that distinguishes the two.
- The proof test is not throwaway — it's a permanent regression guard against the bug returning.
- The same run that proves the outdated ones **flushes out the mis-labelled live ones** (fail on
  target → VERIFIABLE), which is exactly the backlog hygiene you want.
