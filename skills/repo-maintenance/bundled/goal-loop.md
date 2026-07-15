# Goal plus persisted-workflow pattern

Repository maintenance combines two separate mechanisms:

- bundled `/goal` drives one invocation toward concrete success criteria with a
  finite continuation budget;
- `save_workflow` persists a heartbeat that starts a fresh invocation when it is
  time to check for new work.

A loop therefore follows: **drain -> go quiet -> heartbeat -> reconcile -> drain
again**.

## Required capabilities

`/goal` is bundled with the plugin. Persistent standing mode additionally
requires `save_workflow`, `run_workflow`, and `list_workflows`. If those tools
are unavailable, the loop may run on demand but is not armed.

## Invocation contract

Every workflow fire is a fresh session. Its prompt must be self-contained and:

1. load `<repo>-codebase` and the relevant loop skill;
2. run `runtime/repo_identity.py` and use its absolute `state_dir` and
   `backlog_path`;
3. acquire the repository lease with
   `runtime/maintenance_lock.py acquire <state_dir> --loop <loop-name>`, retain
   the returned token, and exit cleanly on busy status without touching Goal or
   shared state;
4. reload the durable backlog file and reconcile it with the live tracker;
5. check the success criteria before doing work and exit cleanly when already
   satisfied;
6. set a finite `/goal` objective when work exists;
7. drain only items permitted by the configured authority mode;
8. heartbeat with `<state_dir>` and the retained token during long delegated
   batches **and immediately before every durable/shared/remote write**;
9. if a heartbeat is nonzero or `not-owner`, terminate immediately before any further durable, shared,
   or remote write. Do not write a shared-state error record or attempt cleanup; emit local/session
   status only. A nonzero/not-owner release is not successful ownership and is reported locally;
10. write every disposition and artifact reference back to the durable backlog only after the pre-write
   heartbeat gate succeeds. Review handoffs include
   the thread/comment ref, draft text, recommended resolution, escalation target/status/time; a prepared
   draft is not a provider-thread tail;
11. release with `<state_dir>` and the retained token on every still-owned exit path;
12. report blockers or budget exhaustion without claiming completion.

The session database is only a working mirror. It never replaces the backlog
file as the cross-invocation source of truth.

**Scope of the lease vs. `/goal`:** steps 3 and 6–9 gate this loop's own repo-shared/durable writes
(the backlog file, `identity.json`, tracker/PR/branch operations, alerts) and this loop's one-time act
of *setting* its `/goal` objective for the fire. They do not reach into `/goal`'s own internal
continuation bookkeeping — `/goal` is a generic, session-scoped skill used far outside repository
maintenance, its state lives under `${COPILOT_PLUGIN_DATA}/goals` rather than under this lease's
`state_dir`, and its `agentStop` hook stays fail-open and functional independent of this lease's
status. Losing the lease stops this loop's own further maintenance writes; it never disables or
gates the ambient Goal continuation hook itself.

The **global PR transport invariant** applies to every automation-created implementation, CI
quarantine, outdated closure, self-improve artifact, and post-merge revert PR; no specialized loop
bypasses it. Before any initial branch or PR mutation, require a live submitted WI linked to the future
PR. If missing, submit it only with persisted `file_tracker_item`; otherwise prepare/escalate the WI and
diff and do not push or open. Persist a two-phase canonical `branch-ownership` record in the
backlog/log. A `pending` absent-remote reservation records source repository identity, exact intended
head ref/class, that WI, creation evidence, and BOTH the persisted `initial_push` (push) grant and the
persisted `open_draft_pr` grant; `initial_push` alone must never authorize the push, since an unopened
DRAFT PR would orphan the remote branch. A lone `open_draft_pr` grant never supplies push authority.
A preflight re-check immediately before the push confirms both grants and the live WI still hold; it
then permits exactly one matching initial push, followed by an immediate DRAFT PR bind to immutable
identity/URL. If PR API creation still fails unexpectedly, forbid further mutation and escalate
cleanup/retry. Every later mutation requires the bound record to match the live PR source and exact
head plus applicable persisted push/update authority; an allowed branch prefix alone never grants
ownership. A missing, failed, pending-after-first-push, or mismatched record is read-only, and human
adoption requires prepare/confirm authority.
For post-merge, a red entry may dedup only to an ACTIVE live WI for its current episode; authority-
granted filing uses `regression-filed`, while conservative mode uses a durable
`regression-escalated` prepared handoff. The current target is complete when it is PASS,
`regression-filed` with an active linked WI and alert/evidence, or `regression-escalated` with a
prepared alert/evidence handoff; retain the last checked target SHA. Every later
target advance reruns **EVERY retained entry**, including prior PASS and red entries; a closed/resolved
WI never satisfies the new episode.

## Loop objectives and heartbeats

| Loop | Goal objective | Suggested heartbeat |
|---|---|---|
| triage | every backlog item has a disposition and artifact | hourly |
| implement | every unlocked `VERIFIABLE` item has an authority-permitted gated draft PR (both `initial_push` and `open_draft_pr` grants plus a live WI) or a durable prepared/escalated handoff | hourly |
| pr-maintenance | every actionable comment has a current durable review-handoff artifact with an escalated status (a human posts) | hourly |
| auto-review | the bounded sweep dispositioned every evidence-backed find (filed with the `file_tracker_item` grant, or a durable prepared/escalated handoff without it) | daily |
| pr-review | targeted PRs were reviewed against a current profile; a prior incomplete scan snapshot/pending set is resumed before capturing a new one | on demand; profile refresh weekly |
| report | the period's digest exists | daily at a chosen local time |
| dep-sweep | every reachable advisory was dispositioned (filed with the `file_tracker_item` grant, or a durable prepared/escalated handoff without it) | daily |
| ci-health | every proven flake has a live submitted de-flake WI + two-phase/both-grant quarantine draft, or a durable prepared WI + diff handoff | hourly after CI activity |
| post-merge | every current entry is PASS, `regression-filed` with an active linked WI, or `regression-escalated` with a handoff; optional revert transport uses that WI + both grants | hourly |
| self-improve | every converged learning has a submitted self-improve WI + two-phase/both-grant draft, or a durable prepared WI + diff handoff | weekly |

Use a custom `cron_expression` when the exact time matters; otherwise use the
coarsest built-in interval that meets the need. Stagger workflows so expensive
loops do not collide.

## Wiring

1. Define the loop name, durable backlog path, authority mode, objective, finite
   budget, no-op predicate, and lease TTL.
2. Save one enabled workflow whose prompt implements the invocation contract.
3. Confirm it appears enabled in `list_workflows`.
4. Proof-fire it with `run_workflow`.
5. Verify that it loads the required skills, serializes against a second lease
   owner, reaches the configured tracker, writes durable state, releases its
   lease, and no-ops when drained.

Do not report the maintenance system as armed until every supported standing
loop is enabled and at least one has been proof-fired.

## Why both mechanisms

A goal without a heartbeat eventually goes quiet forever. A heartbeat without a
goal can repeatedly perform work without a meaningful stop condition. Combining
them provides bounded within-run persistence and durable re-engagement without
busy-looping.
