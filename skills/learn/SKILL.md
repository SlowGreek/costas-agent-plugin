---
name: learn
description: Distill a reusable skill from a directory, URL, conversation, or pasted notes and save a validated SKILL.md.
user-invocable: true
argument-hint: <source>
---

# Learn

Inspect the supplied source and extract repeatable decisions, prerequisites,
procedures, failure modes, verification, and boundaries. Separate durable
method from project-specific facts and secrets.

Draft a narrowly named skill with valid YAML frontmatter (`name`,
`description`, and `user-invocable` when appropriate). Make trigger conditions
and non-goals explicit. Write executable steps with authoritative stop
conditions, then test the skill against one representative task and one case
where it should not be used. Never include credentials, private identifiers, or
unlicensed substantial text.
