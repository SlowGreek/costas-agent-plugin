# Autonomous Prod-Repo Maintenance Workflow — Design

A self-running system that keeps a production repository healthy: onboard once, then a small
set of standing loops continuously **triage the backlog**, **fix the testable items behind
gated draft PRs**, **maintain those PRs**, and **surface new bugs** — every change routed
through one gated pipeline, with a human only at the escalation boundary.

This document is the design. The companion `SKILL.md` is the runnable orchestrator that
executes it. It is written to be **repo-agnostic**: the loops, gates, and taxonomy are the
*harness*; a per-repo *adapter* (a codebase skill + a build recipe + an ownership boundary) is
the only thing you re-derive per repo.

---

## 0. Core thesis — a verifier wrapped around a maker

> "You shouldn't be prompting coding agents anymore. You should be designing loops that prompt
> your agents." — Peter Steinberger
>
> "An unattended loop without a verifier is a machine that ships bugs with high confidence."

The whole system is **loop engineering**: a recursive goal + a way to find work + act + verify
+ remember. The hard part is *verify*. Two distinct failure classes have to be defended
against, and they are not the same:

1. **Ships a bug with confidence** — the classic "no verifier" failure. Defended by a
   maker/verifier split: a green build is necessary, never sufficient; an independent skeptic
   must try to *refute* every change before it ships.
2. **Ships the *wrong fix* with confidence** — the failure we actually hit in production. The
   fix was correct, well-tested, and green — but it solved a *different* problem than the one
   filed (an adjacent bug, or a reframed version of the ticket). A correctness verifier *passes*
   this. It took a human asking "did this fix the bug that was actually filed?" to catch it,
   twice.

**Design consequence:** the maker (the implementing agent) *will* drift, over-reach, or declare
false defeat. The loop's entire job is to make the maker's "it's done" mean something. Every
rule below exists to close one specific way a maker's "done" lied to us.

---

## 1. System at a glance

```
            ┌─────────────────────────── PHASE 0: ONBOARD (once per repo) ───────────────────────────┐
            │  /repo-learn → codebase skill · crack the build (runnable red/green) · seed backlog   │
            └───────────────────────────────────────────────────────────────────────────────────────┘
                                                     │
                                                     ▼
                       ┌──────────────  THE BACKLOG  ──────────────┐   ← single locked source of truth
                       │  every item carries: id, disposition,     │
                       │  proof/why, owner-lock, links, evidence   │
                       └───────────────────────────────────────────┘
        ┌──────────────────────┬─────────────────────┬────────────────────────┬────────────────────────┐
        ▼                      ▼                     ▼                        ▼                          │
   ┌─────────┐          ┌────────────┐        ┌──────────────┐        ┌──────────────────┐               │
   │ TRIAGE  │          │ IMPLEMENT  │        │ PR-MAINTAIN  │        │  AUTO-REVIEW     │               │
   │  loop   │  ──────► │   loop     │ ─────► │   loop       │        │ (bug sweeper)    │               │
   │ sorts + │   feeds  │ fixes the  │ submits│ comments +   │ submit/│ finds NEW bugs   │ ──────────────┘
   │ maintains│  testable│ testable  │ /preps │ WI-fidelity  │ prepare│ SUBMIT/PREPARE   │   feeds backlog
   │         │  items   │  via gates │  PRs   │ verifier     │  WIs  │ (never auto-fix) │
   └─────────┘          └────────────┘        └──────────────┘        └──────────────────┘
        ▲
        └────────── new items (from engineers' discovered-issue protocol + the sweeper) ───┘

   Shared by all loops: the codebase skill · maker/verifier split · the disposition taxonomy ·
   durable state · the human-escalation boundary · cost/stop discipline.
```

The defining architectural choice: **there is exactly one pipeline, and many sources feed it.**
Filed tickets, reviewer comments, and auto-discovered bugs *all* enter as backlog items and *all*
pass the same triage and the same gates. There is no privileged "find and fix it now" path —
that path is precisely the unscoped behavior that produces wrong fixes.

Beyond the original four, four more standing loops (all §4) hang off that same one pipeline — two new
**sources** that only *file* into the backlog (a dependency/supply-chain sweeper §4.7, a CI/flaky-test
health loop §4.8) and two new **verifiers** that guard the far end (a post-merge regression sentinel
§4.9, a self-improvement loop §4.10 that feeds the system's own lessons back into the harness). The
rule holds for every one of them: no privileged fast path — everything through triage and the gates.

---

## 2. Phase 0 — Onboard (once per repo)

Three steps, in order. Do not start a loop until all three are done.

1. **Run `/repo-learn` → a codebase skill.** Architecture map, conventions (DI/state/logging
   idioms), build/test/deploy commands, PR & branch policy, and the gotchas. Every agent in
   every loop loads this skill *first*, before doing anything. This is the per-repo *adapter*.

2. **Crack the build — the highest-leverage hour you will spend.** Get a *single unit test to run
   red/green from an agent-controlled checkout*. Until red/green actually executes, every fix is
   reasoned-not-verified and every staleness check is unreliable — the entire pipeline's value is
   gated on this. Bake the exact working recipe (flavor, env, wrapper, isolation quirks) into the
   codebase skill so no agent re-derives it. **This is a hard gate: no triage-to-action until a
   test runs.**

3. **Seed the backlog source of truth — and make it durable.** Pull every existing work item /
   issue into the one backlog store. Each row gets: `id`, `title`, `disposition` (initially
   untriaged), `proof/why`, `owner-lock`, `links` (PR, branch, WI), `evidence`, `source`
   (filed / reviewer / sweeper). **Critical:** the in-session task list is *ephemeral* — it does
   not survive a session exit or a machine reboot (learned the hard way: a remote reboot wiped the
   entire task-list backlog mid-run). So the **authoritative copy lives in a file on disk**
   (`<triage-dir>/backlog.md` or `.json`, append-only history preferred); the task list is a
   working *mirror* of it, and every disposition write updates the file, not just the list. See §7.2.

---

## 3. The disposition taxonomy — the heart of triage

Every backlog item resolves to exactly one disposition. **Each disposition requires a specific
artifact** — a disposition without its artifact is not done; it is a guess.

| Disposition | Meaning | **Required artifact (no artifact → not done)** |
|---|---|---|
| `OUTDATED` | Already fixed / no longer reproduces | **Proof:** a repro test that *passes on the current `{TARGET_REMOTE}/{TARGET_BRANCH}` today*. Write the test, run it red-first; if it passes pre-fix, the item is outdated — attach the test as proof, then close. |
| `NOT-ACTIONABLE` | Cannot be done as a bounded code change in this repo | **Why:** out-of-repo (name the system that owns it) / no safe bounded change exists / **the data or signal it assumes does not exist** (see §5 feasibility check). |
| `NEEDS-QA` | Real, but its load-bearing behavior is a rendered layout / device setting / visual that a headless test cannot assert | **The check:** the exact on-device / visual verification a human must run. Do **not** touch the code; hand QA a precise script. |
| `VERIFIABLE` | Real, and a logic/test can prove the fix | → enters the **Implement loop**. |
| `NEEDS-DECISION` | Real, but the right fix needs a product call or is a larger cross-cutting change | **The question:** the specific product/architecture decision required. Escalate; do not guess a smaller fix and let the real one rot. |

Rules:
- **Most of a stale backlog is not "fix the code."** Expect the bulk to land in `OUTDATED` /
  `NOT-ACTIONABLE` / `NEEDS-QA`. Reporting those faithfully, *with their artifact*, is a correct
  result and is what makes an unattended run trustworthy — not a failure to find work.
- **Staleness gate first.** Before anything else, write the repro test and run it against the current
  `{TARGET_REMOTE}/{TARGET_BRANCH}`.
  Backlogs accrete faster than they close; assume an item is already fixed until a red test
  proves otherwise. This single gate reclassifies a large fraction of items.

---

## 4. The standing loops

Each loop has: a **trigger**, a **unit of work**, the **gates it runs**, and an explicit
**drain/done condition**. All loops read and write the one locked backlog. Six form the original core
(§4.1–4.6); four extend it (§4.7–4.10) — two new **sources** that only ever file into the same backlog
(dep-sweep, ci-health) and two new **verifiers** that watch what the per-PR gates cannot (post-merge
integration, self-improvement). No loop gets a privileged path; every find routes through Triage and
the same gates.

### 4.0 How a loop runs — goal-driven, with a cron heartbeat

A loop is **not** a bare timer-cron that re-does a fixed action every N minutes. It is the **native
`/goal`** (a recursive goal with explicit success criteria) **with a recurring cron attached** as a
heartbeat:

- **Native `/goal` drives to done.** The goal *is* the loop's done-condition (the **Done** line in
  each loop below). `/goal` sets a session Stop-hook that blocks the agent from stopping until the
  success criteria are met, then **auto-clears** — it does not stop half-drained. This is "work until
  the backlog is triaged," not "do one pass."
