"""cover 生成:脚手架(链接重编号)与最终拼接(splice 进 format-patch 骨架)。"""

from __future__ import annotations

import re
from pathlib import Path

from harness.cover.parse import CoverDoc

CHANGELOG_PLACEHOLDER = "<!-- CHANGELOG_PLACEHOLDER: 由 finalize 从台账生成英文条目;条目须按 kernel 惯例动词开头 -->"


def _shift_refs(text: str, shift_from: int) -> str:
    """把 text 中 [N](N >= shift_from) 的引用编号 +1,降序替换避免串位。"""
    for n in range(9, shift_from - 1, -1):
        text = text.replace(f"[{n}]", f"[{n + 1}]")
    return text


def scaffold_next(cover: CoverDoc, next_version: int, prev_version: int,
                  prev_lore_url: str, patch_count: int, out_path: Path) -> Path:
    """从上一版 cover 生成下一版草稿。

    - 实现描述拷贝(引用编号顺移);
    - 新增空的 "Changes since v<prev> [2]:" 节(插在最旧节之前);
    - 旧 changelog 节整体顺移([N] -> [N+1],N >= 2);
    - 链接区:新链接(上一版自己的 lore url)插为 [2],原 [2..] 顺移。
    """
    desc = "\n".join(cover.description)
    desc = _shift_refs(desc, 2) if any(n >= 2 for n, _ in cover.links) else desc

    sections: list[str] = []
    sections.append(f"Subject: [PATCH v{next_version} 00/{patch_count}] {cover.title}\n")
    sections.append(desc.strip("\n"))

    sections.append(f"\n\nChanges since v{prev_version} [2]:\n\n{CHANGELOG_PLACEHOLDER}\n")

    for log in cover.changelogs:
        body = "\n".join(log.lines).strip("\n")
        body = _shift_refs(body, 2)
        sections.append(f"\n\nChanges since v{log.version} [{log.ref + 1}]:\n\n{body}\n")

    links = ["\n"]
    links.append(f"[1] {cover.link_of(1)}" if cover.link_of(1) else "")
    links.append(f"[2] {prev_lore_url}")
    for n, url in cover.links:
        if n >= 2:
            links.append(f"[{n + 1}] {url}")
    sections.append("\n".join(l for l in links if l) + "\n")

    sections.append("\n" + "\n".join(cover.sobs))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(sections).rstrip("\n") + "\n", encoding="utf-8")
    return out_path


def read_final_cover(final_path: Path) -> tuple[str, str]:
    """读最终 cover 文件 -> (标题, 正文)。

    文件格式:首行 Subject: [PATCH vN 00/MM] <标题>,空行后是正文
    (到 SoB 结束;shortlog/diffstat 由 format-patch 骨架自动生成)。
    """
    text = Path(final_path).read_text(encoding="utf-8")
    first, _, rest = text.partition("\n")
    m = re.match(r"^Subject:\s*\[PATCH[^\]]*\]\s*(.+)$", first)
    title = m.group(1).strip() if m else ""
    body = rest if m else text
    return title, body.strip("\n") + "\n"


def splice_into_format_patch(final_path: Path, fp_0000: Path) -> Path:
    """把最终 cover 拼进 format-patch --cover-letter 生成的 0000 骨架。"""
    title, body = read_final_cover(final_path)
    fp = Path(fp_0000).read_text(encoding="utf-8")
    if "*** SUBJECT HERE ***" not in fp or "*** BLURB HERE ***" not in fp:
        raise ValueError(f"format-patch 骨架缺少占位符: {fp_0000}")
    fp = fp.replace("*** SUBJECT HERE ***", title)
    fp = re.sub(r"\*\*\* BLURB HERE \*\*\*", body.rstrip("\n"), fp, count=1)
    Path(fp_0000).write_text(fp, encoding="utf-8")
    return Path(fp_0000)
