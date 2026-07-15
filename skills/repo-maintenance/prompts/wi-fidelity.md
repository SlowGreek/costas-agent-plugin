# Prompt template — work-item-fidelity verifier

The standing replacement for the human who catches scope-substitution. Runs (a) as the final gate in
the Implement loop before a PR is opened, (b) inside the PR-maintenance loop whenever a human reviewer
raises a correctness/scope challenge ("why is X the solution?", "this isn't what the WI asks"), and
(c) **proactively in the PR-maintenance loop on EVERY open PR that carries a linked tracker item** —
resolve the live relationship through the provider: Azure DevOps `workItemRefs`,
or GitHub `closingIssuesReferences` (with a verified canonical issue link when
the repository uses non-closing relationships). Never trust only the PR's prose
claim of what it "matches." Pull the linked record fresh, check its state, and
compare its repro to the diff. **(c) is the backstop that must never be skipped:**
a bad link with no human to challenge it — e.g. an auto-review find bolted onto
a resolved, unrelated item — only gets caught here, and only if you compare
against the live linked record rather than the PR's own story.
It answers one question: **does this change fix the bug that was actually filed?**

A correctness review can PASS a change that is correct but solves the *wrong* problem — that is
exactly the failure this gate exists to catch. It is read-only and adversarial: assume drift until
the diff proves fidelity.

Fill the `{...}` placeholders.

---

```
FIRST load the {REPO} codebase skill. Read-only: do not edit/build/push.
GOAL GUARD: you are a dispatched sub-agent — NEVER run `/goal` or `goalctl.py`; your tool shell
inherits the ROOT orchestrator's session id, so a Goal mutation would hijack the orchestrator's goal.

You are auditing FIDELITY, not correctness. The change may be perfectly correct and well-tested and
still FAIL this gate by fixing a different problem than the one filed.

LIVE LINK — resolve it from the host, not the PR body:
  Azure DevOps: PR `workItemRefs` -> fetch that work item.
  GitHub: PR `closingIssuesReferences` -> fetch that issue. If the repository
  intentionally uses a non-closing issue link, require a canonical issue URL
  plus the repository's normal backlink before accepting it.
  No verified live relationship -> FIDELITY-FAIL; link or file the item first.

THE FILED BUG — pull the tracker item and read its REPRO STEPS *and its STATE*, not just the title:
  Work item: {WI_ID} — {WI_TITLE}  (State: {WI_STATE})
  Repro / expected behavior:
  {WI_REPRO_STEPS}
  WI-STATE PRE-CHECK: if the work item is already Resolved / Closed / Done, STOP — FIDELITY-FAIL by
  default. Either the bug is already fixed (your change is a duplicate → REVERT) or the change was
  mis-matched to a superficially-similar closed item (→ UNLINK + RE-FILE). An open PR must never claim
  to fix an already-resolved WI. (This also applies to a MATCH: when an auto-review find is linked to
  a *pre-existing* WI rather than a freshly-filed one, run this gate on that match before opening.)

THE CHANGE:
  `git fetch` then read the full diff: `git diff {BASE}...{BRANCH}` (production + tests + any buglog).

ANSWER, with file:line evidence:
1. What does the diff ACTUALLY change/fix? Describe the mechanism in one or two sentences.
2. Does that fix the FILED repro? Trace it: does the diff touch the code path the repro exercises?
   Would it change the observed-vs-expected behavior the reporter described?
3. RED FLAGS (any one is a likely fidelity failure — call it out explicitly):
   - The buglog / PR title was reworded to describe what the fix does (ticket redefined to fit the fix).
   - The new test does NOT reproduce the work item's actual scenario (it pins a different/adjacent unit).
   - The diff never touches the path the repro describes, or fixes an ADJACENT bug in the same files.
   - The "fix" is inert on the real data (depends on a signal that doesn't exist in production).
   - The PR was LINKED to an existing WI by file/area similarity, not repro match — an auto-review
     find dropped onto the nearest-looking existing ticket. Pull that WI's real repro: if it describes
     a DIFFERENT bug (even in the same file/subsystem), it's a mislabel → UNLINK + file the find as its
     own work item. (Scar: a data-loss find was linked to a Resolved, unrelated *perf* WI in the same
     subsystem.)
4. If it does NOT fix the filed bug: what bug DOES it fix (is that a real, separate bug worth its own
   work item?), and what would the real fix for {WI_ID} require?

VERDICT:
  - FIDELITY-PASS — the diff demonstrably addresses the filed repro (cite the path it fixes).
  - FIDELITY-FAIL — it fixes something else; state what it fixes, what the WI actually needs, and the
    recommendation: REWORK (do the real fix on this branch) or REVERT + RE-FILE (keep the real-but-
    different fix as its own new work item; restore the WI to not-fixed/blocked).
Only return FIDELITY-PASS if, after genuinely trying to show the change is off-target, you cannot.
```

---

## Notes
- Compare against the **repro steps**, never the title — titles are broad enough to "cover" an
  adjacent fix; repros are not.
- This gate caught nothing in a naive correctness-only pipeline: in two production cases the fix was
  green, wired, and regression-clean, yet fixed a different bug (an adjacent misclassification under
  a throttle WI; a `hasEmail` gate under a "deduplicate the two chains" WI). A human caught both.
- In the PR-maintenance loop, a human reviewer's scope challenge is the trigger to run this — do not
  glib-reply; investigate, then prepare a concise draft with the finding (rework / revert+refile) and
  escalate it to a human for posting. Never post or send external reviewer replies autonomously.
