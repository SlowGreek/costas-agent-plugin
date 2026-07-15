# Prompt template — self-improvement loop (report learnings → gated PRs)

Dispatch template for the **Self-improvement loop** (`DESIGN.md` §4.10). The Report cadence (§4.5)
already does the hard part: it mines the ground-truth signal — human reviewer feedback and the
system's own friction — and distills each into *"a concrete improvement to the codebase skill, a gate,
or a prompt."* But today those improvements sit in a digest until a human hand-applies them. This loop
closes the continuous-improvement loop the design aspires to: it turns the report's converged learning
items into **submitted WI + gated DRAFT pairs or prepared WI + diff handoffs against the artifacts
themselves**, so the system's own scars become durable edits to how it works.

It is deliberately the most conservative loop in the pack, because its blast radius is the whole
system: an edit to a gate or a prompt changes how *every future change* is verified. So it is **strict
prepare-and-escalate** — it opens draft PRs with evidence and never merges them, and it may **only add
or sharpen safeguards, never weaken one to make its own life easier.** Fill the `{...}` placeholders.

---

```
FIRST load the {REPO} codebase skill AND read the recent reports ({REPORTS_DIR}/*.md). Prepare-and-
escalate ONLY: you submit dedicated WIs and DRAFT PRs only under every persisted exact grant; otherwise
you prepare both artifacts. A human reviews and lands every PR. You never merge, and you never touch
running loops' state.
GOAL GUARD: you are a dispatched sub-agent — NEVER run `/goal` or `goalctl.py` (this applies beyond
"running loops' state" above — it covers ANY session's Goal, including one you cannot see). Your tool
shell inherits the ROOT orchestrator's session id, so a Goal mutation would hijack the orchestrator's
goal.

TWO TARGET SURFACES (a learning item names which it belongs to):
  • the per-repo `<repo>-codebase` skill — repo-specific learnings (a new convention a reviewer
    enforced, a domain fact, a build gotcha, a style rule). Lives at `{CODEBASE_SKILL_REPO_OR_PATH}`,
    covered by the orchestrator's existing repository lease for THIS repo.
  • the HARNESS itself — the `repo-maintenance` skill pack (a gate that missed a class of bug, a prompt
    that needs a new clause, a taxonomy gap). Lives in its OWN repo `{HARNESS_REPO}`; a PR there
    improves the harness for every repo it runs on.

CROSS-REPO LEASE (load-bearing when the target is `{HARNESS_REPO}`): `{HARNESS_REPO}` is a DIFFERENT
repository from the one this loop runs in, with its own canonical identity and its own
`runtime/maintenance_lock.py` state. Never reuse this run's current-repo lease token or `state_dir` for
a write there. Before any branch/PR/backlog write against `{HARNESS_REPO}`, its own canonical identity
(`repo_identity.py --cwd {HARNESS_REPO}`) and its own lease must be acquired — report back to the
orchestrator so it can acquire that second lease rather than assuming this one covers it. If both this
repo's lease and `{HARNESS_REPO}`'s lease must be held at once, they are acquired in deterministic
`repo_id`-sorted order (lexicographically smaller first); never force an out-of-order second acquire —
prepare/escalate the learning instead. Heartbeat BOTH held leases before any cross-repo write, and
release them in the REVERSE order they were acquired. The branch-ownership pending reservation and the
`self-improve` WI for a harness-pack change are recorded under `{HARNESS_REPO}`'s OWN identity/backlog,
never under the source repo's.

SELECT — only CONVERGED, EVIDENCED learnings become PRs (same bar the report uses to flag a priority):
  1. RECURRENCE: the learning appears across ≥{R} reports / comments, not a one-off. A single reviewer
     aside is a data point, not yet a rule. (One-offs stay in the digest.)
  2. EVIDENCE: it cites concrete artifacts — the exact human comment(s) quoted with PR/WI links, or the
     specific repeated friction (e.g. "the adversarial gate sent back the same class of change N times").
     No concrete evidence → no PR.
  3. NOT ALREADY IN FLIGHT: dedup against open self-improve PRs by the rule/evidence.

THE SELF-LOBOTOMY GUARD (the load-bearing rule — read twice):
  This loop may ADD a check, ADD a convention, sharpen a prompt, tighten a gate. It may NOT weaken,
  loosen, or delete a gate, a pinned rule, or a documented convention to reduce its own send-backs.
  "The adversarial gate keeps bouncing my changes, so loosen it" is EXACTLY backwards — the bounces are
  the system working. A change that REMOVES or relaxes a safeguard is only allowed when the REPORT
  records an explicit HUMAN instruction to do so (quoted, linked); never on the loop's own initiative.
  Mirror the pr-review echo-chamber split (§4.6): learn from HUMAN feedback and the system's FRICTION,
  never from the system's own preference for an easier path. The system does not get to make itself
  weaker.

FOR EACH SELECTED LEARNING:
  1. Create and link a dedicated `self-improve` WI only when persisted `file_tracker_item` authority
     grants this exact operation. Otherwise prepare the complete WI and diff together in a drainable
     `self-improve-escalated` handoff and escalate; do not push or open.
  2. With that live submitted WI, invoke the global two-phase canonical `branch-ownership` procedure.
     PR transport requires BOTH persisted `initial_push` and `open_draft_pr` grants in the pending
     reservation for the target source repository and exact absent head ref/class, with WI + evidence.
     A lone `open_draft_pr` grant never supplies push authority. Preflight all prerequisites, perform
     exactly one initial push, immediately open ONE DRAFT PR, and bind immutable identity/URL; freeze
     every mutation and escalate if binding fails. Later mutation requires the bound live source/head
     match and applicable push/update authority. Missing either transport grant means prepare/escalate
     the WI and diff without remote mutation.
  3. The draft on the right surface contains:
  - the DIFF: the minimal edit to the codebase skill / the gate prompt / the taxonomy that encodes the
    learning. Smallest reviewable change; match the artifact's existing voice.
  - the EVIDENCE: the quoted human comment(s) / the friction, with PR/WI/report links.
  - the EXPECTED EFFECT: what this would have caught — e.g. "this clause added to wi-fidelity.md would
    have flagged PR #{X}, where the fix solved an adjacent bug." Make it falsifiable.
  - the CLASSIFICATION: add-check / add-convention / sharpen-prompt (a relax-safeguard PR must quote the
    human authorization or it is not opened at all).
     Keep it DRAFT, tagged `self-improve`. Escalate the PR to the human for review. Do NOT merge.
     Never claim a prepared WI or diff was submitted.

CADENCE: weekly (aligned with the report/pr-review refresh), or when a report flags a recurring
priority. NO-OP when no learning has converged since the last run — a quiet week means the system has
already absorbed its recent feedback, which is success, not idleness.

OUTPUT: submitted WI + draft PR pairs, durable prepared WI + diff handoffs, or "no converged learnings
this period".
```

---

## Why this loop exists (and why it is the most conservative)
- **The report finds; nothing applied.** §4.5 already produces the highest-value output in the pack —
  human feedback mapped to a concrete fix to a skill/gate/prompt. Leaving it as prose means the same
  reviewer comment recurs and the same gate keeps missing. This loop makes the feedback *stick*.
- **Prepare-and-escalate, always.** A prompt/gate edit changes verification for every future change —
  far too high blast radius to auto-merge. Every self-improvement is a draft PR a human lands, exactly
  like the pr-review loop's outbound comments (§4.6, §9).
- **The guard is the whole risk.** An improvement loop with a bug optimizes for fewer send-backs — and
  the cheapest way to get fewer send-backs is to weaken the gates. That is self-lobotomy, and it is the
  one thing this loop must never do. It may only make the system *more* careful; loosening a safeguard
  requires a human's explicit, recorded say-so.
- **Two repos, one discipline.** Repo-specific lessons harden the `<repo>-codebase` adapter; harness
  lessons harden the pack for everyone. Both go through the same evidence bar and the same human land.
