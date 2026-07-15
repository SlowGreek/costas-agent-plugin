#!/usr/bin/env python3
"""Resolve bounded repository adapter and maintenance-state paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

MAX_SKILL_NAME = 64
DIGEST_LENGTH = 12
READABLE_LENGTH = 36
DEFAULT_PORTS = {"http": 80, "https": 443, "ssh": 22, "git": 9418}
# `/C:/repo.git` (from `file:///C:/repo.git`) or a bare `C:\repo.git` — a
# Windows drive-qualified path, which must be normalized with pure Windows
# semantics rather than resolved against the running checkout's drive.
WINDOWS_DRIVE_RE = re.compile(r"^[\\/]?([A-Za-z]):[\\/](.*)$")
WINDOWS_UNC_RE = re.compile(r"^(?:\\\\|//)([^\\/]+)[\\/]+([^\\/]+)(.*)$")


def git(cwd: Path, *args: str) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def strip_git_suffix(path: str) -> str:
    normalized = path.strip().strip("/")
    return normalized[:-4] if normalized.lower().endswith(".git") else normalized


def provider_remote(host: str, authority: str, remote_path: str) -> tuple[str, str]:
    path = strip_git_suffix(remote_path)
    components = [part for part in path.split("/") if part]
    azure: tuple[str, str, str] | None = None

    if host in {"ssh.dev.azure.com", "vs-ssh.visualstudio.com"}:
        if len(components) >= 4 and components[0].lower() == "v3":
            azure = (components[1], components[2], components[3])
    elif host == "dev.azure.com":
        if len(components) >= 4 and components[2].lower() == "_git":
            azure = (components[0], components[1], components[3])
    elif host.endswith(".visualstudio.com"):
        organization = host[: -len(".visualstudio.com")]
        if len(components) >= 3 and components[-2].lower() == "_git":
            azure = (organization, components[-3], components[-1])

    if azure is not None and ":" not in authority:
        organization, project, repository = (part.lower() for part in azure)
        readable = f"{organization}/{project}/{repository}"
        return f"azure:{readable}", readable

    if host == "github.com" and ":" not in authority:
        path = path.lower()
    return f"remote:{authority}/{path}", path


def current_platform_semantics() -> str:
    return "windows" if os.name == "nt" else "posix"


def normalize_windows_path(path: PureWindowsPath) -> str:
    return path.as_posix().casefold()


def windows_drive_remote(raw_path: str) -> tuple[str, str] | None:
    """Normalize a Windows drive path (``C:/repo.git``) with pure Windows
    semantics so it is stable regardless of the OS this helper runs on and is
    never joined onto the running checkout's drive."""
    match = WINDOWS_DRIVE_RE.match(raw_path)
    if match is None:
        return None
    drive = match.group(1).upper()
    remainder = match.group(2)
    normalized = normalize_windows_path(PureWindowsPath(f"{drive}:/{remainder}"))
    return f"local-remote:{normalized}", normalized


def windows_unc_remote(raw_path: str) -> tuple[str, str] | None:
    match = WINDOWS_UNC_RE.match(raw_path)
    if match is None:
        return None
    server = match.group(1)
    share = match.group(2)
    remainder = match.group(3).replace("/", "\\")
    normalized = normalize_windows_path(PureWindowsPath(f"//{server}/{share}{remainder}"))
    return f"local-remote:{normalized}", normalized


def local_remote(raw_path: str, base: Path, platform_semantics: str) -> tuple[str, str]:
    if platform_semantics == "windows":
        windows = windows_drive_remote(raw_path) or windows_unc_remote(raw_path)
        if windows is not None:
            return windows
    local = Path(raw_path).expanduser()
    if not local.is_absolute():
        local = base / local
    resolved = local.resolve()
    return f"local-remote:{resolved}", resolved.as_posix()


def file_url_remote(
    authority: str,
    path: str,
    base: Path,
    platform_semantics: str,
) -> tuple[str, str]:
    normalized_authority = authority.casefold()
    if platform_semantics == "windows" and normalized_authority not in {"", "localhost"}:
        return local_remote(f"//{authority}{path}", base, platform_semantics)
    return local_remote(path, base, platform_semantics)