- **The cron is the re-check heartbeat.** Once the goal is achieved the loop **goes quiet** (no cost).
  The attached recurring cron re-fires every interval, **re-checks whether the goal still holds**
  (new items? a new reviewer comment? a fresh bug from the sweeper?), and **re-engages the goal only
  if there is work.** Achieved + nothing new = the cron does a cheap no-op and goes back to sleep.

So a loop's life is: **drive to done → go quiet → cron re-checks → re-engage on new work → drive to
done again.** The goal gives a real success condition (so "done" means something and it stops
manufacturing work — §10); the cron gives it a pulse (so it notices new work without a human). This
is the concrete mechanism behind "drain detection" (§7) and "know when you're done": `/goal` is the
*know-when*, the cron is the *check-again*.

| Loop | Goal (success criteria) | Cron heartbeat (re-check cadence) |
|---|---|---|
| Triage | every item has a disposition **+** its required artifact | frequent (new untriaged items arrive often) |
| Implement | every unlocked `VERIFIABLE` item **without an existing PR** has a gated draft PR linked to its WI | on new `VERIFIABLE` items |
| PR-maintenance | every actionable comment has a current durable review-handoff artifact; each PR is WI/gate checked | periodic (e.g. hourly) |
| Auto-review | a full sweep has filed all new bugs (loop-until-dry, K empty rounds) | periodic re-sweep / after large merges |
| PR-review (learned) | every targeted PR has advisory findings vs. the team profile; the profile is current | Review: per targeted PR; Refresh: weekly |
| Report (digest) | the period's digest exists, with its learning items extracted | daily / every 2 days |
| Dep-sweep | every *reachable* vuln/stale dependency is filed (loop-until-dry) | daily (or on advisory-feed / lockfile change) |
| CI-health | every confirmed flake has authority-permitted submitted artifacts or a durable prepared/escalated handoff | hourly (after CI runs) |
| Post-merge | every current entry is PASS, `regression-filed` with an active linked WI, or `regression-escalated` with a durable handoff; every target advance reruns EVERY retained entry | hourly (after merges land) |
| Self-improve | every *converged* report-learning has a draft PR on its artifact | weekly |

**Cadence by cost.** Set each heartbeat by what a *no-op* fire costs, not by impatience. Cheap-when-
idle loops (triage, implement — essentially a backlog read) can fire often (e.g. every ~30 min) to
cut filing→PR latency. An *expensive* heartbeat — the auto-review sweeper spins a heavy background
crawl every fire — should be infrequent (hours) and **self-throttle**: once it hits dry-twice,
downgrade it to a cheap "did new code land?" churn-check instead of re-crawling clean subsystems.

