"""线程解析:拆分 mbox、提取头、Message-ID 增量、意见->patch 关联推断。

纯 python(email/mailbox 标准库),不依赖 grep/formail/git-mailsplit。
"""

from __future__ import annotations

import email
import email.policy
import email.utils
import mailbox
import re
from dataclasses import dataclass, field
from pathlib import Path

from harness.lore.b4fetch import normalize_msgid

# [PATCH v5 12/15] / [PATCH v5 00/15] / [PATCH 12/15](无版本号兜底)
PATCH_SUBJECT_RE = re.compile(r"^\s*\[PATCH(?:\s+v(\d+))?\s+(\d+)/(\d+)\]\s*(.*)$")
REPLY_RE = re.compile(r"^\s*(re|答复|回复)\s*:", re.IGNORECASE)


@dataclass
class MailMsg:
    path: Path
    msgid: str
    in_reply_to: str | None
    refs: list[str] = field(default_factory=list)
    from_name: str = ""
    from_email: str = ""
    date: str = ""
    subject: str = ""            # 原始(unfold 后)
    subject_clean: str = ""      # 空白折叠
    body: str = ""
    is_patch: bool = False       # 系列自身的 patch 邮件(非 Re:,带 [PATCH vN x/y])
    patch_seq: int | None = None # patch 序号(1 起;0 = cover)

    @property
    def is_cover(self) -> bool:
        return self.is_patch and self.patch_seq == 0


def _clean_header(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_message(path: Path) -> MailMsg | None:
    msg = email.message_from_binary_file(open(path, "rb"), policy=email.policy.default)
    msgid = normalize_msgid(msg.get("Message-ID"))
    if not msgid:
        return None
    irt = normalize_msgid(msg.get("In-Reply-To"))
    refs = [r for r in (normalize_msgid(x) for x in re.split(r"\s+", msg.get("References") or "")) if r]
    frm_name, frm_email = email.utils.parseaddr(str(msg.get("From") or ""))
    subject = str(msg.get("Subject") or "")
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_content()
                break
    else:
        try:
            body = msg.get_content()
        except Exception:
            body = str(msg.get_payload())
    subject_clean = _clean_header(subject)
    m = PATCH_SUBJECT_RE.match(subject_clean)
    is_patch = False
    patch_seq = None
    if m and not REPLY_RE.match(subject_clean):
        is_patch = True
        patch_seq = int(m.group(2))
    return MailMsg(
        path=path, msgid=msgid, in_reply_to=irt, refs=refs,
        from_name=frm_name, from_email=frm_email,
        date=_clean_header(str(msg.get("Date") or "")),
        subject=subject.replace("\r\n", " ").replace("\n", " ").strip(),
        subject_clean=subject_clean,
        body=body or "",
        is_patch=is_patch, patch_seq=patch_seq,
    )


def split_mbox(mbox_path: Path, out_dir: Path) -> list[MailMsg]:
    """拆分线程 mbox 为单邮件 .eml 并解析,按 mbox 内顺序返回。

    写出时把正文解码为纯文本(quoted-printable/base64 还原),头部保持原样,
    便于 LLM 直接阅读;原始字节级保真由 round mbox 快照承担。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    msgs: list[MailMsg] = []
    for i, msg in enumerate(mailbox.mbox(mbox_path), start=1):
        eml = out_dir / f"{i:04d}.eml"
        raw = msg.as_bytes(policy=email.policy.default)
        head, _, _ = raw.partition(b"\n\n")
        body = ""
        parsed_raw = email.message_from_bytes(raw, policy=email.policy.default)
        if parsed_raw.is_multipart():
            for part in parsed_raw.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_content()
                    break
        else:
            try:
                body = parsed_raw.get_content()
            except Exception:
                body = str(parsed_raw.get_payload())
        eml.write_bytes(head + b"\n\n" + body.encode("utf-8", errors="replace"))
        parsed = parse_message(eml)
        if parsed:
            msgs.append(parsed)
    return msgs


def diff_msgids(msgs: list[MailMsg], seen: set[str]) -> list[MailMsg]:
    """本轮消息中去掉已见过的 Message-ID,保持顺序(幂等)。"""
    return [m for m in msgs if m.msgid not in seen]


def associate(msg: MailMsg, patch_index: dict[str, int],
              msg_index: dict[str, MailMsg], cover_seq: int = 0) -> int:
    """推断一条意见针对哪个 patch。

    返回 patch seq:0 = 系列级(cover/整体);>0 = 某个 patch;-1 = 无法确定。
    顺序:In-Reply-To 直配 -> References 从右往左(最近祖先优先) ->
    沿 In-Reply-To 链向上爬 -> 兜底 0。
    """
    if msg.is_patch:
        return msg.patch_seq if msg.patch_seq is not None else -1
    for cand in [msg.in_reply_to, *reversed(msg.refs)]:
        if cand and cand in patch_index:
            return patch_index[cand]
    cur = msg.in_reply_to
    climbed: set[str] = set()
    while cur and cur not in climbed:
        climbed.add(cur)
        if cur in patch_index:
            return patch_index[cur]
        parent = msg_index.get(cur)
        cur = parent.in_reply_to if parent else None
    # 爬到根(cover)或链断:按系列级处理,LLM 可在 triage 时从引用内容修正
    return cover_seq


def patch_index_of(msgs: list[MailMsg]) -> dict[str, int]:
    """{patch msgid -> seq(0=cover)}。"""
    idx: dict[str, int] = {}
    for m in msgs:
        if m.is_patch and m.patch_seq is not None:
            idx.setdefault(m.msgid, m.patch_seq)
    return idx


def is_review(msg: MailMsg, series_authors: set[str]) -> bool:
    """是否生成台账 item:非系列 patch/cover 的一切跟进邮件。"""
    return not msg.is_patch and msg.from_email.lower() not in {a.lower() for a in series_authors}


def subject_of_seq(msgs: list[MailMsg], seq: int) -> str | None:
    for m in msgs:
        if m.is_patch and m.patch_seq == seq:
            m2 = PATCH_SUBJECT_RE.match(m.subject_clean)
            if m2:
                return m2.group(4).strip()
    return None
