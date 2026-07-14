#!/usr/bin/env python3
"""Dependency-free structural and behavioral validation for the plugin."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "costas-agent-plugin"
MARKETPLACE_NAME = "costas-agent-tools"
REPOSITORY_URL = "https://github.com/SlowGreek/costas-agent-plugin"
EXPECTED_SKILLS = {
    "adversarial-loop",
    "costas-agent-guide",
    "creative-ideation",
    "failure-work-queue",
    "frontend-design",
    "goal",
    "learn",
    "loop-design",
    "mechanical-migration",
    "semantic-port-audit",
    "ultracode",
    "workflow",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(
    command: list[str],
    *,
    extra_env: dict[str, str] | None = None,
    remove_env: tuple[str, ...] = (),
) -> None:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    env.update(extra_env or {})
    for name in remove_env:
        env.pop(name, None)
    completed = subprocess.run(command, cwd=ROOT, env=env, text=True, check=False)
    require(completed.returncode == 0, f"command failed ({completed.returncode}): {' '.join(command)}")


def load_json(relative: str) -> object:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def parse_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    require(text.startswith("---\n"), f"{path.relative_to(ROOT)} must begin with YAML frontmatter")
    marker = text.find("\n---\n", 4)
    require(marker > 4, f"{path.relative_to(ROOT)} has unterminated frontmatter")
    values: dict[str, str] = {}
    for line in text[4:marker].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        require(":" in line, f"{path.relative_to(ROOT)} has malformed frontmatter line: {line}")
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def validate_vendored() -> None:
    """Verify third-party vendored files are byte-for-byte identical to their pinned upstream digests."""
    import hashlib

    manifest = load_json("tests/vendor_hashes.json")
    require(isinstance(manifest, dict), "vendor_hashes.json must be an object")
    files = manifest.get("files")
    require(isinstance(files, dict) and files, "vendor_hashes.json must list vendored files")
    for relative, expected in files.items():
        path = ROOT / relative
        require(path.is_file(), f"vendored file missing: {relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        require(actual == expected, f"vendored file changed (must match upstream byte-for-byte): {relative}")
    # Guard against silently dropping vendored files: every file under a vendored
    # skill tree must be pinned in the manifest.
    for base in ("skills/creative-ideation", "skills/frontend-design"):
        for path in sorted((ROOT / base).rglob("*")):
            if path.is_file():
                relative = path.relative_to(ROOT).as_posix()
                require(relative in files, f"vendored file not pinned in vendor_hashes.json: {relative}")
    require((ROOT / "skills/frontend-design/LICENSE.txt").is_file(), "frontend-design upstream LICENSE.txt missing")
    print(f"validated: {len(files)} vendored files match pinned upstream digests")


def validate_manifest() -> None:
    manifest = load_json(".plugin/plugin.json")
    marketplace = load_json(".github/plugin/marketplace.json")
    require(isinstance(manifest, dict), "plugin manifest must be an object")
    require(manifest.get("name") == PLUGIN_NAME, "unexpected plugin name")
    require(manifest.get("extensions", {}).get("paths") == ["./extensions"], "extension path mismatch")
    require(manifest.get("skills", {}).get("paths") == ["./skills"], "skill path mismatch")
    require(manifest.get("hooks") == "./hooks/hooks.json", "hook path mismatch")
    require(manifest.get("repository") == REPOSITORY_URL, "plugin repository URL mismatch")
    require(marketplace.get("name") == MARKETPLACE_NAME, "marketplace name mismatch")
    marketplace_plugin = marketplace.get("plugins", [{}])[0]
    require(marketplace_plugin.get("name") == PLUGIN_NAME, "marketplace plugin name mismatch")
    require(marketplace_plugin.get("source") == ".", "marketplace source mismatch")
    require(marketplace_plugin.get("repository") == REPOSITORY_URL, "marketplace repository URL mismatch")
    require(
        marketplace_plugin.get("postInstallMessage") == manifest.get("postInstallMessage"),
        "post-install messages must match",
    )
    require("/costas-agent-guide overview" in manifest.get("postInstallMessage", ""), "onboarding message missing")
    for path in ("skills", "extensions", "rules", "hooks/hooks.json", "LICENSE", "NOTICE", "README.md"):
        require((ROOT / path).exists(), f"manifest/package path is missing: {path}")


def validate_skills() -> None:
    files = sorted((ROOT / "skills").glob("*/SKILL.md"))
    names = set()
    for path in files:
        metadata = parse_frontmatter(path)
        name = metadata.get("name")
        require(name == path.parent.name, f"{path.relative_to(ROOT)} name must match its directory")
        require(bool(metadata.get("description")), f"{path.relative_to(ROOT)} needs a description")
        names.add(name)
    require(names == EXPECTED_SKILLS, f"skill inventory mismatch: {sorted(names ^ EXPECTED_SKILLS)}")


def validate_loop_design_policy() -> None:
    skill = (ROOT / "skills/loop-design/SKILL.md").read_text(encoding="utf-8")
    require("[repo|chats|both]" in skill, "Loop Design source modes are missing")
    require("Scope chat history to the current repository" in skill, "chat history must default to local scope")
    require(
        "Require explicit approval before\n   inspecting unrelated repositories" in skill,
        "wider chat-history access must require approval",
    )
    require("do not persist raw transcripts" in skill, "raw chat transcripts must not be persisted")
    require("Count recurrence across distinct sessions" in skill, "chat recurrence must be session-based")


def validate_guide() -> None:
    guide = (ROOT / "skills/costas-agent-guide/SKILL.md").read_text(encoding="utf-8")
    for name in EXPECTED_SKILLS - {"costas-agent-guide"}:
        require(f"`/{name}`" in guide, f"guide is missing /{name}")
    for section in ("## When to Use", "## Prerequisites", "## Procedure", "## Quick Reference", "## Pitfalls", "## Verification"):
        require(section in guide, f"guide is missing {section}")
    require("does not start\nagents" in guide, "guide must not start work implicitly")
    require("smallest sufficient mechanism" in guide, "guide must discourage over-orchestration")
    require("GH_TOKEN" in guide and "GITHUB_TOKEN" in guide, "guide must explain Ultracode credentials")


def validate_markdown_links() -> None:
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for document in ROOT.rglob("*.md"):
        for target in link_pattern.findall(document.read_text(encoding="utf-8")):
            target = target.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            require((document.parent / target).resolve().exists(), f"broken link in {document}: {target}")


def validate_hooks() -> None:
    hooks = load_json("hooks/hooks.json")
    require(hooks.get("version") == 1, "hook schema version must be 1")
    agent_stop = hooks.get("hooks", {}).get("agentStop")
    require(isinstance(agent_stop, list) and len(agent_stop) == 1, "exactly one agentStop hook is required")
    command = agent_stop[0]
    require("${PLUGIN_ROOT}/runtime/goal_continue.py" in command.get("bash", ""), "portable bash hook missing")
    require("${PLUGIN_ROOT}/runtime/goal_continue.py" in command.get("powershell", ""), "portable PowerShell hook missing")
    require(
        command.get("env", {}).get("GOAL_STATE_DIR") == "${COPILOT_PLUGIN_DATA}/goals",
        "Goal state must use plugin data",
    )
    require((ROOT / "runtime/goal_continue.py").is_file(), "Goal hook target missing")
    require((ROOT / "runtime/goalctl.py").is_file(), "Goal controller missing")


def validate_source_syntax() -> None:
    for path in ROOT.rglob("*.py"):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    for path in ROOT.rglob("*.mjs"):
        run(["node", "--check", str(path)])
    run(["node", "--check", str(ROOT / "tests/fixtures/runtime path with spaces/index.js")])


def validate_blocker_policies() -> None:
    extension = (ROOT / "extensions/ultracode/extension.mjs").read_text(encoding="utf-8")
    policy = (ROOT / "extensions/ultracode/runtime-policy.mjs").read_text(encoding="utf-8")
    combined = extension + policy
    require("RuntimeConnection.forStdio(runtimeConnectionOptions(launch))" in extension, "resolver is not wired to SDK")
    require("process.env.GH_TOKEN" not in combined, "extension must not read GH_TOKEN")
    require("gitHubToken:" not in combined, "extension must not copy a GitHub token into SDK options")
    require("GITHUB_TOKEN" not in combined, "extension source must not claim filtered GITHUB_TOKEN")
    require("COPILOT_GITHUB_TOKEN" not in combined, "extension source must not claim filtered COPILOT_GITHUB_TOKEN")
    require('"task"' in policy, "task must be excluded")
    require('"search_code_subagent"' in policy, "search_code_subagent must be excluded")
    require("...childToolPolicy(run.state.permissionMode)" in extension, "child policy is not applied")
    require('mode: "empty"' in policy, "child SDK must use empty mode")
    require("enableConfigDiscovery: false" in extension, "child config discovery must be disabled")


def validate_runtime_evidence() -> Path | None:
    configured = os.environ.get("COPILOT_RUNTIME_SOURCE")
    runtime = Path(configured).expanduser() if configured else Path.home() / ".copilot/repos/copilot-agent-runtime"
    if not runtime.is_dir():
        print("runtime evidence: skipped (set COPILOT_RUNTIME_SOURCE to a checkout)")
        return None

    extension_host = (runtime / "src/core/extensionHost.ts").read_text(encoding="utf-8")
    secret_env = (runtime / "src/runtime/src/secrets/env.rs").read_text(encoding="utf-8")
    sdk_types = (runtime / "dist-cli/copilot-sdk/types.d.ts").read_text(encoding="utf-8")
    search_tool = (runtime / "src/tools/searchSubagentTool.ts").read_text(encoding="utf-8")
    task_names = (runtime / "src/tools/agentToolNames.ts").read_text(encoding="utf-8")
    executor_callers = {
        path.relative_to(runtime).as_posix()
        for path in (runtime / "src").rglob("*.ts")
        if "new SessionAgentExecutor" in path.read_text(encoding="utf-8")
    }

    require("new Set(envVarNamesToFilterFromShellsAndMCP)" in extension_host, "extension host filter changed")
    require("COPILOT_CLI_DIST_DIR: this.options.cliDistDir" in extension_host, "CLI dist env injection changed")
    require('"GITHUB_TOKEN"' in secret_env, "GITHUB_TOKEN is no longer in the secret blocklist")
    require('"COPILOT_GITHUB_TOKEN"' in secret_env, "COPILOT_GITHUB_TOKEN is no longer blocked")
    require('"GH_TOKEN"' not in secret_env, "GH_TOKEN is now blocked; update auth documentation and tests")
    require(re.search(r"forStdio:[\s\S]{0,180}args\?: readonly string\[\]", sdk_types) is not None, "SDK stdio args missing")
    require('name: "search_code_subagent"' in search_tool, "search subagent tool name changed")
    require("new SessionAgentExecutor" in search_tool, "search tool no longer spawns SessionAgentExecutor")
    require('TASK_TOOL_NAME = "task"' in task_names, "task tool name changed")
    require(
        executor_callers
        == {
            "src/agents/customAgents/agentContext.ts",
            "src/apps/runtime-compat/tools/blackbird.ts",
            "src/core/sidekickAgentManager.ts",
            "src/tools/searchSubagentTool.ts",
        },
        f"SessionAgentExecutor caller inventory changed: {sorted(executor_callers)}",
    )
    print(f"runtime evidence: {runtime}")
    return runtime


def validate_install_smoke(runtime: Path | None) -> None:
    explicit = os.environ.get("COPILOT_CLI_PATH")
    cli: list[str] | None = None
    if explicit:
        cli_path = Path(explicit).expanduser()
        require(cli_path.is_file(), f"COPILOT_CLI_PATH is not a file: {cli_path}")
        cli = ["node", str(cli_path)] if cli_path.suffix in {".js", ".mjs"} else [str(cli_path)]
    elif discovered := shutil.which("copilot"):
        cli = [discovered]
    elif runtime and (runtime / "dist-cli/index.js").is_file():
        cli = ["node", str(runtime / "dist-cli/index.js")]

    if cli is None:
        print("install smoke: skipped (set COPILOT_CLI_PATH or put copilot on PATH)")
        return

    with tempfile.TemporaryDirectory(prefix="costas-agent-plugin-install-") as home:
        env = {**os.environ, "COPILOT_HOME": home}
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN"):
            env.pop(name, None)

        def invoke(*args: str) -> str:
            completed = subprocess.run(
                [*cli, *args],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            output = completed.stdout + completed.stderr
            require(completed.returncode == 0, f"install smoke failed: {' '.join(args)}\n{output}")
            return output

        add_output = invoke("plugin", "marketplace", "add", str(ROOT))
        require(f'Marketplace "{MARKETPLACE_NAME}" added successfully.' in add_output, "marketplace was not added")

        install_output = invoke("plugin", "install", f"{PLUGIN_NAME}@{MARKETPLACE_NAME}")
        require("Installed 12 skills." in install_output, "installer did not discover all skills")
        require("/costas-agent-guide overview" in install_output, "installer did not show the onboarding message")

        list_output = invoke("plugin", "list")
        require(f"{PLUGIN_NAME}@{MARKETPLACE_NAME} (v1.0.0)" in list_output, "installed plugin was not listed")

        installed = Path(home) / "installed-plugins" / MARKETPLACE_NAME / PLUGIN_NAME
        installed_skills = list((installed / "skills").glob("*/SKILL.md"))
        require(len(installed_skills) == len(EXPECTED_SKILLS), "installed skill count mismatch")
        for relative in (
            ".plugin/plugin.json",
            "hooks/hooks.json",
            "rules/agentic-engineering.md",
            "extensions/ultracode/extension.mjs",
            "skills/costas-agent-guide/SKILL.md",
        ):
            require((installed / relative).is_file(), f"installed package is missing {relative}")

    print(f"install smoke: {PLUGIN_NAME}@{MARKETPLACE_NAME}")


def main() -> int:
    validate_manifest()
    validate_skills()
    validate_loop_design_policy()
    validate_guide()
    validate_vendored()
    validate_markdown_links()
    validate_hooks()
    validate_source_syntax()
    validate_blocker_policies()
    runtime = validate_runtime_evidence()
    validate_install_smoke(runtime)

    run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test_goal.py"])
    run(["node", "--test", "tests/test_ultracode_runtime.mjs"])
    run(["node", "--test", "tests/test_ultracode_extension_boot.mjs"])
    run(["node", "--test", "tests/test_ultracode_worker.mjs"])
    if runtime and (runtime / "dist-cli/index.js").is_file():
        run(
            ["node", "--test", "tests/test_sdk_startup.mjs"],
            extra_env={
                "COPILOT_SDK_PATH": str(runtime / "dist-cli/copilot-sdk"),
                "COPILOT_CLI_DIST_DIR": str(runtime / "dist-cli"),
            },
            remove_env=("GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN", "GH_TOKEN"),
        )
    print("validated: install, manifest, 12 skills, onboarding guide, Loop Design, hooks, Goal, Ultracode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
