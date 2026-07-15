# Prompt template — dependency / supply-chain sweeper (SUBMIT OR PREPARE ONLY)

Dispatch template for the **Dependency-sweep loop** (`DESIGN.md` §4.7). It is the auto-review sweeper
(§4.4) pointed at a different surface: not *our* code, but the **dependency surface** — the lockfiles,
manifests, and the transitive tree — hunting for **known-vulnerable, deprecated, or abandoned
dependencies**. Like auto-review it is **SUBMIT OR PREPARE ONLY**: it submits a WI only with persisted
`file_tracker_item` authority and otherwise prepares a complete handoff; it never bumps a version or
edits a lockfile. Every submitted-or-prepared find re-enters Triage, where a bump is dispositioned
like any other change (a patch bump with green tests → `VERIFIABLE`; a breaking major →
`NEEDS-DECISION`). There is no privileged "see a CVE, bump it" path, because an unscoped auto-bump is
the same freelance behavior the whole system prevents — and a dependency bump is one of the highest
blast-radius changes there is.

The one idea that keeps this high-signal (and stops it becoming Dependabot-style noise) is
**reachability**: a CVE against a package we depend on but never *call on a vulnerable path* is not a
work item — it is the dep-sweep analog of an auto-review find with no failing repro test. Fill the
`{...}` placeholders.

---

