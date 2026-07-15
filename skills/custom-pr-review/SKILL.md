---
name: custom-pr-review
description: Learn a team's demonstrated PR review standards from merged history and apply them as advisory findings.
version: 1.0.0
user-invocable: true
---

# /custom-pr-review — learned team-style reviewer

Standalone entry point to **loop 6** of the repo-maintenance harness. It learns *how this team
reviews* from merged history and applies that taste as advisory findings — augmenting, never
replacing, the static style gate.

## Run
1. **Load the harness:** resolve this skill's base directory, then read
   `../repo-maintenance/SKILL.md` (§6), `../repo-maintenance/prompts/pr-review.md`,
   `../repo-maintenance/review-profile.template.md`, and
   `../repo-maintenance/HARNESS-COPILOT.md`. Load the repo's `<repo>-codebase`
   skill (run `/repo-learn` first if it is missing).
2. **Resolve identity and acquire the lease** (before any durable/shared/remote write, including
   `/goal`): resolve the sibling `repo-maintenance` directory and run
   `runtime/repo_identity.py --cwd <repo-root>` (read-only) for its `state_dir`/`backlog_path` — this is
   `<triage-dir>` (the profile also lives under it). If the conductor already supplied a token, verify
   ownership with `runtime/maintenance_lock.py heartbeat` and retain it; otherwise acquire with
   `runtime/maintenance_lock.py acquire <state_dir> --loop custom-pr-review` and record that this
   command owns the returned token. On busy or any nonzero result, stop before touching the profile,
   `/goal`, or any scan-cursor state. Heartbeat immediately before every later durable/shared/remote
   write; a nonzero or `not-owner` heartbeat aborts immediately with no further writes. Release the
   lease on every still-owned exit only when this standalone command acquired it (an inherited
   conductor token remains the conductor's). See `HARNESS-COPILOT.md`'s invocation contract for the
   full pre-write heartbeat gate.
3. **Scope & host:** the current repo, via its host — Azure DevOps (`ado-repo_pull_request` /
   `_thread`) or GitHub (`gh pr`).
4. **Refresh the profile:** mine the **N most-recently-MERGED PRs against the default branch**
   (default N≈100) for recurring asks, bounce triggers, and review-only conventions. **Fan out a swarm
   of background `task` agents** using the strongest available model across PR
   batches (each extracts signals from its batch). **Resume before capturing anything new:** if a
   persisted prior scan snapshot/high-watermark has a non-empty pending-PR set, that scan is
   INCOMPLETE — drain it against the SAME snapshot/high-watermark (retrying each pending PR until it is
   processed or explicitly dispositioned with provider evidence; a PR closing/unmerging mid-scan is
   dispositioned with its final-state evidence, never silently dropped) before touching a new one. Only
   then, on every refresh, capture an immutable open-PR
   snapshot plus a scan-start comment high-watermark, seed the pending set with that exact snapshot, and poll each snapshot PR for human comments
   newer than **that immutable PR's own cursor** and no newer than the high-watermark. Advance only
   that PR's cursor and remove it from the pending set after its successful processing; new events after the watermark wait for the
   next refresh. Keep the merged-PR style cursor separate. Then
   synthesize one `review-profile.md` with a dated CHANGELOG diff. **Pinned + codebase-skill rules are
   sacrosanct.**
5. **Echo-chamber guard:** learn *preferences* from human comments on **all** PRs (incl. bot ones),
   but *style exemplars* from **human-authored diffs only** — never from our own bot diffs.
6. **Apply (advisory):** run the profile over the target PRs (default scope `our-draft-PRs-only`);
   write findings to a file and surface them in the report. **Never auto-post; never block.** A human
   posts anything that ships. Release the lease (§2) on every exit path.

To run this continuously, `/maintain-repo` arms it as a weekly heartbeat.
