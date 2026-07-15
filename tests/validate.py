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
PLUGIN_VERSION = "1.1.0"
MARKETPLACE_NAME = "costas-agent-tools"
REPOSITORY_URL = "https://github.com/SlowGreek/costas-agent-plugin"
EXPECTED_SKILLS = {
    "adversarial-loop",
    "costas-agent-guide",
    "creative-ideation",
    "custom-pr-review",
    "failure-work-queue",
    "frontend-design",
    "goal",
    "learn",
    "loop-design",
    "maintain-repo",
    "mechanical-migration",
    "repo-auto-review",
    "repo-ci-health",
    "repo-dep-sweep",
    "repo-implement",
    "repo-learn",
    "repo-maintenance",
    "repo-post-merge",
    "repo-pr-maintenance",
    "repo-report",
    "repo-self-improve",
    "repo-triage",
    "semantic-port-audit",
    "ultracode",
    "workflow",
}
MAINTENANCE_SKILLS = {
    "custom-pr-review",
    "maintain-repo",
    "repo-auto-review",
    "repo-ci-health",
    "repo-dep-sweep",
    "repo-implement",
    "repo-learn",
    "repo-maintenance",
    "repo-post-merge",
    "repo-pr-maintenance",
    "repo-report",
    "repo-self-improve",
    "repo-triage",
}
MAINTENANCE_RESOURCES = {
    "SKILL.md",
    "DESIGN.md",
    "HARNESS-COPILOT.md",
    "README.md",
    "review-profile.template.md",
    "bundled/goal-loop.md",
    "bundled/learn.md",
    "prompts/adversarial-gate.md",
    "prompts/auto-review.md",
    "prompts/ci-health.md",
    "prompts/dep-sweep.md",
    "prompts/engineer-charter.md",
    "prompts/outdated-closure.md",
    "prompts/post-merge.md",
    "prompts/pr-review.md",
    "prompts/report.md",
    "prompts/self-improve.md",
    "prompts/triage.md",
    "prompts/wi-fidelity.md",
    "runtime/maintenance_lock.py",
    "runtime/repo_identity.py",
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
    require(manifest.get("version") == PLUGIN_VERSION, "unexpected plugin version")
    require(manifest.get("extensions", {}).get("paths") == ["./extensions"], "extension path mismatch")
    require(manifest.get("skills", {}).get("paths") == ["./skills"], "skill path mismatch")
    require(manifest.get("hooks") == "./hooks/hooks.json", "hook path mismatch")
    require(manifest.get("repository") == REPOSITORY_URL, "plugin repository URL mismatch")
    require(marketplace.get("name") == MARKETPLACE_NAME, "marketplace name mismatch")
    marketplace_plugin = marketplace.get("plugins", [{}])[0]
    require(marketplace_plugin.get("name") == PLUGIN_NAME, "marketplace plugin name mismatch")
    require(marketplace_plugin.get("version") == PLUGIN_VERSION, "marketplace plugin version mismatch")
    require(marketplace_plugin.get("source") == ".", "marketplace source mismatch")
    require(marketplace_plugin.get("repository") == REPOSITORY_URL, "marketplace repository URL mismatch")
    require(marketplace.get("metadata", {}).get("version") == PLUGIN_VERSION, "marketplace metadata version mismatch")
    require(
        marketplace_plugin.get("postInstallMessage") == manifest.get("postInstallMessage"),
        "post-install messages must match",
    )
    require("/costas-agent-guide overview" in manifest.get("postInstallMessage", ""), "onboarding message missing")
    require("/maintain-repo" in manifest.get("postInstallMessage", ""), "maintenance onboarding message missing")
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
    require(len(files) == len(EXPECTED_SKILLS), "duplicate or extra skill entry point")
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


def validate_readme() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = re.sub(r"\s+", " ", readme)
    require(
        "only when an Ultracode call requests" not in normalized,
        "README must not claim git is only needed for Ultracode; repository maintenance shells out to it too",
    )
    require(
        re.search(r"git.{0,40}repository maintenance", normalized, flags=re.IGNORECASE) is not None,
        "README must state that repository maintenance itself requires git",
    )
    require(
        "repo_identity.py" in normalized,
        "README must name the maintenance helper that shells out to git",
    )
    require(
        re.search(r"worktree:\s*true", normalized) is not None,
        "README must keep the Ultracode worktree:true git requirement too",
    )


def validate_guide() -> None:
    guide = (ROOT / "skills/costas-agent-guide/SKILL.md").read_text(encoding="utf-8")
    normalized = re.sub(r"\s+", " ", guide)
    for name in EXPECTED_SKILLS - {"costas-agent-guide"}:
        require(f"`/{name}`" in guide, f"guide is missing /{name}")
    for section in ("## When to Use", "## Prerequisites", "## Procedure", "## Quick Reference", "## Pitfalls", "## Verification"):
        require(section in guide, f"guide is missing {section}")
    require("does not start\nagents" in guide, "guide must not start work implicitly")
    require("smallest sufficient mechanism" in guide, "guide must discourage over-orchestration")
    require("GH_TOKEN" in guide and "GITHUB_TOKEN" in guide, "guide must explain Ultracode credentials")
    require(
        re.search(r"`git` is required only.{0,80}Ultracode", normalized, flags=re.IGNORECASE)
        is None,
        "guide must not claim git is only needed for Ultracode",
    )
    require(
        re.search(
            r"`git`.{0,40}repository maintenance.{0,80}Ultracode worktree",
            normalized,
            flags=re.IGNORECASE,
        )
        is not None,
        "guide must require git for maintenance and Ultracode worktrees",
    )
    require(
        "verify `git` is on `PATH`" in normalized,
        "guide troubleshooting must check git for repository maintenance",
    )


def validate_maintenance() -> None:
    shared = ROOT / "skills/repo-maintenance"
    for relative in MAINTENANCE_RESOURCES:
        require((shared / relative).is_file(), f"maintenance resource missing: {relative}")
    require(not (shared / "install.py").exists(), "standalone installer must not be packaged")
    require(not (shared / "tests").exists(), "standalone installer tests must not be packaged")

    for name in MAINTENANCE_SKILLS:
        path = ROOT / "skills" / name / "SKILL.md"
        metadata = parse_frontmatter(path)
        require(metadata.get("user-invocable") == "true", f"/{name} must be user-invocable")
        text = path.read_text(encoding="utf-8")
        if name not in {"maintain-repo", "repo-maintenance"}:
            require("../repo-maintenance/" in text, f"/{name} must load shared maintenance resources")
        for relative in re.findall(r"`(\.\./repo-maintenance/[^`]+)`", text):
            require((path.parent / relative).resolve().exists(), f"/{name} has missing shared resource: {relative}")

    conductor = (shared / "SKILL.md").read_text(encoding="utf-8")
    alias = (ROOT / "skills/maintain-repo/SKILL.md").read_text(encoding="utf-8")
    require("/repo-learn" in conductor, "maintenance conductor must use /repo-learn")
    require("save_workflow" in conductor and "system is not armed" in conductor, "scheduler must fail closed")
    require("repository lease" in conductor, "maintenance loops must serialize shared state")
    require(
        conductor.index("2. **Resolve canonical state and acquire") < conductor.index("3. **Run `/repo-learn` under"),
        "bootstrap must acquire the lease before onboarding writes",
    )
    require("GitHub" in conductor and "Azure DevOps" in conductor, "provider mappings are incomplete")
    require("../repo-maintenance/SKILL.md" in alias, "/maintain-repo must delegate to the conductor")
    require("exact alias" in alias, "/maintain-repo alias contract is missing")

    combined = "\n".join(
        (shared / relative).read_text(encoding="utf-8") for relative in sorted(MAINTENANCE_RESOURCES)
    )
    for forbidden in (
        "notify-costas",
        "~/.claude/",
        ".claude/skills/",
        "/Users/",
        "never Sonnet/Haiku",
        "smartest model only",
    ):
        require(forbidden not in combined, f"maintenance harness contains non-portable text: {forbidden}")

    onboarding = (shared / "bundled/learn.md").read_text(encoding="utf-8")
    require("repo_identity.py" in onboarding, "repo adapter must use the identity helper")
    identity = (shared / "runtime/repo_identity.py").read_text(encoding="utf-8")
    require("COPILOT_HOME" in identity, "repo adapter must honor COPILOT_HOME")
    require("MAX_SKILL_NAME = 64" in identity, "repo adapter name must be bounded")
    require("hashlib.sha256" in identity, "repo adapter identity must be collision-resistant")

    harness = (shared / "HARNESS-COPILOT.md").read_text(encoding="utf-8")
    for command in ("maintenance_lock.py acquire", "maintenance_lock.py heartbeat", "maintenance_lock.py release"):
        require(command in harness, f"workflow prompt is missing lease command: {command}")
    require("absolute `state_dir`" in harness, "workflow lease root must be canonical across worktrees")

    design = (shared / "DESIGN.md").read_text(encoding="utf-8")
    require("unmasked process result plus test evidence" in design, "build gate trusts weak evidence")
    require("Gate the push on the build's *text*" not in design, "legacy text-only build gate remains")

    fidelity = (shared / "prompts/wi-fidelity.md").read_text(encoding="utf-8")
    require("workItemRefs" in fidelity and "closingIssuesReferences" in fidelity, "provider fidelity mapping missing")
    require(
        "prepare a concise draft" in fidelity
        and "escalate it to a human for posting" in fidelity
        and "Never post or send external reviewer replies autonomously" in fidelity,
        "fidelity replies must be prepared and escalated, never posted autonomously",
    )
    require(
        "reply with the finding" not in fidelity and "in the reviewer's thread" not in fidelity,
        "fidelity prompt still authorizes direct replies",
    )

    post_merge = (shared / "prompts/post-merge.md").read_text(encoding="utf-8")
    require("never reset" in post_merge and "isolated workspace" in post_merge, "post-merge isolation guard missing")
    require(
        "landed-repros.json" in post_merge and "20 later target-branch advances" in post_merge,
        "post-merge repros must remain under retention",
    )

    ci_health = (shared / "prompts/ci-health.md").read_text(encoding="utf-8")
    require(
        ci_health.index("FILE the de-flake work item FIRST") < ci_health.index("QUARANTINE transport invokes"),
        "CI-health must require the submitted de-flake WI before PR transport",
    )

    implement = (ROOT / "skills/repo-implement/SKILL.md").read_text(encoding="utf-8")
    require("branch is supporting\n   evidence, not a requirement" in implement, "PR dedup must include teammate branches")
    require("ai/outdated-closure-<date>-<digest>" in implement, "closure branch exception is missing")

    pr_maintenance = (ROOT / "skills/repo-pr-maintenance/SKILL.md").read_text(encoding="utf-8")
    require("never submit outward-facing text autonomously" in pr_maintenance, "reply authority is too broad")

    auto_review = (shared / "prompts/auto-review.md").read_text(encoding="utf-8")
    require("Optionally also push" not in auto_review, "file-only sweeper must not push repro branches")

    pr_review = (shared / "prompts/pr-review.md").read_text(encoding="utf-8")
    profile_template = (shared / "review-profile.template.md").read_text(encoding="utf-8")
    custom_pr_review = (ROOT / "skills/custom-pr-review/SKILL.md").read_text(encoding="utf-8")
    require("REVIEW_COMMENT_CURSORS_BY_PR" in pr_review, "PR profile refresh needs per-PR comment cursors")
    require("REVIEW_COMMENT_SCAN_HIGH_WATERMARK" in pr_review, "PR profile refresh needs a scan high-watermark")
    require("review_comment_cursors_by_pr" in profile_template, "review profile must persist per-PR comment cursors")
    require("review_comment_scan_snapshot" in profile_template, "review profile must persist the scan snapshot")
    require("review_comment_cursor:" not in profile_template, "aggregate review-comment cursor is unsafe")
    require("immutable PR's own cursor" in custom_pr_review, "standalone review must use per-PR cursors")

    # --- Semantic guardrails for the three cross-surface workflow contracts ---
    post_merge_skill = (ROOT / "skills/repo-post-merge/SKILL.md").read_text(encoding="utf-8")
    goal_loop = (shared / "bundled/goal-loop.md").read_text(encoding="utf-8")

    # Gap 1 — tracked external (teammate/human) landed fixes accepted by dedup must
    # be enrolled in the post-merge registry, exactly like our own ai/wi-* merges,
    # scoped to durable-backlog maintenance items (never arbitrary team work).
    enrollment_surfaces = {
        "post-merge prompt": post_merge,
        "post-merge skill": post_merge_skill,
        "conductor": conductor,
        "design §4.9": design,
    }
    for label, text in enrollment_surfaces.items():
        require(
            "teammate/human/external" in text,
            f"post-merge enrollment in {label} must cover deduped teammate/human/external landed fixes",
        )
        require(
            "durable-backlog" in text,
            f"post-merge enrollment in {label} must scope to durable-backlog maintenance items",
        )
    # Guard against the regressive 'only OUR ai/wi-* merges' enrollment wording.
    for label, text, forbidden in (
        ("post-merge prompt", post_merge, "query OUR newly merged `ai/wi-*` PRs since the host cursor"),
        ("post-merge skill", post_merge_skill, "add newly merged OUR `ai/wi-*` PRs and their validated repros"),
    ):
        require(forbidden not in text, f"{label} still enrolls only our ai/wi-* merges: {forbidden!r}")

    # Gap 2 — PR maintenance may push/rebase only branches this automation owns;
    # deduped teammate/human/external branches are read-only and escalated.
    branch_surfaces = {
        "pr-maintenance skill": pr_maintenance,
        "conductor": conductor,
        "design §4.3": design,
    }
    for label, text in branch_surfaces.items():
        require(
            "read-only" in text and "teammate/human/external" in text,
            f"{label} must keep deduped external branches read-only",
        )
        require(
            "never push or mutate their branch" in text,
            f"{label} must forbid pushing/mutating a teammate/human/external branch",
        )
        # The exact owned-branch exception must be preserved (provider-neutral).
        require(
            "ai/wi-" in text and "ai/outdated-closure-" in text,
            f"{label} must preserve the exact ai/wi-* + ai/outdated-closure-* push exception",
        )
    require(
        "IN-REVIEW" in pr_maintenance and "handoff recorded" in pr_maintenance,
        "external-branch PRs must stay IN-REVIEW with the handoff recorded",
    )

    # Gap — the test/coverage-request path in PR-maintenance must not authorize
    # autonomous landing. "add it on an owned branch, verify, land" would let a
    # scoped engineer's verified change merge with no persisted `land` grant at
    # all, breaking the otherwise-uniform rule that landing always needs its own
    # exact authority. DESIGN's fuller narrative is the only surface that ever
    # had this exact phrasing; assert it stays fixed and stays fixed the same way
    # everywhere the clause exists.
    require(
        "verify, land," not in design,
        "DESIGN test/coverage-request clause must not autonomously land without the exact land grant",
    )
    test_coverage_surfaces = {
        "design §4.3": design,
        "conductor": conductor,
        "pr-maintenance skill": pr_maintenance,
    }
    for label, text in test_coverage_surfaces.items():
        normalized = re.sub(r"\s+", " ", text)
        match = re.search(r"test/coverage (?:request|ask)\b(.{0,400})", normalized, flags=re.IGNORECASE)
        require(match is not None, f"{label} must describe the test/coverage-request handling path")
        clause = match.group(1)
        require(
            re.search(r"\bland\b", clause, flags=re.IGNORECASE) is None
            or re.search(r"\bland\b.{0,80}\bgrant\b|\bgrant\b.{0,80}\bland\b|`land`|persisted", clause, flags=re.IGNORECASE)
            is not None,
            f"{label} must not let a test/coverage engineer land without the exact persisted land grant",
        )

    # Gap 3 — every outward-facing reply/comment/thread-resolution is prepared and
    # escalated; no surface may authorize an autonomous reply, resolve, or the
    # substantive-only loophole.
    reply_surfaces = {
        "pr-maintenance skill": pr_maintenance,
        "conductor": conductor,
        "design": design,
    }
    for label, text in reply_surfaces.items():
        require(
            "never post, send, or resolve" in text,
            f"{label} must forbid autonomous reply/comment/thread-resolution",
        )
        require(
            "bot, style, preference" in text,
            f"{label} must apply the escalation rule to every comment class (bot/style/preference)",
        )
    # Ban autonomous reply/resolve and substantive-only wording across ALL the
    # outward-facing surfaces at once, so a safe sentence in one file can never
    # mask unsafe wording surviving in another.
    outward_blob = "\n".join(
        (pr_maintenance, conductor, design, harness, goal_loop, post_merge_skill)
    )
    for forbidden in (
        "reply with rationale, resolve",
        "reply w/ rationale",
        "reply with rationale;",
        "push, file WIs, reply",
        "our reply as its tail",
        "substantive reply as its tail",
        "verify, land, reply.",
        "prepare substantive reviewer replies and escalate",
    ):
        require(forbidden not in outward_blob, f"autonomous/substantive-only reply wording remains: {forbidden!r}")
    require(
        "Reviewer replies/comments/thread resolutions are always prepare-and-escalate" in harness,
        "loop authority must never permit autonomous reviewer communication",
    )

    # Gap 4 — branch names never establish ownership. The durable backlog/log
    # record and a live source/head match are both required before mutation.
    ownership_surfaces = {
        "repo-implement": implement,
        "repo-pr-maintenance": pr_maintenance,
        "conductor": conductor,
        "design": design,
        "Copilot harness": harness,
    }
    ownership_blob = "\n".join(ownership_surfaces.values())
    for label, text in ownership_surfaces.items():
        require("branch-ownership" in text, f"{label} must name the durable branch-ownership record")
        require(re.search(r"canonical\s+backlog", text) is not None,
                f"{label} must use the canonical backlog/log for ownership")
        require("source repository" in text, f"{label} must verify the source repository identity")
        require("exact head ref" in text, f"{label} must verify the exact head ref")
        require("read-only" in text, f"{label} must fail closed to read-only")
        require("ai/wi-" in text and "ai/outdated-closure-" in text,
                f"{label} must preserve both allowed branch classes")
    for required in (
        "creation/adoption evidence",
        "immutable PR identity",
        "prepare/confirm authority",
        "branch name is never proof",
        "unrecorded",
    ):
        require(required in ownership_blob, f"ownership guardrail is missing: {required}")
    for forbidden in (
        "branch name alone proves ownership",
        "branch name by itself proves ownership",
        "branch prefix proves ownership",
        "infer ownership from the branch name",
        "ownership inferred from the branch name",
    ):
        require(forbidden not in ownership_blob, f"name-only branch ownership wording remains: {forbidden!r}")
    for line in ownership_blob.splitlines():
        name_only_claim = re.search(
            r"(?:branch name|branch prefix|branch pattern|prefix).*(?:proves?|establishes?|grants?|determines?).*ownership",
            line,
            flags=re.IGNORECASE,
        )
        if name_only_claim and not re.search(
            r"\b(?:never|not|insufficient|read-only|mismatch|absent)\b", line, flags=re.IGNORECASE
        ):
            raise AssertionError(f"name-only branch ownership claim remains: {line.strip()}")

    # Gap 5 — post-merge completion is PASS-or-disposition, not all-green-only.
    post_merge_surfaces = {
        "post-merge prompt": post_merge,
        "post-merge skill": post_merge_skill,
        "conductor": conductor,
        "design §4.9": design,
        "Copilot harness": harness,
        "goal loop": goal_loop,
    }
    post_merge_blob = "\n".join(post_merge_surfaces.values())
    for label, text in post_merge_surfaces.items():
        require("regression-filed" in text, f"{label} must define regression-filed state")
        require("linked" in text and "WI" in text, f"{label} must retain a linked regression WI")
        require("alert" in text and "evidence" in text, f"{label} must retain alert/evidence")
        require(re.search(r"last\s+checked\s+target\s+SHA", text) is not None or "last_checked_target_sha" in text,
                f"{label} must retain the last checked target SHA")
        require("PASS" in text, f"{label} must define the passing disposition")
        require("red" in text.lower() and ("rerun" in text.lower() or "re-run" in text.lower()),
                f"{label} must rerun retained red entries on target advances")
    require("current episode" in post_merge_blob, "post-merge must keep regression dedup scoped to an episode")
    require("all-green-only requirement" in post_merge_blob,
            "post-merge must state that completion is not all-green-only")
    for forbidden in (
        "every retained landed repro passes after the latest target advance",
        "every retained landed repro re-passes on the latest integrated target",
        "every retained landed fix re-passes its repro on the latest integrated target",
        "all retained repros must pass",
    ):
        require(forbidden not in post_merge_blob, f"all-green-only post-merge objective remains: {forbidden!r}")
    for line in post_merge_blob.splitlines():
        all_green_claim = re.search(
            r"\b(?:every|all)\b.*\bretained\b.*\brepros?\b.*\bpass(?:es|ed)?\b",
            line,
            flags=re.IGNORECASE,
        )
        if all_green_claim and not re.search(
            r"\b(?:or|never|not|do not|don't|unless|otherwise)\b", line, flags=re.IGNORECASE
        ):
            raise AssertionError(f"all-green-only post-merge claim remains: {line.strip()}")

    # Gap 6 — prepared replies are durable handoffs, not provider-thread tails.
    handoff_surfaces = {
        "pr-maintenance": pr_maintenance,
        "conductor": conductor,
        "design": design,
        "Copilot harness": harness,
        "goal loop": goal_loop,
    }
    handoff_blob = "\n".join(handoff_surfaces.values())
    for label, text in handoff_surfaces.items():
        require("review-handoff" in text, f"{label} must define the review-handoff artifact")
        require("thread/comment ref" in text, f"{label} must retain the thread/comment ref")
        require("draft text" in text, f"{label} must retain the draft text")
        require("recommended resolution" in text, f"{label} must retain the recommended resolution")
        require("escalation" in text, f"{label} must retain escalation state")
        require("not a provider-thread tail" in text,
                f"{label} must distinguish a handoff from a provider-thread tail")
    require("every actionable comment" in handoff_blob,
            "review-maintenance completion must cover every actionable comment")
    require("current" in handoff_blob and "escalated status" in handoff_blob,
            "review-maintenance completion must require a current escalated artifact")
    require("never claim" in handoff_blob and "appears in the provider thread" in handoff_blob,
            "review-maintenance must not claim prepared text is in the provider thread")
    for forbidden in (
        "prepared reply as the thread tail",
        "prepared reply as its tail",
        "prepared-reply-as-thread-tail",
    ):
        require(forbidden not in handoff_blob, f"prepared-reply-as-thread-tail wording remains: {forbidden!r}")
    for line in handoff_blob.splitlines():
        tail_claim = re.search(
            r"\b(?:prepared\s+(?:reply|draft)|draft)\b.*\bas\s+(?:its\s+)?(?:provider-)?thread\s+tail\b",
            line,
            flags=re.IGNORECASE,
        )
        provider_claim = re.search(
            r"\b(?:prepared\s+(?:reply|draft)|draft)\s+appears?\s+in\s+the\s+provider\s+thread\b",
            line,
            flags=re.IGNORECASE,
        )
        if (tail_claim or provider_claim) and not re.search(
            r"\b(?:not|never|no|without)\b", line, flags=re.IGNORECASE
        ):
            raise AssertionError(f"prepared reply is incorrectly treated as a provider-thread tail: {line.strip()}")

    # Workflow-edge repair batch — guard the contracts that must remain aligned
    # across standalone skills, conductor, design, harness, bundled goal, prompts,
    # templates, and this validator.
    two_phase_surfaces = {
        "repo-implement": implement,
        "repo-pr-maintenance": pr_maintenance,
        "conductor": conductor,
        "design": design,
        "Copilot harness": harness,
        "goal loop": goal_loop,
    }
    for label, text in two_phase_surfaces.items():
        require("pending" in text, f"{label} must define pending branch ownership")
        require("initial push" in text, f"{label} must define the initial-push exception")
        require("bound" in text, f"{label} must require bound ownership after PR creation")
        require("immutable" in text and "PR" in text, f"{label} must bind immutable PR identity")
    require(
        re.search(r"A\s+live PR is not required before the initial push", implement) is not None,
        "initial ownership must not require a circular live PR before the first push",
    )
    for label, text in two_phase_surfaces.items():
        require(
            "failed" in text or "fails" in text,
            f"{label} must fail closed when PR binding cannot complete",
        )
    reservation_surfaces = {
        label: text
        for label, text in two_phase_surfaces.items()
        if label != "repo-pr-maintenance"
    }
    for label, text in reservation_surfaces.items():
        require("WI" in text and "authority" in text,
                f"{label} must retain WI and push authority in the pending reservation")
        require("absent" in text and "remote" in text,
                f"{label} must limit the initial push to an absent remote ref")
        require("DRAFT" in text and "PR" in text,
                f"{label} must bind a draft PR immediately after the initial push")
        require("forbid" in text or "freezes" in text,
                f"{label} must forbid further mutation after PR creation failure")
    for line in "\n".join(two_phase_surfaces.values()).splitlines():
        circular_pr_contract = re.search(
            r"\blive PR\b.*\b(?:required|verify|verified)\b.*\b(?:before|for)\b.*\binitial push\b",
            line,
            flags=re.IGNORECASE,
        )
        if circular_pr_contract and not re.search(r"\b(?:not|never|no)\b", line, flags=re.IGNORECASE):
            raise AssertionError(f"circular live-PR-before-first-push contract remains: {line.strip()}")

    # Two-phase gap — initial_push granted alone must never authorize the push: the pending
    # reservation and its preflight re-check must require BOTH the persisted initial_push (push)
    # grant and the persisted open_draft_pr grant, plus a live WI, before the one initial push.
    # Otherwise a remote branch could be pushed with no authority left to cover it with a DRAFT PR.
    for label, text in reservation_surfaces.items():
        require("open_draft_pr" in text,
                f"{label} must require the persisted open_draft_pr grant before the initial push")
        require("initial_push" in text,
                f"{label} must require the persisted initial_push grant before the initial push")
        require("live WI" in text,
                f"{label} must require a live WI before the initial push, not just a grant")
        require(re.search(r"preflight", text, flags=re.IGNORECASE) is not None,
                f"{label} must re-verify both grants at preflight immediately before executing the push")
        require(
            re.search(r"orphan", text, flags=re.IGNORECASE) is not None,
            f"{label} must explain that initial_push granted alone would orphan the remote branch",
        )
    for line in "\n".join(reservation_surfaces.values()).splitlines():
        push_alone_claim = re.search(
            r"\binitial[_-]push\b.*\balone\b.*\bauthorize\b.*\bpush\b",
            line,
            flags=re.IGNORECASE,
        )
        if push_alone_claim and not re.search(r"\b(?:never|not|no)\b", line, flags=re.IGNORECASE):
            raise AssertionError(f"initial_push-alone-authorizes-push contract remains: {line.strip()}")

    lease_surfaces = {
        "conductor": conductor,
        "design": design,
        "Copilot harness": harness,
        "goal loop": goal_loop,
    }
    for label, text in lease_surfaces.items():
        normalized = re.sub(r"\s+", " ", text)
        require("pre-write heartbeat gate" in normalized, f"{label} must gate every write on heartbeat")
        require("not-owner" in normalized, f"{label} must recognize lost lease ownership")
        require("local/session status" in normalized or "local status" in normalized,
                f"{label} must report a lost lease locally only")
        require("shared-state error" in normalized or "shared error record" in normalized,
                f"{label} must forbid a shared-state error write after lease loss")
        require("release" in normalized and ("not successful" in normalized or "local failure" in normalized or "not success" in normalized),
                f"{label} must not treat a not-owner release as success")
    lock = (shared / "runtime/maintenance_lock.py").read_text(encoding="utf-8")
    require(
        lock.count('emit({"status": "not-owner"})') >= 2 and "return EXIT_NOT_OWNER" in lock,
        "maintenance lock must fail heartbeat/release with not-owner",
    )

    ci_authority_surfaces = {
        "ci-health skill": (ROOT / "skills/repo-ci-health/SKILL.md").read_text(encoding="utf-8"),
        "ci-health prompt": ci_health,
        "design": design,
        "conductor": conductor,
    }
    for label, text in ci_authority_surfaces.items():
        require("file_tracker_item" in text and "open_draft_pr" in text,
                f"{label} must grant CI filing/drafts per exact authority")
        require("prepared" in text and "escalat" in text,
                f"{label} must prepare/escalate CI artifacts in conservative mode")
        require("file the product bug" not in text or "file the product bug only" in text,
                f"{label} must not file product-race bugs without exact authority")
    post_authority_surfaces = {
        "post-merge skill": post_merge_skill,
        "post-merge prompt": post_merge,
        "design": design,
        "conductor": conductor,
        "Copilot harness": harness,
        "goal loop": goal_loop,
    }
    for label, text in post_authority_surfaces.items():
        require("regression-escalated" in text, f"{label} must retain a conservative regression handoff")
        require("ACTIVE" in text, f"{label} must require an active regression WI for dedup")
        require("closed/resolved" in text, f"{label} must not let closed WIs satisfy a new episode")
        require("EVERY retained" in text, f"{label} must rerun every retained entry on target advance")
    for label, text in {
        "post-merge skill": post_merge_skill,
        "post-merge prompt": post_merge,
        "design": design,
        "conductor": conductor,
    }.items():
        require("file_tracker_item" in text and "reopen_tracker_item" in text and "send_alert" in text,
                f"{label} must grant file/reopen/alert per exact authority")

    closure_surfaces = {
        "outdated-closure prompt": (shared / "prompts/outdated-closure.md").read_text(encoding="utf-8"),
        "conductor": conductor,
        "design": design,
    }
    for label, text in closure_surfaces.items():
        require("classification" in text, f"{label} must treat the first closure run as classification")
        require("mixed" in text, f"{label} must allow mixed closure outcomes")
        require("normal triage" in text, f"{label} must return non-confirmed closure items to triage")
        require("exit 0" in text, f"{label} must require a green confirmed-only rerun")
    closure_prompt = closure_surfaces["outdated-closure prompt"]
    require("remove that\n  test addition" in closure_prompt, "closure must remove still-live test additions")
    require("If no confirmed\ntests remain, do not open a PR" in closure_prompt,
            "closure must not open a PR when nothing confirms outdated")

    # Gap — outdated-closure compile blockers: an aggregate compile error can hide every
    # candidate's per-test outcome. Bounded SERIAL diagnostic passes (never fanned-out builds)
    # must be permitted to shrink the batch to something runnable before classification proceeds,
    # and opening the closure PR itself needs the persisted open_draft_pr grant (every confirmed
    # item already carries a live WI from Triage).
    for label, text in closure_surfaces.items():
        require(re.search(r"aggregate\s+compile\s+error", text, flags=re.IGNORECASE) is not None,
                f"{label} must name the aggregate-compile-error failure mode that hides per-test outcomes")
        require(re.search(r"\bSERIAL\b", text) is not None,
                f"{label} must require bounded SERIAL diagnostic passes, not fanned-out builds")
        require(
            re.search(r"never\s+fan\s+out|never\s+N\s+concurrent\s+builds|do\s+NOT\s+fan\s+out", text, flags=re.IGNORECASE)
            is not None,
            f"{label} must forbid fanning out concurrent diagnostic builds",
        )
        require(re.search(r"capp?ed\b", text, flags=re.IGNORECASE) is not None and "per remaining candidate" in text,
                f"{label} must bound diagnostic passes to the remaining candidates")
        require("open_draft_pr" in text,
                f"{label} must gate opening the closure PR on the persisted open_draft_pr grant")
    require(
        "runnable" in closure_prompt.lower() and "no candidates remain" in closure_prompt.lower(),
        "closure prompt must keep shrinking the batch until it is runnable or exhausted",
    )

    # Gap — outdated-closure diagnostic passes must terminate even when a compile
    # error cannot be pinned to a specific candidate (an ambiguous/cross-cutting
    # location). Without an explicit rule, an unattributable error could consume
    # the pass budget without ever shrinking the batch, or worse, leave the loop
    # with no defined exit. Each surface must state that an unattributable pass
    # marks every remaining candidate unprovable/triage-bound and stops the
    # diagnostic loop immediately, rather than retrying or opening a PR from an
    # unresolved batch.
    for label, text in closure_surfaces.items():
        normalized = re.sub(r"\s+", " ", text)
        require(
            re.search(r"cannot\s+attribute", normalized, flags=re.IGNORECASE) is not None,
            f"{label} must handle a compile error that cannot be attributed to a specific candidate",
        )
        require(
            re.search(r"(?:stop|terminate)\w*\s+the\s+diagnostic\s+loop\s+immediately", normalized, flags=re.IGNORECASE)
            is not None,
            f"{label} must terminate the diagnostic loop immediately on an unattributable error, not retry it",
        )
        require(
            re.search(r"triage|unprovable", normalized, flags=re.IGNORECASE) is not None,
            f"{label} must return unattributable candidates to triage/unprovable rather than guessing",
        )
    for line in "\n".join(closure_surfaces.values()).splitlines():
        loops_forever_claim = re.search(r"\bretry\w*\b.*\bunattributable\b|\bunattributable\b.*\bretry\w*\b", line, flags=re.IGNORECASE)
        if loops_forever_claim and not re.search(r"\b(?:not|never|do not|don't)\b", line, flags=re.IGNORECASE):
            raise AssertionError(f"unattributable-error retry-forever wording remains: {line.strip()}")

    # Gap — exact external-write authority must be globally consistent, not just CI/post-merge.
    # Every maintenance loop that files tracker items, opens/updates draft PRs, or sends alerts must
    # gate that exact external write on its own persisted grant, or persist a complete
    # prepared/escalated handoff instead — never claim a prepared artifact was submitted. Core roles
    # stay intact: auto-review/dep-sweep remain find-only, self-improve remains tighten-only,
    # implementation never opens a PR without a live WI.
    auto_review_skill = (ROOT / "skills/repo-auto-review/SKILL.md").read_text(encoding="utf-8")
    dep_sweep_skill = (ROOT / "skills/repo-dep-sweep/SKILL.md").read_text(encoding="utf-8")
    dep_sweep_prompt = (shared / "prompts/dep-sweep.md").read_text(encoding="utf-8")
    self_improve_skill = (ROOT / "skills/repo-self-improve/SKILL.md").read_text(encoding="utf-8")
    self_improve_prompt = (shared / "prompts/self-improve.md").read_text(encoding="utf-8")

    # Global PR transport invariant — enumerate every operational surface that can create an
    # automation PR. Every entry point must invoke the same two-phase branch-ownership procedure and
    # state the live-WI/both-grants bar; a specialized loop may not treat open_draft_pr as push
    # authority. This inventory is intentionally explicit so adding another PR producer requires
    # making its transport contract visible here.
    maintain_alias = (ROOT / "skills/maintain-repo/SKILL.md").read_text(encoding="utf-8")
    pr_transport_surfaces = {
        "maintain-repo alias": maintain_alias,
        "repo-implement (implementation + closure entry)": implement,
        "outdated-closure prompt": closure_prompt,
        "ci-health skill": ci_authority_surfaces["ci-health skill"],
        "ci-health prompt": ci_health,
        "self-improve skill": self_improve_skill,
        "self-improve prompt": self_improve_prompt,
        "post-merge skill (revert producer)": post_merge_skill,
        "post-merge prompt (revert producer)": post_merge,
        "conductor": conductor,
        "design": design,
        "Copilot harness": harness,
        "bundled goal loop": goal_loop,
    }
    for label, text in pr_transport_surfaces.items():
        normalized = re.sub(r"\s+", " ", text)
        require("branch-ownership" in text and "two-phase" in text.lower(),
                f"{label} must invoke the canonical two-phase branch-ownership procedure")
        require("live submitted WI" in normalized,
                f"{label} must require a live submitted WI linked to an automation-created PR")
        require("initial_push" in text and "open_draft_pr" in text,
                f"{label} must require both persisted PR-transport grants")
        require(
            re.search(
                r"\bBOTH\b.{0,120}`initial_push`.{0,160}`open_draft_pr`",
                normalized,
                flags=re.IGNORECASE,
            )
            is not None,
            f"{label} must state the initial_push + open_draft_pr bar together",
        )
        require(re.search(
                    r"\ba lone `open_draft_pr` grant never supplies push authority\b",
                    normalized,
                    flags=re.IGNORECASE,
                ) is not None,
                f"{label} must reject open_draft_pr-only push authorization")
        require("bound" in text.lower() and "source" in text.lower() and "head" in text.lower(),
                f"{label} must require a bound live source/head match for later mutation")
        require("push/update authority" in normalized,
                f"{label} must require applicable later push/update authority")

        # Reject the former specialized-loop wording directly: an open_draft_pr-only paragraph may
        # not authorize creating/submitting a PR. Requiring initial_push in the same paragraph keeps
        # references to the grant safe while catching "with open_draft_pr, open a PR".
        for paragraph in re.split(r"\n\s*\n", text):
            compact = re.sub(r"\s+", " ", paragraph)
            open_only_authorizer = (
                re.search(
                    r"only when.{0,100}`open_draft_pr`.{0,180}\b(?:open|create|submit)\b.{0,80}\bPR\b",
                    compact,
                    flags=re.IGNORECASE,
                )
                or re.search(
                    r"`open_draft_pr`.{0,120}\bwith (?:it|the grant)\b.{0,160}"
                    r"\b(?:open|create|submit)\b.{0,80}\bPR\b",
                    compact,
                    flags=re.IGNORECASE,
                )
            )
            if open_only_authorizer and "initial_push" not in compact:
                raise AssertionError(f"{label} still authorizes PR transport from open_draft_pr alone")

    for label, text in {
        "self-improve skill": self_improve_skill,
        "self-improve prompt": self_improve_prompt,
        "conductor": conductor,
        "design": design,
    }.items():
        normalized = re.sub(r"\s+", " ", text)
        require("dedicated `self-improve` WI" in normalized,
                f"{label} must create/link a dedicated self-improve WI before PR transport")
        require("file_tracker_item" in text and "WI" in text and "diff" in text,
                f"{label} must submit the self-improve WI only with authority or prepare WI + diff")

    # Gap — self-improve's harness-pack target is a SECOND, DIFFERENT repository.
    # Holding only the current repo's lease must never authorize a write there:
    # each surface must require the harness repo's own identity/lease, deterministic
    # cross-lease ordering, heartbeating both before a cross-repo write, and
    # releasing in reverse acquisition order.
    cross_repo_surfaces = {
        "self-improve skill": self_improve_skill,
        "self-improve prompt": self_improve_prompt,
        "design §4.10": design,
        "Copilot harness": harness,
    }
    for label, text in cross_repo_surfaces.items():
        normalized = re.sub(r"\s+", " ", text)
        require(
            re.search(r"canonical\s+identity", normalized, flags=re.IGNORECASE) is not None,
            f"{label} must require the harness-pack repo's own canonical identity, not the current repo's",
        )
        require(
            re.search(r"deterministic\s+`?repo_id`?[\s-]*sorted\s+order|deterministic\s+.{0,20}repo.id.{0,20}order",
                      normalized, flags=re.IGNORECASE) is not None,
            f"{label} must require deterministic repo_id-sorted lease-acquisition ordering",
        )
        require(
            re.search(r"revers\w+\s+(?:acquisition\s+)?order", normalized, flags=re.IGNORECASE) is not None,
            f"{label} must release cross-repo leases in reverse acquisition order",
        )
    require(
        re.search(r"never reuse", "\n".join(cross_repo_surfaces.values()), flags=re.IGNORECASE) is not None
        or re.search(r"never\s+(?:reuse|assum\w+ this (?:one|lease) covers)",
                      re.sub(r"\s+", " ", "\n".join(cross_repo_surfaces.values())), flags=re.IGNORECASE) is not None,
        "self-improve cross-repo guidance must forbid reusing the current repo's lease/token for the other repo",
    )

    for label, text in {
        "post-merge skill": post_merge_skill,
        "post-merge prompt": post_merge,
        "conductor": conductor,
        "design": design,
    }.items():
        normalized = re.sub(r"\s+", " ", text)
        require("revert" in text.lower() and "active regression WI" in normalized,
                f"{label} must use the active regression WI for optional revert transport")

    external_write_surfaces = {
        "auto-review skill": auto_review_skill,
        "auto-review prompt": auto_review,
        "dep-sweep skill": dep_sweep_skill,
        "dep-sweep prompt": dep_sweep_prompt,
        "repo-implement": implement,
        "outdated-closure prompt": closure_prompt,
        "self-improve skill": self_improve_skill,
        "self-improve prompt": self_improve_prompt,
        "conductor": conductor,
        "design": design,
        "Copilot harness": harness,
        "goal loop": goal_loop,
    }
    for label, text in external_write_surfaces.items():
        require(
            re.search(r"file_tracker_item|open_draft_pr", text) is not None,
            f"{label} must gate its exact external write on a persisted authority grant",
        )
        require(
            re.search(r"escalat", text, flags=re.IGNORECASE) is not None,
            f"{label} must fall back to a durable prepared/escalated handoff without the grant",
        )
    require("never fix" in auto_review_skill.lower() or "never fixes" in auto_review_skill.lower(),
            "auto-review must stay find-only even when authority-gated")
    require("never bump" in dep_sweep_skill.lower(),
            "dep-sweep must stay find-only (never bump) even when authority-gated")
    require(
        re.search(r"tighten|self-lobotomy|never\s+weaken", self_improve_skill, flags=re.IGNORECASE) is not None,
        "self-improve must stay tighten-only even when authority-gated",
    )
    require(
        "no PR without a WI" in conductor or "no PR without" in implement.replace("\n", " "),
        "implement must never open a PR without a live work item",
    )
    require("live WI" in closure_prompt or "live, submitted" in conductor,
            "a quarantine/draft/implementation PR must require a live submitted WI, not open_draft_pr alone")

    # Gap — every standalone maintenance entry point must bootstrap the repository
    # lease ITSELF before any durable/shared/remote write (including onboarding or
    # /goal), not merely inherit one from the conductor. Enumerate exactly the 13
    # bundled commands/alias (MAINTENANCE_SKILLS) so a 14th silently ungated entry
    # point — or a 13th quietly dropping its bootstrap step — cannot go unnoticed.
    require(len(MAINTENANCE_SKILLS) == 13, "maintenance entry-point inventory must stay at exactly 13")
    repo_report_skill = (ROOT / "skills/repo-report/SKILL.md").read_text(encoding="utf-8")
    repo_triage_skill = (ROOT / "skills/repo-triage/SKILL.md").read_text(encoding="utf-8")
    repo_learn_skill = (ROOT / "skills/repo-learn/SKILL.md").read_text(encoding="utf-8")
    # Two of the 13 are validated by delegation/pre-existing checks rather than
    # their own restated bootstrap text: `repo-maintenance` (the conductor; its
    # onboarding-lease-before-writes ordering is already asserted above) and
    # `maintain-repo` (an exact alias that executes the conductor's procedure
    # inline, asserted above via its delegation to "../repo-maintenance/SKILL.md").
    delegated_to_conductor = {"repo-maintenance", "maintain-repo"}
    lease_bootstrap_texts = {
        "repo-learn": repo_learn_skill,
        "repo-triage": repo_triage_skill,
        "repo-implement": implement,
        "repo-pr-maintenance": pr_maintenance,
        "repo-auto-review": auto_review_skill,
        "custom-pr-review": custom_pr_review,
        "repo-dep-sweep": dep_sweep_skill,
        "repo-ci-health": ci_authority_surfaces["ci-health skill"],
        "repo-post-merge": post_merge_skill,
        "repo-report": repo_report_skill,
        "repo-self-improve": self_improve_skill,
    }
    require(
        set(lease_bootstrap_texts) | delegated_to_conductor == MAINTENANCE_SKILLS,
        "lease-bootstrap enumeration must cover exactly the 13 bundled commands/alias",
    )
    for name, text in lease_bootstrap_texts.items():
        normalized = re.sub(r"\s+", " ", text)
        require(
            re.search(r"repo_identity\.py", normalized) is not None,
            f"/{name} must resolve canonical repository identity before any shared write",
        )
        require(
            re.search(r"maintenance_lock\.py\s+acquire", normalized) is not None,
            f"/{name} must acquire the maintenance lease before any shared write",
        )
        require(
            re.search(r"maintenance_lock\.py\s+heartbeat", normalized) is not None,
            f"/{name} must be able to verify/heartbeat lease ownership",
        )
        require(
            re.search(r"release\s+(?:the|every)\s+lease", normalized, flags=re.IGNORECASE) is not None,
            f"/{name} must release the lease it acquired on exit",
        )
    # The ten loop-style standalone commands run potentially long dispatched-agent
    # batches between writes (unlike repo-learn's short one-shot onboarding pass
    # with no shared write after its one long local build-crack step), so each
    # must additionally fail closed on a lost lease: abort before any further
    # write on a nonzero/not-owner heartbeat, and the bootstrap must explicitly
    # cover /goal, not just backlog/tracker writes.
    for name, text in lease_bootstrap_texts.items():
        if name == "repo-learn":
            continue
        normalized = re.sub(r"\s+", " ", text)
        require(
            re.search(r"nonzero", normalized, flags=re.IGNORECASE) is not None
            and re.search(r"not-owner", normalized) is not None,
            f"/{name} must abort without further writes on a nonzero/not-owner heartbeat",
        )
        require(
            re.search(r"durable/shared/remote write.{0,20}including.{0,10}`?/goal`?", normalized, flags=re.IGNORECASE)
            is not None,
            f"/{name} must acquire the lease before onboarding/Goal writes too, not only backlog/tracker writes",
        )

    # Gap — report notification is outward-facing communication like any other
    # alert, so it must be gated on the persisted send_alert authority with a
    # prepare/escalate fallback — not a free best-effort send every fire performs
    # regardless of configured authority. The credentials-missing clean-skip
    # behavior must survive alongside the new authority gate, not be replaced by it.
    report_prompt = (shared / "prompts/report.md").read_text(encoding="utf-8")
    notify_surfaces = {
        "repo-report skill": repo_report_skill,
        "report prompt": report_prompt,
        "conductor": conductor,
        "design §4.5": design,
        "Copilot harness": harness,
    }
    for label, text in notify_surfaces.items():
        normalized = re.sub(r"\s+", " ", text)
        require(
            "send_alert" in normalized,
            f"{label} must gate report notification on the persisted send_alert authority",
        )
        require(
            re.search(r"never claim it was sent|do not send", normalized, flags=re.IGNORECASE) is not None,
            f"{label} must not claim an unsent notification was delivered",
        )
    for label, text in {
        "repo-report skill": repo_report_skill,
        "report prompt": report_prompt,
    }.items():
        normalized = re.sub(r"\s+", " ", text)
        require(
            "clean" in normalized.lower() and "skip" in normalized.lower(),
            f"{label} must keep the credentials-missing clean-skip behavior alongside the authority gate",
        )

    # Gap — review-comment scan recovery: resume any incomplete persisted prior scan
    # snapshot/high-watermark before capturing a new one; retain failed/inaccessible PR ids in a
    # pending set until processed or explicitly dispositioned with provider evidence; a PR closing or
    # unmerging mid-scan must not silently drop its comments.
    scan_recovery_surfaces = {
        "pr-review prompt": pr_review,
        "review-profile template": profile_template,
        "custom-pr-review skill": custom_pr_review,
        "design": design,
    }
    for label, text in scan_recovery_surfaces.items():
        require(
            re.search(r"pending[\s_-]*(?:PR)?s?[\s_-]*set|pending[\s_-]*prs", text, flags=re.IGNORECASE) is not None,
            f"{label} must persist a pending-PR set for an incomplete scan",
        )
        require(
            re.search(r"resum\w*|drain", text, flags=re.IGNORECASE) is not None,
            f"{label} must resume/drain an incomplete prior scan before capturing a new snapshot",
        )
        require(
            re.search(r"dispositioned?\s+with\s+provider\s+evidence|disposition\w*\s+evidence", text, flags=re.IGNORECASE)
            is not None,
            f"{label} must explicitly disposition a failed/closed PR with provider evidence",
        )
        require(
            re.search(r"closes?\s+or\s+unmerges?|closing.{0,20}unmerging|unmerg\w*", text, flags=re.IGNORECASE)
            is not None,
            f"{label} must handle a PR closing/unmerging mid-scan without silently dropping comments",
        )
    require(
        re.search(r"INCOMPLETE", pr_review) is not None,
        "pr-review prompt must flag a non-empty pending set as an INCOMPLETE prior scan",
    )
    for line in "\n".join(scan_recovery_surfaces.values()).splitlines():
        silent_drop_claim = re.search(r"\bdrop\w*\b.*\bcomments?\b", line, flags=re.IGNORECASE)
        if silent_drop_claim and not re.search(r"\b(?:not|never|no|without)\b", line, flags=re.IGNORECASE):
            raise AssertionError(f"silently-dropped-comments risk remains: {line.strip()}")

    operational_paths = [
        ROOT / "skills/repo-auto-review/SKILL.md",
        ROOT / "skills/repo-dep-sweep/SKILL.md",
        ROOT / "skills/repo-post-merge/SKILL.md",
        ROOT / "skills/repo-pr-maintenance/SKILL.md",
        ROOT / "skills/repo-self-improve/SKILL.md",
        ROOT / "skills/custom-pr-review/SKILL.md",
        ROOT / "skills/repo-maintenance/SKILL.md",
        shared / "DESIGN.md",
        shared / "HARNESS-COPILOT.md",
        shared / "bundled/goal-loop.md",
        shared / "prompts/auto-review.md",
        shared / "prompts/dep-sweep.md",
        shared / "prompts/engineer-charter.md",
        shared / "prompts/outdated-closure.md",
        shared / "prompts/post-merge.md",
        shared / "prompts/report.md",
        shared / "prompts/triage.md",
        shared / "prompts/pr-review.md",
        shared / "prompts/self-improve.md",
        shared / "review-profile.template.md",
    ]
    operational_blob = "\n".join(path.read_text(encoding="utf-8") for path in operational_paths)
    require("origin/main" not in operational_blob, "operational surfaces must not hardcode origin/main")
    require(re.search(r"\bMAIN\b", operational_blob) is None,
            "operational surfaces must not hardcode MAIN")
    for forbidden in (
        "integrated main",
        "passes on main",
        "passing-on-main",
        "against main.",
        "against current main",
        "default_branch:     main\n",
        "default_branch: main\n",
        "main-grounded",
    ):
        require(forbidden not in operational_blob,
                f"operational surfaces must not hardcode target-overriding wording: {forbidden!r}")
    require("{TARGET_REMOTE}/{TARGET_BRANCH}" in operational_blob,
            "operational surfaces must load the provider-neutral integration target somewhere")
    for label, text in {
        "post-merge skill": post_merge_skill,
        "post-merge prompt": post_merge,
        "conductor": conductor,
        "design": design,
    }.items():
        require("{TARGET_REMOTE}/{TARGET_BRANCH}" in text,
                f"{label} must load the exact provider-neutral integration target")


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
    goalctl = (ROOT / "runtime/goalctl.py").read_text(encoding="utf-8")
    continuation = (ROOT / "runtime/goal_continue.py").read_text(encoding="utf-8")
    require("COPILOT_AGENT_SESSION_ID" in goalctl, "Goal state must be session-scoped")
    require(
        'payload.get("sessionId")' in continuation,
        "Goal hook must derive identity from the agentStop payload",
    )
    require(
        "COPILOT_AGENT_SESSION_ID" not in continuation and "effective_session_id(" not in continuation,
        "Goal hook must not derive identity from ambient process state",
    )
    require(
        "if session_id is None:" in continuation,
        "Goal hook must fail open when payload identity is missing or malformed",
    )
    # Part A — the v1.0 -> v1.1 legacy migration must stay present and single-winner.
    require(
        "def claim_legacy_state(" in goalctl and "def legacy_state_path(" in goalctl,
        "Goal controller must keep the one-time legacy (cwd-only) state migration",
    )
    require(
        "os.rename(legacy, claim)" in goalctl,
        "legacy migration must claim atomically (move, not copy) so only one session adopts it",
    )

    # Part B — /goal is root-orchestrator-only; dispatched workers must never mutate Goal.
    goal_skill = (ROOT / "skills/goal/SKILL.md").read_text(encoding="utf-8")
    require("root-orchestrator-only" in goal_skill, "/goal must declare root-orchestrator-only ownership")
    require(
        "goalctl.py" in goal_skill and "hijack" in goal_skill and "sub-agent" in goal_skill,
        "/goal must forbid dispatched sub-agents from mutating Goal and explain the root-id hazard",
    )
    prompts_dir = ROOT / "skills/repo-maintenance/prompts"
    prompt_files = sorted(prompts_dir.glob("*.md"))
    require(len(prompt_files) == 12, f"prompt template inventory changed size unexpectedly: {len(prompt_files)}")
    # Every dispatched-worker prompt template must carry the GOAL GUARD verbatim —
    # enumerate the FULL directory (not a fixed sample) so a new prompt file can
    # never silently ship without it. `outdated-closure.md` is the sole documented
    # exception: it has no fenced dispatch block of its own (an orchestrator-run,
    # multi-stage recipe whose only dispatched workers are engineer-charter.md
    # makers, already guarded), so it carries an explanatory note instead of a
    # duplicate guard clause.
    no_own_dispatch_block = {"outdated-closure.md"}
    require(
        no_own_dispatch_block < {path.name for path in prompt_files},
        "the no-own-dispatch-block exception list must reference a real prompt file",
    )
    for path in prompt_files:
        worker = path.read_text(encoding="utf-8")
        require("GOAL GUARD" in worker, f"{path.name} must carry the GOAL GUARD for dispatched workers")
        if path.name in no_own_dispatch_block:
            require(
                re.search(r"no\s+fenced\s+dispatch\s+block", worker, flags=re.IGNORECASE) is not None,
                f"{path.name} must explain why it has no fenced dispatch block of its own",
            )
            continue
        require(
            "goalctl.py" in worker and "NEVER run" in worker,
            f"{path.name} must explicitly forbid goalctl/Goal mutation",
        )
    design = (ROOT / "skills/repo-maintenance/DESIGN.md").read_text(encoding="utf-8")
    require("Makers never touch Goal" in design, "DESIGN must state the maker Goal prohibition")


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
    session = (runtime / "src/core/session.ts").read_text(encoding="utf-8")
    secret_env = (runtime / "src/runtime/src/secrets/env.rs").read_text(encoding="utf-8")
    session_manager_test = (runtime / "test/core/localSessionManager.test.ts").read_text(encoding="utf-8")
    sdk_types = (runtime / "dist-cli/copilot-sdk/types.d.ts").read_text(encoding="utf-8")
    search_tool = (runtime / "src/tools/searchSubagentTool.ts").read_text(encoding="utf-8")
    task_names = (runtime / "src/tools/agentToolNames.ts").read_text(encoding="utf-8")
    interactive_shell = (runtime / "src/tools/interactiveShellTool.ts").read_text(encoding="utf-8")
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
        "COPILOT_AGENT_SESSION_ID: this.config.sessionId" in interactive_shell,
        "tool shells no longer receive the Goal session ID",
    )
    require(
        "sessionId: this.sessionId" in session,
        "subagent tool configuration no longer retains the root session ID",
    )
    require(
        "sessionId: this.agentId ?? this.sessionId" in session,
        "agentStop payload no longer identifies root stops by session ID and child stops by agent ID",
    )
    # Part B (rejected runtime fix): a child's tool shell receives the ROOT session
    # id (this.config.sessionId) and the runtime injects NO per-child agentId marker
    # into that shell, so goalctl running inside a worker cannot tell it is a child.
    # That is why child Goal isolation is a prompt contract, not a runtime marker;
    # the Stop hook stays correct because it reads the per-invocation stop payload.
    require(
        "COPILOT_AGENT_SESSION_ID: this.agentId" not in interactive_shell,
        "tool shells must not expose the child agentId; there is no child marker for goalctl to key on",
    )
    require(
        '"should not mutate process.env.COPILOT_AGENT_SESSION_ID on session creation"' in session_manager_test
        and 'await manager.createSession({ sessionId: "no-env-write-test" });' in session_manager_test
        and "expect(process.env.COPILOT_AGENT_SESSION_ID).toBeUndefined();" in session_manager_test,
        "session creation no longer proves that hook identity cannot rely on ambient process env",
    )
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
        skip_message = (
            "install smoke: SKIPPED — not a real install validation "
            "(set COPILOT_CLI_PATH or put copilot on PATH for one)"
        )
        require(
            os.environ.get("REQUIRE_INSTALL_SMOKE") != "1",
            f"{skip_message}; REQUIRE_INSTALL_SMOKE=1 forbids skipping the real check",
        )
        print(skip_message)
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
        require(
            f"Installed {len(EXPECTED_SKILLS)} skills." in install_output,
            "installer did not discover all skills",
        )
        require("/costas-agent-guide overview" in install_output, "installer did not show the onboarding message")

        list_output = invoke("plugin", "list")
        require(
            f"{PLUGIN_NAME}@{MARKETPLACE_NAME} (v{PLUGIN_VERSION})" in list_output,
            "installed plugin was not listed",
        )

        installed = Path(home) / "installed-plugins" / MARKETPLACE_NAME / PLUGIN_NAME
        installed_skills = list((installed / "skills").glob("*/SKILL.md"))
        installed_names = {path.parent.name for path in installed_skills}
        require(installed_names == EXPECTED_SKILLS, "installed skill inventory mismatch")
        for relative in (
            ".plugin/plugin.json",
            "hooks/hooks.json",
            "rules/agentic-engineering.md",
            "extensions/ultracode/extension.mjs",
            "skills/costas-agent-guide/SKILL.md",
            "skills/maintain-repo/SKILL.md",
            "runtime/goalctl.py",
            "runtime/goal_continue.py",
        ):
            require((installed / relative).is_file(), f"installed package is missing {relative}")
        for relative in MAINTENANCE_RESOURCES:
            installed_resource = installed / "skills/repo-maintenance" / relative
            require(installed_resource.is_file(), f"installed maintenance resource is missing {relative}")

    print(f"install smoke: {PLUGIN_NAME}@{MARKETPLACE_NAME}")


def main() -> int:
    validate_manifest()
    validate_skills()
    validate_loop_design_policy()
    validate_guide()
    validate_readme()
    validate_maintenance()
    validate_vendored()
    validate_markdown_links()
    validate_hooks()
    validate_source_syntax()
    validate_blocker_policies()
    runtime = validate_runtime_evidence()
    validate_install_smoke(runtime)

    run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"])
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
    print(
        f"validated: install, manifest, {len(EXPECTED_SKILLS)} skills, "
        "maintenance harness, onboarding guide, Loop Design, hooks, Goal, Ultracode"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
