"""SKILL.md 规范:frontmatter / 行数 / python 代码块语法。"""

import ast
import re
import textwrap
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"


def _skill_files():
    return sorted(p for p in SKILLS_DIR.glob("*/SKILL.md"))


def test_skills_present():
    names = {p.parent.name for p in _skill_files()}
    assert names == {"autofix-upstream", "series-init", "review-triage",
                     "fix-executor", "series-finalize"}


def test_frontmatter():
    for p in _skill_files():
        text = p.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        assert m, f"{p}: 缺 frontmatter"
        fm = m.group(1)
        assert re.search(r"^name:\s*" + p.parent.name + r"\s*$", fm, re.M), p
        desc = re.search(r"^description:\s*(.+)$", fm, re.M)
        assert desc and len(desc.group(1).strip()) > 10, f"{p}: description 过短"


def test_line_budget():
    for p in _skill_files():
        n = len(p.read_text(encoding="utf-8").splitlines())
        assert n <= 300, f"{p}: {n} 行,超过 300 行预算"


def test_iron_rule_no_send_present():
    """铁律固化:每个 SKILL.md 都必须声明"绝不发送 patch"。"""
    for p in _skill_files():
        text = p.read_text(encoding="utf-8")
        assert "绝不发送" in text, f"{p}: 缺铁律声明(绝不发送 patch)"
        assert "send-email" in text or "b4 send" in text, \
            f"{p}: 铁律未点名禁止的发送工具(git send-email / b4 send)"


def test_python_blocks_parse():
    for p in _skill_files():
        text = p.read_text(encoding="utf-8")
        for i, block in enumerate(re.findall(r"```python\n(.*?)```", text, re.S)):
            try:
                ast.parse(textwrap.dedent(block))
            except SyntaxError as e:
                raise AssertionError(f"{p} 第 {i+1} 个 python 块语法错误: {e}")
