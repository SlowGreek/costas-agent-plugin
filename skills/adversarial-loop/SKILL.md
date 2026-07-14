---
name: adversarial-loop
description: Implement high-risk changes through separate implementer, bug-seeking reviewer, and fixer contexts.
user-invocable: true
---

# Adversarial Implement–Review–Fix

1. Extract a contract containing behavior, invariants, forbidden shortcuts,
   compatibility, and acceptance evidence.
2. Give one implementer the contract and exclusive write scope.
3. Freeze the exact diff/source artifact without the implementer's reasoning.
4. Use independent reviewers for behavioral/API regressions and for
   lifecycle/concurrency/platform/error-path risks.
5. Require each finding to identify location, trigger, failure mechanism,
   expected behavior, and verification.
6. Give one fixer the contract, diff, and reports. Validate claims rather than
   applying them blindly.
7. Re-review material fixes in a fresh context.
8. Run focused and broad evidence gates. Completion requires every accepted
   finding to be fixed and every rejection to have evidence.
