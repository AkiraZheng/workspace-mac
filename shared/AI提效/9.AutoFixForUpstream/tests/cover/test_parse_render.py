"""cover 解析与生成:五段切分 / 链接重编号 / splice。"""

from harness.cover.parse import parse_cover
from harness.cover.render import scaffold_next, splice_into_format_patch


def test_parse_cover_sections(v5_cover):
    doc = parse_cover(v5_cover)
    assert doc.subject == "[PATCH v5 00/3] test series for cover parse"
    assert doc.title == "test series for cover parse"
    assert doc.author == "T Tian <t@example.com>"
    assert "This series implements a test feature" in "\n".join(doc.description)
    assert "Comments welcome." in "\n".join(doc.description)
    assert [(c.version, c.ref) for c in doc.changelogs] == [(4, 2), (3, 3)]
    assert [n for n, _ in doc.links] == [1, 2, 3]
    assert doc.link_of(2) == "https://lore.kernel.org/all/v4@example.com/"
    assert doc.sobs == ["Signed-off-by: T Tian <t@example.com>"]
    assert doc.base_commit == "1111222233334444555566667777888899990000"
    assert any("Did A." in l for c in doc.changelogs if c.version == 4 for l in c.lines)


def test_scaffold_renumbers_links(v5_cover, tmp_path):
    doc = parse_cover(v5_cover)
    out = scaffold_next(doc, 6, 5, "https://lore.kernel.org/all/v5@example.com/", 3,
                        tmp_path / "v6draft.md")
    text = out.read_text(encoding="utf-8")
    assert "Subject: [PATCH v6 00/3] test series for cover parse" in text
    # 新 changelog 节 + 占位符
    assert "Changes since v5 [2]:" in text
    assert "CHANGELOG_PLACEHOLDER" in text
    # 旧节顺移:[2]->[3] 的 v4,[3]->[4] 的 v3
    assert "Changes since v4 [3]:" in text
    assert "Changes since v3 [4]:" in text
    # 链接区重编号
    assert "[1] https://lore.kernel.org/all/rfc@example.com/" in text
    assert "[2] https://lore.kernel.org/all/v5@example.com/" in text
    assert "[3] https://lore.kernel.org/all/v4@example.com/" in text
    assert "[4] https://lore.kernel.org/all/v3@example.com/" in text
    # SoB 保留
    assert "Signed-off-by: T Tian <t@example.com>" in text


def test_splice(v5_cover, tmp_path):
    fp = tmp_path / "0000-cover-letter.patch"
    fp.write_text(
        "From 0000 Mon Sep 17 00:00:00 2001\n"
        "From: T <t@example.com>\n"
        "Date: Mon, 5 Oct 2026 10:00:00 +0000\n"
        "Subject: [PATCH v6 00/3] *** SUBJECT HERE ***\n"
        "\n"
        "*** BLURB HERE ***\n"
        "\n"
        "T Tian (3):\n"
        "  first\n"
        "\n"
        " f1 | 1 +\n"
        " 1 file changed, 1 insertion(+)\n"
        "\n"
        "base-commit: 1111\n", encoding="utf-8")
    final = tmp_path / "final.md"
    final.write_text("Subject: [PATCH v6 00/3] the real title\n\nbody line\n",
                     encoding="utf-8")
    splice_into_format_patch(final, fp)
    text = fp.read_text(encoding="utf-8")
    assert "*** SUBJECT HERE ***" not in text
    assert "*** BLURB HERE ***" not in text
    assert "Subject: [PATCH v6 00/3] the real title" in text
    assert "body line" in text
    assert "T Tian (3):" in text
    assert "base-commit: 1111" in text
