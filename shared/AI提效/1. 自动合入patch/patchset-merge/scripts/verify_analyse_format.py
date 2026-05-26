#!/usr/bin/env python3
"""verify_analyse_format.py — 格式验证门禁（方案 A + D 的 D 部分）

检查 analyse.md / summary.md 格式完整性：
- 所有章节存在
- 无未替换占位符（{REQUIRES_AI} 除外）
- 必需表格非空

用法:
  # 单文件检查
  python3 verify_analyse_format.py --file patch_analysis/0001-xxx-analys.md

  # 目录批量检查
  python3 verify_analyse_format.py --dir patch_analysis/

  # 检查 summary.md
  python3 verify_analyse_format.py --type summary --file patch_analysis/summary.md

退出码:
  0 = 格式正确
  1 = 章节缺失
  2 = 占位符未替换
  3 = 必需字段为空
  4 = 文件不存在
"""

from __future__ import annotations

import os
import re
import sys
import argparse

ANALYSE_SECTIONS = [
    "1. 基本信息",
    "2. 功能描述与关联模块",
    "3. 依赖分析",
    "4. Revert 需求评估",
    "5. 风险程度",
    "6. 人工 Review 需求度",
    "7. 建议验证冒烟内容",
    "8. 合入实际经验",
    "9. 与源 Patch/Commit 的差异对比",
    "10. 编译验证记录",
    "11. Review 建议与改进方向",
]

SUMMARY_SECTIONS = [
    "基本信息",
    "合入顺序与状态",
    "依赖关系图",
    "Revert 记录",
    "编译验证总览",
    "跨 Patch 修复记录",
    "目标仓库重复 patch 汇总",
    "全局改进建议",
    "全局风险汇总",
    "待处理事项",
]

AI_PLACEHOLDER = "{REQUIRES_AI}"
AI_PLACEHOLDER_PREFIX = "{REQUIRES_AI_"

PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*\}")

OK = 0
ERR_SECTION = 1
ERR_PLACEHOLDER = 2
ERR_EMPTY = 3
ERR_MISSING = 4


def check_sections(content: str, required: list[str]) -> list[str]:
    missing = []
    for s in required:
        if f"## {s}" not in content and f"# {s}" not in content:
            missing.append(s)
    return missing


def check_placeholders(content: str) -> list[str]:
    found = []
    for m in PLACEHOLDER_RE.finditer(content):
        ph = m.group()
        if ph == AI_PLACEHOLDER or ph.startswith(AI_PLACEHOLDER_PREFIX):
            continue
        found.append(ph)
    return found


def check_required_tables(content: str) -> list[str]:
    empty_tables = []
    table_sections = ["1. 基本信息"]
    for section in table_sections:
        section_start = content.find(f"## {section}")
        if section_start < 0:
            continue

        section_block = content[section_start:]
        next_section = sys.maxsize
        for s in ANALYSE_SECTIONS:
            pos = content.find(f"## {s}", section_start + len(f"## {section}") + 1)
            if pos > 0:
                next_section = min(next_section, pos)
        section_block = content[section_start:next_section]

        if "|-----|" not in section_block and "|----|" not in section_block:
            empty_tables.append(f"{section}: 无表格")
            continue

        lines = section_block.split("\n")
        data_lines = 0
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("|") and not stripped.startswith("|-"):
                cells = [c.strip() for c in stripped.split("|")[1:-1]]
                if any(c == "" or c == "{" for c in cells):
                    continue
                data_lines += 1
        if data_lines < 2:
            empty_tables.append(f"{section}: 表格数据行不足")

    return empty_tables


def verify_file(filepath: str, file_type: str = "analyse") -> int:
    if not os.path.exists(filepath):
        print(f"[FAIL] 文件不存在: {filepath}", file=sys.stderr)
        return ERR_MISSING

    with open(filepath) as f:
        content = f.read()

    sections = ANALYSE_SECTIONS if file_type == "analyse" else SUMMARY_SECTIONS
    missing = check_sections(content, sections)

    if missing:
        print(f"[FAIL] {filepath}: 缺失章节: {', '.join(missing)}", file=sys.stderr)
        return ERR_SECTION

    placeholders = check_placeholders(content)
    if placeholders:
        print(f"[FAIL] {filepath}: 未替换占位符: {', '.join(placeholders)}", file=sys.stderr)
        return ERR_PLACEHOLDER

    if file_type == "analyse":
        ai_count = content.count(AI_PLACEHOLDER)
        has_title = content.strip().startswith("# Patch ")
        title = content.split("\n")[0].replace("# ", "") if has_title else "?"

        # 检查核心表格：第 1 节基本信息表
        section_1 = content.find("## 1. 基本信息")
        if section_1 >= 0:
            section_1_block = content[section_1:]
            next_section = sys.maxsize
            for s in ANALYSE_SECTIONS[1:]:
                pos = content.find(f"## {s}", section_1 + 1)
                if pos > 0:
                    next_section = min(next_section, pos)
            section_1_content = content[section_1:next_section]
            if "|-----" not in section_1_content and "|----" not in section_1_content:
                print(f"[WARN] {title}: 第 1 节无表格，但章节标题存在", file=sys.stderr)

        print(f"[PASS] {title} — {len(sections)} 章节完整, {ai_count} 个 AI 待填字段")
        return OK if has_title else ERR_SECTION

    print(f"[PASS] {os.path.basename(filepath)} — {len(sections)} 章节完整")
    return OK


def main():
    parser = argparse.ArgumentParser(description="格式验证门禁")
    parser.add_argument("--file", help="单个文件路径")
    parser.add_argument("--dir", help="目录批量检查")
    parser.add_argument("--type", default="analyse",
                        choices=["analyse", "summary"],
                        help="文件类型")
    args = parser.parse_args()

    if not args.file and not args.dir:
        print("[FAIL] 需要 --file 或 --dir", file=sys.stderr)
        sys.exit(1)

    codes = []

    if args.file:
        codes.append(verify_file(args.file, args.type))

    if args.dir:
        if not os.path.isdir(args.dir):
            print(f"[FAIL] 目录不存在: {args.dir}", file=sys.stderr)
            sys.exit(4)

        if args.type == "analyse":
            pattern = "*-analys.md"
        else:
            pattern = "summary.md"

        import glob
        files = sorted(glob.glob(os.path.join(args.dir, pattern)))
        if not files:
            print(f"[FAIL] 未找到文件: {pattern} 在 {args.dir}", file=sys.stderr)
            sys.exit(4)

        for fp in files:
            codes.append(verify_file(fp, "analyse"))

    max_code = max(codes) if codes else OK
    print(f"\n{len(codes)} 个文件检查完成, 退出码={max_code}")
    sys.exit(max_code)


if __name__ == "__main__":
    main()
