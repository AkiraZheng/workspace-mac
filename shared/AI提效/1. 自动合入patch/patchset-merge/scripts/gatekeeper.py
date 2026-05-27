#!/usr/bin/env python3
"""gatekeeper.py — merge 流程状态机门禁

用法:
  # BUILD 开始时标记 in_progress
  python3 gatekeeper.py --merges-file <path> --task-id 0001 \\
    --step BUILD --result in_progress

  # BUILD 完成后更新状态
  python3 gatekeeper.py --merges-file <path> --task-id 0001 \\
    --step BUILD --result pass --error-count 0 --product arch/arm64/boot/Image

  # COMMIT 前门禁检查
  python3 gatekeeper.py --merges-file <path> --task-id 0001 \\
    --step COMMIT --check

  # COMMIT 完成后更新状态
  python3 gatekeeper.py --merges-file <path> --task-id 0001 \\
    --step COMMIT --result pass --commit abc123

  # 恢复模式：读取 current_state 判断是否需要恢复
  python3 gatekeeper.py --merges-file <path> --restore

  # 清除恢复标记（恢复完成后）
  python3 gatekeeper.py --merges-file <path> --restore --clear

状态约束:
  COMMIT 前必须有 BUILD pass 记录
  REVIEW 前必须有 COMMIT pass 记录

退出码:
  0 = 通过 / 更新成功
  1 = merge_tasks.json 不存在或 task 未找到
  2 = 前置步骤未完成
  3 = JSON 写入失败
  10 = current_state 有未完成工作（--restore 时返回）
"""

from __future__ import annotations

import json
import os
import sys
import argparse
from datetime import datetime, timezone


STEP_ORDER = ["BUILD", "COMMIT", "REVIEW", "DONE"]
STEP_PRE_REQUISITES = {
    "COMMIT": ["BUILD"],
    "REVIEW": ["COMMIT"],
    "DONE": ["BUILD", "COMMIT"],
    "BUILD": [],
}

WORKFLOW_HINTS = {
    "BUILD_FIX": (
        "只修改 patch 相关文件；config 问题临时修改后 git restore；"
        "错误超过 10 个时暂停等待用户决策"
    ),
    "COMMIT_ORDER": "必须按 merge_order 顺序，每个 patch 一个 commit",
    "REVERT_POLICY": "逆序 revert（最新→最旧），每 revert 一个就 commit 一个",
    "BUILD_REQUIREMENT": "编译整个仓库 $BUILD_CMD -j$(nproc)，error=0 + 产物存在",
}


