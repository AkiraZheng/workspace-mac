"""线程解析:拆分/增量/关联推断。"""

from harness.lore import thread as T
from tests.conftest import make_mbox


def test_split_and_parse(thread_mbox, tmp_path):
    msgs = T.split_mbox(thread_mbox, tmp_path / "out")
    assert len(msgs) == 9
    patches = [m for m in msgs if m.is_patch and m.patch_seq > 0]
    assert len(patches) == 3
    cover = next(m for m in msgs if m.is_cover)
    assert cover.patch_seq == 0
    p2 = next(m for m in msgs if m.patch_seq == 2)
    assert p2.msgid == "<p2@example.com>"
    # 嵌套人类回复:非 patch
    rev2 = next(m for m in msgs if m.msgid == "<rev2@kernel.org>")
    assert not rev2.is_patch


def test_diff_msgids_preserves_order_and_idempotent(thread_mbox, tmp_path):
    msgs = T.split_mbox(thread_mbox, tmp_path / "out")
    seen = {m.msgid for m in msgs[:5]}
    new = T.diff_msgids(msgs, seen)
    assert [m.msgid for m in new] == [m.msgid for m in msgs[5:]]
    # 幂等:再跑一次为空
    assert T.diff_msgids(msgs, {m.msgid for m in msgs}) == []


def test_associate_paths(thread_mbox, tmp_path):
    msgs = T.split_mbox(thread_mbox, tmp_path / "out")
    pidx = T.patch_index_of(msgs)
    midx = {m.msgid: m for m in msgs}
    get = lambda mid: next(m for m in msgs if m.msgid == mid)
    # 1) In-Reply-To 直配
    assert T.associate(get("<rev1@kernel.org>"), pidx, midx) == 1
    # 2) References 从右往左(bot 只有 References,最右是 p3)
    assert T.associate(get("<bot1@intel.com>"), pidx, midx) == 3
    # 3) 沿 In-Reply-To 向上爬(rev2 挂在 sashiko 下,sashiko 回复 p2)
    assert T.associate(get("<rev2@kernel.org>"), pidx, midx) == 2
    # 4) 兜底:链断(irt 未知且 refs 清空)-> 0
    fake_root_reply = get("<rev1@kernel.org>")
    fake_root_reply.in_reply_to = "<unknown@nowhere>"
    fake_root_reply.refs = []
    assert T.associate(fake_root_reply, pidx, midx) == 0


def test_init_patch_extraction_filter(thread_mbox, tmp_path):
    """init 模式交给 patch-merge-workflow 的过滤:只要非 cover 的 patch 邮件。"""
    msgs = T.split_mbox(thread_mbox, tmp_path / "out")
    patches = [m for m in msgs if m.is_patch and not m.is_cover]
    assert [m.patch_seq for m in patches] == [1, 2, 3]
    assert all(m.body.startswith(("first", "second", "third")) for m in patches)
    # review/作者回复一律不进 patch 目录
    assert not any("Re:" in m.subject_clean for m in patches)


def test_quoted_printable_body_decoded(tmp_path):
    import email.policy
    import mailbox
    raw = ("From x@example.com Mon Oct  5 10:00:00 2026\n"
           "From: sashiko-bot@kernel.org\n"
           "Subject: Re: [PATCH v5 1/3] first\n"
           "Message-ID: <qp@example.com>\n"
           "Content-Type: text/plain; charset=utf-8\n"
           "Content-Transfer-Encoding: quoted-printable\n"
           "\n"
           "found=20one=20issue=\n"
           "continued\n")
    p = tmp_path / "qp.mbox"
    p.write_text(raw, encoding="utf-8")
    msgs = T.split_mbox(p, tmp_path / "qp")
    assert msgs[0].body.strip() == "found one issuecontinued"


def test_subject_unfolding(tmp_path):
    raw = ("From x@example.com Mon Oct  5 10:00:00 2026\n"
           "From: maz@kernel.org\n"
           "Subject: Re: [PATCH v5 12/15] KVM: arm64: Derive the VM hardware dirty mode\n"
           " from dirty logging\n"
           "Message-ID: <fold@example.com>\n"
           "\nbody\n")
    p = tmp_path / "fold.mbox"
    p.write_text(raw, encoding="utf-8")
    msgs = T.split_mbox(p, tmp_path / "fold")
    assert msgs[0].subject_clean == \
        "Re: [PATCH v5 12/15] KVM: arm64: Derive the VM hardware dirty mode from dirty logging"


def test_rfc_prefixed_patch_subjects(tmp_path):
    """watch 线程的 RFC 系列:[RFC PATCH x/y] 也是 patch 邮件,不是意见。"""
    raw = ("From x@example.com Mon Oct  5 10:00:00 2026\n"
           "From: leo.bras@arm.com\n"
           "Subject: [RFC PATCH 1/5] KVM: arm64: pgtables: Change write bit\n"
           "Message-ID: <rfc1@arm.com>\n"
           "\nbody\n"
           "From x@example.com Mon Oct  5 10:01:00 2026\n"
           "From: leo.bras@arm.com\n"
           "Subject: [RFC PATCH v2 2/5] second\n"
           "Message-ID: <rfc2@arm.com>\n"
           "\nbody\n"
           "From x@example.com Mon Oct  5 10:02:00 2026\n"
           "From: maz@kernel.org\n"
           "Subject: Re: [RFC PATCH 1/5] KVM: arm64: pgtables: Change write bit\n"
           "Message-ID: <rfcrev@kernel.org>\n"
           "In-Reply-To: <rfc1@arm.com>\n"
           "\nbody\n")
    p = tmp_path / "rfc.mbox"
    p.write_text(raw, encoding="utf-8")
    msgs = T.split_mbox(p, tmp_path / "rfc")
    assert [m.patch_seq for m in msgs if m.is_patch] == [1, 2]
    # 回复不因 RFC 前缀被误判为 patch,且能关联到 rfc patch 1
    rev = next(m for m in msgs if m.msgid == "<rfcrev@kernel.org>")
    assert not rev.is_patch
    pidx = T.patch_index_of(msgs)
    midx = {m.msgid: m for m in msgs}
    assert T.associate(rev, pidx, midx) == 1
