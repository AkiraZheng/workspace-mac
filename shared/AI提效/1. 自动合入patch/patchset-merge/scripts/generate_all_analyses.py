#!/usr/bin/env python3
"""generate_all_analyses.py — 批量生成所有 patch 的 analyse.md

从 merge_tasks.json 读取所有 task，对每个 task 调用 generate_analyse_md.py
的核心逻辑，确定性生成所有 analyse.md 文件。

用法:
  python3 generate_all_analyses.py \
    --analysis-cache analysis_cache.json \
    --merge-tasks merge_tasks.json \
    --diff-script scripts/generate_diff_report.py \
    --repo-path "$KERNEL_REPO_PATH" \
    --output-dir "$KERNEL_REPO_PATH/patch_analysis/"

退出码:
  0 = 全部成功
  1 = 部分失败（输出中列出跳过和失败的 task）
  2 = 参数错误或文件缺失
"""

from __future__ import annotations

import argparse
import json
import os
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

import generate_analyse_md as gen


def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def slugify_subject(subject: str, max_len: int = 40) -> str:
    """Create a short filename-safe slug from patch subject."""
    s = subject.strip()
    s = s.replace("/", "-").replace(":", "-").replace(" ", "-")
    s = "".join(c for c in s if c.isalnum() or c in "._-")
    s = s.strip("_-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("_-")
    return s if s else "patch"


def generate_all(analysis_cache_path: str, merge_tasks_path: str,
                 diff_script: str, repo_path: str, output_dir: str,
                 patch_dir: str = "/tmp/patches") -> tuple[list, list, list]:
    """Generate all analyse.md files.

    Returns:
      success: list of (task_id, output_file)
      skipped: list of (task_id, reason)
      failed:  list of (task_id, error_message)
    """
    analysis_cache = load_json(analysis_cache_path)
    merge_data = load_json(merge_tasks_path)

    all_tasks = []
    for section in ["deps_order", "merge_order"]:
        for t in merge_data.get(section, []):
            all_tasks.append(t)

    if not all_tasks:
        print("错误: merge_tasks.json 中没有找到任何 task", file=sys.stderr)
        sys.exit(2)

    os.makedirs(output_dir, exist_ok=True)

    success = []
    skipped = []
    failed = []

    for task in all_tasks:
        task_id = task.get("task_id", "unknown")
        subject = task.get("subject", task_id)
        slug = slugify_subject(subject)
        output_file = os.path.join(output_dir, f"{task_id}-{slug}-analys.md")

        # Skip tasks that have no content
        if task.get("action") == "skip" and not task.get("execution_log"):
            skipped.append((task_id, "skip 且无合入记录，跳过"))
            continue

        try:
            # Use core generate function directly
            content = gen.generate_analyse_md(
                analysis_cache, merge_data, task_id,
                merge_tasks_path, diff_script, repo_path, patch_dir,
                commit_hash=task.get("commit", "HEAD"),
                mode=task.get("mode", "merge"),
            )

            with open(output_file, "w") as f:
                f.write(content)

            placeholder_count = content.count("{REQUIRES_AI_")
            print(f"[GEN] {task_id} → {os.path.basename(output_file)} "
                  f"({placeholder_count} 个 AI 待填字段)")
            success.append((task_id, output_file))

        except SystemExit as e:
            if e.code == 2:
                failed.append((task_id, "task 数据不完整"))
            else:
                failed.append((task_id, str(e)))
        except Exception as e:
            failed.append((task_id, str(e)))

    return success, skipped, failed


def print_summary(success, skipped, failed, output_dir):
    """Print batch generation summary."""
    total = len(success) + len(skipped) + len(failed)

    print()
    print("=" * 60)
    print("  批量生成 analyse.md 完成")
    print("=" * 60)
    print(f"  总计: {total} 个 task")
    print(f"  ✅ 成功: {len(success)}")
    print(f"  ⏭️  跳过: {len(skipped)}")
    print(f"  ❌ 失败: {len(failed)}")

    if failed:
        print()
        print("  失败详情:")
        for task_id, err in failed:
            print(f"    {task_id}: {err}")

    if skipped:
        print()
        print("  跳过的 task:")
        for task_id, reason in skipped:
            print(f"    {task_id}: {reason}")

    print()
    print(f"  输出目录: {output_dir}")
    print()
    print("  ⚠️  请执行验证:")
    print(f"    python3 verify_analyse_format.py "
          f"--dir '{output_dir}' "
          f"--expected-from '{merge_tasks}'")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="批量生成所有 analyse.md")
    parser.add_argument("--analysis-cache", required=True,
                        help="analysis_cache.json 路径")
    parser.add_argument("--merge-tasks", required=True,
                        help="merge_tasks.json 路径")
    parser.add_argument("--diff-script", required=True,
                        help="generate_diff_report.py 路径")
    parser.add_argument("--repo-path", required=True,
                        help="内核仓库路径")
    parser.add_argument("--output-dir", required=True,
                        help="输出目录（如 $KERNEL_REPO_PATH/patch_analysis/）")
    parser.add_argument("--patch-dir", default="/tmp/patches",
                        help="patch 文件目录")
    args = parser.parse_args()

    if not os.path.exists(args.merge_tasks):
        print(f"错误: merge_tasks.json 不存在: {args.merge_tasks}", file=sys.stderr)
        sys.exit(2)

    if not os.path.exists(args.analysis_cache):
        print(f"错误: analysis_cache.json 不存在: {args.analysis_cache}", file=sys.stderr)
        sys.exit(2)

    success, skipped, failed = generate_all(
        args.analysis_cache, args.merge_tasks,
        args.diff_script, args.repo_path, args.output_dir,
        args.patch_dir,
    )

    print_summary(success, skipped, failed, args.output_dir)

    if failed:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