### 4.1 Triage loop
- **Trigger:** new untriaged items (from filing, the sweeper, or engineers' discovered issues), on
  a schedule.
- **Work:** classify each untriaged item into the §3 taxonomy, attaching the required artifact.
  Run the staleness gate and the feasibility pre-check (§5) here.
- **Done:** no untriaged items remain. Then go quiet.
- It is the **backlog reviewer**: every new bug — filed by a human, by an engineer's
  discovered-issue protocol, or by the sweeper — lands here and gets a disposition before any code
  is written.

### 4.2 Implement loop
- **Trigger:** `VERIFIABLE` items with no owner-lock **and no open PR**.
- **PR-existence pre-check (first, always — no duplicate PRs).** Before claiming an item, query the
  repo's open PRs for one already covering this work item. Resolve the provider's
  live WI/issue relationship and compare the PR diff against the repro. The
  `ai/wi-<id>-*` branch convention is supporting evidence, not a requirement;
  teammate and human branches count. If one exists: record the link, set the
  item's state to `IN-REVIEW`, hand it to PR-maintenance (§4.3), and **do not
  open a second PR.** Only an item with no covering PR proceeds. The batch form is
  `ai/outdated-closure-<date>-<digest>`; dedup those PRs by their complete linked-WI set plus the
  `outdated-closure` label/title.
- **Work (per surviving item, fanned out in parallel via workflows):** claim/lock → repro test
  (red-first on the real broken path) → TDD to green → style review → security review → **adversarial
  gate** → **WI-fidelity gate** → **draft PR linked to the work item**. Every agent loads the codebase
  skill first.
- **Global PR transport invariant — two-phase branch ownership before mutation:** every
  automation-created PR uses this procedure: implementation, outdated closure, CI quarantine,
  self-improve artifact, and post-merge revert draft. No specialized loop bypasses it. A provider
  cannot have a live PR before the remote head exists. Before branch creation/adoption, persist a
  `branch-ownership` **pending reservation** in
  the canonical backlog/append-only log: canonical source repository identity; exact intended head ref
  and branch class; a live submitted WI; creation/adoption evidence; and BOTH the persisted
  `initial_push` (push) grant and the persisted `open_draft_pr` grant. If the WI is missing, submit it
  only with persisted `file_tracker_item`; otherwise prepare/escalate the WI and diff without remote
  mutation. A live PR is not required before the initial push, but both exact grants and the WI are:
  `initial_push` granted alone must never authorize the push —
  a pushed remote head this automation cannot then cover with a DRAFT PR (because `open_draft_pr` was
  never granted) would orphan that branch. A lone `open_draft_pr` grant never supplies push authority
  either. A preflight re-check immediately before executing the push reconfirms both grants and the
  live submitted WI still hold. The pending record permits **exactly one** initial
  push only if the remote ref is absent and the reservation matches. Immediately create a DRAFT PR and
  bind that record to immutable provider identity/URL. If PR API creation still fails unexpectedly,
  freeze further branch/remote mutation and create a cleanup/retry escalation. Every later push/rebase/update
  requires a **bound** record matching the live PR source repository and exact head ref plus applicable
  persisted push/update authority. A branch name is never proof of ownership.
  Explicit human adoption creates this record only through prepare/confirm authority, never by inference.
- **Makers are code-only and strictly scoped** (§6). The orchestrator owns builds and landing (§8).
- **Outdated-closure batch:** its first batched **classification** run classifies per-test results; mixed status is expected
  and is not a green gate. If an **aggregate compile error** (rather than a
  per-test failure) hides every candidate's outcome, run bounded SERIAL diagnostic passes — never fan
  out concurrent builds — using the compiler's file/line locations to remove/mark the offending
  unprovable test addition(s) one pass at a time, capped at one pass per remaining candidate, and rerun
  the shrinking batch until it is runnable or no candidates remain. **If a diagnostic pass cannot
  attribute the compile error to specific remaining candidate(s)** (an ambiguous or cross-cutting
  location), it must not retry the same unattributable error: mark every still-remaining candidate
  unprovable in that pass, return all their WIs to normal triage, and terminate the diagnostic loop
  immediately — this stays within the existing pass cap and guarantees the loop never spins forever or
  opens a PR from an unresolved batch. Once runnable through successful attribution, remove still-reproducing,
  failing, and unprovable test additions from the candidate batch and return their WIs to normal triage.
  A whole-batch unattributable exit leaves no candidates and skips classification. Re-run only retained confirmed-outdated passing
  tests and require exit 0 before opening a PR; none retained means no PR. Every confirmed item already
  carries a live submitted WI from Triage, but closure transport still invokes the global two-phase
  `branch-ownership` procedure and requires BOTH persisted `initial_push` and `open_draft_pr` grants;
  the latter alone is never push authority. Without every prerequisite, persist a drainable
  `outdated-closure-escalated` prepared handoff instead of pushing or opening the PR.
- **Done:** no unlocked `VERIFIABLE` item lacks an open PR or its durable prepared/escalated handoff in
  conservative mode.

### 4.3 PR-maintenance loop  *(= the standing PR steward + WI-fidelity verifier)*
- **Trigger:** **every open PR for our work items** — including ones this run did not create
  (pre-existing, teammate-opened, or carried over from a prior run; this is the dedup target handed
  over by §4.2) — plus any new reviewer activity, on a schedule.
- **Work — for each open PR, keep it comment-clean, WI-faithful, and good:**
  - **(a) Comments** — classify each, then act:
    - **Bot / style nit / preference we disagree with** → create a durable review-handoff artifact
      (`thread/comment ref`, `draft text`, `recommended resolution`, `escalation target`, `escalation
      status`, `escalation time`), then prepare the reply and escalate it; never post the reply or
      resolve the thread autonomously. This artifact is not a provider-thread tail, and the loop must
      never claim the draft appears in the provider thread.
    - **Test/coverage request** → dispatch a scoped engineer to add it on an owned branch and verify it;
      landing (pushing the update / merging it in) requires the persisted exact `land` grant like any
      other landing action — with it, land; without it, leave the verified addition ready on the owned
      branch (never merged) and note that in the handoff. Either way, create/update the review-handoff
      artifact and escalate the reply (never post it autonomously).
    - **Human correctness-or-scope challenge** ("why is X the solution?", "this isn't what the WI
      asks") → **do not glib-reply.** Run the WI-fidelity verifier (below); if it fixes the wrong
      thing, rework (or revert + re-file), then **create/update the review-handoff artifact with the
      finding and escalate the reply** (never post it autonomously).
    - **Bot findings cut both ways.** A bot/CI comment is a free adversary (it surfaces real gaps —
      see (c)) but it also *false-positives*. Run the same WI-fidelity check before acting on a
      bot-flagged "gap": one we hit was a bot flagging "the WI also asks for X" when X was a
      *deliberate, WI-recorded decision* — the gate's answer was document-and-recommend-closing
      (escalated), not implement.
    - **Resolve vs. leave open — a recommendation, never an autonomous action.** Update the
      review-handoff artifact with a resolve-or-leave-open recommendation and escalate it; a human
      resolves/closes the thread. Recommend closing when the human's ask is fully met or they asked to
      close; recommend leaving it Active when you've answered an *open analytical question* and the
      human should get the last word. **Every outward-facing reply, comment, and thread resolution —
      bot, style, preference, or substantive — is prepared and escalated; the loop will never post,
      send, or resolve a thread itself.**
  - **(b) WI-fidelity (proactive)** — confirm the PR actually does its linked work item (diff vs. the
    work item's **repro steps, not its title**) on **every** open PR, not only when a human challenges
    it.
  - **(c) Quality (proactive)** — ensure the PR has cleared the gate bar (style · security ·
    adversarial); if a carried-over/teammate PR never went through the gates, run them now. Fix findings
    only on an owned branch; for an external branch, prepare the remediation and escalate it to the owner.
  - **(d) Freshness (proactive) — keep the PR mergeable, but only on branches this automation owns.**
    An open draft rots as the target branch moves under it: the base drifts, conflicts accrue, and its
    gates were run against a now-stale tree. Before refreshing a PR on a branch this automation might
    own (`ai/wi-*`, explicit `ai/outdated-closure-*`), verify the durable `branch-ownership` record in
    the canonical backlog/log against the live PR's source repository identity and exact head ref.
    The allowed branch pattern alone is insufficient; an unrecorded or mismatched branch is read-only.
    For a verified owned branch, keep it rebased on the current PR-target, and **re-run the repro +
    the regression gate (§5.4) after any non-trivial rebase** — a clean *textual* rebase can still be
    *behaviourally* broken by what landed underneath it (this is the pre-merge echo of the §4.9
    post-merge sentinel). For a deduped **teammate/human/external branch, stay read-only**: monitor its
    freshness/CI/reviews and prepare a concrete patch/rebase/fix recommendation for the branch owner,
    then escalate it — never push or mutate their branch. Keep such an item `IN-REVIEW`/blocked with the
    handoff recorded rather than pretending it was refreshed. A PR that cannot be cleanly refreshed is
    surfaced, never force-landed.
- This is the standing replacement for the human reviewer who caught these — and it covers the PRs the
  Implement loop *didn't* create (the dedup target), so nothing open goes unstewarded.
- **Done:** every new actionable comment has a current review-handoff artifact with an escalated
  status and every open PR is WI-faithful and gate-checked. Owned branches are current only after the
  durable ownership record verification; external branches have freshness findings and the owner
  handoff recorded.

### 4.4 Auto-review loop (bug sweeper) — **SUBMIT OR PREPARE ONLY**
- **Trigger:** schedule (and/or after large merges).
- **Work:** crawl the codebase hunting for *new* bugs (multi-modal: by subsystem, by data-flow, by
  invariant, by recent churn). For each candidate: consult the persisted `file_tracker_item` grant for
  this exact operation. With the grant, **file a work item** with a concrete repro + evidence; without
  it, persist a complete `auto-review-escalated` prepared handoff on the canonical backlog under a
  valid lease (no external authority needed for that local write) and do not submit externally — never
  claim a prepared find was filed. **It never fixes anything.** Dedup against the existing backlog
  before filing.
- **Why submit-or-prepare-only:** the discovery re-enters triage as a submitted WI or a drainable
  prepared handoff — it inherits every
  safeguard, gives the human a veto (a discovery can be triaged `NOT-ACTIONABLE` before a line is
  written), and avoids the exact unscoped "find-and-freelance-fix" behavior the system exists to
  prevent. Routing every discovery through the gate is what makes the loop's output trustworthy.
- **Stop discipline:** loop-until-dry — stop after K consecutive rounds surface nothing new;
  do not crawl infinitely.

### 4.5 Report cadence (daily / every 2 days)
A reporting digest *over* the work loops — it observes, it does not act on the repo.
- **Trigger:** a daily or bi-daily cron (a cadence, not a drain loop). **Goal:** the period's digest
  exists, with its learning items extracted.
- **Work (read-only over the backlog + durable log + PR reviewer threads for the window):** produce a
  bundled report (`prompts/report.md`) with —
  - **By the numbers:** items filed / triaged / handled by disposition; draft PRs opened & landed;
    sweeper finds; reviewer comments received (human vs bot) / replied / reworked; the pr-review **profile refresh** (the week's `review-profile` CHANGELOG diff).
  - **Gate catch-rates:** WI-fidelity, adversarial, feasibility, and staleness-OUTDATED catches — a
    high catch-rate is the system working, not failing.
  - **Human feedback worth learning from** *(the highest-value section):* each substantive human
    reviewer comment → the pattern → a **concrete improvement to the codebase skill, a gate, or a
    prompt** (a scope challenge the gates missed → strengthen which gate; a repeated style nit → add
    it to the codebase skill; a domain fact → fold it in). Recurring patterns flagged as priority.
  - **Issues & friction:** an honest self-report of what struggled (build hangs, undispositionable
    items, "can't-be-done" verdicts that needed re-tracing, repeated gate send-backs) — skips and
    failures included, not hidden.
  - **Needs the human:** the NEEDS-DECISION / NEEDS-QA queue + pending landing approvals + open
    escalations.
  - **Trend / next:** backlog burn-down vs. inflow, catch-rate & revert-rate trend, rough cost, focus.
  - **Metrics substrate + degradation alarm:** the *By-the-numbers* counts are appended to a durable
    per-run series (`<triage-dir>/metrics.jsonl`), so the trend line is **computed, not eyeballed** — the
    report reads history instead of re-deriving it each period. On top of the series sits a **degradation
    alarm:** a threshold-cross on the signals that mean the system is getting *worse* — revert-rate
    climbing, WI-fidelity/adversarial catch-rate falling (gates going blind), inflow outpacing burn-down
    for N periods, or a loop that filed/handled **nothing** across its expected cadence (a silent-death
    tell, §7.3) — escalates as a NEEDS-DECISION, never buried mid-digest. A metric moving the wrong way is
    the earliest signal the harness needs a human; surface it loudly.
- **Delivery is authority-gated and best-effort; the digest *file* is the source of truth.** Write the
  digest to disk first. Sending it anywhere is outward-facing communication exactly like a post-merge
  or CI-health alert, so it is gated on the persisted `send_alert` authority (§9) — not a free action
  every fire performs regardless of configured authority. **With the grant**, *attempt* to notify the
  human (email/DM); notification must **degrade gracefully** — a missing/expired auth token (or, as we
  hit, an *expired tenant*) makes the send fail, and that must be a clean, distinct "skipped" exit,
  never a hang or a loud loop failure. Never let the notifier fall into a blocking interactive re-auth
  in a headless run. Delivery auto-resumes when auth is restored; until then the file + in-session
  surfacing carry it. **Without the grant** (default conservative mode), never attempt delivery: prepare
  the exact notification text and escalate it instead of sending it — never claim it was sent.
- This is the system's **accountability + continuous-improvement** layer: it closes the loop between
  human feedback (the ground truth) and the harness getting better. When a learning **recurs** across
  reports, the **self-improvement loop (§4.10)** turns it into a gated draft PR against the artifact — so
  the digest's highest-value section stops being advice a human must hand-apply and becomes a reviewable
  change. (The report *finds* the lesson; self-improve *acts* on the converged ones.)

### 4.6 PR-review loop (learned, team-specific reviewer) — **advisory, prepare-and-escalate**
A fifth work loop, added after the original four: it learns the team's *demonstrated* review standards
from merged PRs and applies them as an evidence-based, advisory review layer — the **learned**
counterpart to the static style review (§5, step 5). Prompt: `prompts/pr-review.md`; artifact:
`review-profile.template.md` → the per-repo `review-profile.md`. (Distinct from the §4.4 auto-review
*bug sweeper* and the §4.3 *comment* steward — this is the learned outbound-standards layer.)
- **Two rhythms (cadence-by-cost, §4.0).** **Review** is cheap (apply the profile to one PR's diff) →
  runs per targeted PR alongside Implement / PR-maintenance. **Learn/Refresh** is expensive (fan-out
  over the N most-recently-merged PRs) → a **weekly** cron, like the sweeper.
- **Learn — two corpora.** Fan out (Workflow) over (i) the {N=100} most-recently-**merged,
  human-authored** PRs into the default branch (the *style-exemplar* corpus) and (ii) human review
  comments across PRs **merged *and* open** (the *preference* corpus). Mine the team's demonstrated
  standards — recurring asks + how they resolved, bounce triggers, test/coverage expectations,
  conventions enforced in review but not by lint/CI, fast-merge vs. many-rounds. Synthesize an
  evidence-backed `review-profile.md` — every rule cites the PRs it came from, tagged
  must-fix / nit / signal.
- **The echo-chamber split (load-bearing).** Mine **preferences/asks** from human comments across PRs
  merged *and* open — *including humans' comments on our own `ai/wi-*` bot PRs* (which rarely merge, so
  the richest "humans correcting the machine" feedback is on open drafts — best alignment signal, zero
  circularity). Mine **style exemplars** from the **merged, human-authored** corpus only — never treat
  the system's own bot diffs as "good examples." Distinguish human reviewers from an automated AI-review
  bot (lint-like findings, not preference). Weight by review engagement.
- **Review.** Apply the profile to a PR → findings tied to evidence ("your team asks for this in PRs
  #X/#Y"), must-fix vs. nit. **Scope is chosen at setup** (`our-draft-PRs-only` default ·
  `all-open-team-PRs` · `both`). For our PRs, findings are an **advisory** input to the Implement /
  PR-maintenance gate — they do **not** block. For others, comments are **prepared and escalated** to
  the human, **never auto-posted** (§9).
- **Refresh.** The weekly cron maintains a separate merged-PR style cursor plus
  review-comment cursors **per immutable PR id**. **Resume before capturing anything new:** if a
  persisted prior scan snapshot/high-watermark has a non-empty pending-PR set, that scan is INCOMPLETE
  — drain it against the SAME snapshot/high-watermark first (retry each pending PR until it is
  processed or explicitly dispositioned with provider evidence; a failed/inaccessible PR stays pending
  and is retried on every later refresh — never dropped silently, and a PR that closes or unmerges
  mid-scan is dispositioned with its final-state evidence rather than silently losing its comments).
  Only once that pending set is drained does it capture the NEXT fixed eligible-PR snapshot
  and one provider comment high-watermark, seeding a fresh pending set from that snapshot. For each snapshot PR, it polls events newer than that PR's
  cursor and no newer than the high-watermark, advancing only that PR (and clearing it from the pending
  set) after successful processing;
  later comments wait for the next refresh. It advances the style cursor only after that source and merges
  changes into the profile **fully autonomously** (no approval gate) — but every
  change is appended as a dated CHANGELOG diff, and pinned rules plus codebase
  conventions are sacrosanct. A refresh where both sources add no rule is dry.
- **Learn/review against the default branch only** — merged PRs are target-grounded by construction, so
  the reviewer never learns from (or reviews) dead working-branch-only code.
- **Not** security / correctness / WI-fidelity / lint (those are the §5 gates) — this is the
  taste/convention layer only, and it **augments** the static style review, it does not replace it.
- **Done:** every targeted open PR has advisory findings against a **current** profile; the profile is
  refreshed within its cadence.

### 4.7 Dependency-sweep loop (supply-chain sweeper) — **SUBMIT OR PREPARE ONLY**
The §4.4 sweeper aimed at a second surface: not our code, but the **dependency surface** — lockfiles,
manifests, the transitive tree. Prompt: `prompts/dep-sweep.md`.
- **Trigger:** schedule, with **two churn sources** — a changed lockfile/manifest *or* a newly published
  advisory against an unchanged set (a CVE can land with zero code change, so the churn-gate keys on
  {lockfile-hash + advisory-feed cursor}, never HEAD alone).
- **Work:** audit the target-branch lockfile with the ecosystem's tool (`npm audit` / `pip-audit` /
  `govulncheck` / `osv-scanner` / the host advisory feed). Two find-classes — **SECURITY** (a CVE/GHSA/OSV
  affecting a version we resolve) and **HYGIENE** (deprecated / abandoned / hopelessly-behind). For each,
  consult the persisted `file_tracker_item` grant for this exact operation: with the grant, **file a
  work item** with the advisory id, our resolved-vs-fixed versions, and a **reachability proof**;
  dedup, tag `dep-sweep`, mirror to the backlog. Without the grant, persist a complete
  `dep-sweep-escalated` prepared handoff on the canonical backlog under a valid lease and do not submit
  externally — never claim a prepared advisory was filed. **It never bumps a version.**
- **Reachability is the noise filter** (the load-bearing rule). A CVE against a package we depend on but
  never *call on a vulnerable path* is **not** a work item — it is the dep-sweep analog of an auto-review
  find with no failing repro test (log it on-disk as `dep-unreachable`, never the tracker). This is what
  keeps the loop from becoming the wall-of-red dependency-bot noise the team learns to mute.
- **Why file-only:** a bump is one of the highest-blast-radius changes there is; routing it through Triage
  lets a human veto a breaking major (`NEEDS-DECISION`) and forces the fix through the gates — the
  **regression gate (§5.4)** especially, since a green audit says nothing about whether the bump breaks *us*.
- **Done:** every reachable advisory + every MED+ hygiene item is filed (or has a durable
  prepared/escalated handoff in conservative mode); loop-until-dry (K empty rounds).

### 4.8 CI-health loop (flaky-test sentinel)
The verifier's verifier. Every gate in §5 trusts one signal — the test result — and the design guards
*green ≠ correct*; this loop guards the other direction: **red must mean real, and green must mean safe.**
A flaky test breaks both, and a flaky *green* is the silent killer — it passes a real regression through a
trusted gate, the exact "ships a bug with confidence" failure sneaking in the back door. Prompt:
`prompts/ci-health.md`.
- **Trigger:** new CI runs (schedule after CI activity); NO-OP on a static run history.
- **Work:** mine the last N pipeline runs per test for **disagreement on identical code** — a pass and a
  fail on the *same commit SHA* (or fail→pass on a bare re-run). Rank by flake-rate × how many PRs it
  blocked. For each confirmed flake, submit the de-flake WI first only with persisted
  `file_tracker_item`; otherwise prepare it and do not transport a PR. A quarantine invokes the global
  two-phase canonical `branch-ownership` procedure: the live submitted WI and BOTH persisted
  `initial_push` and `open_draft_pr` grants are mandatory, and a lone `open_draft_pr` grant never
  supplies push authority. Missing prerequisites produce a drainable prepared WI + quarantine-diff
  handoff. Backlink, alert, and later bound-source/head mutation each require their applicable exact
  update/push authority. The flake then re-enters Implement and a submitted quarantine is lifted in the
  same fix PR.
- **The false-quarantine guard** (the load-bearing rule — it cuts the dangerous way): "it's flaky" is a
  *claim*. Require ≥M observed both-outcome runs on one SHA before quarantining; a **consistently-red**
  test is a real failure, never a flake; and if the non-determinism is in the **product** (a genuine
  race), file the product bug only with persisted `file_tracker_item` authority, otherwise
  prepare/escalate it — do **not** quarantine (that would hide a live race). Quarantine is for
  test-harness non-determinism *only*, or the loop lobotomizes its own suite.
- **Done:** every confirmed harness-flake has the authority-permitted submitted artifact(s), or a durable
  prepared/escalated handoff; broader CI health (build-time regressions, the §8 build-result gate
  integrity) is surfaced in the report.

### 4.9 Post-merge regression sentinel
Every §5 gate runs *before* the merge, but the **land is the human's call** (§9) and two failures appear
only *after* it, on the integrated branch no per-PR gate ever saw: a **semantic conflict** (two PRs each
green alone that break each other once both land) and a **fix that didn't stick** (a later merge reverted
or shadowed it). This loop is the integration-level counterpart to the WI-fidelity gate — WI-fidelity asks
"does the diff fix the filed bug?"; the sentinel asks "did it **stay** fixed after landing?" Prompt:
`prompts/post-merge.md`.
- **Trigger:** any target-branch advance while the persistent landed-repro
  registry is non-empty, or a **tracked maintenance fix merges** — ours (`ai/wi-*`) or a
  teammate/human/external branch the dedup gate (§4.2) accepted for a durable-backlog item. NO-OP only
  when the target SHA is unchanged and no new fix needs registering.
- **Work:** load the exact `{TARGET_REMOTE}/{TARGET_BRANCH}` target from the codebase adapter, enroll every durable-backlog maintenance item that just landed through a verified covering
  PR — ours (`ai/wi-*`) or a deduped teammate/human/external branch — and add its validated repro to
  `<triage-dir>/landed-repros.json` (scope to backlog items with a verified linked PR/WI + a validated
  repro; never sweep arbitrary team work). A deduped external fix is retained and rerun exactly like an
  agent-authored one. Then on the **current integrated target** re-run **EVERY retained** validated repro,
  including previously PASS and red entries. PASS updates its last-verified SHA and retention counters;
  it does not immediately drop the proof. Retain entries for at least 90 days and
  20 later target advances by default. **RED → current regression episode:** key it by original WI +
  repro + red target SHA + suspect merge. Dedup only to an **ACTIVE live** regression WI for that
  episode; a closed/resolved historical WI never completes it. Reopen only if provider policy and
  persisted `reopen_tracker_item` authority allow; otherwise file a new episode only with
  `file_tracker_item` authority, or persist `regression-escalated` with a complete prepared WI/alert
  handoff, and record `last_checked_target_sha`. Set `regression-filed` only with an active linked WI. Submit alerts only with exact
  `send_alert` authority; otherwise prepare/escalate them again. Also alert/escalate immediately if the
  target's own build broke right after a tracked fix landed.
- **Detection only; a revert is not routine.** Reverting a landed, human-approved merge is an irreversible
  shared-state action. An optional revert draft uses the active regression WI as its live submitted
  WI and invokes the global two-phase canonical `branch-ownership` procedure, including BOTH persisted
  `initial_push` and `open_draft_pr` grants; the latter alone is never push authority. Missing
  prerequisites leave a drainable prepared regression-WI + revert-diff handoff. A submitted DRAFT is
  escalated, never applied by the loop (§9). A found regression re-enters the one pipeline as a normal
  gated fix.
- **It reuses the proof we already have:** no new test-writing — the repro that
  gated the fix in remains an active sentinel across later merges.
- **Done:** for the current target, every retained entry is PASS, `regression-filed` with an ACTIVE
  linked WI, or `regression-escalated` with a durable prepared/escalated handoff. Every later target
  advance reruns **EVERY retained entry**, including prior PASS and red entries: recover a red entry to
  PASS with evidence, or update its current episode and alert/escalate again. Completion is never an
  all-green-only requirement.

### 4.10 Self-improvement loop — **prepare-and-escalate**
The Report cadence (§4.5) already produces the pack's highest-value output — human feedback and the
system's own friction, each distilled into "a concrete change to the codebase skill, a gate, or a prompt."
But that sits in a digest until a human hand-applies it, so the same reviewer comment recurs and the same
gate keeps missing. This loop closes the continuous-improvement loop the design aspires to: it turns the
report's **converged** learnings into **submitted WI + gated draft pairs, or prepared WI + diff
handoffs, against the artifacts themselves.** Prompt:
`prompts/self-improve.md`.
- **Trigger:** weekly (aligned with the report / pr-review refresh), or a report flagging a recurring
  priority; NO-OP when nothing has converged.
- **Two target surfaces:** the per-repo `<repo>-codebase` skill (repo-specific lessons, covered by the
  loop's existing repository lease) and the **harness pack itself** (a gate/prompt/taxonomy that missed —
  improving it for every repo it runs on), which lives in its **own, different repository**.
- **Cross-repo lease (harness-pack target only):** the harness repo is not the repo this loop is running
  in, so it has its own canonical identity and its own `runtime/maintenance_lock.py` state — the
  current repo's lease/token never covers a write there. Resolve the harness repo's own identity
  (`repo_identity.py` against its checkout) and acquire/heartbeat/release its own lease before any
  branch/PR/backlog write against it. When both leases are needed at once, acquire them in
  deterministic `repo_id`-sorted order (never out of order — prepare/escalate instead of forcing a
  second acquire against the ordering), heartbeat both before any cross-repo write, and release in the
  reverse order they were acquired. The branch-ownership reservation and the `self-improve` WI for a
  harness-pack change live under the harness repo's own identity/backlog, never the source repo's.
- **Work:** select only learnings that **recur** (across ≥R reports/comments — a one-off is a data point,
  not a rule) and carry **evidence** (the quoted human comment with PR/WI links, or the specific repeated
  friction). For each, create/link a dedicated `self-improve` WI only with persisted
  `file_tracker_item`; otherwise prepare/escalate both WI and diff. With the live submitted WI, invoke
  the global two-phase canonical `branch-ownership` procedure; BOTH persisted `initial_push` and
  `open_draft_pr` grants are mandatory and a lone `open_draft_pr` grant never supplies push authority.
  When every prerequisite holds, open ONE **DRAFT** PR (`self-improve`) with the minimal diff + evidence
  + a **falsifiable expected effect** ("this clause would have caught PR #X"). Dedup vs in-flight
  self-improve PRs. Otherwise persist a complete drainable `self-improve-escalated` prepared WI + diff
  handoff on the canonical backlog under a valid lease and do not push or open.
- **The self-lobotomy guard** (the load-bearing rule): it may **add** a check, add a convention, sharpen a
  prompt, tighten a gate — it may **never weaken, loosen, or delete** a gate, a pinned rule, or a documented
  convention to reduce its own send-backs. "The adversarial gate keeps bouncing my changes, so loosen it"
  is exactly backwards — the bounces are the system working. A relax-a-safeguard PR is allowed **only** when
  a report records an explicit *human* instruction (quoted, linked), never on the loop's own initiative. It
  learns from human feedback and friction, never from the system's own preference for an easier path (the
  §4.6 echo-chamber split, applied to the harness itself).
- **Strict prepare-and-escalate:** a prompt/gate edit changes verification for *every future change* — far
  too high blast-radius to auto-merge. Every self-improvement is a draft PR a human lands, or in
  conservative mode its durable prepared/escalated handoff — never claim a prepared diff was opened (§9).
- **Done:** every converged learning this period has an authority-permitted draft PR on its artifact, or
  in conservative mode its durable prepared/escalated handoff (or the period was quiet —
  itself success: the system has already absorbed its recent feedback).

---

## 5. The gates — the verifier stack

A change is not done because it is green. It is done when it survives the stack. Run in this
order; any gate can send it back.

1. **Staleness / repro gate.** A repro test that *fails red on the real broken path* pre-fix. If
   it passes pre-fix → `OUTDATED`, stop. (A test that passes against unmodified code tested the
   wrong thing.)
2. **Feasibility / data-existence pre-check.** Before committing to a fix, confirm the data or
   signal the fix depends on *actually exists in the real pipeline*, not merely that a test can
   construct it by hand. The "wrong/absent data signal" failure: an item looks testable, a
   hand-built fixture goes green, but the fix is **inert in production because the signal doesn't
   exist** (e.g. a "mute" flag the API never exposes; an unwired button; a query that strips the
   very record the logic keys on). If the signal isn't real → `NOT-ACTIONABLE` / `NEEDS-DECISION`.
3. **TDD to green** on the real firing path (not a helper).
4. **Regression gate.** The change's own repro going green is necessary, not sufficient — the
   **impacted existing suite must stay green** too. Run the tests the diff can plausibly affect (the
   touched modules' suites; the full suite when the blast radius is wide or the suite is cheap), and
   gate on their literal pass: a fix that greens its own test but reds a neighbor is a *regression*,
   sent back. Especially load-bearing for wide-blast changes — a dependency bump (§4.7), a shared-helper
   edit — where the item's repro says nothing about what else moved. (Distinct from the adversarial gate
   below, which *reasons* about refutation; this one just *runs the neighbors*.)
5. **Style review** against the codebase skill's conventions (comment discipline, naming, idioms).
6. **Security review** of the diff.
7. **Adversarial gate** — 3 independent skeptics (correctness · test-validity · edge/security),
   each with a mandate to **refute**, not bless. Required for any stateful / data-source /
   upgrade-path change. A passing build is not enough; this catches data-loss, torn-snapshot,
   wrong-of-two-paths, over-exclusion, and migration-gap bugs that the unit test misses.
8. **WI-fidelity gate** — compare the diff against the work item's **repro steps, not its title**,
   and answer **"does this fix the bug that was actually filed?"** Red flags: the buglog/PR title
   was rewritten to match what the fix does; the new test doesn't reproduce the WI's scenario; the
   diff never touches the path the repro describes; the fix solves an *adjacent* problem in the
   same files. This gate is owned by the PR-maintenance loop (§4.3) and is the single
   highest-value addition over a naive pipeline.

**Maker/verifier separation is law:** the agent that reviews is *never* the agent that wrote the
code; the verifier's job is to refute. "Can't be done / already fixed / no such signal" is itself
a **claim that triggers an independent adversarial re-trace** before it is accepted — especially
when the same agent then conveniently ships an easier adjacent fix.

---

## 6. Engineer scoping & the discovered-issue protocol

The makers must not freelance. This is enforced structurally, not by hope.

- **Charter.** Each engineer is chartered to fix *exactly* its work item's repro. Every changed
  line must trace to that item. Touch only what the fix requires; do not "improve" adjacent code.
- **Discovered-issue protocol.** If an engineer spots an *adjacent* bug, it **does not fix it.**
  It emits a structured **proposed work item** (title + concrete repro + evidence + file:line) and
  returns. The orchestrator **files** that as a new backlog item; it re-enters the Triage loop
  like any other. An adjacent find gets its *own* ticket — never a relabel of the current one.
- **"Can't fix" protocol.** If blocked, the engineer returns *why* (with evidence) — it does **not**
  substitute a different, easier fix under the same work item. A "can't be done" return is a claim
  the orchestrator re-traces independently before accepting it.
- **Smoking gun to watch for.** An engineer rewriting the work item's title/description (in a
  buglog or PR body) to match what it fixed = the ticket was silently redefined to fit the fix.
  The WI-fidelity gate exists to catch exactly this.

