# Running this harness under Copilot CLI

The original design artifacts retain some **Claude Code** terms (`CronCreate`,
the "Workflow tool", Stop-hooks, and `Task` subagents). The design is
harness-agnostic; this file binds those terms to the capabilities bundled with
the Costas Agent Plugin and the current Copilot host.

> Terminology note: DESIGN.md §11 "harness vs adapter" uses *harness* = the reusable workflow and
> *adapter* = the per-repo codebase skill. This file is a **third thing** — a *CLI* adapter that ports
> the orchestration verbs to Copilot CLI. It does not change the design.

## Verb map (Claude Code → Copilot CLI)

| Capability | Claude Code (as written) | Copilot CLI equivalent |
|---|---|---|
| Onboard a repo → codebase skill | `/learn` (`bundled/learn.md`) | Run bundled `/repo-learn`. It follows `bundled/learn.md`, saves the uniquely identified adapter under the active `$COPILOT_HOME/skills`, and proves one red-to-green test before loops can arm. |
| Drive a loop to done | native `/goal` + **Stop-hook** | Bundled `/goal` + its `agentStop` hook. Use a finite budget and verifiable success criteria; budget exhaustion permits wrap-up but never proves completion. |
| Recurring re-engage heartbeat | `CronCreate "0 17 * * *"` / `/loop 20m` — **session-only, dies on exit** | **`save_workflow`** (`interval: hourly\|daily\|weekly`, or a `cron_expression`). **Persists on disk, survives restart.** `run_workflow` = fire now; `list_workflows` = inspect. |
| Parallel multi-stage fan-out | "Workflow tool" | Bundled `/workflow` for dynamic orchestration, `/ultracode` for bounded persisted fan-out, or background `task` agents when the host provides them. The conductor reads every result before advancing. |
| Agent roles | `Task` subagents (`bug-finder`, `engineer`, `reviewer`, …) | Map to the host's maker, explore, code-review, security-review, adversarial, and research roles. Prefer the highest-capability available model; if a requested model is unavailable, disclose the fallback instead of silently changing it. |
| Backlog = source of truth | file on disk + in-session task list | **Same file on disk** (`<triage-dir>/backlog.md\|json`) + the **`sql` `todos` table** (this session DB). The DB is ephemeral; the file is durable — write every disposition to the file. |
| Issues, work items, PRs, and CI | Host-specific APIs | Detect the repository host. Use GitHub tools or `gh` for GitHub; use available `ado-*` tools for Azure DevOps. Require equivalent read, create/update, PR-thread, link, and CI-run operations before enabling a loop that needs them. |
| Notify the human | `hook-notify.js` | Gated on the persisted `send_alert` authority, like any other outward-facing alert (§9 / SKILL.md Pitfalls). **With the grant**, use an available notification integration; missing credentials are a clean skip, never a hang. **Without it** (default conservative mode), do not send — surface the prepared alert in the maintenance report and escalate instead. |

## What actually changes behaviourally (read these — they're the gotchas)

1. **Goal continuation is bounded.** The bundled `/goal` installs an `agentStop`
   hook and persists its objective in plugin data. Set each loop's success
   criteria as the objective and give it a finite budget. The criteria must be
   concrete and verifiable (an empty backlog query, an existing draft PR, a
   passing test), never vibes. Exhausting the budget is not completion.

2. **Workflows persist on disk (an upgrade).** Claude's crons are session-only and die on exit — hence
   the skill's "re-arm the crons on restart" rehydrate runbook and the "`durable` flag is unreliable"
   pitfall. **Copilot `save_workflow` entries survive restarts**, so that whole class of pain mostly
   goes away: you do **not** re-arm heartbeats on restart. (Verify with `list_workflows`.)

