#!/usr/bin/env python3
"""execute_revert.py — 执行 revert_plan.json（预执行 + 正式执行 + 失败处理）

流程:
  1. 检查 revert_plan.json 是否存在
  2. 创建回滚 checkpoint
  3. 逐 item 执行：
     a. 预执行（git revert --no-commit）
     b. 无冲突 → 正式执行（git commit）
     c. 有冲突 → 失败处理（降级/暂停/回退）
  4. 全部完成 → 清理 checkpoint

用法:
  python3 execute_revert.py \
    --plan revert_plan.json \
    --repo-path "$KERNEL_REPO_PATH"

退出码:
  0 = 全部成功
  1 = 部分失败，需要用户决策
  2 = revert_plan.json 不存在
  3 = 用户选择回退
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

CHECKPOINT_REF = "BACKUP_PRE_REVERT"


def run_git(repo_path: str, *args, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo_path] + list(args),
        capture_output=True, text=True,
    )


def create_checkpoint(repo_path: str) -> None:
    run_git(repo_path, "branch", "-f", CHECKPOINT_REF, "HEAD")
    print(f"[CHECKPOINT] 回滚点: {CHECKPOINT_REF}")


def cleanup_checkpoint(repo_path: str) -> None:
    run_git(repo_path, "branch", "-D", CHECKPOINT_REF)
    print(f"[CHECKPOINT] 已清理: {CHECKPOINT_REF}")


def execute_revert(repo_path: str, commit: str) -> bool:
    """预执行 + 正式执行 revert，返回是否成功"""
    result = run_git(repo_path, "revert", "--no-commit", commit)

    if result.returncode != 0:
        print(f"  [DRY-RUN FAIL] 预执行冲突: {commit[:12]}")
        print(f"  stderr: {result.stderr.strip()[:200]}")
        run_git(repo_path, "revert", "--abort")
        return False

    result = run_git(repo_path, "commit", "-m",
                     f"Revert {commit} (auto revert by merge-patchset)",
                     "--no-edit")

    if result.returncode != 0:
        print(f"  [COMMIT FAIL] git commit 失败: {commit[:12]}")
        print(f"  stderr: {result.stderr.strip()[:200]}")
        return False

    print(f"  [PASS] revert {commit[:12]}")
    return True


def rollback(repo_path: str) -> None:
    print(f"[ROLLBACK] 回退到 {CHECKPOINT_REF}")
    run_git(repo_path, "reset", "--hard", CHECKPOINT_REF)
    cleanup_checkpoint(repo_path)


def handle_failure(repo_path: str, item: dict, failed_commit: str,
                   completed: list[str], plan_path: str) -> str:
    """失败处理：返回用户选择的动作"""
    print()
    print("=" * 60)
    print(f"  ❌ REVERT 失败")
    print(f"  失败 commit: {failed_commit[:12]}")
    print(f"  已完成:      {[c[:12] for c in completed]}")
    print("=" * 60)
    print()
    print("  请选择处理方式:")
    print("  [1] 跳过此项，继续下一个 item")
    print("  [2] 回退全部已执行的 reverts")
    print("  [3] 中止，保存当前状态")
    print("  [4] 手动修复冲突后继续")
    print()

    while True:
        try:
            choice = input("  选择 [1-4]: ").strip()
            if choice == "1":
                run_git(repo_path, "checkout", "--", ".")
                return "skip"
            elif choice == "2":
                rollback(repo_path)
                return "rollback"
            elif choice == "3":
                print(f"[ABORT] 状态已保存，退出")
                return "abort"
            elif choice == "4":
                print("[MANUAL] 请手动修复冲突后执行 git commit")
                print("         完成后输入 'done'")
                while input("  > ").strip().lower() != "done":
                    pass
                return "continue"
        except (KeyboardInterrupt, EOFError):
            return "abort"


def execute_plan(plan_path: str, repo_path: str) -> int:
    if not os.path.exists(plan_path):
        print(f"错误: {plan_path} 不存在", file=sys.stderr)
        return 2

    with open(plan_path) as f:
        plan = json.load(f)

    items = plan.get("revert_items", [])
    if not items:
        print("revert_plan 为空，跳过 PRE_REVERT")
        return 0

    print("=" * 60)
    print(f"  PRE_REVERT: {len(items)} 项")
    print("=" * 60)

    create_checkpoint(repo_path)

    for item in items:
        seq = item["seq"]
        strategy = item.get("strategy", "no_revert")
        revert_targets = item.get("revert_targets", [])
        revert_order = item.get("revert_order", revert_targets)

        print(
            f"\n[{seq}] {item['pr_id']}: "
            f"{item.get('strategy_label', strategy)}"
        )

        if not revert_targets:
            print("  [SKIP] 无 revert 目标")
            continue

        completed = []
        failed = []

        for commit in revert_order:
            if execute_revert(repo_path, commit):
                completed.append(commit)
            else:
                failed.append(commit)

                # 自动降级：整个 PR 失败 → 逐个 revert
                if strategy == "revert_whole_pr" and len(failed) == 1:
                    print("  [DEGRADE] 整体 revert 失败，降级为逐个 revert")
                    remaining = [c for c in revert_order
                                 if c not in completed and c != commit]
                    for rc in remaining:
                        if execute_revert(repo_path, rc):
                            completed.append(rc)
                        else:
                            failed.append(rc)

                if failed:
                    action = handle_failure(
                        repo_path, item, commit, completed, plan_path
                    )
                    if action == "skip":
                        break
                    elif action == "rollback":
                        return 3
                    elif action == "abort":
                        return 1
                    elif action == "continue":
                        completed.append(commit)
                        continue

        if failed:
            print(f"\n  ⚠️  {item['pr_id']}: {len(completed)}/{len(revert_order)} 成功")
        else:
            print(f"\n  ✅ {item['pr_id']}: 全部成功")

    cleanup_checkpoint(repo_path)
    print("\n[DONE] PRE_REVERT 完成")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="执行 revert_plan.json"
    )
    parser.add_argument("--plan", required=True,
                        help="revert_plan.json 路径")
    parser.add_argument("--repo-path", required=True,
                        help="目标内核仓库路径")
    args = parser.parse_args()

    if not os.path.isdir(args.repo_path):
        print(f"错误: {args.repo_path} 不是有效目录", file=sys.stderr)
        sys.exit(1)

    rc = execute_plan(args.plan, args.repo_path)
    sys.exit(rc)


if __name__ == "__main__":
    main()