---

## 7. Loop coordination & durable state

Ten loops on one backlog will collide unless coordinated.

- **One locked source of truth — and it must be durable.** The backlog is authoritative — not the
  chat, not any agent's memory. But the in-session **task list is a volatile mirror**, not the
  durable record: it is wiped on session exit / reboot. The authoritative copy is a **file on disk**
  (see §7.2); every loop reads and writes that file, and mirrors it into the task list for the live
  session.
- **Ownership / locking.** An item being worked is *owned/locked* so a second loop won't pick it.
  One item → one owner at a time.
- **Repository execution lease.** Before setting `/goal` or reading/writing the
  shared backlog, every loop acquires the cross-process lease implemented by
  `runtime/maintenance_lock.py`. A busy lease is a clean no-op. Long runs heartbeat it, and a
  **pre-write heartbeat gate** runs immediately before every durable/shared/remote write. Any
  heartbeat nonzero/not-owner ends the run before another write; it writes no shared error record and
  emits local/session status only. A nonzero/not-owner release is not success or ownership. This
  serializes repository-scoped Goal state and durable-file updates even when scheduler fires overlap.
- **Idempotency & re-entrancy.** Long autonomous runs get compacted, interrupted, and resumed.
  Every loop must be safe to re-run and able to reconstruct state from the backlog + an append-only
  log. Write the *why* of each disposition down before context is lost.
