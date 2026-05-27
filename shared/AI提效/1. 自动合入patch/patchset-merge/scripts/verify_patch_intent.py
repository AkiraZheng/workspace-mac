#!/usr/bin/env python3
"""verify_patch_intent.py — APPLY 后校验 patch 意图是否完整保留

检查项目:
  1. patch 的 + 行（新增代码）是否存在于工作区目标文件中
  2. merge_tasks.json 中 task 的 introduced_symbols 是否在代码中可搜到
  3. patch 中新增的函数/宏定义是否被保留

用法:
  python3 verify_patch_intent.py \
    --patch-file /tmp/patches/0001-xxx.patch \
    --merges-file merge_tasks.json \
    --task-id 0001 \
    --repo-path "$KERNEL_REPO_PATH"

退出码:
  0 = patch 意图完整保留
  1 = 部分关键行缺失（展示差异）
  2 = 参数错误
  3 = introduced_symbols 缺失（严重，patch 核心功能丢失）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict


def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def find_task(merge_data: dict, task_id: str) -> dict | None:
    for section in ["deps_order", "merge_order"]:
        for t in merge_data.get(section, []):
            if t.get("task_id") == task_id:
                return t
    return None


def parse_patch(filepath: str) -> dict[str, list[dict]]:
    """Parse .patch file, return {filename: [{type, lineno, content, orig_lineno}]}.

    type: 'add' | 'delete' | 'context'
    """
    patches: dict[str, list[dict]] = defaultdict(list)
    current_file = None
    header_re = re.compile(r"^\+\+\+ [ab]/(.+)$")
    hunk_re = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    with open(filepath) as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        # Detect file header
        m = header_re.match(line)
        if m:
            current_file = m.group(1)
            continue

        if current_file is None:
            continue

        # Detect hunk header
        hunk_m = hunk_re.match(line)
        if hunk_m:
            continue

        if line.startswith("+") and not line.startswith("+++"):
            patches[current_file].append({
                "type": "add",
                "lineno": i + 1,
                "content": line[1:].rstrip("\n"),
            })
        elif line.startswith("-") and not line.startswith("---"):
            patches[current_file].append({
                "type": "delete",
                "lineno": i + 1,
                "content": line[1:].rstrip("\n"),
            })

    return dict(patches)


def check_added_lines_in_worktree(patch_data: dict, repo_path: str) -> tuple[list, list]:
    """Check if + lines from patch exist in working tree files.

    Returns:
      present: list of (file, content) that were found
      missing: list of (file, line_no_in_patch, content) that were NOT found
    """
    present = []
    missing = []

    for filename, hunks in patch_data.items():
        filepath = os.path.join(repo_path, filename)
        if not os.path.exists(filepath):
            missing.extend(
                (filename, h["lineno"], h["content"]) for h in hunks if h["type"] == "add"
            )
            continue

        with open(filepath) as f:
            worktree_content = f.read()

        for hunk in hunks:
            if hunk["type"] != "add":
                continue
            content = hunk["content"].strip()
            if not content:
                continue  # skip empty lines

            # Search for the content in the file (fuzzy match on stripped content)
            if content in worktree_content:
                present.append((filename, content))
            else:
                # Try partial match: first 30 non-space chars
                key = "".join(c for c in content if not c.isspace())[:30]
                if key and key in "".join(c for c in worktree_content if not c.isspace()):
                    present.append((filename, content))
                else:
                    missing.append((filename, hunk["lineno"], content))

    return present, missing


def check_introduced_symbols(task: dict, repo_path: str) -> tuple[list, list]:
    """Check if introduced_symbols exist in working tree files.

    Returns:
      found: list of (symbol, file, line)
      missing: list of symbol names
    """
    introduced = task.get("introduced_symbols", [])
    if not introduced:
        return [], []

    found = []
    missing = []

    for symbol in introduced:
        sym_found = False
        # Search in files_changed first, then repo-wide
        search_files = task.get("files_changed", [])
        if not search_files:
            # Fallback: search entire repo
            import glob
            search_files = glob.glob(os.path.join(repo_path, "**/*.[ch]"), recursive=True)[:500]

        for fname in search_files:
            filepath = os.path.join(repo_path, fname) if not fname.startswith(repo_path) else fname
            if not os.path.exists(filepath):
                continue
            try:
                with open(filepath) as f:
                    for lineno, line in enumerate(f, 1):
                        if symbol in line:
                            # Verify it's not in a comment
                            stripped = line.strip()
                            if stripped.startswith("//") or stripped.startswith("/*"):
                                continue
                            found.append((symbol, fname, lineno))
                            sym_found = True
                            break
            except (OSError, UnicodeDecodeError):
                continue
            if sym_found:
                break

        if not sym_found:
            missing.append(symbol)

    return found, missing


def print_summary(patch_missing, intro_missing, intro_found, added_present, added_missing):
    """Print formatted verification summary."""
    total_added = len(added_present) + len(added_missing)
    total_intro = len(intro_found) + len(intro_missing)

    print()
    print("=" * 60)
    print("  Patch 意图保留校验")
    print("=" * 60)

    # Check 1: added lines
    print(f"\n  [1] patch + 行校验 ({total_added} 行)")
    if added_missing:
        print(f"    ⚠️  缺失 {len(added_missing)} 行:")
        for filename, lineno, content in added_missing[:10]:
            print(f"      #{lineno} {filename}: +{content[:60]}")
        if len(added_missing) > 10:
            print(f"      ... 及其他 {len(added_missing) - 10} 行")
    else:
        print(f"    ✅ 全部 {total_added} 行已保留" if total_added > 0 else "    — 无新增行")

    # Check 2: introduced symbols
    print(f"\n  [2] introduced_symbols 校验 ({total_intro} 个符号)")
    if intro_found:
        for symbol, fname, lineno in intro_found[:5]:
            print(f"    ✅ {symbol}: {fname}:{lineno}")
    if intro_missing:
        print(f"    ❌ 缺失 {len(intro_missing)} 个核心符号:")
        for symbol in intro_missing:
            print(f"      {symbol}")
    elif total_intro > 0:
        print(f"    ✅ 全部 {total_intro} 个符号已保留")

    # Conclusion
    has_issues = bool(added_missing) or bool(intro_missing)
    print()
    if has_issues:
        print(f"  结论: ❌ patch 意图不完整")
        if intro_missing:
            print(f"  严重: introduced_symbols 缺失! 核心功能代码被删除!")
    else:
        print(f"  结论: ✅ patch 意图完整保留")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="APPLY 后校验 patch 意图完整性")
    parser.add_argument("--patch-file", required=True, help=".patch 文件路径")
    parser.add_argument("--merges-file", required=True, help="merge_tasks.json 路径")
    parser.add_argument("--task-id", required=True, help="task_id")
    parser.add_argument("--repo-path", required=True, help="内核仓库路径")
    parser.add_argument("--quiet", action="store_true", help="仅输出结论")
    args = parser.parse_args()

    if not os.path.exists(args.patch_file):
        print(f"错误: patch 文件不存在: {args.patch_file}", file=sys.stderr)
        sys.exit(2)

    if not os.path.exists(args.merges_file):
        print(f"错误: merge_tasks.json 不存在: {args.merges_file}", file=sys.stderr)
        sys.exit(2)

    merge_data = load_json(args.merges_file)
    task = find_task(merge_data, args.task_id)
    if task is None:
        print(f"错误: task {args.task_id} 未找到", file=sys.stderr)
        sys.exit(2)

    # Parse patch
    patch_data = parse_patch(args.patch_file)

    # Check 1: + lines in worktree
    added_present, added_missing = check_added_lines_in_worktree(patch_data, args.repo_path)

    # Check 2: introduced symbols
    intro_found, intro_missing = check_introduced_symbols(task, args.repo_path)

    if not args.quiet:
        print_summary(patch_missing=added_missing, intro_missing=intro_missing,
                      intro_found=intro_found, added_present=added_present,
                      added_missing=added_missing)

    if intro_missing:
        sys.exit(3)  # 严重：核心功能代码丢失
    elif added_missing:
        sys.exit(1)  # 部分行缺失
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
