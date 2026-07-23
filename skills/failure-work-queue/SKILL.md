---
name: failure-work-queue
description: Turn compiler, test, runtime, or CI failures into persistent grouped queues for bounded repair loops.
user-invocable: true
disable-model-invocation: true
---

# Failure Work Queue

Capture one authoritative failing command and preserve its raw output. Normalize
failures by root-cause signature, affected owner/files, and dependency order;
do not create one task per repeated symptom.

For each queue item record reproduction, expected result, evidence, owner,
attempt count, status, and dependencies. Repair ready items with disjoint write
scope. Re-run the smallest proving check, then the authoritative aggregate gate.
Regenerate the queue after each round because one fix may remove many symptoms.
Stop on green, a fixed round cap, or two no-progress rounds with the same
evidence. Never hide failures by deleting tests, weakening assertions, or
silencing diagnostics.
