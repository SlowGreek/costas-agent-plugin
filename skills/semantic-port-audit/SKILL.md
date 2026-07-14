---
name: semantic-port-audit
description: Audit source-to-target ports for language semantic mismatches and produce focused regression tests.
user-invocable: true
---

# Semantic Port Audit

Build a source/target behavior matrix before reviewing syntax. Check numeric
overflow and division, nullability, equality and hashing, collection ordering,
string/Unicode behavior, exceptions, resource lifetime, async cancellation,
threading, serialization, filesystem/path rules, locale/time zones, and
debug/release differences.

Trace each mismatch to concrete source and target locations. Supply a triggering
input, expected source behavior, observed target behavior, and a focused
regression test. Reject stylistic differences without behavioral impact.
Prioritize silent data corruption, security boundaries, and platform-specific
release behavior. Completion requires tests for accepted semantic gaps and
parity evidence for the audited inventory.
