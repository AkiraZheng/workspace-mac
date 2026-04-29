#!/usr/bin/env python3
"""CLI entry point for merge-patchset command"""
import sys
from pathlib import Path
from .skill import execute_patchset_merge

def main():
    if len(sys.argv) < 2:
        print("用法: merge-patchset <patch_url> [--source <源码目录>] [--branch <分支名>]")
        print("")
        print("参数:")
        print("  patch_url    lore.kernel.org 上的 patch URL")
        print("  --source     源码目录 (默认: 当前目录)")
        print("  --branch     分支名 (不指定则自动根据 patch 主题生成)")
        print("")
        print("示例:")
        print("  merge-patchset https://lore.kernel.org/lkml/xxx/")
        print("  merge-patchset https://lore.kernel.org/lkml/xxx/ --source /path/to/linux --branch my-branch")
        sys.exit(1)

    patch_url = sys.argv[1]
    source_dir = Path(".")
    branch_name = None  # None 表示由函数自动生成

    # 解析参数
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--source" and i + 1 < len(args):
            source_dir = Path(args[i + 1])
            i += 2
        elif args[i] == "--branch" and i + 1 < len(args):
            branch_name = args[i + 1]
            i += 2
        else:
            i += 1

    try:
        result = execute_patchset_merge(patch_url, source_dir, branch_name)
        print(f"✓ Merge 完成! 差异报告: {result.diff_report_path}")
    except Exception as e:
        print(f"✗ 错误: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
