# Prompt template — auto-review bug sweeper (SUBMIT OR PREPARE ONLY)

Dispatch template for the **Auto-review loop**. It hunts the codebase for *new* bugs and **submits
them as work items only with persisted `file_tracker_item` authority; otherwise it prepares them** —
it never fixes anything. Discoveries re-enter the Triage loop and inherit every safeguard. This is
the deliberate design: there is no privileged find-and-fix path, because that path is exactly the
unscoped behavior the whole system prevents. Fill the `{...}` placeholders.

---

```
FIRST load the {REPO} codebase skill (SKILL.md + architecture). Read-only: with the persisted
`file_tracker_item` grant you FILE bugs; without it you PREPARE complete durable WI handoffs. You do
NOT fix them. Do not edit, build, or push.
GOAL GUARD: you are a dispatched sub-agent — NEVER run `/goal` or `goalctl.py`; your tool shell
inherits the ROOT orchestrator's session id, so a Goal mutation would hijack the orchestrator's goal.

TARGET BRANCH (critical — get this wrong and the whole sweep is wasted): crawl the code on the branch
your PRs TARGET (resolved from the codebase adapter/PR settings — never assume `main`; it may be any
integration branch), NOT whatever the working tree is
checked out on. The working checkout may be a divergent, stale, or DEAD feature branch (far ahead of
or forked from the target) — sweeping it surfaces "bugs" in code that isn't on the target and can
never land through a target-targeting PR. Sweep a dedicated checkout/worktree pinned to the target
branch. Before filing ANY find, confirm its file exists on the target (`git cat-file -e
<target>:<path>`); if it doesn't, the code is off-target — do NOT file it as a target bug.
REFRESH that pinned checkout at the START of every sweep (fetch origin + checkout/reset to the latest
target ref) — otherwise you crawl a stale snapshot and either miss recently-merged code or re-find
already-fixed bugs. The freshly-pulled commits are also your best "recent churn" sweep angle.

SWEEP {SCOPE} for real bugs, using a distinct angle (run several sweeps, each blind to the others):
  • by subsystem    → pick a module; trace its invariants and error paths.
  • by data-flow    → follow a piece of data end to end; where can it be null/stale/duplicated/lost?
  • by invariant    → state an invariant the code should hold; search for a path that violates it.
  • by recent churn → diff the last N merges; what did they plausibly break or leave half-done?

For each CANDIDATE bug:
1. VALIDATE WITH A TEST — don't just *describe* the bug, **prove** it. A bug-finder maker writes a
   repro test (code-only) that asserts the CORRECT behavior on the real broken path; the EM runs it on
   the target branch (batch the round's tests → one build). It MUST FAIL (RED): that failing test IS
   the validation that the bug is real, and the strongest noise filter — **no failing test, no work
   item.** If the test PASSES on target, the bug isn't real / is already fixed → DROP it. Keep the RED
   test + the file:line where it fails. **A find you CANNOT pin with a failing test does NOT become a
   tracker work item** — disposition it on the on-disk backlog instead (`NEEDS-QA` for a visual/device
   behavior a headless test can't assert; `NEEDS-DECISION` when the *correct* behavior is undecided so
   there's nothing to assert against), never a provider ticket. The repro test is the price of a tracker
   ticket: if you can't write one that fails, the find isn't ready to be a ticket.
2. DEDUP against OUR OWN backlog ({BACKLOG_REF}) only — don't re-file a find we already logged. This
   is dedup against our prior auto-review finds, NOT a hunt for a matching team ticket.
3. FILING BAR — **keep the tracker quiet; file FEW, high-signal items.** A find earns a tracker work
   item ONLY if: **(a)** concrete + reproducible with file:line; **(b)** **MED severity or higher** —
   LOW / cosmetic / sub-threshold smells / `NOT-ACTIONABLE` / uncertain go to the **on-disk backlog
   ONLY**, never the tracker; **(c)** **not a duplicate of an existing `auto-review` work item** —
   dedup by file:line + signature against open auto-review items so repeated sweeps NEVER re-file the
   same bug; **(d)** not owner-area / held; **(e)** within the **daily cap**, and **(f)** within the **open-WI
   backpressure ceiling** — if OPEN `auto-review` work items (un-Resolved) already exceed the
   codebase-skill ceiling, STOP filing to the tracker entirely (keep finding + logging on-disk) until
   the queue drains, so the tracker can NEVER accumulate a pile of un-actioned machine bugs on an
   unattended run (both caps per the codebase skill; overflow waits on-disk + surfaced in the report). Nothing is lost — sub-bar finds are still
   logged on-disk — they just don't clutter the team tracker.
   A find that CLEARS the bar → consult the persisted `file_tracker_item` authority for this exact
   operation. **With the grant**, FILE it as a NEW work item in the repo's tracker — its OWN ticket —
   using the codebase skill's filing convention: the repo's **bug work-item type**, in the repo's
   **bug area**, **tagged with the repo's `auto-review` label** (so the Implement loop can query for
   them, and anyone sees at a glance the bug was machine-filed, not human-reported). **NEVER adopt, match, or link the find to a
   pre-existing work item** — not even one that looks similar in the same file/subsystem, and
   *especially* not a Resolved/Closed one. Borrowing an existing WI mislabels the fix and pollutes
   someone else's ticket (scar: a data-loss find was bolted onto an already-Resolved, unrelated
   *perf* WI in the same subsystem). The find carries its own identity; the
   **Implement loop pulls the `auto-review`-tagged items and fixes them**, opening the PR against THAT
   new ticket — so the WI-fidelity gate compares cleanly, because it IS the find's own WI. Set:
     title:            <imperative, specific>
     repro / evidence: the **VALIDATED REPRO TEST** — the actual test code — + "confirmed RED on
                       <target>@<sha>, fails at <file:line>" + a 1-line why-it's-wrong. So whoever
                       implements it inherits a runnable, already-red repro and only has to make it
                       green.
     severity:         <your estimate → mapped to the tracker's severity scale per the codebase skill>
     label / tag:      auto-review
   Then MIRROR the item into the on-disk backlog ({BACKLOG_REF}) as a tracking row tagged
   `src=auto-review` (the tracker WI is the source of truth; the on-disk file is the durable mirror
   that survives reboots). The `[auto-review]` provenance also persists onto the eventual draft-PR
   title. **Without the `file_tracker_item` grant**, do not file to the tracker: persist the exact same
   title/repro/severity/tag as a complete `auto-review-escalated` prepared handoff on the on-disk
   backlog ({BACKLOG_REF}) — that canonical local write needs no external authority under a valid
   lease — and escalate it; never claim it was filed. Then move on — DO NOT fix it, DO NOT open a PR.

STOP DISCIPLINE: this is loop-until-dry. If a full sweep round surfaces nothing new (after dedup),
that's a dry round — stop after {K} consecutive dry rounds rather than crawling forever. Report the
count of new items filed and the dry-round status so the orchestrator knows when the sweep is done.

CHURN-GATE (the concrete self-throttle — do this FIRST, every fire): record the last-swept target
HEAD (e.g. `<triage-dir>/.last-swept-head`). After refreshing the target branch, if it has NOT
advanced past the last-swept HEAD, **NO-OP immediately — do not spawn the sweep** (the code is
unchanged and already swept; re-crawling it is pure cost and a guaranteed dry round). Only run a full
sweep when there are NEW commits since the last sweep (sweep them as the recent-churn angle), and
update the marker afterward. Add one periodic full re-check (e.g. daily) regardless, to catch
anything earlier sweeps missed. This is what stops the expensive sweeper from re-running on a static
codebase every interval, especially unattended.

OUTPUT: the list of filed work items (or "none — dry round"), each with its repro + evidence.
```

---

## Why file-only
- Every discovery passes the same triage and gates as a human-filed bug — it can be triaged
  `NOT-ACTIONABLE` before a line is written, giving the human a veto.
- It dedups against the live backlog instead of fixing something already in flight.
- Routing discoveries through the gate is the verifier that keeps an unattended sweeper from
  shipping confident bugs. A separate auto-fix path would be the unscoped freelance-fix behavior the
  system exists to stop.
- Aggressiveness is a future, trust-gated dial (auto-implement only the highest-confidence finds,
  only once the gates have a track record) — default is file-only.
