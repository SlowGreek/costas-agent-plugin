# Costas Agent Plugin

An Open Plugin bundle for bounded agent workflows, persistent goals, migration
and review loops, and gated repository maintenance.

## Install

Register the public marketplace and install the plugin:

```bash
copilot plugin marketplace add SlowGreek/costas-agent-plugin
copilot plugin install costas-agent-plugin@costas-agent-tools
copilot plugin list
```

The same flow works with a private repository when every installer has read
access and non-interactive Git credentials. For GitHub, run `gh auth login` and
`gh auth setup-git` first. For another Git host, pass its clone URL to
`marketplace add`. Marketplace installs are preferred because direct repository
installs are deprecated by current Copilot CLI runtimes.

For local development, either load the source tree for one session:

```bash
copilot --plugin-dir /absolute/path/to/costas-agent-plugin
```

or exercise the same marketplace installation used by published releases:

```bash
copilot plugin marketplace add /absolute/path/to/costas-agent-plugin
copilot plugin install costas-agent-plugin@costas-agent-tools
```

The package uses the Open Plugins `.plugin/plugin.json` layout. It contributes
25 skills, one `agentStop` hook, shared agent rules, and the Ultracode
extension.

## Start here

After installation, run:

```text
/costas-agent-guide overview
```

The guide explains what the plugin installed and how its skills, shared rules,
Goal hook, and Ultracode extension fit together. It can recommend the smallest
appropriate capability for a task, generate tailored examples, teach operating
practices, and troubleshoot prerequisites:

```text
/costas-agent-guide choose "migrate every API client safely"
/costas-agent-guide examples "repair recurring CI failures"
/costas-agent-guide best-practices
/costas-agent-guide troubleshoot "Ultracode child startup failed"
```

## Repository maintenance

`/maintain-repo` is the user-facing alias for `/repo-maintenance`. The conductor
onboards the current repository, establishes gated maintenance state, and can
arm persistent loops when workflow scheduling is available. Eleven standalone
skills expose each phase independently:

```text
/repo-learn
/repo-triage
/repo-implement
/repo-pr-maintenance
/repo-auto-review
/custom-pr-review
/repo-dep-sweep
/repo-ci-health
/repo-post-merge
/repo-report
/repo-self-improve
```

Run `/repo-learn` first to create a repository-specific codebase skill and prove
its test recipe. Use a standalone loop for one-off work; use `/maintain-repo`
only when you want the complete system. Persistent standing mode requires
`save_workflow`, `run_workflow`, and `list_workflows`; without them the loops
remain available on demand and the conductor reports that the system is not
armed. A bundled cross-process lease serializes per-repository Goal and backlog
updates when scheduled loops overlap.

## Loop Design sources

`/loop-design` can discover automation opportunities from the repository,
scoped agent-session history, or both:

```text
/loop-design repo release
/loop-design chats CI failures
/loop-design both migrations
```

Chat inventory includes the current conversation and available history for the
current repository, workspace, or project. It queries session metadata before
relevant turns, reports the sampled scope, and summarizes recurring patterns
without persisting raw transcripts. Reading unrelated or global history requires
explicit approval. If session history is unavailable, the skill reports the
limitation instead of silently treating repository evidence as chat recurrence.

## Runtime prerequisites

- GitHub Copilot CLI with Open Plugins and extension support. This package is
  validated against CLI `1.0.69-2` and bundled `@github/copilot-sdk` `1.0.3`.
- Python 3 for Goal state, continuation hooks, and the repository-maintenance
  execution lease (`python3` on macOS/Linux, `python` in the bundled
  PowerShell hook).
- `git` on `PATH` for repository maintenance: `runtime/repo_identity.py` shells
  out to it to resolve repository identity, and every maintenance loop fetches,
  diffs, branches, and pushes with it directly. Ultracode additionally needs
  `git` whenever a call requests `worktree: true`.
- Repository maintenance requires issue, PR, review-thread, and CI access for
  the repository host. Persistent standing mode also requires the Copilot
  workflow scheduling tools.
- Ultracode child agents need one authentication route that is actually visible
  to an extension:
  - set `GH_TOKEN` before launching Copilot CLI, or
  - install GitHub CLI and run `gh auth login`; the child runtime uses
    `gh auth token`.

`GITHUB_TOKEN` and `COPILOT_GITHUB_TOKEN` are **not** Ultracode extension
credentials. Current extension-host startup removes both through the runtime
secret environment blocklist before forking an extension. `GH_TOKEN` is not on
that blocklist. Ultracode never reads, logs, copies into state, or passes a token
through `gitHubToken`; the SDK child inherits the extension environment and
performs its normal logged-in-user resolution.

## Child runtime startup

The SDK adds `--headless --no-auto-update --stdio`. Ultracode resolves what it
must launch without a shell:

