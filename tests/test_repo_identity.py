from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/repo-maintenance/runtime/repo_identity.py"


def _load_repo_identity():
    spec = importlib.util.spec_from_file_location("repo_identity_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


repo_identity = _load_repo_identity()


class RepoIdentityTests(unittest.TestCase):
    def make_repo(self, root: Path, name: str, remote: str) -> Path:
        repo = root / name
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", remote],
            check=True,
        )
        return repo

    def resolve(self, repo: Path, copilot_home: Path) -> dict[str, str]:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--cwd", str(repo)],
            env={**os.environ, "COPILOT_HOME": str(copilot_home)},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_identity_is_bounded_unique_and_uses_copilot_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copilot_home = root / "copilot-home"
            first = self.make_repo(root, "first", "git@github.com:foo/bar-baz.git")
            second = self.make_repo(root, "second", "git@github.com:foo-bar/baz.git")
            long = self.make_repo(
                root,
                "long",
                "https://github.com/"
                + ("owner" * 20)
                + "/"
                + ("repository" * 20)
                + ".git",
            )

            first_identity = self.resolve(first, copilot_home)
            second_identity = self.resolve(second, copilot_home)
            long_identity = self.resolve(long, copilot_home)

            self.assertNotEqual(first_identity["repo_id"], second_identity["repo_id"])
            self.assertLessEqual(len(long_identity["skill_name"]), 64)
            self.assertEqual(
                Path(first_identity["adapter_path"]).parent.parent,
                copilot_home.resolve() / "skills",
            )
            self.assertEqual(
                Path(first_identity["state_dir"]).parent,
                copilot_home.resolve() / "repo-maintenance",
            )

    def test_worktrees_without_an_origin_share_one_state_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "main"
            worktree = root / "worktree"
            copilot_home = root / "copilot-home"
            subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "initial"],
                env={
                    **os.environ,
                    "GIT_AUTHOR_NAME": "Test",
                    "GIT_AUTHOR_EMAIL": "test@example.invalid",
                    "GIT_COMMITTER_NAME": "Test",
                    "GIT_COMMITTER_EMAIL": "test@example.invalid",
                },
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "add", "--quiet", "-b", "test", str(worktree)],
                check=True,
            )

            main_identity = self.resolve(repo, copilot_home)
            worktree_identity = self.resolve(worktree, copilot_home)
            self.assertEqual(main_identity["repo_id"], worktree_identity["repo_id"])
            self.assertEqual(main_identity["state_dir"], worktree_identity["state_dir"])

    def test_remote_aliases_and_ports_are_canonicalized_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copilot_home = root / "copilot-home"
            azure_ssh = self.make_repo(
                root,
                "azure-ssh",
                "git@ssh.dev.azure.com:v3/ExampleOrg/ExampleProject/ExampleRepo",
            )
            azure_https = self.make_repo(
                root,
                "azure-https",
                "https://dev.azure.com/ExampleOrg/ExampleProject/_git/ExampleRepo",
            )
            azure_encoded_ssh = self.make_repo(
                root,
                "azure-encoded-ssh",
                "git@ssh.dev.azure.com:v3/ExampleOrg/Cool%20Project/ExampleRepo",
            )
            azure_encoded_https = self.make_repo(
                root,
                "azure-encoded-https",
                "https://dev.azure.com/ExampleOrg/Cool%20Project/_git/ExampleRepo",
            )
            azure_distinct_project = self.make_repo(
                root,
                "azure-distinct-project",
                "https://dev.azure.com/ExampleOrg/CoolProject/_git/ExampleRepo",
            )
            port_2222 = self.make_repo(
                root,
                "port-2222",
                "ssh://git@example.com:2222/team/repo.git",
            )
            port_2223 = self.make_repo(
                root,
                "port-2223",
                "ssh://git@example.com:2223/team/repo.git",
            )
            file_remote = self.make_repo(
                root,
                "file-remote",
                "file:///srv/git/team/repo.git",
            )

            self.assertEqual(
                self.resolve(azure_ssh, copilot_home)["repo_id"],
                self.resolve(azure_https, copilot_home)["repo_id"],
            )
            self.assertEqual(
                self.resolve(azure_encoded_ssh, copilot_home)["repo_id"],
                self.resolve(azure_encoded_https, copilot_home)["repo_id"],
            )
            self.assertNotEqual(
                self.resolve(azure_encoded_ssh, copilot_home)["repo_id"],
                self.resolve(azure_distinct_project, copilot_home)["repo_id"],
            )
            self.assertNotEqual(
                self.resolve(port_2222, copilot_home)["repo_id"],
                self.resolve(port_2223, copilot_home)["repo_id"],
            )
            self.assertEqual(
                self.resolve(file_remote, copilot_home)["canonical_source"],
                f"local-remote:{Path('/srv/git/team/repo.git').resolve()}",
            )

    def test_file_url_host_is_dropped_and_localhost_is_equivalent(self) -> None:
        # POSIX Git file transport drops the URL authority, so
        # `file://server/share/repo.git` clones `/share/repo.git` while
        # `file:///server/share/repo.git` clones `/server/share/repo.git`.
        base = Path("/posix/checkout")
        host, _ = repo_identity.canonical_remote_for_platform(
            "file://server/share/repo.git", base, "posix"
        )
        root_scheme, _ = repo_identity.canonical_remote_for_platform(
            "file:///server/share/repo.git", base, "posix"
        )
        localhost, _ = repo_identity.canonical_remote_for_platform(
            "file://localhost/share/repo.git", base, "posix"
        )
        no_host, _ = repo_identity.canonical_remote_for_platform(
            "file:///share/repo.git", base, "posix"
        )

        self.assertNotEqual(host, root_scheme)
        self.assertEqual(host, "local-remote:/share/repo.git")
        self.assertEqual(root_scheme, "local-remote:/server/share/repo.git")
        self.assertEqual(localhost, no_host)
        self.assertEqual(localhost, "local-remote:/share/repo.git")

    def test_relative_origin_in_linked_worktree_shares_state_root(self) -> None:
        # A relative `remote.origin.url` is shared by every worktree via the
        # common config; it must resolve against one stable base (the main
        # worktree), so a nested linked worktree lands on the same state root.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copilot_home = root / "copilot-home"
            subprocess.run(["git", "init", "--quiet", "--bare", str(root / "upstream.git")], check=True)
            repo = root / "main"
            subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "initial"],
                env={
                    **os.environ,
                    "GIT_AUTHOR_NAME": "Test",
                    "GIT_AUTHOR_EMAIL": "test@example.invalid",
                    "GIT_COMMITTER_NAME": "Test",
                    "GIT_COMMITTER_EMAIL": "test@example.invalid",
                },
                check=True,
                capture_output=True,
            )
            # Relative origin, deliberately, to exercise base resolution.
            subprocess.run(
                ["git", "-C", str(repo), "remote", "add", "origin", "../upstream.git"],
                check=True,
            )
            nested = root / "a" / "b" / "linked"
            nested.parent.mkdir(parents=True)
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "add", "--quiet", "-b", "feat", str(nested)],
                check=True,
            )

            main_identity = self.resolve(repo, copilot_home)
            linked_identity = self.resolve(nested, copilot_home)
            self.assertEqual(main_identity["repo_id"], linked_identity["repo_id"])
            self.assertEqual(main_identity["state_dir"], linked_identity["state_dir"])
            # The relative origin resolves to the shared upstream, not per-worktree cwd.
            self.assertEqual(
                main_identity["canonical_source"],
                f"local-remote:{(root / 'upstream.git').resolve()}",
            )
            self.assertEqual(main_identity["canonical_source"], linked_identity["canonical_source"])

    def test_windows_drive_file_urls_normalize_without_checkout_drive(self) -> None:
        # Pure-function coverage for Windows semantics: runs on any OS because it
        # uses PureWindowsPath, not the real filesystem, and never mutates os.
        base = Path("/posix/checkout")
        c_drive, c_path = repo_identity.canonical_remote_for_platform(
            "file:///C:/Repo.git", base, "windows"
        )
        self.assertEqual(c_drive, "local-remote:c:/repo.git")
        self.assertEqual(c_path, "c:/repo.git")
        # Drive and path casing are folded so casing cannot fork identity.
        lower, _ = repo_identity.canonical_remote_for_platform(
            "file:///c:/repo.GIT", base, "windows"
        )
        self.assertEqual(lower, c_drive)
        # A bare Windows drive path normalizes identically.
        bare, _ = repo_identity.canonical_remote_for_platform(r"C:\REPO.git", base, "windows")
        self.assertEqual(bare, c_drive)
        # Distinct drives and nested repos stay distinct.
        d_drive, _ = repo_identity.canonical_remote_for_platform(
            "file:///D:/team/repo.git", base, "windows"
        )
        self.assertNotEqual(d_drive, c_drive)
        self.assertEqual(d_drive, "local-remote:d:/team/repo.git")
        # The POSIX checkout drive/cwd is never prefixed onto the drive path.
        self.assertNotIn(str(base), c_drive)
        self.assertTrue(c_drive.startswith("local-remote:c:/"))

    def test_windows_file_url_unc_retains_server_and_normalizes_case(self) -> None:
        base = Path("/posix/checkout")
        unc, unc_path = repo_identity.canonical_remote_for_platform(
            "file://SERVER/Share/Repo.git", base, "windows"
        )
        same_unc, _ = repo_identity.canonical_remote_for_platform(
            r"\\server\share\repo.GIT", base, "windows"
        )
        other_share, _ = repo_identity.canonical_remote_for_platform(
            "file://server/other/repo.git", base, "windows"
        )
        other_server, _ = repo_identity.canonical_remote_for_platform(
            "file://other/share/repo.git", base, "windows"
        )
        drive, _ = repo_identity.canonical_remote_for_platform(
            "file:///C:/share/repo.git", base, "windows"
        )

        self.assertEqual(unc, "local-remote://server/share/repo.git")
        self.assertEqual(unc_path, "//server/share/repo.git")
        self.assertEqual(same_unc, unc)
        self.assertNotEqual(other_share, unc)
        self.assertNotEqual(other_server, unc)
        self.assertNotEqual(drive, unc)


if __name__ == "__main__":
    unittest.main()