- **Drain detection.** Every loop has an explicit done condition and **goes quiet** when there's
  nothing actionable. Do not manufacture marginal work to look busy. Recognizing "complete" and
  handing remaining decisions back to the human is part of the job.

### 7.1 Where the loops run

Each persisted workflow fire starts a fresh Copilot session. Independent
analysis may fan out inside that run, but only one maintenance orchestrator may
own a repository at a time:

- Acquire the repository execution lease before loading the backlog into working
  state or setting `/goal`.
- Keep item-level owner locks for fan-out within the lease-owning run.
- Heartbeat the lease before and after long delegated batches **and immediately before every
  durable/shared/remote write**.
- Release it on still-owned success, no-op, blocker, budget exhaustion, and error paths. Treat
  `not-owner`/nonzero release as a local failure, never as a successful release.
- If the lease is busy, exit without modifying Goal, the backlog, branches, or
  remote state. If heartbeat loses ownership, terminate without a shared-state error record, remote
  cleanup, or further write; local/session status only. The next heartbeat will retry.

This intentionally serializes orchestrators while still allowing parallel
read-only analysis and disjoint code-only makers under one owner.

### 7.2 Persistence and restart

Copilot workflow definitions and the on-disk backlog persist; invocation-local
Goal and `todos` state do not.

