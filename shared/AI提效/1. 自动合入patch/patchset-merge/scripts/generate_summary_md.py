#!/usr/bin/env python3
"""generate_summary_md.py — 确定性生成 summary.md

从 analyse.md 文件和 merge_tasks.json 生成汇总报告。

用法:
  python3 generate_summary_md.py \
    --analyse-dir patch_analysis/ \
    --merge-tasks merge_tasks.json \
    --output patch_analysis/summary.md

退出码: 0=成功, 1=参数错误
"""

from __future__ import annotations

import json
import os
import re
import sys
import argparse
from collections import defaultdict
from datetime import datetime, timezone


def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def parse_patch_id(filename: str) -> str:
    m = re.match(r"(\d{4}|dep-\d+)", os.path.basename(filename))
    return m.group(1) if m else filename


def parse_section(content: str, section_name: str) -> str:
    """Extract section content by header."""
    pattern = rf"##\s+{re.escape(section_name)}"
    m = re.search(pattern, content)
    if not m:
        return ""
    start = m.end()
    next_s = re.search(r"^##\s+", content[start:], re.MULTILINE)
    if next_s:
        return content[start:start + next_s.start()].strip()
    return content[start:].strip()


def build_status_table(tasks, analyse_files):
    """Build 合入顺序与状态 table."""
    rows = []
    for t in tasks:
        tid = t.get("task_id", "?")
        status_map = {
            "done": "合入成功", "skipped": "已跳过", "failed": "合入失败",
            "committed": "合入成功", "built": "已编译",
        }
        status = status_map.get(t.get("status", ""), t.get("status", "?"))
        risk = t.get("risk_level", "-")
        review = t.get("review_required", "-")
        note = t.get("skip_reason", "") or t.get("special_notes", "") or "-"

        if t.get("action") == "skip":
            status = "已跳过"

        rows.append(
            f"| {t.get('seq', '?')} | {tid} | {status} "
            f"| {risk} | {review} | {note} |"
        )
    return rows


def build_revert_table(global_revert_order):
    rows = []
    for r in global_revert_order or []:
        commits = ", ".join(r.get("commits", []))
        reason = r.get("revert_strategy", "")
        related = ", ".join(r.get("related_patches", []))
        rows.append(f"| {commits} | {reason} | {related} |")
    return rows if rows else ["| (无) | | |"]


def build_build_summary(tasks):
    rows = []
    for t in tasks:
        tid = t.get("task_id", "?")
        exec_log = t.get("execution_log", [])
        error_count = 0
        retry = 0
        result = "—"

        for e in exec_log:
            if e.get("step") == "BUILD":
                retry += 1
                if e.get("result") == "pass":
                    result = "通过"
                    error_count = e.get("error_count", 0)
                elif e.get("result") == "fail":
                    result = "失败"

        if t.get("status") in ("skipped", "pending"):
            result = "—"
            retry = 0

        rows.append(f"| {tid} | {result} | {error_count} | {retry} |")
    return rows


def build_deps_graph(tasks):
    has_deps = [t for t in tasks if t.get("depends_on")]
    if not has_deps:
        return "无内部依赖"

    lines = []
    for t in sorted(has_deps, key=lambda x: x.get("seq", 0)):
        tid = t.get("task_id", "?")
        deps = ", ".join(t.get("depends_on", []))
        lines.append(f"- {tid} ← {deps}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="生成 summary.md")
    parser.add_argument("--analyse-dir", required=True, help="analyse.md 目录")
    parser.add_argument("--merge-tasks", required=True, help="merge_tasks.json 路径")
    parser.add_argument("--output", required=True, help="输出文件路径")
    args = parser.parse_args()

    if not os.path.isdir(args.analyse_dir):
        print(f"[FAIL] 目录不存在: {args.analyse_dir}", file=sys.stderr)
        sys.exit(1)

    merge_data = load_json(args.merge_tasks)
    info = merge_data.get("patchset_info", {})
    all_tasks = list(merge_data.get("deps_order", [])) + list(merge_data.get("merge_order", []))
    all_tasks.sort(key=lambda x: x.get("seq", 999))

    import glob
    analyse_files = sorted(glob.glob(os.path.join(args.analyse_dir, "*-analys.md")))
    if not analyse_files:
        analyse_files = sorted(glob.glob(os.path.join(args.analyse_dir, "*.md")))
        analyse_files = [f for f in analyse_files if "summary" not in os.path.basename(f).lower()]

    success = sum(1 for t in all_tasks
                  if t.get("status") in ("done", "committed", "built"))
    skipped = sum(1 for t in all_tasks
                  if t.get("action") == "skip" or t.get("status") == "skipped")
    failed = sum(1 for t in all_tasks
                 if t.get("status") == "failed")
    total = len(all_tasks)

    risk_high = [t.get("task_id") for t in all_tasks if t.get("risk_level") == "高"]
    review_high = [t.get("task_id") for t in all_tasks if t.get("review_required") == "高"]

    content = f"""# Patchset Merge 汇总报告

## 基本信息
| 项 | 值 |
|----|-----|
| 来源 | {info.get('source', '—')} |
| 下载方式 | {info.get('download_method', '—')} |
| Patch 总数 | {info.get('total_patches', total)} |
| 合入成功 | {success} |
| 跳过 | {skipped} |
| 失败 | {failed} |
| 目标分支 | {info.get('target_branch', '—')} |
| 目标内核 | {info.get('target_kernel', '—')} |
| 编译目标 | {info.get('build_target', '—')} |
| 生成时间 | {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} |

## 合入顺序与状态
| 序号 | Patch | 状态 | 风险 | Review | 备注 |
|-----|-------|------|------|--------|------|
{chr(10).join(build_status_table(all_tasks, analyse_files))}

## 依赖关系图
{build_deps_graph(all_tasks)}

## Revert 记录
| Commit | 原因 | 关联 Patch |
|--------|------|-----------|
{chr(10).join(build_revert_table(merge_data.get('global_revert_order', [])))}

## 编译验证总览
| Patch | 结果 | 错误数 | 修复次数 |
|-------|------|--------|---------|
{chr(10).join(build_build_summary(all_tasks))}

## 跨 Patch 修复记录
{chr(10).join(f"- {f}" for f in analyse_files) if analyse_files else '{REQUIRES_AI}'}

## 目标仓库重复 patch 汇总
{{REQUIRES_AI_汇总重复信息}}

## 全局改进建议

### 高优先级
{{REQUIRES_AI_高优建议}}

### 中优先级
{{REQUIRES_AI_中优建议}}

### 低优先级 / 长期
{{REQUIRES_AI_低优建议}}

## 全局风险汇总
- 高风险 patch：{', '.join(risk_high) if risk_high else '无'}
- 建议重点人工 review：{', '.join(review_high) if review_high else '无'}

## 待处理事项
{{REQUIRES_AI_待处理事项}}
"""

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        f.write(content)

    print(f"[GEN] {args.output} 已生成")
    sys.exit(0)


if __name__ == "__main__":
    main()
