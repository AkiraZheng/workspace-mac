"""store:创建/状态迁移/phase 守卫/台账 schema。"""

import pytest

from harness.series.store import SeriesError, SeriesStore


@pytest.fixture
def store(git_repo):
    cfg = {
        "repo_path": str(git_repo.path), "work_branch": "main",
        "prev_version": 5, "new_version": 6, "prev_msgid": "<cover@example.com>",
        "series_authors": ["t@example.com"],
    }
    st = SeriesStore.create(git_repo.path, "t-series", cfg)
    st.init_state(
        git_repo.base,
        [{"seq": i + 1, "sha": s, "subject": f"series-{i+1}", "msgid": None, "new_sha": None}
         for i, s in enumerate(git_repo.series)],
        [{"sha": f, "subject": "fix", "target_seq": 2, "origin": "imported"}
         for f in git_repo.fixes],
        root_msgid="<cover@example.com>", import_mode=True)
    return st


def test_init_and_phase_guard(store):
    assert store.state["phase"] == "monitoring"
    assert len(store.state["series_commits"]) == 5
    assert len(store.state["fix_commits"]) == 2
    store.require_phase("monitoring")
    with pytest.raises(SeriesError):
        store.require_phase("finalizing")


def test_save_state_schema_rejects_bad_phase(store):
    with pytest.raises(SeriesError, match="schema"):
        store.save_state(phase="bogus")


def test_ledger_schema_rejects_bad_item(store):
    with pytest.raises(SeriesError, match="schema"):
        store.save_ledger([{"id": "bad", "status": "not-a-status"}])


def test_record_fix_and_status(store, git_repo):
    from tests.conftest import commit
    (git_repo.path / "f3.txt").write_text("series-3\nnew\n")
    sha = commit(git_repo.path, "fix c", fixup=git_repo.series[2])
    store.record_fix(sha, 3, "r0-001")
    st = store.state
    assert any(f["sha"] == sha and f["target_seq"] == 3 for f in st["fix_commits"])
    with pytest.raises(SeriesError):
        store.record_fix(sha, 3, "dup")
    d = store.status_dict()
    assert d["patches"] == 5 and d["fixes"] == 3 and d["phase"] == "monitoring"


def test_exclude_written(git_repo, store):
    excl = (git_repo.path / ".git" / "info" / "exclude").read_text()
    assert ".autofix/" in excl
