---
name: workflow
description: Plan and run a dynamic multi-agent workflow for large, parallel, or adversarial tasks.
user-invocable: true
disable-model-invocation: true
---

# Workflow

Use multiple agents only when independent context or parallel work is valuable.
Define the objective, work-unit inventory, shared invariants, dependencies,
ownership, barriers, verifier rubric, and stop condition first.

Choose fan-out for independent units, a pipeline for dependent phases, an
implement-review-fix loop for risk, or a bounded repair queue for failures.
Provide complete context to every worker and never overlap write ownership.
Collect evidence rather than trusting summaries. At barriers, reconcile counts,
run authoritative checks, and adapt the workflow when repeated defects reveal a
systematic prompt or partitioning problem.
