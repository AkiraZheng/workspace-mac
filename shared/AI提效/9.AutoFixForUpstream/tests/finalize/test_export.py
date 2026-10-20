"""导出:format-patch 骨架 + cover splice。"""

from harness.finalize import autosquash, export as export_mod
from tests.finalize.test_autosquash import make_state
from tests.conftest import git


def test_export_series(git_repo, tmp_path):
    state = make_state(git_repo.base, git_repo.series,
                       [(git_repo.fixes[0], 2), (git_repo.fixes[1], 2)])
    todo = autosquash.build_todo(state, git_repo.path)
    autosquash.run_rebase(git_repo.path, git_repo.base, todo, tmp_path / "todo")

    cover = tmp_path / "cover.final"
    cover.write_text(
        "Subject: [PATCH v6 00/5] test series\n\n"
        "Body of the cover.\n\n"
        "Changes since v5 [2]:\n\n- Did X.\n\n"
        "[2] https://lore.kernel.org/all/v5@example.com/\n\n"
        "Signed-off-by: T <t@example.com>\n", encoding="utf-8")
    out = tmp_path / "v6"
    patches = export_mod.export_series(git_repo.path, git_repo.base, 6, cover, out)
    assert len(patches) == 6  # 0000 + 5
    assert patches[0].name.startswith("0000-")
    cov = patches[0].read_text(encoding="utf-8")
    assert "*** SUBJECT HERE ***" not in cov
    assert "*** BLURB HERE ***" not in cov
    assert "test series" in cov.splitlines()[3]
    assert "Changes since v5" in cov
    assert "Did X." in cov
    assert f"base-commit: {git_repo.base}" in cov
    # fix 内容在 0002(第 2 个 patch),且无 fix message 痕迹
    p2 = (out / "0002-series-2.patch").read_text(encoding="utf-8")
    assert "fix-a" in p2 and "fix-b" in p2
    subj = [l for l in p2.splitlines() if l.startswith("Subject:")][0]
    assert subj == "Subject: [PATCH v6 2/5] series-2"
