# Prompt template — periodic digest / report (daily or every 2 days)

Dispatch template for the **Report cadence** — a digest that runs once a day (or every two days) and
explains what the system did, what's worth *learning* from, and what needs the human. It is the
accountability + continuous-improvement layer over the work loops: it doesn't act on the repo,
it observes the backlog + the durable log + the PR threads over the period and produces a bundled
report. Fill the `{...}` placeholders.

The single highest-value section is **human feedback worth learning from** — human reviewer comments
are the ground truth, and each one should be mined for a concrete improvement to the system itself
(the codebase skill, a gate, a prompt), not just acknowledged.

---

```
FIRST load the {REPO} codebase skill. Read-only: this produces a report, it does not change code.
GOAL GUARD: you are a dispatched sub-agent — NEVER run `/goal` or `goalctl.py`; your tool shell
inherits the ROOT orchestrator's session id, so a Goal mutation would hijack the orchestrator's goal.

PERIOD: {SINCE} → {NOW}. Gather from: the backlog (task list), the durable run log, and the PR
reviewer threads, restricted to this window.

Produce a bundled report with these sections:

1. HEADLINE — one line: is the backlog draining or growing this period, and the single most important
   thing that happened.

2. BY THE NUMBERS
   - Backlog filed: new items this period, broken down by source (human / auto-review sweeper /
     engineer-discovered).
   - Backlog handled: items triaged this period, broken down by disposition (OUTDATED / NOT-ACTIONABLE
     / NEEDS-QA / VERIFIABLE / NEEDS-DECISION); items still untriaged.
   - PRs: draft PRs opened, PRs landed, PRs in flight.
   - Auto-review: bugs the sweeper filed.
   - Reviewer activity: comments received (human vs bot), replied, reworked-in-response.
   - Extension loops: dependency advisories filed (reachable) vs. logged-unreachable; flaky tests
     quarantined + de-flake WIs raised; post-merge regressions caught on the integrated target; self-improvement
     draft PRs opened against the codebase skill / the harness.
   - Append this period's counts to the durable metrics series ({METRICS_PATH e.g. metrics.jsonl}) so the
     trend is computed from history, not eyeballed.

3. GATE PERFORMANCE — what the verifier stack caught: WI-fidelity catches (fixes that were green but
   solved the wrong/adjacent bug), adversarial-gate catches, regression-gate catches (greened its own
   test but red a neighbor), feasibility rejections (inert-on-real-data), staleness OUTDATED closures,
   and post-merge regressions (a landed fix that didn't stay fixed on the integrated target). A high
   catch-rate is the system working, not failing.

4. HUMAN FEEDBACK WORTH LEARNING FROM  ← the important one.
   For each substantive HUMAN reviewer comment this period, extract the lesson and a concrete action:
     - A scope/correctness challenge the gates missed → strengthen which gate, or what the WI-fidelity
       check should also look for.
     - A repeated style/convention nit → add it to the codebase skill so future PRs avoid it.
     - A domain fact the reviewer supplied → fold into the codebase skill.
     - A "why did you do X" that revealed a wrong assumption → the assumption to drop.
   Format each: comment (quoted, with PR/WI) → pattern → suggested improvement (skill / gate / prompt).
   If a pattern recurs across comments, call it out as a priority.

5. ISSUES & FRICTION — honest self-report of what the system struggled with: build hangs/retries,
   items it couldn't disposition, "can't-be-done" verdicts that needed re-tracing, gates that sent the
   same change back repeatedly, anything that stalled. Do not hide skipped or failed steps.

6. NEEDS THE HUMAN — the queue you must look at: NEEDS-DECISION items (with their question), NEEDS-QA
   items (with their check), pending landing-authority approvals, and any open escalations.

7. TREND / NEXT — backlog burn-down vs. inflow, gate catch-rate and revert-rate trend, rough cost, and
   the one or two things to focus on next period. Raise a DEGRADATION ALARM (escalate as NEEDS-DECISION)
   if a signal is moving the wrong way — revert-rate climbing, gate catch-rate falling, inflow outpacing
   burn-down for N periods, or a loop that filed/handled nothing across its expected cadence (a
   silent-death tell).

OUTPUT: write the report to {REPORT_PATH e.g. reports/{date}.md}. Keep it skimmable — numbers up top,
the learning section concrete, the friction honest. Notification is outward-facing communication like
any other: consult the persisted `send_alert` authority before sending anything. **With the grant**,
if a delivery channel is configured (email / chat), send a one-line "digest ready" pointer; do not dump
the whole report into a channel unasked; a missing/expired credential or tenant is a clean, distinct
skip, never a hang or a headless interactive re-auth. **Without the grant** (default conservative
mode), do not send: prepare the exact pointer text and surface it, escalated, in the run result —
never claim it was sent. The report FILE is always the source of truth regardless of delivery.
```

---

## Notes
- **Cadence:** daily or every 2 days, via a cron heartbeat (see `bundled/goal-loop.md`). The "goal" is
  simply "the period's digest exists with its learning items extracted."
- **Learning is the point.** Sections 4 and 5 are what make the system improve over time — they turn
  human feedback and the system's own friction into edits to the codebase skill, the gates, and these
  prompts. A report that's only numbers is a missed opportunity.
- **Honest by default.** Section 5 reports failures and skips faithfully — a digest that only shows
  wins is not trustworthy.