def canonical_remote_for_platform(
    raw: str,
    base: Path,
    platform_semantics: str,
) -> tuple[str, str]:
    platform_semantics = platform_semantics.casefold()
    if platform_semantics not in {"posix", "windows"}:
        raise ValueError(f"unsupported platform semantics: {platform_semantics}")
    value = raw.strip()
    scp = re.fullmatch(r"(?:[^@/\s]+@)?([^:/\s]+):(.+)", value)
    if scp and "://" not in value and not re.match(r"^[A-Za-z]:[\\/]", value):
        host = scp.group(1).lower()
        remote_path = strip_git_suffix(unquote(scp.group(2)))
        return provider_remote(host, host, remote_path)

    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme == "file":
        return file_url_remote(
            unquote(parsed.netloc),
            unquote(parsed.path),
            base,
            platform_semantics,
        )
    if parsed.hostname:
        host = parsed.hostname.lower()
        remote_path = strip_git_suffix(unquote(parsed.path))
        port = parsed.port
        host_display = f"[{host}]" if ":" in host else host
        authority = host_display
        if port is not None and port != DEFAULT_PORTS.get(scheme):
            authority = f"{host_display}:{port}"
        return provider_remote(host, authority, remote_path)

    return local_remote(value, base, platform_semantics)


def canonical_remote(raw: str, base: Path) -> tuple[str, str]:
    return canonical_remote_for_platform(raw, base, current_platform_semantics())


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def resolve_common_dir(repo_root: Path) -> Path:
    """The common Git directory shared by a repository and every linked
    worktree. This is stable across worktrees, so it anchors both relative
    remote resolution and the origin-less identity."""
    common_raw = git(repo_root, "rev-parse", "--git-common-dir")
    if common_raw is None:
        raise ValueError("unable to resolve the repository common Git directory")
    common_dir = Path(common_raw)
    if not common_dir.is_absolute():
        common_dir = repo_root / common_dir
    return common_dir.resolve()


def resolve_identity(cwd: Path) -> dict[str, str]:
    repo_root_raw = git(cwd, "rev-parse", "--show-toplevel")
    if repo_root_raw is None:
        raise ValueError(f"{cwd} is not inside a Git repository")
    repo_root = Path(repo_root_raw).resolve()

    common_dir = resolve_common_dir(repo_root)
    # A relative `remote.origin.url` (e.g. `../bare.git`) is shared by every
    # worktree via the common config, so it must resolve against one stable base
    # — the main working tree derived from the common Git directory — not each
    # worktree's own cwd. For a normal (single-worktree) repo this base is the
    # repo root, so behavior is unchanged.
    base = common_dir.parent if common_dir.name == ".git" else common_dir

    origin = git(repo_root, "config", "--get", "remote.origin.url")
    if origin:
        canonical_source, remote_path = canonical_remote(origin, base)
        components = [part for part in remote_path.split("/") if part]
        readable_source = "-".join(components[-2:]) if components else repo_root.name
    else:
        canonical_source = f"git-common-dir:{common_dir}"
        readable_source = common_dir.parent.name or repo_root.name

    readable = slug(readable_source)[:READABLE_LENGTH].strip("-") or "repo"
    digest = hashlib.sha256(canonical_source.encode("utf-8")).hexdigest()[:DIGEST_LENGTH]
    repo_id = f"{readable}-{digest}"
    skill_name = f"{repo_id}-codebase"
    if len(skill_name) > MAX_SKILL_NAME:
        raise ValueError(f"generated skill name exceeds {MAX_SKILL_NAME} characters")

    copilot_home = Path(os.environ.get("COPILOT_HOME", Path.home() / ".copilot")).expanduser().resolve()
    skills_root = copilot_home / "skills"
    state_dir = copilot_home / "repo-maintenance" / repo_id
    return {
        "repo_id": repo_id,
        "skill_name": skill_name,
        "canonical_source": canonical_source,
        "repo_root": str(repo_root),
        "copilot_home": str(copilot_home),
        "skills_root": str(skills_root),
        "adapter_path": str(skills_root / skill_name / "SKILL.md"),
        "state_dir": str(state_dir),
        "backlog_path": str(state_dir / "backlog.md"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        print(json.dumps(resolve_identity(args.cwd.resolve()), indent=2, sort_keys=True))
    except (OSError, ValueError) as error:
        print(f"repository identity error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
