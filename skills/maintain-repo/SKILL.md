---
name: maintain-repo
description: Run the complete gated repository-maintenance conductor, from onboarding through persisted standing loops.
user-invocable: true
disable-model-invocation: true
argument-hint: "[repository or authority mode]"
---

# Maintain Repo

This is the exact alias for `/repo-maintenance` and its user-facing entry point. It runs the complete
conductor; it does not merely describe the maintenance commands or perform a
one-time triage.

Resolve this skill's base directory, read
`../repo-maintenance/SKILL.md`, `../repo-maintenance/HARNESS-COPILOT.md`, and
`../repo-maintenance/DESIGN.md`, then execute the conductor procedure inline.
Preserve every prerequisite, authority boundary, verifier gate, durable-backlog
requirement, and completion condition from the shared harness.

In particular, invoke its global two-phase canonical `branch-ownership` procedure for every
automation-created PR. Require a linked live submitted WI plus BOTH persisted `initial_push` and
`open_draft_pr` grants before the one absent-head initial push; a lone `open_draft_pr` grant never
supplies push authority. Bind the DRAFT PR immediately, freeze/escalate on failure, and allow later
mutation only from the bound live source/head match with applicable push/update authority. If the WI
is missing, submit it only with `file_tracker_item`; otherwise keep the prepared WI + diff handoff
drainable and do not push or open.

Completion requires the repository codebase skill and review profile to exist,
all supported standing loops to be enabled, and at least one loop to have been
proof-fired. If persistent workflow tools are unavailable, report that the
system is not armed and run only the explicitly requested loop on demand.