- **The durable backlog is a file on disk, not the task list.** Keep the
  authoritative backlog as an owned file (`<triage-dir>/backlog.md` or `.json`),
  append-only history preferred. The in-session task list is a working mirror
  rebuilt from that file at each fire.
- **Do not blindly recreate workflows after restart.** Use `list_workflows`,
  update missing or changed definitions by ID, and preserve existing schedules.
  Re-arming every loop unconditionally can create duplicate heartbeats.
- **Rehydrate against reality.** Reload the backlog, query live open PRs and
  tracker items, re-check reviewer threads, inspect the execution lease, and
  resume only after reconciliation. A stale lease may be replaced after its TTL;
  a live lease means another run owns the repository.

### 7.3 Scheduler liveness and auth pre-flight

Persistent definitions are not proof that fires are succeeding. Use workflow
run history plus the durable metrics series as the liveness signal:

- **The scheduler or repeated fires failed and no one noticed.** A dead
  maintainer produces the same surface as a quiet, drained one, so silence is
  ambiguous. An external watchdog checks each workflow's latest successful run
  and the metrics timestamp. Missing more than one expected cadence escalates:
  *"maintenance is down; inspect workflow history and run the §7.2 rehydrate."*
  The watchdog must live outside the workflow it observes.
- **Auth was dead before the work started.** The notifier already degrades on an expired token/tenant
  (§4.5), but the deeper waste is doing a full loop of real work and only discovering at the *push / PR /
  notify* step that the credential expired hours ago. Run an **auth pre-flight** at loop start: cheaply
  confirm the tokens the loop will need (remote push, PR API, advisory feed, notifier) are live **before**
  spending a maker. Dead/expiring credential → surface it as its own clean NEEDS-DECISION and skip the
  doomed run; never fall into a blocking interactive re-auth in a headless loop (the same trap as the
  notifier). Pre-flight turns an expired credential from a wasted loop + a confusing late failure into an
  early, legible "refresh me."

### 7.4 Durable ownership and review-handoff records

The canonical backlog row and its append-only log are the only durable state model. The following are
record schemas within that existing model, not new executable runtime state or a new file format.

