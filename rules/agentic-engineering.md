# Agentic engineering rules

- Preserve the user's complete objective and explicit constraints.
- Inventory authoritative work units before claiming an "all" or "every" task.
- Pilot behavior-preserving batch changes before broad fan-out.
- Give isolated workers complete prompts, paths, ownership boundaries, and
  verifiable stop conditions.
- Never let concurrent writers own overlapping files or the same checkout.
- Separate implementer, bug-seeking reviewer, and fixer roles for risky work.
- Require evidence for findings: location, failure mechanism, trigger, expected
  behavior, and reproduction.
- Treat repeated worker mistakes as workflow defects; repair the prompt,
  partitioning, shared artifact, or verifier.
- Serialize compiler/test failures into a bounded queue rather than launching
  competing aggregate builds.
- Reject stubs, placeholders, skipped tests, silent scope reduction, and
  destructive git shortcuts.
- Stop only on an authoritative gate, a bounded no-progress condition, or a
  genuinely external blocker.
