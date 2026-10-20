"""git 只读操作封装(写操作仅在 finalize/fix 流程的受控入口)。"""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def run_git(repo: Path, *args: str, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} 失败:\n{proc.stderr.strip()}")
    return proc


def rev_list(repo: Path, base: str, ref: str = "HEAD") -> list[str]:
    """rev-list --reverse base..ref,返回从旧到新的 sha 列表。"""
    proc = run_git(repo, "rev-list", "--reverse", f"{base}..{ref}")
    return [l for l in proc.stdout.splitlines() if l.strip()]


def subjects(repo: Path, shas: list[str]) -> list[str]:
    out = []
    for sha in shas:
        proc = run_git(repo, "log", "-1", "--format=%s", sha)
        out.append(proc.stdout.strip())
    return out


def subject_of(repo: Path, sha: str) -> str:
    return subjects(repo, [sha])[0]


def is_clean(repo: Path) -> bool:
    return run_git(repo, "status", "--porcelain").stdout.strip() == ""


def commit_exists(repo: Path, sha: str) -> bool:
    return run_git(repo, "cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0


def merge_base(repo: Path, a: str, b: str) -> str:
    return run_git(repo, "merge-base", a, b).stdout.strip()


def head(repo: Path) -> str:
    return run_git(repo, "rev-parse", "HEAD").stdout.strip()


def current_branch(repo: Path) -> str:
    return run_git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def commit_files(repo: Path, sha: str) -> list[str]:
    proc = run_git(repo, "show", "--name-only", "--format=", sha)
    return [l for l in proc.stdout.splitlines() if l.strip()]
