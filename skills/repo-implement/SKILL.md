---
name: repo-implement
description: Turn verified items into submitted or prepared gated draft PRs with reproduction, regression, review, and fidelity checks.
version: 1.0.0
user-invocable: true
disable-model-invocation: true
---

# /repo-implement — gated implement loop

Standalone entry point to **loop 2** of the repo-maintenance harness: a verifier wrapped around a
maker. A green build is necessary, never sufficient.

## Run
1. **Load the harness:** resolve this skill's base directory, then read
   `../repo-maintenance/SKILL.md` (§5),
   `../repo-maintenance/prompts/engineer-charter.md`,
   `../repo-maintenance/prompts/adversarial-gate.md`,
   `../repo-maintenance/prompts/wi-fidelity.md`,
   `../repo-maintenance/prompts/outdated-closure.md`, and
   `../repo-maintenance/HARNESS-COPILOT.md`; load the repo's `<repo>-codebase`
   skill (its exact build recipe).
2. **Resolve identity and acquire the lease** (before any durable/shared/remote write, including
   `/goal`): resolve the sibling `repo-maintenance` directory and run
   `runtime/repo_identity.py --cwd <repo-root>` (read-only) for its `state_dir`/`backlog_path` — this is
   `<triage-dir>`. If the conductor already supplied a token, verify ownership with
   `runtime/maintenance_lock.py heartbeat` and retain it; otherwise acquire with
   `runtime/maintenance_lock.py acquire <state_dir> --loop repo-implement` and record that this command
   owns the returned token. On busy or any nonzero result, stop before touching the backlog, `/goal`,
   or the tracker. Heartbeat immediately before every later durable/shared/remote write; a nonzero or
   `not-owner` heartbeat aborts immediately with no further writes. Release the lease on every
   still-owned exit only when this standalone command acquired it (an inherited conductor token remains
   the conductor's). See `HARNESS-COPILOT.md`'s invocation contract for the full pre-write heartbeat
   gate.
3. **Scope:** the current repo + host. Backlog = `<triage-dir>/backlog.md` -> `todos`.
4. **Dedup FIRST:** before working an item, check open PRs for one already covering its work item
   using the provider's verified live WI/issue relationship, then inspect the
   diff against that item's repro. A matching `ai/wi-<id>-*` branch is supporting
   evidence, not a requirement; teammate and human branches count too. For an
   outdated-closure batch, dedup by every linked WI plus the
   `outdated-closure` PR label/title. If coverage is real, mark `IN-REVIEW` and
   hand to `/repo-pr-maintenance` — never open a second PR.
5. **Build (gated):** for each unlocked `VERIFIABLE` item, fan out **code-only** makers via background
   `task` agents (general-purpose; strongest available model); gates = the
   **regression gate** (the full existing suite still green on the fix,
   not just the new repro test) + `code-review` + `security-review` + a `rubber-duck`
   adversarial lens + the WI-fidelity gate (diff vs the WI's *repro steps*, not its title). **This
   session runs builds ONE AT A TIME and owns landing.**
6. **Hard invariant — no PR without a WI:** if an item has no work item, consult the persisted
   `file_tracker_item` authority for this exact operation. With the grant, create it first (tag
   `auto-review` if machine-found; carry the validated repro) and link it before any branch/PR work
   proceeds. Without it, persist a complete `implement-escalated` prepared handoff (title, repro,
   evidence, escalation target/status/time) on the canonical backlog under a valid lease and do not
   proceed to branch/PR mutation for that item — a missing, unsubmitted WI blocks the two-phase
   ownership step below exactly like a missing `open_draft_pr` grant does: no live submitted WI, no PR,
   ever.
7. **Global PR transport invariant — implementation and outdated closure:** invoke this same two-phase
   procedure for either PR type; no specialized mode may bypass it. GitHub/Azure cannot expose a live
   PR until the remote head exists. Before the first push, persist a durable `branch-ownership`
   **pending reservation** in the
   canonical backlog/append-only log: source repository identity, exact intended `refs/heads/...` head
   ref, allowed branch class, a live submitted WI, creation/adoption evidence, and BOTH the persisted
   `initial_push` (push) grant and the persisted `open_draft_pr` grant.
   A live PR is not required before the initial push, but both exact grants and the live submitted WI are:
   `initial_push` granted alone must never authorize the push — pushing a remote head this automation
   cannot then cover with a DRAFT PR (because `open_draft_pr` was never granted) would orphan that
   branch. A lone `open_draft_pr` grant never supplies push authority either. Immediately before
   executing it, a preflight re-check confirms both grants and the live submitted WI still hold. Permit
   **exactly that one initial push** only when the remote ref is absent, both grants and the WI are
   current, and this pending reservation matches. Immediately create a
   **DRAFT** PR and bind the same record to its immutable provider identity and URL. If PR API
   creation still fails unexpectedly, forbid every further branch/remote mutation and escalate a
   cleanup/retry handoff. Only a **bound** record whose live PR source repository and exact head ref
   match, plus applicable persisted push/update authority, may authorize a later push, rebase, or
   update. A branch name is never proof of ownership:
   explicit human adoption may create the record only through
   prepare/confirm authority, never by inference.
8. **Authority:** push only when the branch class is `ai/wi-<id>-*` or the explicit
   `ai/outdated-closure-<date>-<digest>` exception **and** the two-phase durable record permits that
   precise action. Pending permits only the absent-remote initial push; all later writes require the
   bound live-PR match. An unrecorded, failed, pending-after-first-push, or mismatched branch remains
   read-only, regardless of its prefix (never force/delete; never protected). **PRs stay DRAFT**
   (merging escalates to the human). Drain-aware: no-op if no unlocked VERIFIABLE item lacks a PR.
   Closure mode (`prompts/outdated-closure.md`) proves + closes OUTDATED items in one batched PR.
   Release the lease (§2) on every exit path.

To run this continuously, `/maintain-repo` arms it as an hourly heartbeat.
