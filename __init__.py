"""Hermes Agent adapter for the dual-host Costas Agent Plugin.

GitHub Copilot consumes the Open Plugin manifest under ``.plugin/`` directly.
Hermes loads this module and exposes the same skill sources through qualified
names such as ``costas-agent-plugin:super-goal``. The adapter deliberately does
not emulate Copilot extensions or hooks; Hermes-native equivalents remain owned
by Hermes itself.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_ROOT = Path(__file__).resolve().parent
_SKILLS_ROOT = _ROOT / "skills"
_HERMES_SKILLS_ROOT = _ROOT / "hermes-skills"
_DESCRIPTION_RE = re.compile(r"^description:\s*(.+?)\s*$", re.MULTILINE)


def _skill_description(skill_path: Path) -> str:
    """Read the compact frontmatter description without a YAML dependency."""

    content = skill_path.read_text(encoding="utf-8")
    match = _DESCRIPTION_RE.search(content)
    if match is None:
        return f"Costas Agent Plugin skill: {skill_path.parent.name}"

    description = match.group(1).strip()
    if len(description) >= 2 and description[0] == description[-1] and description[0] in {"'", '"'}:
        description = description[1:-1]
    return description or f"Costas Agent Plugin skill: {skill_path.parent.name}"


def register(ctx: Any) -> None:
    """Register every bundled skill with Hermes under this plugin namespace."""

    for skill_dir in sorted(_SKILLS_ROOT.iterdir(), key=lambda path: path.name):
        hermes_adapter = _HERMES_SKILLS_ROOT / skill_dir.name / "SKILL.md"
        skill_path = hermes_adapter if hermes_adapter.is_file() else skill_dir / "SKILL.md"
        if not skill_path.is_file():
            continue
        ctx.register_skill(
            skill_dir.name,
            skill_path,
            _skill_description(skill_path),
        )
