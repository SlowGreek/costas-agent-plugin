---
name: repo-post-merge
description: Re-run landed fixes, then submit authorized or prepare regression WIs and optional revert drafts.
version: 1.0.0
user-invocable: true
disable-model-invocation: true
---

# /repo-post-merge — post-merge regression sentinel

Standalone entry point to **loop 9** of the repo-maintenance harness. Every §5 gate runs *before* the
merge; this loop watches *after* it — the one state no per-PR gate can see is the **integrated target with
every other PR also applied** (`DESIGN.md` §4.9). WI-fidelity asks "does the diff fix the filed bug?";
the sentinel asks "did it stay fixed after landing?"

## Run
1. **Load the harness:** resolve this skill's base directory, then read
   `../repo-maintenance/SKILL.md` (§4.9),
   `../repo-maintenance/prompts/post-merge.md`, and
   `../repo-maintenance/HARNESS-COPILOT.md`; load the repo's `<repo>-codebase`
   skill (its build/test recipe + exact `{TARGET_REMOTE}/{TARGET_BRANCH}` integration target).
2. **Resolve identity and acquire the lease** (before any durable/shared/remote write, including
   `/goal`): resolve the sibling `repo-maintenance` directory and run
   `runtime/repo_identity.py --cwd <repo-root>` (read-only) for its `state_dir`/`backlog_path` — this is
   `<triage-dir>`. If the conductor already supplied a token, verify ownership with
   `runtime/maintenance_lock.py heartbeat` and retain it; otherwise acquire with
   `runtime/maintenance_lock.py acquire <state_dir> --loop repo-post-merge` and record that this
   command owns the returned token. On busy or any nonzero result, stop before touching the backlog,
   `/goal`, or the tracker. Heartbeat immediately before every later durable/shared/remote write; a
   nonzero or `not-owner` heartbeat aborts immediately with no further writes. Release the lease on
   every still-owned exit only when this standalone command acquired it (an inherited conductor token
   remains the conductor's). See `HARNESS-COPILOT.md`'s invocation contract for the full pre-write
   heartbeat gate.
3. **Scope:** the current repo + host. Backlog = `<triage-dir>/backlog.md`;
   persistent registry = `<triage-dir>/landed-repros.json`; cursors track the
   host merge position and last checked target SHA.
4. **Watch list:** enroll every durable-backlog maintenance item that just landed
   through a **verified covering PR** — ours (`ai/wi-*`) **or** a teammate/human/external
   branch the dedup gate accepted (verified linked PR/WI + a validated repro), scoped to
   backlog items only (never arbitrary team work). A deduped external fix is retained and
   rerun exactly like an agent-authored one. Add each item's validated repro to the
   persistent registry. On every target-branch advance, recheck **EVERY retained entry**, including
   previously PASS and `regression-filed`/`regression-escalated` entries. Retain each for at least 90 days and 20 later target advances; green
   updates evidence but does not immediately remove it.
5. **Pin an isolated clean workspace to the integrated target
   (`{TARGET_REMOTE}/{TARGET_BRANCH}` from the codebase adapter)** after fetching; never reset the shared checkout. Use the current target ref
   (all merges applied), not any one PR branch. **Re-run each watched WI's validated repro**
   (batch → one build; this session owns builds one at a time, §8): it was RED pre-fix and GREEN on the
   fix branch, so it MUST be GREEN on the integrated target. **PASS →** update and retain its registry
   record. **RED → episode handling:** record the original WI + repro + current target SHA + suspect
   merge as a new/current red episode. Dedup only to an **ACTIVE live** regression WI for that same
   episode; a closed/resolved historical ticket never completes it. If a prior WI is closed, reopen it
   only when provider policy and persisted `reopen_tracker_item` authority both allow it; otherwise
   create a new episode WI only with persisted `file_tracker_item` authority. With filing authority,
   set `regression-filed` only after an active linked WI exists. Without it, set
   `regression-escalated` with a durable prepared WI/alert handoff. Submit an alert only when persisted
   `send_alert` authority grants it; otherwise prepare and escalate it again with current evidence.
   Also alert/escalate again if the target's own build broke after a tracked fix landed. The target is
   complete when each current entry is PASS, `regression-filed` with its active linked WI, or
   `regression-escalated` with its durable prepared/escalated handoff; it is never an all-green-only
   requirement. On every later target advance, rerun **EVERY retained entry**, recover it to PASS with
   new evidence, or update its current episode and alert/escalate again.
6. **Authority and optional revert transport:** only persisted configured authority grants
   `file_tracker_item`, `reopen_tracker_item`, `initial_push`, `open_draft_pr`, `send_alert`, later
   push/update, or tracker updates; default conservative mode prepares complete drainable handoffs and
   escalates. A revert draft must link the current episode's active regression WI and invoke the
   harness's global two-phase canonical `branch-ownership` procedure. That live submitted WI plus BOTH
   persisted `initial_push` and `open_draft_pr` grants must be in the pending target-source/exact-
   absent-head reservation with evidence; a lone `open_draft_pr` grant never supplies push authority.
   Preflight, perform exactly one initial push, immediately create the **DRAFT** PR, and bind immutable
   identity/URL; freeze/escalate on bind failure. Later mutation requires the bound live source/head
   match and applicable push/update authority. Without any prerequisite, prepare/escalate the revert
   diff with the regression-WI handoff and do not push or open; never auto-revert. NO-OP when the target
   SHA is unchanged and no new fix needs registering. Release the lease (§2) on every exit path.

To run this continuously, `/maintain-repo` arms it as an hourly heartbeat (after merges land).
