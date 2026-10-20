"""CLI 端到端:import --mbox-file -> poll 幂等 -> poll 增量。"""

import json
import subprocess

import pytest

from harness import cli
from tests.conftest import commit, git, make_mbox


@pytest.fixture
def repo3(tmp_path):
    """3 个系列 commit(主题与 thread_mbox 的 patch 标题一致)。"""
    class R:
        pass
    r = R()
    r.path = tmp_path / "r3"
    r.path.mkdir()
    git(r.path, "init", "-q", "-b", "main")
    (r.path / "x.txt").write_text("base\n")
    r.base = commit(r.path, "base")
    r.series = []
    for title in ("first", "second", "third"):
        (r.path / f"{title}.txt").write_text(title + "\n")
        r.series.append(commit(r.path, title))
    return r


def _cfg(tmp_path, repo):
    p = tmp_path / "series.yaml"
    p.write_text(
        f"series_id: t-cli\n"
        f"repo_path: {repo.path}\n"
        f"work_branch: main\n"
        f"base_commit: {repo.base}\n"
        f"prev_version: 5\n"
        f"new_version: 6\n"
        f"prev_msgid: cover@example.com\n"
        f"series_authors:\n  - t@example.com\n", encoding="utf-8")
    return p


def _run(capsys, *argv):
    rc = cli.main(list(argv))
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_import_then_poll_idempotent(repo3, thread_mbox, tmp_path, capsys):
    cfg = _cfg(tmp_path, repo3)
    rc, out, _e = _run(capsys, "import", "--config", str(cfg),
                   "--mbox-file", str(thread_mbox))
    assert rc == 0
    data = json.loads(out.strip().splitlines()[-1])
    assert data["series_commits"] == 3 and data["messages"] == 9
    assert data["pending"] == 4  # rev1, sash1, bot1, rev2(作者回复 record_only)
    sdir = repo3.path / ".autofix" / "t-cli"
    assert (sdir / "cover" / "cover-v6.draft.md").is_file()
    # msgid 配对(标题匹配)
    state = json.loads((sdir / "state.json").read_text())
    assert all(sc["msgid"] for sc in state["series_commits"])

    # poll 同一 mbox:幂等,零新意见
    rc, out, _e = _run(capsys, "poll", "--repo", str(repo3.path),
                   "--series-id", "t-cli", "--mbox-file", str(thread_mbox), "--json")
    assert rc == 0
    assert json.loads(out.strip())["new_messages"] == 0

    # mbox 追加一封新意见 -> round 1 新 item
    grown = make_mbox(tmp_path / "grown.mbox", json.loads(json.dumps([
        {"from_": "Marc Zyngier <maz@kernel.org>",
         "subject": "Re: [PATCH v5 2/3] second", "msgid": "<newrev@kernel.org>",
         "irt": "<p2@example.com>", "refs": ["<p2@example.com>"],
         "body": "Another late comment."},
    ])))
    grown.write_text(thread_mbox.read_text(encoding="utf-8") +
                     grown.read_text(encoding="utf-8"), encoding="utf-8")
    rc, out, _e = _run(capsys, "poll", "--repo", str(repo3.path),
                   "--series-id", "t-cli", "--mbox-file", str(grown), "--json")
    assert rc == 0
    data = json.loads(out.strip())
    assert data["round"] == 1 and data["new_messages"] == 1
    assert data["new_pending"] == ["r1-001"]

    # 状态渲染
    rc, out, _e = _run(capsys, "status", "--repo", str(repo3.path), "--series-id", "t-cli")
    assert rc == 0 and "t-cli" in out


def test_send_stub_always_refuses(capsys):
    """铁律:CLI 的 send 子命令永远拒绝,不存在任何发送路径。"""
    rc, out, err = _run(capsys, "send")
    assert rc == 2
    assert "绝不发送" in err
    # 任何 send 变体参数同样拒绝
    rc, _, err = _run(capsys, "send", "--to", "someone@x")
    assert rc == 2 and "绝不发送" in err


def test_import_rejects_wrong_branch(repo3, thread_mbox, tmp_path, capsys):
    cfg = _cfg(tmp_path, repo3)
    cfg.write_text(cfg.read_text().replace("work_branch: main", "work_branch: other"))
    rc, out, _e = _run(capsys, "import", "--config", str(cfg),
                   "--mbox-file", str(thread_mbox))
    assert rc == 2 and "checkout" in (_e + out)