def load_merges_file(path: str) -> dict:
    if not os.path.exists(path):
        print(f"[GATEKEEPER] merge_tasks.json 不存在: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"[GATEKEEPER] 读取失败: {e}", file=sys.stderr)
        sys.exit(1)


def save_merges_file(path: str, data: dict) -> None:
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        print(f"[GATEKEEPER] 写入失败: {e}", file=sys.stderr)
        sys.exit(3)


def find_task(data: dict, task_id: str) -> dict | None:
    for section in ["deps_order", "merge_order"]:
        for task in data.get(section, []):
            if task.get("task_id") == task_id:
                return task
    return None


def ensure_state_log(task: dict) -> list[dict]:
    if "state_log" not in task:
        task["state_log"] = []
    return task["state_log"]


def has_step_passed(state_log: list[dict], step: str) -> bool:
    for entry in state_log:
        if entry.get("step") == step and entry.get("result") == "pass":
            return True
    return False


def check_prerequisites(state_log: list[dict], step: str) -> bool:
    required = STEP_PRE_REQUISITES.get(step, [])
    missing = [s for s in required if not has_step_passed(state_log, s)]
    if missing:
        print(f"[GATEKEEPER] 门禁未通过: 缺少前置步骤 {', '.join(missing)} 的 pass 记录",
              file=sys.stderr)
        print(f"  请先执行 {', '.join(missing)} 步骤并通过验证", file=sys.stderr)
        return False
    return True


def record_step(state_log: list[dict], step: str, result: str,
                extra: dict | None = None) -> None:
    entry = {
        "step": step,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "result": result,
    }
    if extra:
        entry.update(extra)
    state_log.append(entry)


def update_current_state(data: dict, task_id: str, phase: str,
                         step: str, status: str) -> None:
    """更新顶层 current_state 字段（用于恢复）"""
    if "current_state" not in data:
        data["current_state"] = {}
    data["current_state"] = {
        "phase": phase,
        "task_id": task_id,
        "step": step,
        "status": status,
        "last_update": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def ensure_workflow_hints(data: dict) -> None:
    """确保 data 包含 workflow_hints（若缺失则写入默认值）"""
    if "workflow_hints" not in data:
        data["workflow_hints"] = dict(WORKFLOW_HINTS)


def do_check(args):
    if not args.task_id:
        print("[GATEKEEPER] --check 需要 --task-id", file=sys.stderr)
        sys.exit(1)
    data = load_merges_file(args.merges_file)
    task = find_task(data, args.task_id)
    if task is None:
        print(f"[GATEKEEPER] task {args.task_id} 未找到", file=sys.stderr)
        sys.exit(1)

    state_log = ensure_state_log(task)

    if check_prerequisites(state_log, args.step):
        # 检查当前 step 是否也已经 pass（幂等）
        if has_step_passed(state_log, args.step):
            print(f"[GATEKEEPER] ✅ {args.step} 已通过，可继续")
        else:
            print(f"[GATEKEEPER] ✅ 前置步骤已通过，可以执行 {args.step}")
        sys.exit(0)
    else:
        sys.exit(2)


def do_record(args):
    if not args.task_id:
        print("[GATEKEEPER] --result 需要 --task-id", file=sys.stderr)
        sys.exit(1)
    data = load_merges_file(args.merges_file)
    ensure_workflow_hints(data)
    task = find_task(data, args.task_id)
    if task is None:
        print(f"[GATEKEEPER] task {args.task_id} 未找到", file=sys.stderr)
        sys.exit(1)

    state_log = ensure_state_log(task)
    extra = {}
    if args.error_count is not None:
        extra["error_count"] = args.error_count
    if args.product:
        extra["product"] = args.product
    if args.commit:
        extra["commit"] = args.commit
    if args.build_target:
        extra["build_target"] = args.build_target
    if args.module_dirs:
        extra["module_dirs"] = args.module_dirs.split(",")
    if args.module_count is not None:
        extra["module_count"] = args.module_count

    record_step(state_log, args.step, args.result, extra or None)

    # 更新 task status
    status_map = {
        "BUILD": "built",
        "COMMIT": "committed",
        "REVIEW": "reviewed",
        "DONE": "done",
    }
    if args.result == "pass":
        task["status"] = status_map.get(args.step, args.result)
    elif args.result == "in_progress":
        task["status"] = "in_progress"

    # 更新全局 current_state（用于跨 session 恢复）
    phase_name = "PHASE_2_MERGE"
    update_current_state(data, args.task_id, phase_name, args.step, args.result)

    save_merges_file(args.merges_file, data)
    result_label = "in_progress" if args.result == "in_progress" else args.result
    print(f"[GATEKEEPER] ✅ {args.step} 已记录 (result={result_label})")
    sys.exit(0)


def do_restore(args):
    data = load_merges_file(args.merges_file)
    ensure_workflow_hints(data)

    current = data.get("current_state")
    if not current:
        print("[GATEKEEPER] 无历史状态，不需要恢复", file=sys.stderr)
        sys.exit(0)

    status = current.get("status", "")

    if args.clear:
        data["current_state"] = None
        save_merges_file(args.merges_file, data)
        print("[GATEKEEPER] ✅ 恢复标记已清除")
        sys.exit(0)

    if status in ("pass", "done"):
        data["current_state"] = None
        save_merges_file(args.merges_file, data)
        print("[GATEKEEPER] 上次任务已完成，无需恢复")
        sys.exit(0)

    task_id = current.get("task_id", "?")
    step = current.get("step", "?")
    phase = current.get("phase", "?")
    last_update = current.get("last_update", "?")

    print(f"[GATEKEEPER] ⚠️  发现未完成工作:")
    print(f"  phase: {phase}")
    print(f"  task : {task_id}")
    print(f"  step : {step}")
    print(f"  state: {status}")
    print(f"  time : {last_update}")
    print("")
    print("[GATEKEEPER] 请调用 gatekeeper.py --restore --clear 确认并清除恢复标记")

    workflow = data.get("workflow_hints", {})
    if workflow:
        print("")
        print("[GATEKEEPER] 以下是关键流程提示（workflow_hints）：")
        for key, val in workflow.items():
            print(f"  {key}: {val}")

    sys.exit(10)


def main():
    parser = argparse.ArgumentParser(description="merge 流程状态机门禁")
    parser.add_argument("--merges-file", required=True,
                        help="merge_tasks.json 路径")
    parser.add_argument("--task-id",
                        help="task_id，如 0001")
    parser.add_argument("--step",
                        choices=["BUILD", "COMMIT", "REVIEW", "DONE"],
                        help="步骤名称")
    parser.add_argument("--check", action="store_true",
                        help="门禁检查模式（检查前置步骤是否通过）")
    parser.add_argument("--result", choices=["pass", "fail", "in_progress"],
                        help="步骤结果（记录模式）")
    parser.add_argument("--error-count", type=int,
                        help="编译 error 数")
    parser.add_argument("--product",
                        help="编译产物路径")
    parser.add_argument("--commit",
                        help="commit hash")
    parser.add_argument("--build-target",
                        help="编译目标（如 Image / Image modules）")
    parser.add_argument("--module-dirs",
                        help="验证的模块目录（逗号分隔）")
    parser.add_argument("--module-count", type=int,
                        help=".ko 文件数量")
    parser.add_argument("--restore", action="store_true",
                        help="恢复模式：检查 current_state 是否有未完成工作")
    parser.add_argument("--clear", action="store_true",
                        help="清除 current_state 恢复标记（与 --restore 配合）")

    args = parser.parse_args()

    if args.restore:
        do_restore(args)
    elif args.clear:
        # 仅清除模式（不需要 --restore）
        data = load_merges_file(args.merges_file)
        data["current_state"] = None
        save_merges_file(args.merges_file, data)
        print("[GATEKEEPER] ✅ current_state 已清除")
        sys.exit(0)
    elif args.check:
        do_check(args)
    elif args.result:
        do_record(args)
    else:
        print("[GATEKEEPER] 需要 --check、--result 或 --restore", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