- **`branch-ownership` record (two phase):** `record_id`; canonical `source_repo` identity; exact
  intended `head_ref` (including `refs/heads/`); branch class; a live submitted WI; creation/adoption evidence
  (actor, authority event, timestamp, source link); and BOTH the persisted `initial_push` (push) grant
  and the persisted `open_draft_pr` grant. Initially `status=pending` and the remote ref must be absent:
  it authorizes exactly one matching initial push, not a rebase/update, and only once both grants and
  the live WI are confirmed at a preflight re-check immediately before the push — `initial_push` granted
  alone must never authorize the push, since a remote head pushed without `open_draft_pr` would be
  orphaned with no DRAFT PR to cover it. A lone `open_draft_pr` grant never supplies push authority.
  Immediately afterward it must bind immutable PR identity/URL as `status=bound`. If DRAFT PR creation
  fails while the lease is still owned, append `status=pr-create-failed` plus a cleanup/retry escalation
  and forbid further mutation; do not make a second push under the reservation. If the lease was lost,
  emit that escalation locally only. `/repo-pr-maintenance` verifies on every later push/rebase/update that a
  **bound** record's live PR source repository and exact head ref match, applicable persisted
  push/update authority still holds, and the head is `ai/wi-*` or the explicit
  `ai/outdated-closure-*` exception. A name or prefix is never proof of ownership. An
  absent, failed, pending-after-first-push, or mismatched record is read-only. Human adoption is valid
  only through a prepare/confirm authority event recorded as adoption evidence; it is never inferred.
- **`regression-episode` record:** original WI; repro identity; red target SHA; suspect merge(s);
  current state; linked active regression WI when submitted; and prepared WI/alert handoff when
  conservative. Dedup only to an ACTIVE live WI matching this current episode. A closed/resolved WI
  may reopen only under provider policy plus persisted `reopen_tracker_item` authority; otherwise a
  new episode is filed only with `file_tracker_item` authority or remains `regression-escalated`.
- **`review-handoff` record:** `thread/comment ref`; source-comment revision or checked-at marker;
  `draft text`; `recommended resolution`; `escalation target`; `escalation status`; and
  `escalation time`. The artifact is the durable handoff to a human, not a provider-thread tail:
  preparing text does not post it, resolve the thread, or make it appear in the provider thread.
  The PR-maintenance drain is reached only when every new actionable comment has a current artifact
  with an escalated status (or an explicit blocked/escalated status), and the backlog/log records it.

---

## 8. Execution model — EM-runs-builds

The orchestrator owns the unreliable and irreversible operations; makers can't touch them.

- **Code-only makers.** Implementing agents have no build/push access — so they *cannot* wedge on
  a hung build and they *cannot* land unreviewed code. They write the diff + a precise recipe and
  hand it back.
- **Makers never touch Goal.** Dispatched sub-agents (makers, reviewers, verifiers) must never run
  `/goal` / `goalctl.py`: their tool shell inherits the *root* orchestrator's `COPILOT_AGENT_SESSION_ID`
  and the runtime exposes no distinct child marker to the shell, so a worker Goal mutation would hijack
  the orchestrator's goal. Only the root orchestrator session owns Goal; the Stop hook stays correct by
  keying off the per-invocation stop-payload identity, not the ambient shell environment.
