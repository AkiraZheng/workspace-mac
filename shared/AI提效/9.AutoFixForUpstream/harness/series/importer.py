"""import 模式:注册一个已在进行中的系列(分支/fix 都已存在)。

校验分支拓扑(master..HEAD == N 系列 commit + M fix commit),
从线程 mbox 提取 patch msgid 与系列 commit 配对,落 state。
"""

from __future__ import annotations

from pathlib import Path

from harness.common import gitops
from harness.lore import thread as thread_mod


class ImportError_(RuntimeError):
    pass


def resolve_sha(repo: Path, sha: str) -> str:
    proc = gitops.run_git(repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}", check=False)
    if proc.returncode != 0:
        raise ImportError_(f"commit 不存在: {sha}")
    return proc.stdout.strip()


def verify_topology(repo: Path, base: str, fix_shas: list[str]) -> tuple[list[str], list[str]]:
    """返回 (series_shas 从旧到新, fix_shas 从旧到新)。"""
    commits = gitops.rev_list(repo, base)
    full_fixes = [resolve_sha(repo, s) for s in fix_shas]
    fix_set = set(full_fixes)
    unknown = [s for s in full_fixes if s not in commits]
    if unknown:
        raise ImportError_(
            f"以下 fix commit 不在 {base[:12]}..HEAD 范围内: {unknown[:3]}\n"
            f"当前分支: {gitops.current_branch(repo)},请先 checkout 系列工作分支")
    series = [c for c in commits if c not in fix_set]
    fixes = [c for c in commits if c in fix_set]
    # fix 必须全部位于系列 commit 之后(允许 fix 之间穿插,但系列在前)
    if fixes and series:
        first_fix_pos = commits.index(fixes[0])
        last_series_pos = max(commits.index(s) for s in series)
        if last_series_pos > first_fix_pos:
            raise ImportError_(
                "系列 commit 与 fix commit 交错,拓扑异常:\n"
                f"  最后一个系列 commit 位于第一个 fix 之后 "
                f"({commits[last_series_pos][:12]} > {commits[first_fix_pos][:12]})")
    return series, fixes


def pair_msgids(repo: Path, series_shas: list[str],
                msgs: list[thread_mod.MailMsg]) -> list[dict]:
    """series commit <-> patch 邮件 msgid 配对(先按标题精确匹配,再按顺序兜底)。"""
    patches = sorted(
        (m for m in msgs if m.is_patch and m.patch_seq and m.patch_seq > 0),
        key=lambda m: m.patch_seq)
    if len(patches) != len(series_shas):
        raise ImportError_(
            f"patch 邮件数({len(patches)}) != 分支系列 commit 数({len(series_shas)}),"
            "请确认线程是本系列的最新版本")

    def patch_title(m: thread_mod.MailMsg) -> str:
        mm = thread_mod.PATCH_SUBJECT_RE.match(m.subject_clean)
        return mm.group(4).strip() if mm else m.subject_clean

    commit_subjects = gitops.subjects(repo, series_shas)
    title_to_msgid: dict[str, str] = {}
    for m in patches:
        title_to_msgid.setdefault(patch_title(m), m.msgid)
    used: set[str] = set()
    out: list[dict] = []
    for i, (sha, subj) in enumerate(zip(series_shas, commit_subjects)):
        msgid = None
        if subj in title_to_msgid and title_to_msgid[subj] not in used:
            msgid = title_to_msgid[subj]
        elif patches[i].msgid not in used:  # 顺序兜底
            msgid = patches[i].msgid
        if msgid:
            used.add(msgid)
        out.append({"seq": i + 1, "sha": sha, "subject": subj, "msgid": msgid, "new_sha": None})
    return out
