# Prompt template — CI / flaky-test health loop

Dispatch template for the **CI-health loop** (`DESIGN.md` §4.8). The whole system is *a verifier
wrapped around a maker*, and every gate trusts one signal: the test result. The design already guards
one direction — **green ≠ correct** (a passing build is necessary, never sufficient). This loop guards
the other, quieter direction: **red must mean real, and green must mean safe.** A *flaky* test breaks
both — a flaky **red** makes a maker chase a phantom or a reviewer bounce a good change; a flaky
**green** (the more dangerous one) lets a real regression through because an intermittently-passing
test happened to pass on the one run that gated the push. A flaky verifier is worse than no verifier,
because it is trusted.

This loop mines CI/pipeline history for tests that are **non-deterministic on identical code**, then
submits authorized or prepares de-flake WIs and gated quarantine drafts (never a silent skip) so each
flake re-enters Implement like any other bug. Fill the `{...}` placeholders.

---

```
FIRST load the {REPO} codebase skill (SKILL.md + the exact test/build recipe + the CI host) and the
persisted authority configuration. Read-only on code by default: each external operation requires its
own configured grant (`file_tracker_item`, `initial_push`, `open_draft_pr`, `send_alert`, later
push/update, or tracker update). Default conservative mode prepares complete artifacts and escalates;
it submits nothing externally.
GOAL GUARD: you are a dispatched sub-agent — NEVER run `/goal` or `goalctl.py`; your tool shell
inherits the ROOT orchestrator's session id, so a Goal mutation would hijack the orchestrator's goal.

SOURCE — pipeline/run history, not a single run: pull the last {N} CI runs per test from the host
(`ado-pipelines_*` / `gh run list` + per-run test results). You are looking for DISAGREEMENT ON
IDENTICAL CODE.

DETECT — a test is a FLAKE CANDIDATE only if it shows BOTH outcomes on the SAME commit SHA (a
pass and a fail across runs/retries of one sha), or fails then passes on a bare re-run with no code
change. Rank candidates by flake-rate × blast (how many distinct PRs/branches it has red-flagged).
  Signals worth capturing: order-dependence (fails only in certain shard/parallel orders), timing
  (sleeps, real clocks, timeouts), shared fixture/DB state, network/external calls, randomness without
  a pinned seed.

THE FALSE-QUARANTINE GUARD (critical — this cuts the dangerous way):
  "It's flaky" is a CLAIM, and the tempting-but-catastrophic move is to quarantine a test that is
  actually catching a REAL, intermittent product bug (a genuine race condition), thereby deleting the
  one signal that was doing its job. So:
    • Require ≥{M} observed runs with BOTH outcomes on the SAME sha before calling a test flaky. One
      failure is not a flake — it is a failure until proven otherwise.
    • A test that is CONSISTENTLY red (fails every run on a sha) is NOT a flake — it is a real failure;
      route it to Triage as a normal bug, NEVER quarantine it.
    • If the "flake" reproduces a real intermittent PRODUCT defect (the non-determinism is in the code
      under test, not the test harness), the fix is to the PRODUCT — file it only when persisted
      `file_tracker_item` authority grants that exact operation, otherwise prepare/escalate the bug;
      DO NOT quarantine (quarantining would hide a live race). Quarantine is only for non-determinism
      in the TEST itself.

ACT — for each CONFIRMED test-harness flake:
  1. If persisted `file_tracker_item` authority grants it, FILE the de-flake work item FIRST (its own
     ticket, tagged `ci-health`) carrying the two
     contradictory runs (sha + run ids + the pass and the fail), the suspected root cause
     (order/timing/state/net), and a note that the quarantine PR is pending. This preserves the hard
     invariant: no submitted PR without a live tracker item. Otherwise prepare this complete WI as a
     durable `ci-health-escalated` handoff with requested operation + escalation target/status/time.
  2. QUARANTINE transport invokes the global two-phase canonical `branch-ownership` procedure. The
     de-flake ticket must now be a live submitted WI linked to the future PR, and BOTH persisted
     `initial_push` and `open_draft_pr` grants must be recorded in a pending reservation for the target
     source repository and exact absent head ref/class with WI + evidence. A lone `open_draft_pr` grant
     never supplies push authority. Preflight all prerequisites, perform exactly one initial push, open
     the DRAFT PR immediately, and bind immutable identity/URL. Freeze all mutation and escalate if
     binding fails. Later mutation requires the bound live source/head match and applicable push/update
     authority. If any bar is missing, add the complete quarantine diff to the same drainable
     prepared/escalated WI handoff and do not push or open. A submitted quarantine still lands only on
     human authority. Quarantine is a stop-the-bleeding holding action, not a fix.
  3. Update a submitted work item with a submitted quarantine backlink only when the persisted exact
     update authority grants it. It re-enters Triage → Implement writes the deterministic fix and lifts
     the quarantine in the same fix PR.
  4. Broader CI health (report-only, no code change): flag build-time regressions, a rising overall
     failure rate, and any breach of the build-result gate (§8 — a pipeline masking the build
     command's nonzero status); surface these in the digest, don't fix them here.

DEDUP: don't re-file a flake already tracked (match by test id + signature) or re-open a second
quarantine PR for the same test.

CHURN/COST: only re-mine when there are NEW CI runs since the last pass (record `.last-ci-scan` =
last run id); a static run history is a NO-OP. Keep the heartbeat coarse.

CURRENT-FIRE COMPLETION: for every confirmed flake, report the authority-permitted submitted WI/draft/
alert artifact(s), or in conservative mode the durable `ci-health-escalated` prepared handoff. Never
claim a prepared artifact was submitted. OUTPUT: those dispositions with contradictory-run evidence, or
"CI healthy — no confirmed flakes".
```

---

## Why this protects everything else
- **The verifier's verifier.** Every other loop's trust bottoms out in "the test said so." If the
  test is non-deterministic, the adversarial gate, the WI-fidelity gate, the regression gate, and the
  post-merge sentinel are all reasoning on noise. This loop is the one that keeps the signal clean.
- **Flaky green is the silent killer.** A flaky *red* is annoying but visible. A flaky *green* passes
  a real regression with confidence — the exact "ships a bug with confidence" failure the whole system
  is built to prevent, sneaking in through a trusted gate. That is why quarantine requires a submitted
  or prepared fix WI and doesn't just mute: a muted flake is a coverage hole.
- **The guard is the point.** The dangerous failure of THIS loop is quarantining a real intermittent
  bug and calling it flaky. The ≥{M}-both-outcomes bar and the "consistently-red ≠ flake" rule keep it
  from lobotomizing its own test suite. Quarantine narrowly (test-harness non-determinism only), file
  the product-race bugs.
