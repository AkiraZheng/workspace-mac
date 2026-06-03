#!/usr/bin/env python3
"""validate_phase1_artifacts.py — Phase 1.5→2 / Phase 2→3 硬性门禁

校验 merge_tasks.json 和 analysis_cache.json 存在且 schema 合法。
门禁不通过则禁止进入下一阶段。

用法:
  python3 validate_phase1_artifacts.py \
    --merge-tasks merge_tasks.json \
    --analysis-cache analysis_cache.json

退出码:
  0 = 全部通过
  1 = merge_tasks.json 不存在或无法读取
  2 = merge_tasks.json schema 不合法
  3 = analysis_cache.json 不存在或无法读取
  4 = analysis_cache.json schema 不合法
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# ── merge_tasks.json schema ──

REQUIRED_TASK_FIELDS = [
    "seq", "task_id", "status", "patch_file", "subject", "author",
    "files_changed", "功能分类", "introduced_symbols", "referenced_symbols",
    "action", "skip_reason", "pre_revert", "depends_on",
    "risk_level", "review_required", "blame_hits", "duplicate_info",
    "conflicts_predicted", "special_notes", "build_checkpoint",
    "pr_mapping", "execution_log",
]

REQUIRED_TOP_FIELDS = [
    "patchset_info", "global_revert_order", "deps_order", "merge_order",
]

REQUIRED_PR_MAPPING_FIELDS = ["upstream_deps", "bugfix_deps", "revert_candidates"]

VALID_STATUSES = {"pending", "in_progress", "done", "blocked", "skipped",
                   "failed", "built", "committed", "reviewed"}
VALID_ACTIONS = {"apply"}  # 只允许 apply（禁止 skip）
VALID_RISK = {"高", "中", "低"}
VALID_REVIEW = {"高", "中", "低"}

# ── analysis_cache.json schema ──

REQUIRED_ANALYSIS_FIELDS = [
    "summary", "modules", "risk", "risk_detail",
    "revert_level", "revert_commits", "revert_reason",
    "high_version_deps", "bugfix_deps", "internal_deps",
    "duplicate_info", "review_required", "review_reason",
    "smoke_tests", "changed_files", "status_in_target",
    "pr_mapping",
]


def _red(msg: str) -> str:
    return msg


def validate_merge_tasks(path: str) -> tuple[bool, str]:
    if not os.path.exists(path):
        return False, f"merge_tasks.json 不存在: {path}"

    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        return False, f"merge_tasks.json 无法读取: {e}"

    errors = []

    # 顶层字段
    for field in REQUIRED_TOP_FIELDS:
        if field not in data:
            errors.append(f"顶层缺少字段: {field}")
    if not isinstance(data.get("deps_order"), list):
        errors.append("deps_order 应为列表")
    if not isinstance(data.get("merge_order"), list):
        errors.append("merge_order 应为列表")

    # 每个 task 的必填字段
    all_tasks = data.get("deps_order", []) + data.get("merge_order", [])
    if not all_tasks:
        errors.append("merge_order 和 deps_order 均为空")

    for task in all_tasks:
        tid = task.get("task_id", "?")
        for field in REQUIRED_TASK_FIELDS:
            if field not in task:
                errors.append(f"task {tid} 缺少字段: {field}")

        if task.get("status") not in VALID_STATUSES:
            errors.append(f"task {tid} status 非法: {task.get('status')}")
        if task.get("action") not in VALID_ACTIONS:
            errors.append(f"task {tid} action 非法: {task.get('action')}")
        if task.get("risk_level") not in VALID_RISK:
            errors.append(f"task {tid} risk_level 非法: {task.get('risk_level')}")
        if task.get("review_required") not in VALID_REVIEW:
            errors.append(f"task {tid} review_required 非法: {task.get('review_required')}")

        pm = task.get("pr_mapping", {})
        for sf in REQUIRED_PR_MAPPING_FIELDS:
            if sf not in pm:
                errors.append(f"task {tid} pr_mapping 缺少: {sf}")
            elif not isinstance(pm[sf], list):
                errors.append(f"task {tid} pr_mapping.{sf} 应为列表")

    if errors:
        return False, "\n".join(errors[:20])
    return True, "merge_tasks.json 校验通过"


def validate_analysis_cache(path: str, merge_tasks_task_ids: set) -> tuple[bool, str]:
    if not os.path.exists(path):
        return False, f"analysis_cache.json 不存在: {path}"

    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        return False, f"analysis_cache.json 无法读取: {e}"

    if not isinstance(data, dict):
        return False, "analysis_cache.json 应为 JSON 对象"

    errors = []
    keys = set(data.keys())

    # 检查每个 merge_order 中的 task_id 在 analysis_cache 中有对应条目
    for tid in merge_tasks_task_ids:
        if tid not in data:
            errors.append(f"analysis_cache 缺少 task_id: {tid}")

    for tid, entry in data.items():
        if not isinstance(entry, dict):
            errors.append(f"analysis_cache {tid} 条目应为对象")
            continue

        for field in REQUIRED_ANALYSIS_FIELDS:
            if field not in entry:
                errors.append(f"analysis_cache {tid} 缺少字段: {field}")

        pm = entry.get("pr_mapping", {})
        for sf in REQUIRED_PR_MAPPING_FIELDS:
            if sf not in pm:
                errors.append(f"analysis_cache {tid} pr_mapping 缺少: {sf}")
            elif not isinstance(pm[sf], list):
                errors.append(f"analysis_cache {tid} pr_mapping.{sf} 应为列表")

    if errors:
        return False, "\n".join(errors[:20])
    return True, "analysis_cache.json 校验通过"


def get_task_ids_from_merge(merge_path: str) -> set[str]:
    try:
        with open(merge_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return set()
    ids = set()
    for section in ("merge_order", "deps_order"):
        for task in data.get(section, []):
            if "task_id" in task:
                ids.add(task["task_id"])
    return ids


def main():
    parser = argparse.ArgumentParser(
        description="Phase 1.5/2 门禁：校验 merge_tasks.json 和 analysis_cache.json"
    )
    parser.add_argument("--merge-tasks", required=True,
                        help="merge_tasks.json 路径")
    parser.add_argument("--analysis-cache", required=True,
                        help="analysis_cache.json 路径")
    args = parser.parse_args()

    print("=" * 50)
    print("  Phase 1.5 Artifacts 门禁校验")
    print("=" * 50)

    # 1. merge_tasks.json
    ok, msg = validate_merge_tasks(args.merge_tasks)
    if not ok:
        print(f"\n[FAIL] merge_tasks.json 校验失败")
        print(f"  {msg}")
        print("=" * 50)
        sys.exit(2)
    print(f"\n✅ {msg}")

    # 2. analysis_cache.json
    task_ids = get_task_ids_from_merge(args.merge_tasks)
    ok, msg = validate_analysis_cache(args.analysis_cache, task_ids)
    if not ok:
        print(f"\n[FAIL] analysis_cache.json 校验失败")
        print(f"  {msg}")
        print("=" * 50)
        sys.exit(4)
    print(f"✅ {msg}")

    print()
    print(f"  merge_tasks: {len(task_ids)} 个 task")
    print(f"  analysis_cache: {len(task_ids)} 个 entry")
    print("=" * 50)
    print("🎉 门禁通过，允许进入下一阶段")
    sys.exit(0)


if __name__ == "__main__":
    main()
