---
name: repo-maintenance
description: Onboard a repository and arm a gated maintenance system that submits authorized artifacts or prepares drainable handoffs.
version: 1.0.0
user-invocable: true
argument-hint: "[repository or authority mode]"
---

# repo-maintenance

A meta-skill that runs a self-maintaining production repository: it compounds a codebase skill
(from `/repo-learn`) with its standing loops — six core (**triage**, **implement**, **pr-maintenance**,
**auto-review**, **report**, **pr-review**) plus four extensions (**dep-sweep**, **ci-health**,
**post-merge**, **self-improve**) — all feeding **one gated backlog**. The output is a steady stream of
small, proven, submitted-or-prepared draft PR artifacts linked to work items, plus a faithfully-
dispositioned backlog. The full rationale is in `DESIGN.md` (read it once); the runnable prompt
templates are in `prompts/`.

The governing idea: **a verifier wrapped around a maker.** A green build is necessary, never
sufficient. The maker will drift, over-reach, or declare false defeat — the loops exist to make its
"it's done" mean something.

## When to use
- "Set up autonomous maintenance / a backlog-triage loop / PR-babysitting / a bug sweeper on this repo."
- "Triage this backlog and fix the testable items behind draft PRs."
- "Run the prod-repo maintenance workflow."
- NOT for a one-off single fix (just fix it), and NOT before the build is cracked (see Phase 0).

## Prerequisites

- Run `/repo-learn` first; the generated `<repo>-codebase` skill must contain a
  proven red-to-green test recipe.
- Configure issue, pull-request, review-thread, and CI access for the repository
  host. Use GitHub tools or `gh` for GitHub and the available `ado-*` tools for
  Azure DevOps.
- Persistent standing mode requires `save_workflow`, `run_workflow`, and
  `list_workflows`. If they are unavailable, run individual loop skills
  on-demand and report that the system is not armed; never claim persistence.
- Python 3 is required for the repository-wide execution lease in
  `runtime/maintenance_lock.py`. Every loop must acquire that lease before
  setting `/goal` or reading/writing shared maintenance state, then pass a
  **pre-write heartbeat gate** before every durable/shared/remote write.
- Use the bundled `/goal`, `/workflow`, and `/ultracode` capabilities. Select the
  highest-capability available model for delegated gates and disclose any
  fallback from a requested model.

## Command suite (slash commands)

This harness is the conductor and registers as `/repo-maintenance`; the bundled
`/maintain-repo` skill is an exact alias. Each loop is also a standalone slash
command. All commands load this skill directory as their shared content library,
so prompts and charters live in exactly one place.

| Command | Does | Loop |
|---|---|---|
| `/maintain-repo` (this skill) | the whole thing — onboard -> arm all loops -> go | — |
| `/repo-learn` | onboard a repo -> `<repo>-codebase` skill + crack the build | Phase 0 |
| `/repo-triage` | disposition every untriaged backlog item (with its artifact) | 1 |
| `/repo-implement` | submit gated DRAFT PRs when authorized, otherwise prepare them | 2 |
| `/repo-pr-maintenance` | steward every open PR's reviewer threads | 3 |
| `/repo-auto-review` | read-only sweep -> submit authorized or prepare new-bug WIs (never fixes) | 4 |
| `/repo-report` | the period's digest (observes the loops) | 5 |
| `/custom-pr-review` | learned team-style reviewer over the ~100 most-recently-merged PRs (advisory) | 6 |
| `/repo-dep-sweep` | audit deps/lockfiles → submit authorized or prepare reachable-risk WIs (never bumps) | 7 |
| `/repo-ci-health` | detect flakes → submit authorized or prepare de-flake WIs/quarantine drafts | 8 |
| `/repo-post-merge` | re-run landed repros → submit authorized or prepare regression/revert artifacts | 9 |
| `/repo-self-improve` | submit authorized or prepare gated self-improve WI/draft pairs | 10 |