- **The orchestrator runs the build**, bounded, one at a time (serialize the contended/flaky
  resource to avoid restore/daemon deadlocks), and detects hangs out-of-band (a blocked agent
  can't report; the orchestrator watches liveness and kills/retries).
- **Gate the push on an unmasked process result plus test evidence.** Run the
  repository-owned command directly and require exit status `0`, the expected
  tests to have executed, and no reported failures. If output must be piped,
  enable the shell's pipeline-failure propagation and capture the build
  command's own status; never trust the last formatter's status. A failure
  marker in output overrides a nominal zero. Do not require one tool-specific
  success string that other build systems never emit.
- **Parallelize the thinking, serialize the scarce resource.** Fan out reading + diff-writing
  across many agents; funnel the build, the device, and git mutations through one lane. Throughput
  from the fan-out; correctness and stability from the funnel.
- **Worktree isolation, verified.** Agents that mutate the tree work in a *fresh worktree*, and
  must verify they are in a worktree (not the main checkout on the protected branch) before any
  checkout — isolation options are not reliable on their own.

---

## 9. Human-in-the-loop — the escalation boundary

The system is conservative by default. Persist configured grants for each exact operation
(`file_tracker_item`, `reopen_tracker_item`, `initial_push`, `open_draft_pr`, `send_alert`, tracker
update, later push/update, and land); no broad "file/alert" mode authorizes a different operation.
Without the exact grant, prepare a
complete durable artifact and escalate it rather than submit externally. It never crosses these lines
alone:

- **Product / design decisions** (`NEEDS-DECISION` items).
- **Outward-facing communication** to humans — **every** reply, comment, and review-thread resolution
  (bot, style, preference, or substantive alike) is prepared and escalated for a human to post; the
  loops **never post, send, or resolve** a thread autonomously. A human's correctness/scope challenge
  triggers re-investigation, not a one-liner; honest replies, never glib defenses. (Code edits and
  pushes to branches this automation owns may stay autonomous under the existing gates and the
  land/push authority.)
- **Irreversible or shared-state actions** — and the **land/push** authority specifically: decide
  up front whether loops may push draft PRs autonomously or must prepare-and-escalate the push.
  (Default conservative: prepared draft artifacts only; land on explicit authority.)
- **Anything where reporting "done" would be unverified.** If a step was skipped or a test
  couldn't run, say so with the evidence.

---

## 10. Cost & stop discipline

Token cost in autonomous loops compounds faster than expected. Controls:

- **Per-loop budget caps.**
- **Prioritize the backlog:** severity × testability — the cheap-and-certain first.
- **Drain detection** (§7) so idle loops cost nothing.
- **Loop-until-dry** for the sweeper (K empty rounds), never an infinite crawl.

---

## 11. Harness vs per-repo adapter

| Transfers to any repo (the harness) | Re-derive per repo (the adapter) |
|---|---|
| The ten loops + the per-item pipeline | The exact build/test command, flavor, toolchain quirks |
| The disposition taxonomy + required artifacts | What "out-of-repo" means here (which subsystems this code owns) |
| The verifier stack (adversarial + WI-fidelity + feasibility) | The device / visual (QA) verification path |
| Maker/verifier split, code-only makers, EM-runs-builds | The repo's PR conventions, branch naming, review policy |
| Engineer scoping + discovered-issue protocol | The codebase skill content (architecture, idioms, gotchas) |
| The pr-review *mechanism* (learn-from-merged-PRs, the echo-chamber split, advisory review) | The learned **review-profile** — this team's demonstrated review standards |
| Loop coordination, durable logs, drain detection | Auth/secret handling specifics |
| Conservative posture + escalation boundary | Landing/push authority for this repo |
| The four extension loops (§4.7–4.10) + the metrics / watchdog substrate | The ecosystem audit tool + advisory feed; the CI/pipeline run-history source; the repro-suite of record |
| The self-improvement mechanism (report learnings → gated artifact PRs; the self-lobotomy guard) | Which artifacts are in-scope to self-edit here (the per-repo codebase skill vs. the shared harness pack) |

**One-line transfer recipe:** `/repo-learn` the repo → crack the build → run every backlog item
through *"is it real? already fixed? can a test prove it? does the signal even exist?"* →
implement the survivors behind the gates → draft-PR them linked to the WI → faithfully disposition
the rest → let the sweeper file new bugs into the same pipeline. The harness is constant; only the
adapter changes.

---

## 12. Why each rule exists — failure → rule

Every rule is a scar. Preserving the "why" keeps future operators from re-learning it the hard way.

| Observed failure (production) | Rule it produced |
|---|---|
| Engineer shipped an *adjacent* bug under the wrong WI, even rewriting the buglog title; a green correctness review passed it; a human caught it twice | **WI-fidelity gate** (§5.8) + **discovered-issue protocol** (§6) + verifier-in-PR-loop (§4.3) |
| "Not implementable" verdict was wrong — the maker built the wrong shape, hit a self-made wall, and substituted an easier fix (it was actually buildable) | **"Can't be done" is a claim → independent re-trace** (§5, §6) |
| Green, well-tested fixes were **inert in production** because the data/signal didn't exist — no mute flag, an unwired button, an unread-only query stripping the keyed record | **Feasibility / data-existence pre-check** (§5.2) |
| A repro test that passed against unmodified code "verified" a non-bug | **Staleness gate / red-first on the real path** (§5.1) |
| Stateful / migration / upgrade-path changes were green but wrong (data-loss, torn snapshot, wrong-of-two-paths, over-exclusion) | **Adversarial gate, 3 refuting lenses** (§5.7) |
| Builds intermittently hung (restore/daemon deadlock); non-terminating Flow tests hung the JVM; agents wedged running their own builds | **EM-runs-builds**, serialize builds, code-only makers, bounded hang-detection (§8) |
| An agent ran a checkout in the *main* working tree and moved it off the protected branch | **Worktree isolation, verified before checkout** (§8) |
| Long runs compacted/interrupted and lost the thread | **Durable append-only log + idempotent, re-entrant loops** (§7) |
| A remote reboot killed legacy session-only crons and wiped the in-session task-list backlog mid-run | **Persisted Copilot workflows + durable on-disk backlog + workflow-history rehydrate** (§2.3, §7.2) |
| A conversation rewind wiped invocation-local state; then a file-only rehydrate under-counted open PRs held outside the maintenance backlog | **Rehydrate reconciles against the live tracker and open-PR list, while preserving existing workflow IDs** (§7.2) |
| A regression test was pushed before the build was actually green — a piped build (`\| sed \| tail`) returned `tail`'s exit `0` and masked an upstream failure | **Require the build command's unmasked zero status plus expected test evidence; propagate pipeline failures** (§8) |
| A correct fix shipped as a large, hard-to-review diff when a ~10-line change would do; the human preferred the small diff and had to push back | **Bias to the minimal diff; surface a larger refactor as an option for the human, don't ship it silently** (§3, §9) |
| The static style gate checks only *documented* conventions — it misses what reviewers actually enforce in practice (and what makes a PR merge vs. bounce) | **A learned, evidence-based team `review-profile` mined from merged PRs, refreshed weekly — advisory, with an echo-chamber guard (never learn style exemplars from our own bot diffs)** (§4.6) |
| The auto-review sweep crawled the WORKING CHECKOUT — a divergent/dead feature branch far ahead of the target branch — and surfaced a "bug" in code that doesn't exist on the PR-target branch, so the fix had nowhere to land; the maker then chased the file onto the dead branch | **Sweep AND fix against the PR-target branch, not the working checkout; verify each find's file exists on the target before filing; a file absent on target = off-target/dead code, report don't chase** (auto-review.md, engineer-charter.md) |
| An auto-review find (a real data-loss bug) was linked to an existing WI by file/area similarity, but that WI described a DIFFERENT bug and was already Resolved/Fixed — the PR claimed `fix(wi-<id>)` against a closed, unrelated ticket | **WI-fidelity also guards WI-MATCHING: before linking a find to a pre-existing WI, confirm repro-match (not area-match) AND that the WI is OPEN; a real find with no matching open WI gets its OWN work item, never the nearest closed one** (wi-fidelity.md state-pre-check) |
| The report email hard-failed (and risked hanging on an interactive re-auth) — root cause an *expired tenant*, not a missing token | **Notification is best-effort + degrades gracefully; the digest file is the source of truth** (§4.5) |
| The bot/reviewer surfaced real scope gaps for free | **Use the repo's own reviewer/CI as a second adversary** (§4.3) |
| A CI/bot comment flagged a "scope gap" that was a deliberate, WI-recorded decision | **Run WI-fidelity on bot findings too — bots false-positive; document-and-close, don't reflex-implement** (§4.3) |
| Loops risked racing on the same item/PR and overwriting repository-scoped Goal state | **Cross-process repository lease + item ownership + drain detection** (§7) |

### 12.1 Anticipated failure classes for the extension loops (design-time — not yet scars)

§12 above is a ledger of failures **observed in production**; every row was paid for. The four extension
loops (§4.7–4.10) have not yet run at that scale, so their guardrails are **predicted, not scarred** —
recorded here, honestly separated, so a future operator knows which rules are battle-tested and which are
still hypotheses to validate (and to promote up into §12 once a real incident confirms one):

| Anticipated failure | Guardrail designed in (unproven) |
|---|---|
| Dependency audit becomes wall-of-red noise the team mutes (every transitive CVE filed regardless of exposure) | **Reachability proof as the filing gate; unreachable = on-disk log, never the tracker** (§4.7) |
| An auto-filed dep bump silently breaks us — a green audit says nothing about our behavior | **File-only, never auto-bump; force it through Triage + the regression gate (§5.4)** (§4.7) |
| A real, consistently-red failure gets mislabeled "flaky" and quarantined, hiding a live bug | **≥M both-outcome runs on one SHA required; consistently-red is never a flake; product races get a product bug, not a skip** (§4.8) |
| Coverage silently erodes as quarantines accumulate and are never lifted | **Quarantine only via a DRAFT human-landed PR, each paired with a de-flake WI that lifts it in the fix** (§4.8) |
| Post-merge sentinel cries wolf on a pre-existing/unrelated target failure and floods alerts | **Re-run only the just-landed WI's own validated repro; bisect to the suspect merge before filing** (§4.9) |
| Self-improvement optimizes for fewer send-backs by *weakening* a gate (the system files PRs to lobotomize itself) | **The self-lobotomy guard: may only add/tighten; a relax-a-safeguard PR needs a quoted human instruction** (§4.10) |
| Self-improvement churns on one-off comments, spamming low-value artifact PRs | **Only *converged* learnings (recur ≥R, carry evidence + a falsifiable expected effect); dedup vs. in-flight** (§4.10) |

---

## 13. Standing it up — runbook

1. `/repo-learn` the target repo → codebase skill. Confirm it loads (ask it the repo's enforced linter;
   wrong answer = it didn't load).
2. Crack the build; bake the recipe into the skill; **prove one test runs red/green.**
3. Seed the backlog into the source-of-truth store.
4. Start the **Triage loop**; let it drain the backlog into dispositions (with artifacts).
5. Start the **Implement loop** on `VERIFIABLE` items (workflows, scoped makers, gates,
   draft PRs).
6. Start the **PR-maintenance loop** (comments + WI-fidelity verifier).
7. Start the **Auto-review loop** (submit-authorized-or-prepare-only) feeding new bugs back to Triage.
8. Stand up the **extension loops** once the core drains clean: **dep-sweep**
   (submit-authorized-or-prepare-only supply-chain audit, daily), **ci-health** (flaky-test sentinel +
   submitted-or-prepared quarantine drafts, hourly), **post-merge** (regression sentinel over the
   integrated target, on tracked-fix merges), **self-improve** (report learnings → submitted-or-prepared
   WI/artifact-draft pairs, weekly). Each writes to the *same* backlog and runs behind the *same* gates.
9. Turn on the **report cadence** + its **metrics series & degradation alarm**, and stand the **liveness
   watchdog** *outside* the session (§7.3).
10. Decide **landing authority** and the **escalation boundary** with the human up front.
11. Keep the durable log; let loops go quiet on drain; surface `NEEDS-DECISION` / `NEEDS-QA` to the
    human.

---

## 14. Open questions / future

- **Auto-review & dep-sweep aggressiveness → trust-gated auto-implement.** Both default file-only. The
  concretization: a **trust gate** that promotes a find-class to auto-implement (still fully gated, still
  a draft PR) *only after* that class clears a tracked bar — e.g. ≥N consecutive landed-without-rework
  fixes and a zero post-merge-regression streak (§4.9) for that class. The metrics series (§4.5) is what
  makes the bar measurable; until a class earns it, file-only stands.
- **Cross-loop prioritization → a global scheduler.** With ten loops draining independently, the
  concretization is one scheduler ordering *all* pending work by severity × testability × cost ×
  freshness, subject to the one-build-at-a-time constraint (§8) and a per-loop **starvation floor** (a
  cheap loop can't permanently crowd out an expensive-but-critical one). Replaces "each loop drains on its
  own heartbeat" with a single weighted queue; the heartbeats become the *fallback*, not the driver.
- **WI-fidelity automation depth → deterministic pre-checks.** Land the cheap, deterministic slice of
  "does this fix the filed bug?" as pre-checks that run *before* the reasoning agent: diff **touches the
  validated repro path**, WI **title/id unchanged**, target WI **OPEN**, repro **red-before / green-after**
  on the target branch. Fail any → bounce without spending the agent; pass all → the agent still makes the
  judgment call. Cheaper and less spoofable than an all-reasoning gate.
- **Metrics → shaped (§4.5).** The per-loop series (dispositions/run, gate catch-rate, revert rate,
  cost/landed-PR) + the degradation alarm are now specified in the report cadence; still open is the
  **dashboard / cross-repo aggregation** once the harness runs on more than one repo at a time.
- **New opens from the extension loops.** Cross-repo self-improvement (a lesson learned on repo A that
  should harden the *shared* harness for B and C — how to promote a per-repo learning up to the pack
  safely, without one repo's quirk over-fitting the harness); and the dep-sweep **auto-bump** question
  (once the regression gate has a proven track record on dependency PRs, does file-only relax to
  trust-gated auto-bump for patch/minor?).