1. A usable explicit `COPILOT_CLI_PATH` wins.
2. In a Node SEA process, `process.execPath` is the Copilot executable.
3. In a regular Node extension process, the extension host's
   `COPILOT_CLI_DIST_DIR/index.js` is passed as the first argument to
   `process.execPath` via SDK `RuntimeConnection.forStdio({ path, args })`.

This distinction is required: invoking regular Node as `node --headless` fails
because `--headless` is a Copilot option, not a Node option. Arguments are
passed as an argv array, so paths containing spaces and shell metacharacters are
not evaluated by a shell. An invalid explicit path fails with a diagnostic
instead of silently selecting a different CLI.

The extension host currently injects `COPILOT_CLI_DIST_DIR`, not
`COPILOT_CLI_PATH`. No launcher script is needed because SDK 1.0.3 supports
leading `args`.

## Ultracode limits and isolation

`ultracode_start` runs a JavaScript workflow in a `node:vm` worker. Workflow
code receives only `agent()`, `pipeline()`, and JSON `args`; imports and dynamic
code generation are blocked.

- concurrency: default 8, maximum 16
- agent calls: default 100, maximum 1,000
- run timeout: default 60 minutes, maximum 360
- per-agent timeout: default 20 minutes, maximum 120
- permission mode: `read-only` by default; `workspace` must be selected
  explicitly

`maxAgents` counts direct `agent()` calls. Workspace children exclude both
current runtime tools that can create nested agent sessions: `task` and
`search_code_subagent`. Agent-management tools are also excluded defensively.
The SDK client uses `mode: "empty"`, disables config discovery, and installs no
plugins in children, closing skill, extension, MCP, and custom-agent recursive
paths. The remaining `SessionAgentExecutor` constructor in
`sidekickAgentManager.ts` is lifecycle-driven rather than a callable tool, and
an empty child runtime has no configured sidekicks.

Runs persist under `$COPILOT_PLUGIN_DATA/ultracode` when that variable is
available. Current extension hosts do not inject plugin data variables into
extension processes, so Ultracode derives the same PluginManager location from
its installed path:
`$COPILOT_HOME/plugin-data/<marketplace>/costas-agent-plugin/ultracode`
(or the `_direct` marketplace for direct/plugin-dir sources).

`workspace` agents can modify files and run commands. Parallel writers must use
separate worktrees or provably disjoint files. Generated worktrees are retained
and reported; Ultracode never resets or removes them automatically.

## Goal hook

`/goal` stores session-and-working-directory-scoped state in
`${COPILOT_PLUGIN_DATA}/goals`. The `agentStop` hook is fail-open: malformed
input, unreadable state, or write failure permits the session to stop. It forces
at most 30 continuation turns by default, never more than 100, then permits one
wrap-up turn. Only a three-turn identical blocker audit may mark a goal blocked.

## Validation

From this directory:

```bash
python3 tests/validate.py
node --test tests/test_ultracode_runtime.mjs
node --test tests/test_ultracode_worker.mjs
```

The validator checks manifests/frontmatter/references, verifies vendored
third-party files against pinned upstream sha256 digests, validates all 25
skills and the maintenance harness resources, syntax-checks Python and
JavaScript, runs Goal and Ultracode regressions, and verifies the credential,
runtime-launch, and delegation policies. When `copilot` is on
`PATH`, `COPILOT_CLI_PATH` is set, or the local runtime checkout is available,
it also performs a marketplace registration and installation under a temporary
isolated `COPILOT_HOME`. Validation never modifies personal installed plugins or
credentials.

## Provenance

Third-party material remains under its upstream license; the package-level
license is Apache-2.0. See [NOTICE](NOTICE) for the full attribution.

| Component | Origin | License | Status |
| --- | --- | --- | --- |
| Goal (runtime + hook) | OpenAI Codex concepts | Apache-2.0 | Adapted / original implementation |
| Learn | NousResearch/hermes-agent concepts | MIT | Adapted |
| Creative Ideation | NousResearch/hermes-agent | MIT | Vendored unchanged (byte-for-byte) |
| Frontend Design | anthropics/skills | Apache-2.0 | Vendored unchanged (byte-for-byte) |
| Costas Agent Guide, Workflow, Ultracode, Adversarial Loop, Mechanical Migration, Failure Work Queue, Semantic Port Audit, Loop Design, Repository Maintenance harness and commands | Local original work | Apache-2.0 | Original / Copilot-adapted |

Vendored files (`skills/creative-ideation/`, `skills/frontend-design/`) are
reproduced exactly from upstream; their sha256 digests are pinned in
[tests/vendor_hashes.json](tests/vendor_hashes.json) and enforced by the
validator, which fails if any vendored file is modified or dropped. Upstream
license texts live in [licenses/](licenses) and, for Frontend Design, in
[skills/frontend-design/LICENSE.txt](skills/frontend-design/LICENSE.txt).
