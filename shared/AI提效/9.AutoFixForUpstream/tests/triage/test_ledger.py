"""台账:stub 生成 / LLM 产物合并(schema 校验)/ 渲染。"""

import json

import pytest

from harness.lore import thread as T
from harness.series.store import SeriesStore
from harness.triage import ledger as L


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
        [], root_msgid="<cover@example.com>", import_mode=True)
    return st


def _stubs(store, thread_mbox):
    msgs = T.split_mbox(thread_mbox, store.round_dir(0))
    non_patch = [m for m in msgs if not m.is_patch]
    pidx = T.patch_index_of(msgs)
    midx = {m.msgid: m for m in msgs}
    ids = L.make_stubs(store, non_patch, 0, pidx, midx)
    return msgs, ids


def test_make_stubs_classification(store, thread_mbox):
    _, ids = _stubs(store, thread_mbox)
    items = {it["id"]: it for it in store.items()}
    assert len(items) == 5  # rev1, sash1, bot1, rev2, author1
    by_msgid = {it["source"]["message_id"]: it for it in items.values()}
    assert by_msgid["<rev1@kernel.org>"]["source"]["sender_class"] == "human"
    assert by_msgid["<sash1@kernel.org>"]["source"]["sender_class"] == "ai_reviewer"
    assert by_msgid["<bot1@intel.com>"]["source"]["sender_class"] == "bot"
    # 作者回复:record_only,不进待办
    a = by_msgid["<author1@example.com>"]
    assert a["source"]["sender_class"] == "author" and a["status"] == "record_only"
    # 关联 patch
    assert by_msgid["<rev1@kernel.org>"]["target_patch"]["seq"] == 1
    assert by_msgid["<rev2@kernel.org>"]["target_patch"]["seq"] == 2  # 沿链爬
    assert by_msgid["<bot1@intel.com>"]["target_patch"]["seq"] == 3
    assert len(store.pending_items()) == 4


def test_merge_round_valid_and_rejected(store, thread_mbox):
    _, ids = _stubs(store, thread_mbox)
    rdir = store.reviews_dir(0)
    # 合法产物
    (rdir / "item-r0-001.json").write_text(json.dumps({
        "id": "r0-001", "verdict": "valid", "fix_type": "code",
        "summary_zh": "人类意见有效", "quotes": ["the foo is wrong"],
        "analysis_zh": "核对源码成立", "fix_approach_zh": "改 bar",
    }, ensure_ascii=False), encoding="utf-8")
    # 违反 schema:多余字段
    (rdir / "item-r0-002.json").write_text(json.dumps({
        "id": "r0-002", "verdict": "invalid", "fix_type": "none",
        "summary_zh": "x", "status": "analyzed",  # status 不许 LLM 写
    }, ensure_ascii=False), encoding="utf-8")
    report = L.merge_round(store, 0)
    assert report["merged"] == ["r0-001"]
    assert len(report["rejected"]) == 1
    assert report["missing"]  # 其余 pending 无产物
    items = {it["id"]: it for it in store.items()}
    assert items["r0-001"]["status"] == "analyzed"
    assert items["r0-001"]["verdict"] == "valid"
    assert items["r0-002"]["status"] == "pending"  # 被拒的不动
    md = L.render_md(store)
    assert "r0-001" in md.read_text(encoding="utf-8")
