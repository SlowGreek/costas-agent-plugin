---
name: mechanical-migration
description: Plan and execute behavior-preserving codebase migrations with pilots, sharded workflows, and parity gates.
user-invocable: true
disable-model-invocation: true
---

# Mechanical Migration

Inventory every work unit before editing. Define source-to-target mappings,
semantic exceptions, generated-file policy, ownership shards, and parity gates.
Pilot representative cases end to end. Review the pilot and repair the mapping
or workflow before fan-out.

Give each worker disjoint files and the same canonical mapping artifact. Run
format/typecheck/unit tests at shard barriers, then aggregate failures into a
bounded repair queue. Compare public API, configuration, serialization, error,
and platform behavior. Stop only when inventory counts match, no old pattern
remains except documented exceptions, and authoritative tests pass.