```
FIRST load the {REPO} codebase skill (SKILL.md + the declared ecosystem + the audit recipe). Read-only:
with the persisted `file_tracker_item` grant you FILE dependency work items; without it you PREPARE
complete durable WI handoffs. You do NOT bump, edit a lockfile, or open a fix PR. The FIX is the
Implement loop's job, through the gates — your job is to find and prove.
GOAL GUARD: you are a dispatched sub-agent — NEVER run `/goal` or `goalctl.py`; your tool shell
inherits the ROOT orchestrator's session id, so a Goal mutation would hijack the orchestrator's goal.

TARGET BRANCH (same discipline as the code sweeper): load `{TARGET_REMOTE}/{TARGET_BRANCH}` from the
codebase adapter and audit that exact target lockfile/manifest, NOT the working tree's — a stale or dead branch's lockfile
produces finds that can never land against the target. Fetch the target ref,
then read it with `git show` or use an orchestrator-provided isolated workspace
at that exact commit. Never reset, clean, stash, or switch the shared checkout.

CHURN-GATE (do this FIRST, every fire — a dependency sweep has TWO churn sources, not one):
  • the dependency set changed  → the target lockfile/manifest advanced since `.last-dep-sweep` (record
    a hash of the resolved lockfile), OR
  • the advisory feed advanced  → a NEW advisory was published against the UNCHANGED set (a CVE can
    land against a lockfile that hasn't moved in months — this is the case a HEAD-only churn-gate
    misses, so key the marker on {lockfile-hash + advisory-feed-cursor/date}, never on HEAD alone).
  If NEITHER moved → NO-OP immediately. Add one periodic full re-audit (e.g. weekly) regardless.

AUDIT the dependency surface using the codebase skill's declared ecosystem tool(s) — e.g.
`npm audit --json` / `pip-audit` / `go list -m -u -json all` + `govulncheck` / `osv-scanner` / the
host's advisory feed (GitHub/GHSA, OSV, or ADO). Two find-classes, filed at different bars:

  A) SECURITY  — a published advisory (CVE / GHSA / OSV id) affecting a version we actually resolve.
     THE REACHABILITY PROOF (this is your "failing repro test" — no proof, no tracker item):
       1. Confirm we resolve a version IN the vulnerable range (from the target lockfile, not the
          manifest's caret range — the resolved pin is what ships).
       2. Confirm the vulnerable symbol/path is REACHABLE from our code: a direct dependency we call,
          or a transitive one on a code path we actually exercise. Prefer a call-graph/reachability
          tool where the ecosystem has one (`govulncheck`, `osv-scanner --call-analysis`); otherwise
          grep the import/usage and state the reachable entry point with file:line.
       3. UNREACHABLE = the advisory is against a dev-only, unused, or never-called transitive dep →
          this is the dep-sweep equivalent of a test that passes pre-fix. Do NOT file a tracker WI;
          log it on the on-disk backlog as `dep-unreachable` (so we don't re-triage it) and move on.
          (Scar-class this defends: a wall of red "critical" audit findings that are all in an unused
          transitive branch — noise that trains the team to ignore the tracker.)

  B) HYGIENE  — no advisory, but the dependency is DEPRECATED, ABANDONED (no release / unmaintained
     upstream past the codebase-skill staleness threshold), or pinned so far behind that a security
     fix would be un-adoptable. Lower priority than (A); filed only at MED+ and within the cap.

For each find that clears its bar:
  1. DEDUP HARD against OUR backlog ({BACKLOG_REF}) + open PRs by {advisory-id + package} (SECURITY)
     or {package} (HYGIENE) — a repeated sweep must NEVER re-file the same CVE or the same stale dep.
  2. FILING BAR — keep the tracker quiet: SECURITY finds file at MED+ with reachability proven;
     HYGIENE at MED+ only. Respect the daily cap AND the open-`dep-sweep`-WI backpressure ceiling
     (if the open queue already exceeds the codebase-skill ceiling, STOP filing to the tracker, keep
     logging on-disk until it drains — an unattended sweep must never pile un-actioned bumps on the team).
  3. FILE a NEW work item — consult the persisted `file_tracker_item` authority for this exact
     operation. **With the grant**, file it (its OWN ticket — never adopt a pre-existing one), tagged the repo's
     `dep-sweep` label, in the repo's bug/security area, with:
       title:      Bump {package} {current}→{fixed} — {advisory-id or "deprecated/abandoned"}
       evidence:   advisory id + summary; vulnerable range; OUR resolved version; the fixed version;
                   the REACHABILITY note (reachable entry point file:line, or why it's a direct dep);
                   for HYGIENE: last-release date / deprecation notice.
       severity:   the advisory's severity, DOWNGRADED if reachability is indirect/uncertain (a
                   reachable critical stays critical; an unproven-reachable one is not filed at all).
       fix-shape:  patch/minor bump (likely VERIFIABLE — the regression gate §5.4 is load-bearing
                   here) vs. MAJOR bump / a required migration (flag as likely NEEDS-DECISION so
                   triage escalates the breaking change instead of a maker silently eating it).
     Then MIRROR the item into {BACKLOG_REF} tagged `src=dep-sweep`. **Without the grant**, do not file
     to the tracker: persist the same title/evidence/severity/fix-shape as a complete
     `dep-sweep-escalated` prepared handoff on {BACKLOG_REF} (canonical local write, no external
     authority required under a valid lease) and escalate it; never claim it was filed. Then move on —
     do NOT bump it.

STOP DISCIPLINE: loop-until-dry — after a full audit surfaces nothing new (post-dedup), that's a dry
round; stop after {K} dry rounds. Report items filed + the dry-round status.

OUTPUT: the list of filed dependency work items (or "none — dry round"), each with its advisory id,
resolved-vs-fixed versions, and reachability proof.
```

---

## Why file-only (and why reachability is the whole game)
- **File-only, same as auto-review.** A bump re-enters Triage and inherits every safeguard — a human
  can veto a risky major bump (`NEEDS-DECISION`) before a line moves, and the fix goes through the
  gates (especially the **regression gate §5.4** — a green audit says nothing about whether the bump
  breaks *us*).
- **Reachability is the noise filter.** The reason dependency bots get muted is they file every CVE in
  the transitive closure regardless of whether the vulnerable code is ever called. Requiring a
  reachable path (the analog of auto-review's mandatory failing repro test) is what keeps the tracker
  trustworthy — few, real, exploitable-here items, not a wall of red.
- **Two churn sources.** Unlike the code sweeper (code changes → new bugs), a dependency find can
  appear with *zero* code change: a new advisory published against a frozen lockfile. The churn-gate
  must watch the advisory feed, not just HEAD — otherwise a freshly-disclosed CVE sits unseen until
  someone happens to touch the lockfile.
- **Bumps are high blast-radius.** A dependency bump can change behavior across the whole app; it is
  exactly the class of change the adversarial + regression gates exist for. Never let the sweeper
  short-circuit them.
