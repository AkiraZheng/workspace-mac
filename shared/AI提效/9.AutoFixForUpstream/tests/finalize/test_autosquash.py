"""finalize rebase 层:todo 生成 / orphans 守卫 / 真跑 rebase / 冲突 abort / 重映射。"""

import pytest

from harness.finalize import autosquash
from tests.conftest import commit, git


def make_state(base: str, series: list[str], fixes: list[tuple[str, int]]) -> dict:
    return {
        "schema_version": "1.0", "series_id": "t", "phase": "monitoring",
        "base": {"commit": base, "subject": "base"},
        "series_commits": [{"seq": i + 1, "sha": s, "subject": f"series-{i+1}",
                            "msgid": None, "new_sha": None} for i, s in enumerate(series)],
        "fix_commits": [{"sha": f, "subject": "fix", "target_seq": tgt, "origin": "test"}
                        for f, tgt in fixes],
    }


def test_build_todo_order(git_repo):
    state = make_state(git_repo.base, git_repo.series,
                       [(git_repo.fixes[0], 2), (git_repo.fixes[1], 2)])
    todo = autosquash.build_todo(state, git_repo.path)
    assert todo[:4] == [
        f"pick {git_repo.series[0]}",
        f"pick {git_repo.series[1]}",
        f"fixup {git_repo.fixes[0]}",
        f"fixup {git_repo.fixes[1]}",
    ]
    assert len(todo) == 5 + 2


def test_orphans_guard_rejects_missing(git_repo):
    state = make_state(git_repo.base, git_repo.series, [(git_repo.fixes[0], 2)])
    todo = autosquash.build_todo(state, git_repo.path)  # 漏了 fixes[1]
    with pytest.raises(autosquash.RebaseError, match="不一致"):
        autosquash.check_orphans(todo, git_repo.path, git_repo.base)


def test_rebase_absorbs_fixes(git_repo, tmp_path):
    """核心链路:fix 挤入目标 patch,树内容不丢,message 不含 fix 信息。"""
    state = make_state(git_repo.base, git_repo.series,
                       [(git_repo.fixes[0], 2), (git_repo.fixes[1], 2)])
    autosquash.archive_fixups(git_repo.path, git_repo.fixes, tmp_path / "arch")
    autosquash.create_backup_branch(git_repo.path, "backup/t")
    todo = autosquash.build_todo(state, git_repo.path)
    autosquash.run_rebase(git_repo.path, git_repo.base, todo, tmp_path / "todo")

    # (a) fix 内容进树
    assert (git_repo.path / "f2.txt").read_text() == "series-2\nfix-a\nfix-b\n"
    # (b) commit 数 == 系列数(fix 被吸收)
    new = git_repo.rev_list()
    assert len(new) == 5
    # (c) 目标 patch 的 message 不含 fix 信息,其余文件不受影响
    msg2 = git(git_repo.path, "log", "-1", "--format=%B", new[1]).stdout
    assert msg2.strip() == "series-2"
    assert (git_repo.path / "f5.txt").read_text() == "series-5\n"
    # (g) sha 重映射
    old_to_new = autosquash.remap_shas(git_repo.path, git_repo.base, state)
    assert [old_to_new[s] for s in git_repo.series] == new
    # 归档与备份存在
    assert len(list((tmp_path / "arch").glob("*.patch"))) == 2
    assert git(git_repo.path, "rev-parse", "--verify", "backup/t").returncode == 0


def test_rebase_with_reword(git_repo, tmp_path):
    """message_change_needed 路径:fixup 后 exec amend 替换 message。"""
    reword = tmp_path / "reword-seq2.msg"
    reword.write_text("series-2 (reworked)\n\nnew body line\n", encoding="utf-8")
    state = make_state(git_repo.base, git_repo.series,
                       [(git_repo.fixes[0], 2), (git_repo.fixes[1], 2)])
    todo = autosquash.build_todo(state, git_repo.path, rewords={2: reword})
    assert f"exec git commit --amend --no-edit -F {reword}" in todo
    autosquash.run_rebase(git_repo.path, git_repo.base, todo, tmp_path / "todo")
    new = git_repo.rev_list()
    msg2 = git(git_repo.path, "log", "-1", "--format=%B", new[1]).stdout
    assert msg2.startswith("series-2 (reworked)")
    assert "new body line" in msg2
    assert (git_repo.path / "f2.txt").read_text() == "series-2\nfix-a\nfix-b\n"


def test_conflict_aborts_and_restores(tmp_path):
    """fix 与后续 series commit 改同一行 -> 冲突自动 abort,分支回到 rebase 前。"""
    import subprocess
    from tests.conftest import GIT_ENV

    def run(*a):
        return subprocess.run(["git", "-C", str(repo), *a], check=True,
                              capture_output=True, text=True, env=GIT_ENV)

    repo = tmp_path / "conf"
    repo.mkdir()
    run("init", "-q", "-b", "main")
    (repo / "r.txt").write_text("base\n")
    base = commit(repo, "base")
    (repo / "f.txt").write_text("a\nb\nc\n")
    s1 = commit(repo, "s1")
    (repo / "g.txt").write_text("g\n")
    s2 = commit(repo, "s2")
    (repo / "f.txt").write_text("a\nB\nc\n")   # s3 改 line2 b->B
    s3 = commit(repo, "s3")
    (repo / "f.txt").write_text("a\nB2\nc\n")  # fix 也改 line2 -> 重放即冲突
    fix = commit(repo, "fix collides with s3")

    state = make_state(base, [s1, s2, s3], [(fix, 1)])
    autosquash.create_backup_branch(repo, "backup/t")
    before = run("rev-parse", "HEAD").stdout.strip()
    todo = autosquash.build_todo(state, repo)
    with pytest.raises(autosquash.RebaseError, match="abort"):
        autosquash.run_rebase(repo, base, todo, tmp_path / "todo")
    # 分支回到 rebase 前,备份仍在
    assert run("rev-parse", "HEAD").stdout.strip() == before
    assert run("rev-parse", "--verify", "backup/t").returncode == 0
    assert (repo / "f.txt").read_text() == "a\nB2\nc\n"
