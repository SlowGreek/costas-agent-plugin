"""Hermes compatibility contract for the dual-host Costas Agent Plugin."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class _HermesContext:
    def __init__(self) -> None:
        self.skills: dict[str, tuple[Path, str]] = {}

    def register_skill(self, name: str, path: Path, description: str = "") -> None:
        self.skills[name] = (path, description)


class HermesPluginCompatibilityTests(unittest.TestCase):
    def test_manifest_and_entrypoint_register_every_skill(self) -> None:
        manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
        self.assertIn("name: costas-agent-plugin", manifest)
        self.assertIn("kind: standalone", manifest)

        entrypoint = ROOT / "__init__.py"
        spec = importlib.util.spec_from_file_location("costas_agent_plugin", entrypoint)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        context = _HermesContext()
        module.register(context)

        expected = {
            skill_dir.name
            for skill_dir in (ROOT / "skills").iterdir()
            if (skill_dir / "SKILL.md").is_file()
        }
        self.assertEqual(set(context.skills), expected)
        self.assertIn("super-goal", context.skills)

        for name, (path, description) in context.skills.items():
            expected_path = (
                ROOT / "hermes-skills" / name / "SKILL.md"
                if name == "super-goal"
                else ROOT / "skills" / name / "SKILL.md"
            )
            self.assertEqual(path, expected_path)
            self.assertTrue(description.strip(), f"{name} must expose a description")


if __name__ == "__main__":
    unittest.main()
