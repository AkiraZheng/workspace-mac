#!/usr/bin/env python3
"""merge_order_sort.py — 全量排序，生成 Phase 2 执行序列

排序优先级：
  1. Revert 项（有 pre_revert 的任务）→ 最前面
  2. deps_order 按依赖插入到需要的 patch 之前
  3. 原始 patch → 保持稳定相对顺序（topo_sort.py 已保证）

用法:
  python3 merge_order_sort.py --merge-tasks merge_tasks.json --output merge_tasks.json

行为:
  - 将 deps_order 中的任务合并入 merge_order（按依赖关系插入）
  - merge_order 中 pre_revert 非空的任务排在前面
  - 原始 patch 相对顺序不变
  - deps_order 清空（全部已插入 merge_order）
  - 重新分配 seq 序号
"""

from __future__ import annotations

import copy
import json
import sys
import argparse


def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def save_json(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def insert_deps_into_merge(merge_order: list[dict],
                           deps_order: list[dict]) -> list[dict]:
    """Insert deps_order tasks into merge_order at dependency-required positions.

    For each dep:
      - Find all merge tasks whose `depends_on` includes this dep's task_id
      - Insert dep before the EARLIEST dependent merge task
      - If no dependent found, insert at the front
    """
    result = list(merge_order)
    inserted = set()

    for dep in deps_order:
        dep_id = dep.get("task_id", "")
        if dep_id in inserted:
            continue

        target_index = 0  # Default: insert at front if no dependent found
        for i, task in enumerate(result):
            if dep_id in task.get("depends_on", []):
                target_index = i
                break

        result.insert(target_index, copy.deepcopy(dep))
        inserted.add(dep_id)

    return result


def assign_seq(order: list[dict]) -> list[dict]:
    """Re-assign seq numbers starting from 1."""
    for i, task in enumerate(order):
        task["seq"] = i + 1
    return order


def sort_merge_order(merge_data: dict) -> dict:
    deps_order = merge_data.get("deps_order", [])
    merge_order = merge_data.get("merge_order", [])

    if not deps_order and not any(t.get("pre_revert") for t in merge_order):
        return merge_data

    # Step 1: Split into groups (revert tasks go first)
    revert_tasks = [t for t in merge_order if t.get("pre_revert")]
    apply_tasks = [t for t in merge_order if not t.get("pre_revert")]

    # Step 2: Collect deps needed by revert tasks (they go in revert group)
    revert_dep_ids = set()
    for t in revert_tasks:
        for d in t.get("depends_on", []):
            if d.startswith("dep-"):
                revert_dep_ids.add(d)

    revert_deps = [d for d in deps_order if d.get("task_id") in revert_dep_ids]
    apply_deps = [d for d in deps_order if d.get("task_id") not in revert_dep_ids]

    # Step 3: Insert deps into each group
    sorted_revert = insert_deps_into_merge(revert_tasks, revert_deps)
    sorted_apply = insert_deps_into_merge(apply_tasks, apply_deps)

    # Step 4: Combine: reverts group first, then apply group
    combined = sorted_revert + sorted_apply
    assign_seq(combined)

    result = dict(merge_data)
    result["merge_order"] = combined
    result["deps_order"] = []

    return result


def build_report(original_merge: list, sorted_merge: list,
                 deps_count: int) -> str:
    """Generate a human-readable summary of the sorting result."""
    lines = ["合并排序完成："]

    revert_tasks = [t for t in sorted_merge if t.get("pre_revert")]
    dep_tasks = [t for t in sorted_merge if t.get("task_id", "").startswith("dep-")]
    apply_tasks = [t for t in sorted_merge
                   if not t.get("pre_revert")
                   and not t.get("task_id", "").startswith("dep-")]

    if deps_count > 0:
        lines.append(f"  ✓ {deps_count} 个 deps 已插入 merge_order, deps_order 已清空")

    if revert_tasks:
        names = [t.get("task_id") for t in revert_tasks]
        deps = [t.get("task_id") for t in revert_tasks
                if t.get("task_id", "").startswith("dep-")]
        lines.append(f"  ✓ {len(revert_tasks)} 个 revert 组排在最前面: "
                     f"{', '.join(names)}")
        if deps:
            lines.append(f"    含 {len(deps)} 个 revert 依赖: {', '.join(deps)}")

    lines.append(f"  总计: {len(sorted_merge)} 个任务 (revert组={len(revert_tasks)}"
                 f" dep={len(dep_tasks)} apply={len(apply_tasks)})")

    lines.append("")
    lines.append(f"{'Seq':<5} {'Task':<10} {'Action':<8} {'Subject'}")
    lines.append("-" * 60)
    for t in sorted_merge:
        seq = t.get("seq", "?")
        tid = t.get("task_id", "?")
        is_revert = bool(t.get("pre_revert"))
        is_dep = tid.startswith("dep-")
        if is_revert:
            action = "revert"
        elif is_dep:
            action = "dep"
        else:
            action = t.get("action", "apply")
        subject = t.get("subject", "")[:40]
        lines.append(f"{seq:<5} {tid:<10} {action:<8} {subject}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="merge_order 全量排序")
    parser.add_argument("--merge-tasks", required=True, help="merge_tasks.json 路径")
    parser.add_argument("--output", required=True, help="输出路径")
    parser.add_argument("--dry-run", action="store_true", help="只输出报告，不写文件")
    args = parser.parse_args()

    data = load_json(args.merge_tasks)

    deps_count = len(data.get("deps_order", []))
    original_merge = data.get("merge_order", [])

    sorted_data = sort_merge_order(data)

    report = build_report(original_merge, sorted_data["merge_order"], deps_count)
    print(report, file=sys.stderr)

    if not args.dry_run:
        save_json(args.output, sorted_data)
        print(f"\n[SORT] 已写入 {args.output}", file=sys.stderr)
    else:
        print("\n[SORT] dry-run 模式，未写入", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