3. **But each workflow fire = a fresh session.** The in-session `todos`/`goal` do **not** carry across
   fires. So every workflow `prompt` must be **self-contained and drain-aware**: on each fire it (a)
   acquires the repository execution lease, (b) reloads the backlog **file** into `todos`, (c) checks
   its success criteria first and **exits immediately (no-op) if already met**, and (d) otherwise sets
   the `goal` and drains. Heartbeat the lease during long batches and release it on every exit path.
   A busy lease exits as a clean no-op without touching `/goal` or shared state. This is exactly the
   "drain-aware phase" fallback in `bundled/goal-loop.md` — under Copilot CLI that fallback is the
   **primary** mode (workflow heartbeat = the re-engage; `goal`+Autopilot = the within-fire drive).

   **Canonical state and lease-token lifecycle:** resolve the installed
   `repo-maintenance` directory, then run:

   ```bash
   python3 <repo-maintenance-dir>/runtime/repo_identity.py --cwd <repo-root>
   python3 <repo-maintenance-dir>/runtime/maintenance_lock.py acquire <absolute-state_dir> --loop <loop-name>
   ```

   Bake the helper's absolute `state_dir` and `backlog_path` into every saved
   workflow prompt. Parse and retain the successful acquire response's `token`
   for this invocation. Exit code `3` means busy and must no-op. During long
   work, run:

   ```bash
   python3 <repo-maintenance-dir>/runtime/maintenance_lock.py heartbeat <absolute-state_dir> --token <token>
   ```

   On every still-owned success, no-op, blocker, budget, or error exit, run:

   ```bash
   python3 <repo-maintenance-dir>/runtime/maintenance_lock.py release <absolute-state_dir> --token <token>
   ```

   **Pre-write heartbeat gate (fail closed):** immediately before **every**
   durable/backlog/log write, shared-state write, branch/remote operation, tracker/PR operation, or
   alert, run the heartbeat command and proceed only on exit 0 (`renewed`). A nonzero result —
   including `not-owner` — terminates the invocation immediately **before any further write**. Do not
   write a shared-state error/disposition, attempt a remote cleanup, or claim completion after losing
   the lease; emit only local/session status. At normal release, `not-owner` or any nonzero release is
   a failed ownership result, not success; report it locally and do not claim the run released/owned the
   lease. Use the available Python 3 command (`python` on hosts where that is the Python 3 executable).
   Never derive the lock root from a worktree-local path.

   **Scope note:** this gate covers this loop's own repo-shared/durable artifacts (the backlog file,
   `identity.json`, tracker/PR/branch operations, alerts) and the loop's own one-time act of *setting*
   `/goal` for the fire. It does **not** extend to `/goal`'s own internal continuation bookkeeping — the
   bundled Goal skill is a generic, session-scoped mechanism used well outside repository maintenance,
   its state lives under `${COPILOT_PLUGIN_DATA}/goals` (not under this lease's `state_dir`), and its
   `agentStop` hook must keep working (and keep being fail-open) regardless of this lease's status. A
   loop that has lost its lease still permits the ambient `/goal` continuation hook to run; it simply
   must not perform any further *maintenance* write itself.

4. **Rehydrate runbook, Copilot version.** On a fresh orchestrator session: reload `backlog.md|json` →
   `todos`, reconcile against the configured live tracker and pull-request host,
   and `list_workflows` to confirm the heartbeats are still armed. Skip the "re-create crons" step —
   they persisted. **Cold-start branch: if `list_workflows` comes back empty (or is missing loops),
   the heartbeats were never armed — arming them is THIS run's job. Do not stop at the reconcile; a
   read-only reconcile with no armed loops is an incomplete run** (see SKILL.md Verification → "The
   system is ARMED").

## Loop wiring under Copilot CLI (mirrors `bundled/goal-loop.md`)

Each loop = a **persisted workflow** (the heartbeat) whose prompt first acquires
the shared lease, is drain-aware, and then sets a **`goal`** (the within-fire
drive). Goal state is scoped to the Copilot session, so another session's stop
hook cannot consume its budget. The repository lease separately serializes
backlog and remote-state mutation. Makers/gates fan out via background `task`
agents while the orchestrator retains the lease.

```
LOOP            goal-skill objective (within-fire drive)              save_workflow heartbeat
triage          every backlog item has a disposition + artifact        hourly  (re-check new items)
implement       every item has an authorized submitted draft or prepared handoff hourly
pr-maintenance  every actionable comment has a current durable review-handoff artifact    hourly
auto-review     this sweep submitted authorized or prepared all new bugs daily
pr-review       targeted PRs reviewed vs a current team profile         per-PR run_workflow; weekly refresh
report          the period's digest exists (learning extracted)         daily  (cron_expression "0 17 * * *")
dep-sweep       reachable advisories submitted or prepared               daily  (or cron on a lockfile change)
ci-health       each proven flake has authority-permitted submitted artifacts or a durable prepared/escalated handoff    hourly (after CI activity; no-op if static)
post-merge      each current entry is PASS, regression-filed with an ACTIVE linked WI, or regression-escalated with a handoff; rerun EVERY retained entry    hourly (no-op when target is unchanged)
self-improve    each learning has a submitted WI/draft or prepared pair  weekly (fixed-cadence, like report)
```

- **Heartbeats (triage/implement/pr-maintenance/auto-review/dep-sweep/ci-health/post-merge)** are
  *re-check* workflows — fire, ask "is there new work?", no-op when there's none (backlog drained, no new
  advisory, static CI history, nothing of ours landed). Keep them coarse (≥ hourly) when idle.
- **report, pr-review *Refresh*, and self-improve** are *fixed-cadence* — they always produce their
  artifact (the digest / the refreshed profile / the converged-learning PRs); use a `cron_expression`
  (`"0 17 * * *"`, or `"0 17 */2 * *"` for every two days), not a daily that fires at midnight.

**Extra read/write surfaces the four extension loops need** (beyond the base verb map): a
**pipeline/run-history** query (`ci-health`, `post-merge` — GitHub Actions or the configured CI API), a
**dependency-audit** run + an **advisory feed** (`dep-sweep` — the ecosystem CLI run by the orchestrator
like any build, plus an OSV/GHSA/host lookup), and **merged-PR polling** (`post-merge`). `self-improve`'s
write target is a **submitted-or-prepared WI + draft pair against the skill-pack repo itself** (or the
`<repo>-codebase` skill). Treat it like any other human-landed draft-PR target; it needs no new verb,
only a second repo to push to — but that second repo means a **second, separate canonical
identity/lease**: resolve and acquire the skill-pack repo's own `repo_identity.py`/`maintenance_lock.py`
state before writing to it, never the current repo's token or `state_dir`. When both must be held at
once, acquire in deterministic `repo_id`-sorted order, heartbeat both before any cross-repo write, and
release in reverse acquisition order (`DESIGN.md` §4.10).

## Swarms and models

The Claude system parallelized via **dynamic workflows**; under Copilot CLI that becomes **swarms of
background `task` agents** (`mode: "background"`). **Use swarms liberally and as necessary** to
parallelize work — whenever a step decomposes into independent units, fan out (one agent per unit /
batch), run them in parallel, and have the orchestrator read each result before advancing (that read
*is* the per-stage verification). It's a tool to reach for, not a mandate to fan out trivial
single-unit steps. Natural fan-out points:

- **Initial backlog seeding** — pulling open work items/issues/PRs + the first
  reconcile: split across parallel agents by tracker pages, PR list, and issue
  list, then merge.
- **Bulk triage** — the first full backlog pass: a swarm of `general-purpose` agents, each
  dispositioning a slice of items (staleness + feasibility pre-checks in parallel), merged back to
  `backlog.md`.
- **PR-profile mining** — the ~100 merged PRs for `/custom-pr-review`: fan a swarm across PR batches,
  each extracting review signals, then synthesize one `review-profile.md`.
- **Implement** — many `VERIFIABLE` items at once (one maker each) + the **3-lens adversarial gate**
  (three refuting agents in parallel) + the style/security gates.
- **Auto-review sweep** — one `explore`/`general-purpose` sweeper per subsystem, in parallel.
- **PR-maintenance** — the multi-PR comment poll farmed to a background agent.
- **Dep-sweep** — one auditor per ecosystem/manifest (npm, pip, go, …), each producing its
  reachable-advisory list, merged + deduped.
- **CI-health** — one analyzer per test-suite/pipeline mining its run-history slice for same-SHA
  disagreement, ranked together.
- **Post-merge** — one repro-runner per just-landed WI, in parallel on the integrated target.

**The orchestrator stays the single owner of builds, landing, and git** (one at a time) — only the
*read-only / code-only* work fans out. Use bundled `/workflow` or `/ultracode`
for cross-session or cross-repo splits and background `task` agents for
in-session fan-out. Bias toward bounded, well-owned agents rather than one long
serial pass.

**MODEL RULE — use the strongest available model for gates and landing-critical
reasoning.** `claude-opus-4.8` at `max` and `gpt-5.5` at `xhigh` are preferred
when available. If they are unavailable, select the strongest permitted
alternative, record the substitution, and keep the same verifier boundaries.

## Setup quickstart (Copilot CLI)

1. **Identity, lease, then adapter (required first):** run `repo_identity.py`
   read-only, acquire the bootstrap lease on its absolute `state_dir`, then run
   `/repo-learn` under that token. Install `<repo>-codebase` at the helper's
   exact `adapter_path` before arming any loops — every
   loop agent loads it first. (Do not arm loops until DESIGN.md §0 onboarding is satisfied for the repo.)
2. **Decide persisted operation authority up front** (DESIGN.md tail): grant or deny each exact
   operation (`file_tracker_item`, `reopen_tracker_item`, `initial_push`, `open_draft_pr`, `send_alert`,
   tracker update, later push/update, and land) and record the escalation boundary. Default
   conservative = **prepare-and-escalate, never
   submit externally**. **This is orthogonal
   to *arming* the loops:** authority governs autonomous pushes and work-item filing — NOT whether you
   stand the loops up. Reviewer replies/comments/thread resolutions are always prepare-and-escalate,
   regardless of push/file authority. Arm all the heartbeats regardless; a conservative
   authority just means they run advisory/escalate-only *within* each fire. "Stay cautious" never means
   "don't arm the loops."
3. **Arm ALL standing loops as persisted `save_workflow` heartbeats — this is the deliverable, not an
   optional proof.** One workflow per loop, each `mode: autopilot`, `enabled: true`, prompt = the
   loop's `prompts/*.md` charter + the exact identity/lease commands above.
   Embed the absolute shared `state_dir`, `backlog_path`, and installed runtime
   path in each prompt; capture its per-run token; if busy, no-op without
   touching Goal or state; otherwise reload the backlog into todos, check success
   criteria first, set the loop's Goal, heartbeat during long work, run the **pre-write heartbeat gate**
   before every durable/shared/remote write, and release on every still-owned exit. A failed
   heartbeat/not-owner terminates locally with no further shared/remote writes. Stagger with
   `cron_expression` to reduce contention:

   | loop | heartbeat | drain-aware goal (within-fire) |
   |---|---|---|
   | triage | hourly | every backlog item has a disposition+artifact |
   | implement | hourly | every unlocked VERIFIABLE item has an authority-permitted gated draft PR (both the persisted `initial_push` and `open_draft_pr` grants plus a live WI, never `initial_push` alone) or a durable prepared/escalated handoff |
   | pr-maintenance | hourly | every actionable comment has a current review-handoff artifact with an escalated status (a human posts) |
   | auto-review | daily | this sweep filed all new bugs with the persisted `file_tracker_item` grant, or persisted a durable prepared/escalated handoff per find (loop-until-dry) |
   | pr-review | weekly refresh + per-PR `run_workflow` | targeted PRs reviewed vs a current profile (ADVISORY — never auto-posts); a prior incomplete scan snapshot/pending set is resumed before any new snapshot is captured |
   | report | `cron_expression "0 17 * * *"` | the period's digest exists |
   | dep-sweep | daily (or cron on a lockfile change) | every reachable advisory + MED+ hygiene item filed with the persisted `file_tracker_item` grant, or persisted as a durable prepared/escalated handoff (never bumps) |
   | ci-health | hourly (after CI activity) | every proven harness flake has authority-permitted submitted artifacts or a durable prepared/escalated handoff |
   | post-merge | hourly | every current entry is PASS, `regression-filed` with an active linked WI, or `regression-escalated` with a durable handoff; rerun EVERY retained entry on every target advance |
   | self-improve | weekly (fixed-cadence) | every converged learning has an authority-permitted submitted self-improve WI + draft PR or a durable prepared WI + diff handoff |

    **Global PR transport invariant:** the conductor uses the existing canonical backlog/append-only
    log for every automation-created implementation, CI quarantine, outdated closure, self-improve,
    and post-merge revert PR. No specialized loop bypasses it. If the required linked WI is missing,
    submit it only with `file_tracker_item`; otherwise prepare/escalate the WI and diff and do not push
    or open. Before any initial branch or PR mutation, persist a two-phase `pending` absent-remote
    `branch-ownership` reservation with source repository identity, exact intended head ref/class, a
    live submitted WI, creation evidence, and BOTH the persisted `initial_push` (push) grant and the
    persisted `open_draft_pr` grant. `initial_push` alone must never authorize the push — that would
    orphan the remote branch with no DRAFT PR able to cover it. A lone `open_draft_pr` grant never
    supplies push authority. A preflight re-check immediately before the push confirms both grants and
    the live WI still hold; that permits exactly one matching initial push only while the remote ref is
    absent, followed immediately by a DRAFT PR bind
    to immutable identity/URL; if PR API creation still fails unexpectedly, forbid further mutation and escalate cleanup/retry.
    `/repo-pr-maintenance` may later mutate only with applicable persisted push/update authority and a
    **bound** allowed `ai/wi-*` or explicit
    `ai/outdated-closure-*` head whose record matches the live PR source and exact head ref; a prefix or
    branch name is never proof. A missing, failed, pending-after-first-push, or mismatched record is
    read-only, and human adoption requires prepare/confirm authority.

    PR-maintenance completion is a durable review-handoff artifact for every new actionable comment,
    carrying the thread/comment ref, draft text, recommended resolution, escalation target/status/time.
    It is not a provider-thread tail: never claim a prepared draft appears in the provider thread.
    Post-merge `regression-filed` entries remain monitored only with an ACTIVE linked WI; conservative
    fires use durable `regression-escalated` prepared handoffs. Each current entry completes as PASS,
    `regression-filed`, or `regression-escalated`, with current target/suspect evidence and last checked
    target SHA recorded.
    Every later target advance reruns **EVERY retained entry**, including prior PASS and red entries;
    a closed/resolved WI never satisfies a new red episode.

   Release the bootstrap lease, then **`run_workflow` one** (e.g. triage) to
   prove the wiring — it loads the skills, reaches the configured tracker,
   and no-ops on a drained backlog — and **`list_workflows` to confirm every loop is armed + enabled.**
   *Done = the list shows all standing loops enabled, not a one-time triage* (SKILL.md Verification →
   "The system is ARMED").
4. **Fan-out the implement loop** with background `task` agents (`general-purpose`, strongest available model) per
   `VERIFIABLE` item; gates = `code-review` + `security-review` + a `rubber-duck` adversarial lens; the
   orchestrator owns builds and uses the configured host integration for draft-PR creation.
5. **Backlog stays a file**; `todos` is the per-session mirror. Reconcile on every fresh session.
   The repository lease serializes Goal and backlog mutations; item ownership
   still prevents duplicate work inside a run.

Everything else in `SKILL.md` / `DESIGN.md` / `prompts/` applies unchanged.