### `/maintain-repo` — one-shot bootstrap (the conductor)
`/maintain-repo` doesn't just arm timers — it **drives the full onboarding by running the other
sub-commands in order**, then stands the loops up on top of what they produced. Invoked on a repo, run
end-to-end — **do not stop at the reconcile**. **Use swarms liberally** to parallelize (seeding,
triage, PR-mining, and within each loop), and use the strongest available model
for landing-critical reasoning and verifier gates (see `HARNESS-COPILOT.md`). The
conductor stays the single owner of builds/landing/git:

1. **Harness** — on Copilot CLI, read [`HARNESS-COPILOT.md`](HARNESS-COPILOT.md) first (the verb map).
2. **Resolve canonical state and acquire the repository lease.** Run
   `runtime/repo_identity.py`, use its absolute `state_dir` as `<triage-dir>`,
   then acquire with `runtime/maintenance_lock.py`. Record the returned token.
   If another maintenance invocation owns it, stop cleanly without writing the
   adapter, `identity.json`, `/goal`, or the backlog. Before every later durable,
   shared, or remote write, heartbeat the retained token; any nonzero/not-owner result terminates the
   run immediately with local/session status only — never a shared-state error record or cleanup write.
3. **Run `/repo-learn` under the existing lease** — onboard the repo -> author the `<repo>-codebase` skill + **crack the build**
   (HARD GATE: one unit test red->green). Every loop loads this skill first, so this comes before
   everything else.
4. **Seed the backlog (swarm)** — fan out `explore` agents to pull open WIs/issues/PRs in parallel and
   reconcile; merge into the durable file `<triage-dir>/backlog.md` (one row per item) + the `todos`
   table.
5. **Bulk-triage the seeded backlog (swarm)** — run `/repo-triage`'s logic across a swarm of
   `general-purpose` agents, each dispositioning a slice (staleness + feasibility pre-checks in
   parallel); merge dispositions back to `backlog.md` before the loops take over.
6. **Run `/custom-pr-review`'s learning pass NOW (swarm)** — fan a swarm across the ~100
   most-recently-MERGED PRs (batched); each agent extracts review signals, then synthesize one
   `review-profile.md`, so the reviewer has a current team profile from **day one** (don't defer it to
   the first weekly refresh).
7. **Persist operation authority** with the human — exact grants for `file_tracker_item`,
   `reopen_tracker_item`, `initial_push`, `open_draft_pr`, `send_alert`, tracker update, later
   push/update, and land —
   *orthogonal to arming*. Default conservative mode prepares complete durable handoffs and escalates;
   it does not submit externally.
8. **Arm ALL standing loops** as persisted `save_workflow` heartbeats — triage/implement/pr-maintenance
   hourly · auto-review daily · report `0 17 * * *` · pr-review weekly · **dep-sweep daily · ci-health
   hourly · post-merge hourly (after merges land) · self-improve weekly** — each `mode: autopilot`,
   self-contained + drain-aware. Every prompt must acquire the same repository
   lease before setting `/goal`, heartbeat it during long work and immediately before every
   durable/shared/remote write, and release it on every still-owned exit. A heartbeat nonzero/not-owner
   stops locally before any further write; a nonzero/not-owner release is a local failure, never a
   successful ownership/release claim; a busy lease is a clean no-op. **This is the deliverable.**
9. **Release the bootstrap lease, then proof-fire one** (`run_workflow`) and
   `list_workflows` to confirm every loop is armed + enabled.
10. **Report** the armed fleet + what needs the human. **Done = `/repo-learn` ran, the codebase skill +
   review-profile exist, and all loops are enabled** — not a one-time triage (see Verification ->
   "The system is ARMED").

> **How the chaining works on Copilot CLI:** slash commands don't call each other as functions. The
> conductor *executes each sub-command's procedure inline* — and since every sub-command points at the
> SAME shared library (`bundled/learn.md`, `prompts/pr-review.md`, …), "run `/repo-learn` as part of
> `/maintain-repo`" is the identical work the standalone `/repo-learn` does. The sub-commands also exist on
> their own so a human can run any single piece (re-learn, re-mine the PR profile, triage once) by hand.

## Procedure

