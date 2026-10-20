"""解析 cover letter(.eml 线程封面 或 format-patch 输出的 0000 文件)。

结构(以 HDBSS v5 为参照):
    [From <sha> ...]                    (mbox 封行,可选)
    邮件头(From/Date/Subject,支持折行头)
    <正文:实现描述 + 评论请求 + 相对 RFC 说明>
    Changes since v(N-1) [2]:  ...      (逐版 changelog)
    [1] https://lore.kernel.org/...     (链接区)
    Signed-off-by: ...                  (SoB 区)
    <作者 shortlog> / <diffstat> / base-commit:  (format-patch 自动区,忽略)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

CHANGELOG_RE = re.compile(r"^Changes since v(\d+)\s*\[(\d+)\]:?\s*$")
LINK_RE = re.compile(r"^\[(\d+)\]\s*(https?://\S+)\s*$")
SHORTLOG_RE = re.compile(r"^\S.*\(\d+\):$")


@dataclass
class Changelog:
    version: int          # 该节描述的旧版本号,如 v4
    ref: int              # 引用的链接编号(v5 cover 中 v4 -> [2])
    lines: list[str] = field(default_factory=list)


@dataclass
class CoverDoc:
    subject: str = ""     # [PATCH v5 00/15] KVM: arm64: ...
    title: str = ""       # 去掉 [PATCH ...] 前缀的标题
    author: str = ""
    date: str = ""
    description: list[str] = field(default_factory=list)  # 首个 changelog 节之前
    changelogs: list[Changelog] = field(default_factory=list)
    links: list[tuple[int, str]] = field(default_factory=list)
    sobs: list[str] = field(default_factory=list)
    base_commit: str = ""

    def link_of(self, num: int) -> str | None:
        for n, url in self.links:
            if n == num:
                return url
        return None


def _split_headers_body(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    """跳过可选的 mbox 封行,展开折行头,返回 (headers, body_lines)。"""
    i = 0
    if lines and lines[0].startswith("From "):
        i = 1
    headers: dict[str, str] = {}
    last: str | None = None
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            break
        if line[:1] in (" ", "\t") and last:
            headers[last] = (headers[last] + " " + line.strip()).strip()
        else:
            m = re.match(r"^([A-Za-z][A-Za-z0-9-]*):\s?(.*)$", line)
            if m:
                last = m.group(1)
                headers[last] = m.group(2).strip()
            else:
                last = None
        i += 1
    return headers, lines[i:]


def parse_cover(path: Path) -> CoverDoc:
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    headers, body = _split_headers_body(lines)
    doc = CoverDoc(
        subject=headers.get("Subject", ""),
        author=headers.get("From", ""),
        date=headers.get("Date", ""),
    )
    m = re.match(r"^\[PATCH[^\]]*\]\s*(.+)$", doc.subject)
    doc.title = m.group(1).strip() if m else doc.subject

    section = "body"
    cur_log: Changelog | None = None
    for line in body:
        m = CHANGELOG_RE.match(line)
        lm = LINK_RE.match(line)
        if section == "body":
            if m:
                cur_log = Changelog(version=int(m.group(1)), ref=int(m.group(2)))
                section = "changelog"
            elif lm:  # 无 changelog 的 cover(v1 系列)
                doc.links.append((int(lm.group(1)), lm.group(2)))
                section = "links"
            elif line.startswith("Signed-off-by:"):
                doc.sobs.append(line.strip())
                section = "sob"
            else:
                doc.description.append(line)
        elif section == "changelog":
            if m:
                if cur_log:
                    doc.changelogs.append(cur_log)
                cur_log = Changelog(version=int(m.group(1)), ref=int(m.group(2)))
            elif lm:
                if cur_log:
                    doc.changelogs.append(cur_log)
                    cur_log = None
                doc.links.append((int(lm.group(1)), lm.group(2)))
                section = "links"
            elif line.startswith("Signed-off-by:"):
                if cur_log:
                    doc.changelogs.append(cur_log)
                    cur_log = None
                doc.sobs.append(line.strip())
                section = "sob"
            elif line.startswith("base-commit:"):
                doc.base_commit = line[len("base-commit:"):].strip()
                break
            elif cur_log is not None:
                cur_log.lines.append(line)
        elif section == "links":
            if lm:
                doc.links.append((int(lm.group(1)), lm.group(2)))
            elif line.startswith("Signed-off-by:"):
                doc.sobs.append(line.strip())
                section = "sob"
            elif line.startswith("base-commit:"):
                doc.base_commit = line[len("base-commit:"):].strip()
                break
        elif section == "sob":
            if line.startswith("Signed-off-by:"):
                doc.sobs.append(line.strip())
            elif line.startswith("base-commit:"):
                doc.base_commit = line[len("base-commit:"):].strip()
                break
            # shortlog/diffstat 区在 SoB 之后、base-commit 之前,继续扫描直到
            # base-commit(format-patch 布局),其余行忽略  # 进入 shortlog/diffstat 区
    if cur_log:
        doc.changelogs.append(cur_log)
    while doc.description and not doc.description[-1].strip():
        doc.description.pop()
    return doc
