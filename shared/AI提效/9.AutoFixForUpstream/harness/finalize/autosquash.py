"""finalize 的 rebase 层:todo 生成 + orphans 守卫 + 非交互执行 + sha 重映射。

核心安全设计:
- todo 完全由 state 的 fix->patch 映射生成(不依赖 "fixup!" 主题字符串匹配,
  因此对导入的普通 fix commit 和新建的 --fixup commit 一视同仁);
- orphans 守卫:todo 中的 sha 集合必须严格等于 rev-list base..HEAD 的集合,
  防止 todo 漏写导致 rebase 静默丢 commit;
- 冲突自动 abort(分支回到 rebase 前,备份分支仍在);
- rebase 前先 format-patch 归档全部 fix commit + 建备份分支。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from harness.common import gitops


class RebaseError(RuntimeError):
    pass


def build_todo(state: dict, repo: Path, rewords: dict[int, Path] | None = None) -> list[str]:
    """从 state 生成完整 rebase todo。

    rewords: {patch seq -> 新 commit message 文件}(仅 message_change_needed 的 patch)。
    """
    fixes_by_seq: dict[int, list[str]] = {}
    for fx in state["fix_commits"]:
        fixes_by_seq.setdefault(fx["target_seq"], []).append(fx["sha"])
    todo: list[str] = []
    for sc in state["series_commits"]:
        todo.append(f"pick {sc['sha']}")
        for fx in fixes_by_seq.get(sc["seq"], []):
            todo.append(f"fixup {fx}")
        if rewords and sc["seq"] in rewords:
            todo.append(f"exec git commit --amend --no-edit -F {rewords[sc['seq']]}")
    return todo


def check_orphans(todo: list[str], repo: Path, base: str) -> None:
    """todo 覆盖的 commit 必须与 base..HEAD 完全一致。"""
    todo_shas = {line.split()[1] for line in todo if line.split()[0] in ("pick", "fixup", "squash")}
    actual = set(gitops.rev_list(repo, base))
    resolved: set[str] = set()
    for s in todo_shas:
        proc = gitops.run_git(repo, "rev-parse", "--verify", "--quiet", f"{s}^{{commit}}", check=False)
        if proc.returncode != 0:
            raise RebaseError(f"todo 引用了不存在的 commit: {s}")
        resolved.add(proc.stdout.strip())
    missing = actual - resolved
    extra = resolved - actual
    if missing or extra:
        raise RebaseError(
            f"todo 与 {base[:12]}..HEAD 不一致(拒绝执行,防止静默丢 commit):\n"
            f"  漏写 {len(missing)} 个: {[m[:12] for m in missing][:5]}\n"
            f"  多余 {len(extra)} 个: {[e[:12] for e in extra][:5]}")


def archive_fixups(repo: Path, fix_shas: list[str], out_dir: Path) -> list[Path]:
    """rebase 前 format-patch 归档全部 fix commit(保险)。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    archived: list[Path] = []
    for i, sha in enumerate(fix_shas, start=1):
        proc = gitops.run_git(repo, "format-patch", "-1", "--stdout", sha)
        p = out_dir / f"{i:04d}-{sha[:12]}.patch"
        p.write_text(proc.stdout, encoding="utf-8")
        archived.append(p)
    return archived


def create_backup_branch(repo: Path, name: str) -> str:
    gitops.run_git(repo, "branch", "-f", name, "HEAD")
    return name


def run_rebase(repo: Path, base: str, todo: list[str], todo_path: Path) -> None:
    """GIT_SEQUENCE_EDITOR=cp 方式非交互执行 rebase;冲突自动 abort。"""
    todo_path.parent.mkdir(parents=True, exist_ok=True)
    todo_path.write_text("\n".join(todo) + "\n", encoding="utf-8")
    check_orphans(todo, repo, base)
    env = dict(os.environ,
               GIT_SEQUENCE_EDITOR=f"cp {todo_path}",
               GIT_EDITOR="true",
              EDITOR="true")
    proc = subprocess.run(
        ["git", "-C", str(repo), "rebase", "-i", "--empty=drop", base],
        env=env, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        subprocess.run(["git", "-C", str(repo), "rebase", "--abort"],
                       capture_output=True, text=True)
        raise RebaseError(
            f"rebase 失败(已自动 abort,分支回到 rebase 前):\n"
            f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}\n"
            "常见原因: fix 与后续 patch 上下文冲突(映射错误或 fix 需拆分),"
            "请检查 fix->patch 映射后重试,或人工处理。")


def remap_shas(repo: Path, base: str, state: dict) -> dict[str, str]:
    """rebase 成功后重建 series commit 的 new_sha(顺序语义不变)。"""
    new_shas = gitops.rev_list(repo, base)
    if len(new_shas) != len(state["series_commits"]):
        raise RebaseError(
            f"rebase 后 commit 数 {len(new_shas)} != 系列数 {len(state['series_commits'])},"
            "请人工检查分支")
    old_to_new: dict[str, str] = {}
    for sc, new in zip(state["series_commits"], new_shas):
        sc["new_sha"] = new
        old_to_new[sc["sha"]] = new
    return old_to_new
