# Prompt template — post-merge regression sentinel

Dispatch template for the **Post-merge sentinel loop** (`DESIGN.md` §4.9). The system's core anxiety is
the *wrong fix shipped with confidence* — and every gate that defends it (adversarial, WI-fidelity,
regression) runs **before** the PR lands. But the land is the human's call (§9), and two failures can
still appear on the integrated branch that no per-PR gate could have caught, because they only exist
*after* the merge:

1. **Semantic conflict.** Two PRs, each green in isolation, that merge textually clean but break each
   other's behavior when both land (a shared assumption one of them silently changed).
2. **The fix didn't stick.** A later merge reverted, shadowed, or re-broke the exact behavior our fix
   established — so the WI is marked fixed but the bug is live again on the integration target.

This loop is the **integration-level counterpart to the WI-fidelity gate**: WI-fidelity asks *"does
this diff fix the filed bug?"* before merge; the sentinel asks *"did it STAY fixed in production after
landing?"* after merge. Its instrument is the one artifact every landed fix already carries — the
**validated repro test** — re-run on the current integrated target. Fill the `{...}` placeholders.

---

```
FIRST load the {REPO} codebase skill (SKILL.md + the exact build/test recipe + `{TARGET_REMOTE}` /
`{TARGET_BRANCH}` integration target) and the persisted authority configuration. Re-run repro tests on
the integrated target. Each external operation requires its own configured grant:
`file_tracker_item`, `reopen_tracker_item`, `initial_push`, `open_draft_pr`, `send_alert`, later
push/update, or tracker update. Default conservative mode prepares complete durable handoffs and
escalates; it submits nothing externally. A revert is irreversible/shared-state (§9), never automatic.
GOAL GUARD: you are a dispatched sub-agent — NEVER run `/goal` or `goalctl.py`; your tool shell
inherits the ROOT orchestrator's session id, so a Goal mutation would hijack the orchestrator's goal.

PERSISTENT REPRO REGISTRY — `<triage-dir>/landed-repros.json`: key by the original
WI + fix PR and retain the validated repro, merge SHA/time, last verified target
SHA, and number of later target advances checked. Each entry also records the current red episode
(`original WI + repro + red target SHA + suspect merge`), and has a state (`watching`,
`regression-filed`, `regression-escalated`, or an equivalent provider-neutral value).
`regression-filed` records an **ACTIVE live** linked regression WI; `regression-escalated` records the
complete prepared WI/alert handoff. On each target-branch advance:
  1. enroll every durable-backlog maintenance item that landed since the host cursor through a
     VERIFIED covering PR — ours (`ai/wi-*`) OR a teammate/human/external branch the dedup gate
     accepted (verified linked PR/WI + a validated repro); scope to backlog items only, never
     arbitrary team work. A deduped external fix is watched exactly like an agent-authored one. Add
     each one's validated repro to the registry;
  2. re-run **EVERY retained registry entry**, including previously PASS, `regression-filed`, and
     `regression-escalated` entries — not only newly enrolled or red ones.
A green check updates `last_verified_target` and `advances_checked` but never
drops the entry immediately. Default retention is at least 90 days AND at least
20 later target-branch advances; repository policy may extend it. A red check may dedup only to an
**ACTIVE live** regression WI for the same current episode — never blindly to an old closed/resolved WI.
If the prior ticket is closed, reopen only when provider policy and `reopen_tracker_item` authority
permit it; otherwise file a new episode only with `file_tracker_item` authority, or retain a durable
`regression-escalated` prepared handoff. Persist the host merge cursor and last checked target SHA separately.
A current target is complete when every entry is PASS, `regression-filed` with an active linked WI, or
`regression-escalated` with its prepared/escalated handoff; do not require all retained repros to be
green. On every later target advance, rerun EVERY retained entry, update its current episode, and
alert/escalate again when red.

ISOLATION HARD GATE: use an orchestrator-provided isolated workspace created for
this run. Verify its repository root and that it has no user changes. If the
workspace is the shared checkout or is dirty, return BLOCKED; never reset,
clean, stash, or switch the user's checkout.

PIN TO THE REAL INTEGRATION BRANCH: fetch exactly `{TARGET_REMOTE}/{TARGET_BRANCH}` from the codebase
adapter and place only the isolated workspace at that exact commit using the repository's safe workspace
procedure. You are testing the INTEGRATED state (all merges
applied), not any one PR's branch and not the user's working tree. This
integrated state is exactly what no per-PR gate ever saw.

PER WATCHED WI:
  1. RE-RUN ITS VALIDATED REPRO TEST on the integrated target (batch the round's tests → one build; the
     orchestrator/this session owns the build, one at a time, §8). The repro was RED pre-fix and GREEN
     on the fix branch — it MUST be GREEN on the integrated target now.
  2. PASS  → the fix still holds; update its registry evidence and retain it
     until the retention policy is satisfied.
  3. RED    → CURRENT REGRESSION EPISODE. The fix did not survive integration. Diagnose the two likely causes:
       • bisect the merges since the fix landed to find which one re-broke it (semantic conflict), or
       • confirm the fix code is still present (was it reverted/overwritten?).
     Key the episode by ORIGINAL WI + repro + red target SHA + suspect merge(s). Dedup only to an
     ACTIVE live regression WI for this episode. If an older regression WI is closed/resolved, reopen
     only when provider policy and persisted `reopen_tracker_item` authority permit; otherwise, with
     `file_tracker_item` authority, FILE a new episode WI (tagged `post-merge`) carrying the now-RED
     repro (test + "was GREEN on <fix-sha>, RED on integrated <target-sha> at file:line"), ORIGINAL
     WI/PR, and suspect merges. Set `state=regression-filed` only with that active linked WI. Without
     filing authority, set `state=regression-escalated` and persist the complete prepared WI/alert
     handoff. Submit an alert only with persisted `send_alert` authority; otherwise prepare and
     escalate it. Red findings alert/escalate again on every target advance. An optional REVERT draft
     uses this active regression WI as its live submitted WI and invokes the global two-phase
     canonical `branch-ownership` procedure: record the target source repository, exact absent head
     ref/class, WI, evidence, and BOTH persisted `initial_push` and `open_draft_pr` grants in the
     pending reservation. A lone `open_draft_pr` grant never supplies push authority. Preflight, perform
     exactly one initial push, immediately create the DRAFT PR, and bind immutable identity/URL; freeze
     all mutation and escalate on bind failure. Later mutation requires the bound live source/head match
     and applicable push/update authority. If the active WI or either grant is absent, persist a
     drainable prepared regression-WI + revert-diff handoff and do not push or open. Never auto-revert
     someone's merge.
  4. ALSO watch the target's own post-merge build/CI: if the target build broke right after a tracked fix
     landed, that is an immediate red alert (we may have broken the integration branch) — surface it
     before anything else.

DEDUP: a red result dedups only to an ACTIVE live regression WI matching ORIGINAL WI + repro + current
red episode/target. A closed/resolved ticket never satisfies the current fire. A regression WI, once
filed, is Triage/Implement's to fix like any other — the sentinel's job is detection, not the fix.

CHURN/COST: NO-OP only when the target SHA is unchanged and no newly merged fix
needs registering. Any target advance rechecks the retained registry because a
later unrelated merge can re-break an older fix.

CURRENT-FIRE COMPLETION / OUTPUT: regressions found (each with its now-red repro + suspect merge), or
a disposition showing each current entry as PASS, `regression-filed` with its active linked WI, or
`regression-escalated` with its durable prepared/escalated handoff. Report submitted artifacts only
when exact authority granted them; never claim a prepared disposition was submitted or that all retained
repros passed.
```

---

## Why this loop exists
- **Gates are pre-merge; integration is post-merge.** Every verifier in §5 runs on a PR branch in
  isolation. The one state no gate can test is *the integrated target with every other PR also applied* — and that is
  precisely where semantic conflicts live. The sentinel is the only thing that looks there.
- **It reuses the proof we already have.** No new test-writing: the validated repro test that gated the
  fix in is the exact instrument to confirm it stayed fixed. Re-running it on the integrated target is cheap
  and definitive.
- **It closes the system's own loop.** The design's headline failure is "shipped the wrong fix with
  confidence, a human caught it twice." WI-fidelity catches it at the PR; the sentinel catches the
  case where the fix was right at the PR but got clobbered on land — the last place a wrong outcome can
  hide. Detection only: a found regression re-enters the one pipeline as a normal, gated fix.
- **A revert is not routine.** Reverting a landed, human-approved merge is a shared-state action —
  prepared and escalated, never taken by the loop alone (§9).
