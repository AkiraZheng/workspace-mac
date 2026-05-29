#!/usr/bin/env python3
"""generate_revert_plan.py — 从 duplicate_analysis.json 生成 revert_plan.json + revert_plan.sh

用法:
  python3 generate_revert_plan.py \
    --duplicate-analysis duplicate_analysis.json \
    --repo-path "$KERNEL_REPO_PATH" \
    --output-dir "$KERNEL_REPO_PATH/patch_analysis/"

退出码: 0=成功, 1=参数错误
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone


def _get_commit_timestamp(repo_path: str, commit_hash: str) -> int:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "log", "--format=%at", "-1", commit_hash],
            capture_output=True, text=True, timeout=5,
        )
        return int(result.stdout.strip()) if result.stdout.strip() else 0
    except (subprocess.TimeoutExpired, ValueError):
        return 0


STRATEGY_LABELS = {
    "revert_whole_pr": "revert 整个 PR",
    "revert_matched": "revert 匹配的 commits（逐个逆序）",
    "direct_revert": "直接 revert 单 commit",
    "no_revert": "不 revert",
}


def generate_revert_plan(dup_analysis: dict, repo_path: str) -> dict:
    revert_order = dup_analysis.get("global_revert_order", [])
    items = []

    for i, entry in enumerate(revert_order):
        commits_info = entry.get("commits", {})
        strategy = entry.get("revert_strategy", "no_revert")
        revert_targets = entry.get("revert_targets", [])
        revert_cmds = entry.get("revert_cmd", [])
        revert_order_list = entry.get("revert_order", revert_targets)

        item_type = "single_commit"
        if entry.get("pr_id", "").startswith("PR #"):
            if strategy == "revert_whole_pr":
                item_type = "pr_whole"
            elif strategy == "revert_matched":
                item_type = "pr_partial"

        items.append({
            "seq": i + 1,
            "type": item_type,
            "pr_id": entry.get("pr_id", ""),
            "pr_info": entry.get("pr_info"),
            "commits": commits_info,
            "commit_count": entry.get("commit_count", 0),
            "matched_count": entry.get("high_match_count", 0),
            "coverage_rate": entry.get("coverage_rate", 0),
            "strategy": strategy,
            "strategy_label": STRATEGY_LABELS.get(strategy, strategy),
            "revert_targets": revert_targets,
            "revert_order": revert_order_list,
            "revert_cmds": revert_cmds,
            "urgency": entry.get("urgency", "无须"),
            "risk_assessment": entry.get("risk_assessment", {}),
            "related_patches": entry.get("related_patches", []),
        })

    # 按 commit 时间重新排序（最新→最旧，避免子 commit 依赖父 commit 的冲突）
    def _item_max_time(item):
        max_ts = 0
        for c in item.get("revert_order", item.get("revert_targets", [])):
            ts = _get_commit_timestamp(repo_path, c)
            if ts:
                max_ts = max(max_ts, ts)
        return max_ts

    items.sort(key=_item_max_time, reverse=True)
    for i, item in enumerate(items):
        item["seq"] = i + 1

    return {
        "generated_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "target_repo": repo_path,
        "revert_items": items,
    }


def generate_revert_sh(revert_plan: dict) -> str:
    lines = [
        "#!/bin/bash",
        "# revert_plan.sh — 自动生成的 revert 执行脚本",
        f"# 生成时间: {revert_plan['generated_at']}",
        "# 用法: bash revert_plan.sh <repo_path>",
        "#",
        "set -euo pipefail",
        'REPO="${1:?需要指定仓库路径}"',
        'BACKUP_REF="BACKUP_PRE_REVERT"',
        "",
        'cd "$REPO" || exit 1',
        "",
        "# 创建回滚点",
        'git branch -f "$BACKUP_REF" HEAD',
        'echo "[CHECKPOINT] 回滚点已创建: $BACKUP_REF"',
        'echo ""',
        "",
    ]

    total = len(revert_plan["revert_items"])
    for i, item in enumerate(revert_plan["revert_items"]):
        lines.append(
            f"# [{i + 1}/{total}] {item['strategy_label']} "
            f"({item['pr_id']}, urgency={item['urgency']})"
        )

        for cmd in item["revert_cmds"]:
            lines.append(f"echo \"[EXEC] {cmd}\"")
            lines.append(f"if {cmd}; then")
            lines.append(f'    echo "  PASS"')
            lines.append(f"else")
            lines.append(f'    echo "  FAIL: revert 失败"')
            lines.append(
                f'    echo "  手动修复: git checkout -- . && git revert --continue"'
            )
            lines.append(
                f'    echo "  或回退:   git reset --hard $BACKUP_REF"'
            )
            lines.append(f"    exit 1")
            lines.append(f"fi")
            lines.append("")

    lines.append('echo ""')
    lines.append('echo "[DONE] 全部 revert 完成"')
    lines.append('echo "如需回退: git reset --hard $BACKUP_REF"')

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="从 duplicate_analysis.json 生成 revert_plan"
    )
    parser.add_argument("--duplicate-analysis", required=True,
                        help="duplicate_analysis.json 路径")
    parser.add_argument("--repo-path", required=True,
                        help="目标内核仓库路径")
    parser.add_argument("--output-dir", required=True,
                        help="输出目录")
    args = parser.parse_args()

    if not os.path.exists(args.duplicate_analysis):
        print(f"错误: {args.duplicate_analysis} 不存在", file=sys.stderr)
        sys.exit(1)

    with open(args.duplicate_analysis) as f:
        dup_analysis = json.load(f)

    plan = generate_revert_plan(dup_analysis, args.repo_path)

    os.makedirs(args.output_dir, exist_ok=True)

    plan_path = os.path.join(args.output_dir, "revert_plan.json")
    with open(plan_path, "w") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
        f.write("\n")

    sh_path = os.path.join(args.output_dir, "revert_plan.sh")
    sh_content = generate_revert_sh(plan)
    with open(sh_path, "w") as f:
        f.write(sh_content)
    os.chmod(sh_path, 0o755)

    print(f"已生成: {plan_path}")
    print(f"已生成: {sh_path}")
    print(f"共 {len(plan['revert_items'])} 项 revert")

    for item in plan["revert_items"]:
        print(
            f"  [{item['seq']}] {item['pr_id']}: "
            f"{item['strategy_label']} ({item['urgency']})"
        )
        for cmd in item["revert_cmds"]:
            print(f"      {cmd}")

    sys.exit(0)


if __name__ == "__main__":
    main()