> Read [`HARNESS-COPILOT.md`](HARNESS-COPILOT.md) first for the runtime verb map.
> It maps the original harness verbs to this plugin: `/repo-learn` authors the
> `<repo>-codebase` skill; `/goal` supplies bounded continuation;
> `CronCreate`/`/loop` → **`save_workflow`/`run_workflow`** (which *persist on disk* — no re-arm on
> restart); the original Workflow tool → bundled `/workflow`, `/ultracode`, or
> background `task` agents; tracker operations → the configured GitHub or Azure
> DevOps tools. The design is unchanged; only the orchestration verbs differ.

Run the phases in order. Phase 0 is one-time per repo; phases 1–4 and 6 are standing work loops and
phase 5 is a reporting cadence over them. Load the
relevant `prompts/*.md` template when you dispatch each agent, and **every dispatched agent loads
the repo's codebase skill first.** **Use the Workflow tool for parallel multi-stage fan-out** —
implementing many `VERIFIABLE` items at once, the 3-lens adversarial gate, and the multi-modal
auto-review sweep — with per-stage verification (pipeline/parallel); fall back to parallel Agent
dispatches where workflows aren't available. The orchestrator owns builds, landing, and git.

**Each standing loop (1–6) runs as a `/goal` (its success criteria = the loop's Done line) with a
recurring cron heartbeat attached** — not a bare timer-cron. The **native `/goal`** drives to done (it
sets a session Stop-hook that blocks the agent from stopping until the success criteria hold, then
auto-clears); the cron re-checks after drain and re-engages only when new work appeared: *drive to
done → go quiet → cron re-checks → re-engage → done again.* See `DESIGN.md` §4.0 and
`bundled/goal-loop.md`.

0. **Onboard (once).** Uses `/repo-learn` and the bundled recipe (`bundled/learn.md`).
   - `/repo-learn` the repo → a **codebase skill** (architecture, conventions, build/test/deploy, PR &
     branch policy, gotchas). Every loop agent loads it first.
   - **Crack the build** — get one unit test to run red/green from an agent-controlled checkout, and
     bake the exact recipe into the codebase skill. **Hard gate: no triage-to-action until a test runs.**
   - Seed the backlog into the single source of truth — **a durable file on disk** (`<triage-dir>/
     backlog.md|json`), mirrored into the task list: one row per item with `id, title, disposition,
     proof/why, owner-lock, links, evidence, source`. The task list alone is **session-ephemeral**
     (a reboot wipes it), so write every disposition to the file. See `DESIGN.md` §7.2.

**Global PR transport invariant (every automation-created PR).** Implementation, CI quarantine,
outdated closure, self-improve artifact, and post-merge revert drafts all invoke the same two-phase
canonical `branch-ownership` procedure; no specialized loop may bypass it. Before any initial remote
push, the target source repository must have an exact absent head ref/class and a **live submitted WI**
linked to the future PR. If that WI is missing, submit it only with the persisted `file_tracker_item`
grant; otherwise prepare/escalate the WI plus diff and do not push or open. Persist a pending
reservation in the canonical backlog/log with that repository/ref/class, WI, creation evidence, and
BOTH persisted `initial_push` and `open_draft_pr` grants; a lone `open_draft_pr` grant never supplies
push authority. Preflight both grants, the live WI, and ref absence; permit exactly one initial push;
immediately create the DRAFT PR and bind immutable identity/URL. Binding failure freezes every further
mutation and produces a cleanup/retry escalation. Subsequent mutation requires a bound record whose
live PR source/head match plus applicable persisted push/update authority. A missing prerequisite
leaves a complete drainable prepared/escalated handoff, never an orphan branch.

1. **Triage loop** (`prompts/triage.md`; disposition taxonomy in `DESIGN.md` §3).
   Classify every untriaged item into exactly one disposition, **attaching its required artifact**:
   `OUTDATED` (proof = repro test passes on the integrated target) · `NOT-ACTIONABLE` (why) · `NEEDS-QA` (the visual
   check) · `VERIFIABLE` (→ implement) · `NEEDS-DECISION` (the product question). Run the staleness
   gate and the feasibility/data-existence pre-check here. Drain, then go quiet. This loop is the
   **backlog reviewer** for every new item — filed, swept, or engineer-discovered.

2. **Implement loop** (`prompts/engineer-charter.md`, `prompts/adversarial-gate.md`, `prompts/wi-fidelity.md`; the verifier stack in `DESIGN.md` §5).
   **First, no duplicate PRs:** before working an item, check the repo's open PRs for one already
   covering its work item. Use the provider's verified live WI/issue
   relationship and compare the diff to the repro; branch naming is only an
   additional signal, so teammate/human branches count. Closure batches match
   the complete linked-WI set plus the `outdated-closure` label/title. If one exists, mark the item `IN-REVIEW` and hand it to the
   PR-maintenance loop instead of opening a second PR. Otherwise, for each unlocked `VERIFIABLE` item, fan out in
   parallel via workflows: claim/lock → red-first repro test → TDD to green → **regression gate (full
   suite still green)** → style review → security review → **adversarial gate (3 refuting lenses)** →
   **WI-fidelity gate** → **draft PR linked to the work item**. Before any branch
   creation/adoption, persist a durable `branch-ownership` **pending reservation** in the canonical
   backlog/append-only log with source repository identity, exact intended head ref/class, a live WI,
   creation/adoption evidence, and BOTH the persisted `initial_push` (push) grant and the persisted
   `open_draft_pr` grant. A live PR is not required before the initial push, but both exact grants and
   the live submitted WI are — `initial_push` alone must never authorize the push, or an unopened DRAFT
   PR would orphan the remote branch. A lone `open_draft_pr` grant never supplies push authority. A
   preflight re-check immediately before the push confirms both grants and the live WI still hold; it
   permits exactly one matching push only while the remote ref is absent.
   Immediately create the DRAFT PR and bind immutable provider identity/URL; if PR API creation still
   fails unexpectedly, forbid further mutation and escalate cleanup/retry. Every later
   push/rebase/update needs the bound record + live source/head match + applicable persisted
   push/update authority. A branch name is never proof; explicit human adoption requires
   prepare/confirm authority, never inference. Makers are
   **code-only and strictly charter-scoped** (`prompts/engineer-charter.md`);
   the orchestrator runs builds and landing (`DESIGN.md` §8).
   - **Hard invariant — no PR without a WI.** Every PR (fix *or* closure) links a **live, submitted**
     work item. If an item has no WI (a fresh auto-review find, an engineer-discovered bug), consult
     the persisted `file_tracker_item` grant for this exact operation: with the grant, **create the WI
     first** (codebase-skill filing convention; tag `auto-review` if machine-found, carry the validated
     repro test) and link it before any branch/PR mutation — never open a WI-less PR, and never let an
     `open_draft_pr` grant alone stand in for the missing WI. Without the grant, persist a complete
     `implement-escalated` prepared handoff on the canonical backlog and hold that item out of
     branch/PR work — a missing WI blocks the PR exactly as a missing `open_draft_pr` grant would. This
     is what keeps the WI-fidelity gate meaningful.
   - **Closure mode** (`prompts/outdated-closure.md`) — the Implement loop also *proves and closes*
     Triage's `OUTDATED-candidate` items (each already carrying a live WI from Triage): parallel
     test-write (one maker each) → **one batched
     classification run** on `{TARGET_REMOTE}/{TARGET_BRANCH}` (mixed exit status is expected; record
     every test outcome). If an **aggregate compile error** stops the build from producing per-test
     outcomes at all (not a per-test failure — no candidate classifies), run bounded SERIAL diagnostic passes: use the
     compiler's own file/line locations to remove/mark the offending unprovable test addition(s), one
     pass at a time (never fan out builds), capped at one pass per remaining candidate, then rerun the
     shrinking batch until it is runnable or no candidates remain. **If a pass cannot attribute the
     compile error to specific candidate(s)** (an ambiguous or cross-cutting location), do not retry it —
     mark every still-remaining candidate `compile-or-unprovable` in that same pass, return all of them
     to normal triage, and stop the diagnostic loop immediately; this still terminates within the same
     pass cap and never opens a PR from an unresolved batch. Once runnable (by attribution or by that
     whole-batch exit), remove
     failing/still-reproducing/unprovable tests from the candidate batch and
     return those items to normal triage → rerun only confirmed-outdated passing tests with exit 0 → style
     + security gates → invoke the global PR transport invariant above. Every retained item already
     supplies a live submitted WI, but BOTH persisted `initial_push` and `open_draft_pr` grants plus
     the two-phase `branch-ownership` reservation are still required; a lone `open_draft_pr` grant is
     never push authority. Submit **one DRAFT PR** only when ≥1 confirmed item remains and every
     prerequisite holds; otherwise persist a complete `outdated-closure-escalated` prepared handoff.
     Stale backlog stays drainable *with evidence*.

3. **PR-maintenance loop** (`prompts/wi-fidelity.md`; `DESIGN.md` §4.3). Steward **every open PR** for
   our work items — including ones this run didn't create (pre-existing / teammate / carried-over):
   (a) handle comments — create a current durable review-handoff artifact for every actionable
   comment, with thread/comment ref, draft text, recommended resolution, escalation target/status/time.
   The artifact is not a provider-thread tail: never claim the prepared draft appears in the provider
   thread. Every outward-facing reply/comment and review-thread resolution (bot, style, preference,
   or substantive) is prepared and escalated for human posting; the loop will **never post, send, or resolve**
   a thread itself; a test/coverage ask → a scoped engineer adds it on an owned
   branch + this session verifies; a **human correctness/scope challenge → run the WI-fidelity verifier
   first, not a glib reply**; (b) proactively confirm each PR actually does its work item (WI-fidelity
   vs. repro steps, on every PR); (c) ensure each has cleared the gate bar (style/security/adversarial —
   run them on any carried-over PR that hasn't); (d) keep each PR fresh, but **push/rebase/update only
   branches this automation owns** (`ai/wi-*`, explicit `ai/outdated-closure-*`). A deduped
   teammate/human/external branch is **read-only**: monitor its freshness/CI/reviews, prepare a concrete
   patch/rebase/fix recommendation for the branch owner and escalate it, keep the item `IN-REVIEW`/
   blocked with the handoff recorded, and never push or mutate their branch. Before refreshing any
   apparently owned PR, verify its durable ownership record matches the live source repository and
   exact head ref; `ai/wi-*` or `ai/outdated-closure-*` alone is insufficient. This loop *is* the standing
   replacement for the human who catches scope-substitution.

4. **Auto-review loop / bug sweeper** (`prompts/auto-review.md`).
   Crawl for new bugs (by subsystem / data-flow / invariant / recent churn). For each: **FILE a work
   item** with a concrete repro + evidence (dedup first), but only when persisted
   `file_tracker_item` authority grants filing; otherwise prepare/escalate the complete artifact.
   **It never fixes anything** — discoveries re-enter the Triage loop. Loop-until-dry (stop after K
   empty rounds).

5. **Report cadence** (`prompts/report.md`). Daily or every 2 days, bundle a digest: items filed /
   triaged / handled by disposition, draft PRs opened / landed, sweeper finds, reviewer comments
   handled; the **gate catch-rates**; **human comments worth learning from** (each mapped to a
   concrete improvement to the codebase skill, a gate, or a prompt); the **issues/friction** it hit
   (honestly, skips included); and what **needs you** (NEEDS-DECISION / NEEDS-QA + escalations). The
   accountability + continuous-improvement layer — it observes the work loops, it does not touch the
   repo; its converged learnings feed the self-improvement loop (10). The digest **file** is always
   written; sending it anywhere is an outward-facing notification gated on the persisted `send_alert`
   authority like any other alert — without that grant, prepare the pointer text and escalate instead
   of sending it.

6. **PR-review loop** (`prompts/pr-review.md`; `review-profile.template.md`; `DESIGN.md` §4.6). A
   *learned* team-style reviewer: it mines the **N most-recently-merged PRs** for the team's
   demonstrated review standards (recurring asks, bounce triggers, conventions enforced in review but
   not by lint), writes an evidence-backed **`review-profile.md`**, and **refreshes weekly** (fully
   autonomously, with a dated CHANGELOG diff; pinned + codebase-skill rules are sacrosanct). It applies
   that profile to PRs as **advisory** findings (never blocks, **never auto-posts** — prepare-and-
   escalate). **Scope is chosen at setup** (default `our-draft-PRs-only`). **Echo-chamber guard:** learn
   *preferences* from human comments on **all** PRs (incl. ours), but *style exemplars* from
   human-authored diffs **only** — never from our own bot diffs. Taste/convention layer only; augments,
   never replaces, the static style gate (§5 step 5).

7. **Dependency-sweep loop** (`prompts/dep-sweep.md`; `DESIGN.md` §4.7). **File-only**, the auto-review
   analog for the dependency surface: audit the target-branch lockfile (`npm audit` / `pip-audit` /
   `govulncheck` / `osv-scanner` / the host advisory feed) on a two-source churn-gate (lockfile-hash **or**
   advisory-feed cursor — a CVE lands with no code change). For each **reachable** advisory + MED+ hygiene
   item: **FILE a work    item** (advisory id, resolved-vs-fixed, reachability proof; tag `dep-sweep`) only when persisted
   `file_tracker_item` authority grants it; otherwise prepare/escalate it without external submission.
   **Reachability is the noise filter** — an unreachable CVE is logged on-disk, never filed. **It never
   bumps a version** — the fix routes through Triage + the gates (the regression gate especially).

8. **CI-health loop** (`prompts/ci-health.md`; `DESIGN.md` §4.8). The verifier's verifier: mine the last
   N pipeline runs for tests that **disagree on the same SHA** (a flaky *green* passes a real regression
   through a trusted gate). Per confirmed flake: **(a)** submit the de-flake WI first only with
   `file_tracker_item`, otherwise prepare it; **(b)** invoke the global two-phase `branch-ownership`
   transport invariant and submit a linked **DRAFT quarantine PR** only with the live submitted WI and
   BOTH persisted `initial_push` and `open_draft_pr` grants (the latter alone is never push authority),
   otherwise prepare the draft with the WI handoff; and **(c)** backlink only when granted. Implement
   later lifts a submitted quarantine in the fix.
   **False-quarantine guard:** ≥M both-outcome runs on one SHA required; consistently-red is a real
   failure, not a flake; a genuine product race gets a product bug, never a quarantine.

9. **Post-merge sentinel** (`prompts/post-merge.md`; `DESIGN.md` §4.9). Enroll each durable-backlog
   maintenance item that landed through a **verified covering PR** — ours (`ai/wi-*`) or a deduped
   teammate/human/external branch (verified linked PR/WI + a validated repro; never arbitrary team
   work) — and add its validated repro to `<triage-dir>/landed-repros.json`; a deduped external fix is
   retained and rerun exactly like an agent-authored one. Re-run every retained repro on
   each integrated-target advance. PASS updates evidence but remains watched
   for at least 90 days and 20 later advances. RED is a current episode keyed by original WI + repro +
   target + suspect merge: dedup only to an ACTIVE live WI; closed/resolved WIs reopen only under provider
   policy + exact authority, otherwise file a new episode when granted or persist
   `regression-escalated` prepared handoff. `regression-filed` requires an active linked WI. Alert only
   under exact authority; otherwise prepare/escalate again. Any optional revert draft uses that active
   regression WI and the global two-phase `branch-ownership` transport invariant: the live submitted WI
   plus BOTH persisted `initial_push` and `open_draft_pr` grants are mandatory, and a lone
   `open_draft_pr` grant is never push authority. Otherwise prepare/escalate the revert diff; a revert is
   never applied by the loop (§9). A current
   target completes when each entry is PASS, `regression-filed`, or `regression-escalated`; every target
   advance reruns **EVERY retained entry**, including prior PASS and red entries.

10. **Self-improvement loop** (`prompts/self-improve.md`; `DESIGN.md` §4.10). **Prepare-and-escalate.**
    Turn the report's **converged** learnings (recur ≥R, carry evidence) into dedicated `self-improve`
    WIs and ONE **DRAFT** PR each against the artifact — the `<repo>-codebase` skill or the harness pack
    itself — with a falsifiable expected effect. Submit the WI first only with `file_tracker_item`;
    otherwise prepare/escalate both WI and diff. PR transport invokes the global two-phase
    `branch-ownership` invariant and requires the live submitted WI plus BOTH persisted `initial_push`
    and `open_draft_pr` grants; a lone `open_draft_pr` grant is never push authority.
    **Self-lobotomy guard:** may only ADD/tighten a gate/rule; **never** weaken or delete one to reduce
    its own send-backs (a relax-a-safeguard PR needs a *quoted human* instruction). Never auto-merges;
    a human lands every artifact change.

Decide two things with the human up front: **landing/push authority** (autonomous
vs. prepare-and-escalate) and the **escalation boundary** (product decisions,
outward-facing replies, and irreversible actions always escalate). Persisted
loops may start in separate sessions, but the repository lease serializes their
orchestrators; only analysis and disjoint code-only makers fan out under the
owner (`DESIGN.md` §7.1). **Authority is orthogonal to arming:** it governs what
loops may do within each fire, never whether the loops are created.

## Pitfalls
- **Don't skip Phase 0's build-crack.** Without a runnable red/green, every fix is reasoned-not-
  verified and triage is unreliable.
- **Pin every loop to the PR-target branch, not the working checkout.** Sweep, base worktrees, and
  build against `{TARGET_REMOTE}/{TARGET_BRANCH}` loaded from the codebase adapter; the on-disk checkout can
  be a divergent, stale, or DEAD feature branch, and a bug found only in off-target code can't land.
  Refresh that target ref before each sweep, and verify a find's file exists on target before filing.
  (Scar: a sweep crawled a dead branch far off the target and filed a bug in code not on the target.)
- **Never let a maker fix an adjacent bug it finds.** It files a new work item and returns
  (`prompts/engineer-charter.md`). A rewritten work-item title to match the fix = the ticket was
  silently redefined — the WI-fidelity gate exists to catch this.
- **A green correctness review does NOT catch the wrong-fix-for-the-right-WI failure** — only the
  WI-fidelity gate (diff vs. *repro steps*, not the title) does.
- **"Can't be done / already fixed / no signal" is a claim, not a verdict** — re-trace it
  independently, especially if the same agent then ships an easier neighbor.
- **Serialize builds and keep makers code-only** (`DESIGN.md` §8) — concurrent
  builds deadlock and agents wedge on hung builds.
- **One locked backlog**; loops are idempotent/re-entrant and **go quiet on drain** — don't
  manufacture work; cost compounds.
- **Workflow schedules persist; invocation state does not.** On restart, reload
  the backlog, reconcile against the live host, and use `list_workflows` to
  confirm existing schedules. Update missing workflows by ID; do not blindly
  recreate all schedules. A stale execution lease may be replaced only after its
  TTL, and every active loop heartbeats its lease.
- **Notification is authority-gated and best-effort.** The report's digest *file* is the source of
  truth; sending it anywhere (email/DM) is outward-facing communication like any other, so it requires
  the persisted `send_alert` authority. **With the grant**, delivery must degrade gracefully (a dead
  token/tenant is a clean skip, never a hang or a headless interactive re-auth). **Without the grant**
  (default conservative mode), never send: prepare the exact notification text and escalate it instead
  — never claim it was sent.
- **PR-review is advisory + echo-chamber-guarded.** The learned reviewer never blocks a PR or
  auto-posts a comment (prepare-and-escalate), and never learns style exemplars from our own bot PRs —
  only humans' *comments* on them. Learn from **merged** PRs against the default branch, never
  working-branch-only code. It augments the static style gate; it does not replace it.
- **Dep-sweep submits authorized WIs or prepares them, never bumps — and reachability is the filter.**
  A version bump is high-blast-radius; it routes through Triage + the gates, never a silent auto-bump.
  A CVE on a package we never call on a vulnerable path is logged on-disk, not submitted — or the loop
  becomes the dependency-bot noise teams mute.
- **Ci-health quarantines only *proven* harness-flakes, only via a DRAFT PR.** "It's flaky" is a claim:
  require repeated both-outcome runs on one SHA; a consistently-red test is a real failure; a product
  race gets a product bug. Never silently skip a test — coverage loss is a human-landed decision (§9).
- **Post-merge reuses the validated repro and never reverts on its own.** It re-runs the fix's own repro
  on the integrated target; a red result remains monitored as `regression-filed` only with an active
  linked regression WI or as `regression-escalated` with a prepared handoff, while a PASS remains
  retained. Later target advances rerun **EVERY retained entry** and recover or update the current
  episode. Reverting a landed,
  human-approved merge is escalate-only. Don't cry wolf on a pre-existing target failure — bisect to the
  suspect merge before filing.
- **PR-maintenance never speaks or writes outside our own branches.** Every outward-facing reply,
  comment, and review-thread resolution — bot, style, preference, or substantive alike — gets a
  current durable review-handoff artifact (thread/comment ref, draft text, recommended resolution,
  escalation target/status/time), is prepared and escalated for a human to post; the artifact is not
  a provider-thread tail and the loop never claims the draft appears there. The loop will **never
  post, send, or resolve** a thread itself. It pushes/rebases only branches this automation owns
  (`ai/wi-*`, explicit `ai/outdated-closure-*`) after verifying the durable record against the live
  source repository and exact head ref. A
  deduped teammate/human/external PR is **read-only**: recommend a patch/rebase/fix and escalate to the
  owner, keep the item `IN-REVIEW` with the handoff recorded, and never push or mutate their branch.
- **Self-improve may only tighten, never loosen.** It turns *converged* human feedback into
  submitted-or-prepared WI/draft pairs on the artifacts; it must never propose a PR that weakens a
  gate/pinned rule to reduce its own send-backs (the self-lobotomy guard). Every artifact change is
  human-landed.

## Verification
- **Onboard worked:** the codebase skill loads (ask it the repo's enforced linter / build command;
  a wrong answer = it didn't load) and **one unit test actually runs red→green**.
- **The system is ARMED (the deliverable):** each standing loop exists as a *persisted* heartbeat —
  `list_workflows` shows one per loop, all **enabled**, and at
  least one **proof-fired** once to confirm it loads the skills, reaches the configured tracker, and no-ops on a drained
  backlog. **A faithfully-dispositioned backlog with no armed loops is a FAILED run, not a complete
  one** — triaging once is the warm-up; standing up the self-running loops is the job.
- **A loop is healthy:** every backlog item has a disposition *with its artifact*; every draft PR is
  linked to a work item and passed the full gate stack; every actionable reviewer comment has a
  current review-handoff artifact with an escalated status (never a claim about a provider-thread
  tail); each sweeper find is submitted under authority or durably prepared (never fixed) and appears
  in Triage.
- **The system is trustworthy:** spot-check that a recently-landed PR's diff actually exercises its
  work item's repro path (the WI-fidelity invariant), and that `OUTDATED` closures each carry a
  passing-on-target test.
- **The extension loops are live:** `dep-sweep` files only *reachable* advisories (unreachable ones
  logged, not filed); each `ci-health` quarantine rides a DRAFT PR **and** a de-flake WI; `post-merge`
  has PASS evidence for every retained landed WI's repro on the latest integrated target, or a
  `regression-filed` entry with an active linked WI or `regression-escalated` prepared handoff,
  alert/evidence, and last checked target SHA;
  every
  `self-improve` PR is a draft that only adds/tightens. And **liveness is observable:** workflow run
  history and the metrics series are advancing (`DESIGN.md` §7.3, §4.5).

See `DESIGN.md` for the full design, the failure→rule table, and the harness-vs-adapter split.
