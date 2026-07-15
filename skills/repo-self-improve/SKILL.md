---
name: repo-self-improve
description: Turn repeated learnings into submitted or prepared self-improve WIs and gated artifact drafts.
version: 1.0.0
user-invocable: true
---

# /repo-self-improve — self-improvement loop

Standalone entry point to **loop 10** of the repo-maintenance harness. The Report cadence (loop 5)
already distills human feedback + the system's friction into "a concrete improvement to the codebase
skill / a gate / a prompt"; this loop turns the **converged** ones into submitted WI + gated draft
pairs or prepared WI + diff handoffs against those artifacts, so the system's scars become durable
edits (`DESIGN.md` §4.10). The most conservative loop in the pack — its blast radius is the whole
verifier.

## Run
1. **Load the harness:** resolve this skill's base directory, then read
   `../repo-maintenance/SKILL.md` (§4.10),
   `../repo-maintenance/prompts/self-improve.md`, and
   `../repo-maintenance/HARNESS-COPILOT.md`; load the repo's `<repo>-codebase`
   skill; read the recent `reports/*.md`.
2. **Resolve identity and acquire the CURRENT repo's lease** (before any durable/shared/remote write,
   including `/goal`): resolve the sibling `repo-maintenance` directory and run
   `runtime/repo_identity.py --cwd <repo-root>` (read-only, current repo) for its `state_dir`/
   `backlog_path` — this is `<triage-dir>`. If the conductor already supplied a token, verify ownership
   with `runtime/maintenance_lock.py heartbeat` and retain it; otherwise acquire with
   `runtime/maintenance_lock.py acquire <state_dir> --loop repo-self-improve` and record that this
   command owns the returned token. On busy or any nonzero result, stop before touching the backlog,
   `/goal`, or either target surface. Heartbeat immediately before every later durable/shared/remote
   write; a nonzero or `not-owner` heartbeat aborts immediately with no further writes. Release the
   lease on every still-owned exit only when this standalone command acquired it (an inherited
   conductor token remains the conductor's). **When the selected learning targets the harness-pack
   surface (a second, separate repository), also resolve and acquire THAT target repository's own
   canonical identity and lease** — see step 2 below and `DESIGN.md` §4.10/§7.1 for the cross-repo
   ordering, heartbeat, and release-order rules. See `HARNESS-COPILOT.md`'s invocation contract for the
   full pre-write heartbeat gate.
3. **Scope — two target surfaces:** the per-repo `<repo>-codebase` skill
   (repo-specific learnings, covered by the current repo's lease above) and, only when the user identifies a writable source
   repository, the **harness pack itself** — a DIFFERENT repository from the one this loop is running
   in. Never edit the installed plugin copy as if it were source; record a proposal when no writable
   source is configured. **Before any write to the harness-pack repository**, resolve its OWN canonical
   identity with `runtime/repo_identity.py --cwd <harness-repo-root>` and acquire/heartbeat/release ITS
   OWN maintenance lease at ITS OWN `state_dir` — never reuse the current repo's token or state_dir for
   a write in the other repository. If both this repo's lease and the harness repo's lease must be held
   at once, acquire them in deterministic canonical-`repo_id` sorted order (lexicographically smaller
   first) to avoid a cross-run deadlock; if the order would have to be violated (the other lease is
   already held out of order), do not force it — prepare/escalate that learning instead. Heartbeat BOTH
   held leases before any cross-repo write, and release them in the REVERSE order they were acquired.
   The branch-ownership pending reservation and the self-improve WI for a harness-pack change live under
   the harness repository's OWN identity/backlog, never the source repo's.
4. **Select converged learnings only:** RECURRENCE (appears across ≥R reports/comments, not a one-off) +
   EVIDENCE (quoted human comment(s) with PR/WI links, or the specific repeated friction) + NOT-ALREADY-
   IN-FLIGHT (dedup vs open `self-improve` PRs). No evidence → no PR.
5. **Self-lobotomy guard (load-bearing):** may ADD a check, ADD a convention, sharpen a prompt, tighten a
   gate — may **NOT** weaken/loosen/delete a gate, a pinned rule, or a documented convention to reduce
   its own send-backs (the bounces are the system working). A relax-safeguard PR is allowed **only** when
   a report records an explicit HUMAN instruction (quoted, linked). Learn from human feedback + friction,
   never from the system's own preference for an easier path.
6. **Act:** for each selected learning, first create and link a dedicated `self-improve` WI only when
   persisted `file_tracker_item` authority grants it. Without that grant, persist a complete drainable
   `self-improve-escalated` handoff containing both the prepared WI and diff, evidence, expected effect,
   classification, and escalation target/status/time; do not push or open. With a live submitted WI,
   invoke the harness's global two-phase canonical `branch-ownership` procedure **against the correct
   target repository's own identity (§2–3)**. PR transport requires
   BOTH persisted `initial_push` and `open_draft_pr` grants in the pending target-source/exact-absent-
   head reservation with WI + evidence; a lone `open_draft_pr` grant never supplies push authority.
   Preflight, perform exactly one initial push, immediately open ONE **DRAFT** PR tagged
   `self-improve`, and bind immutable identity/URL; freeze/escalate on bind failure. Later mutation
   requires the bound live source/head match and applicable push/update authority. If either transport
   grant is missing, prepare/escalate both WI link and diff without remote mutation.
   The draft contains the minimal diff + quoted evidence + falsifiable expected effect ("this clause
   would have caught PR #X") + classification (add-check / add-convention / sharpen-prompt).
   Fan out drafting via background `task` agents using the strongest available
   model where several are independent.
7. **Authority-aware completion:** every selected learning this run ends with either the
   authority-permitted submitted WI + DRAFT PR or, in conservative mode, its durable prepared/escalated
   WI + diff handoff — never claim a prepared artifact was submitted. **Tighten-only, never merge**: this loop
   may only ADD/sharpen a check, convention, or gate, never weaken one (the self-lobotomy guard, §4).
   NO-OP when nothing has converged since the last run. Release every lease still held (§2–3), in
   reverse acquisition order, on every exit path.

To run this continuously, `/maintain-repo` arms it as a weekly heartbeat (aligned with the report/refresh).
