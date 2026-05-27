#!/usr/bin/env python3
"""generate_analyse_md.py — 确定性生成 analyse.md（方案 A + D 的 A 部分）

从 structured JSON 生成 analyse.md，自动填充结构化字段，AI 只需补充第 11 节和文字润色。

用法:
  python3 generate_analyse_md.py \
    --analysis-cache analysis_cache.json \
    --merge-tasks merge_tasks.json \
    --task-id 0001 \
    --diff-script scripts/generate_diff_report.py \
    --repo-path "$KERNEL_REPO_PATH" \
    --patch-dir /tmp/patches/ \
    --output "$KERNEL_REPO_PATH/patch_analysis/0001-xxx-analys.md"

退出码: 0=成功, 1=参数错误, 2=数据不完整
"""

from __future__ import annotations

import json
import os
import sys
import argparse
import subprocess
from datetime import datetime, timezone


SECTION_HEADERS = [
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

def _ai(name: str) -> str:
    """生成唯一命名的 AI 占位符，避免 AI Edit 时出现多匹配错误。"""
    return f"{{REQUIRES_AI_{name}}}"

PLACEHOLDER_REQUIRES_AI = _ai  # 向后兼容别名


def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def find_task(merge_data: dict, task_id: str) -> dict | None:
    for section in ["deps_order", "merge_order"]:
        for t in merge_data.get(section, []):
            if t.get("task_id") == task_id:
                return t
    return None


def find_analysis(analysis_cache: dict, task_id: str) -> dict | None:
    return analysis_cache.get(task_id)


def _status_cn(status: str) -> str:
    m = {
        "done": "合入成功", "skipped": "已跳过", "failed": "合入失败",
        "pending": "待处理", "blocked": "阻塞", "in_progress": "进行中",
        "built": "已编译", "committed": "已提交", "reviewed": "已审查",
    }
    return m.get(status, status)


def _list_val(val, default="无") -> str:
    if not val:
        return default
    if isinstance(val, list):
        return ", ".join(str(v) for v in val)
    return str(val)


def _dict_val(d, key, default="未填写") -> str:
    return str(d.get(key, default)) if d else default


def generate_section_1(task: dict) -> str:
    dup = task.get("duplicate_info", {})
    commit = dup.get("detail", "") if dup.get("level") != "无重复" else _ai("dup_detail")
    return f"""## 1. 基本信息
| 项 | 值 |
|----|-----|
| Patch 编号 | {task.get("task_id", "?")} |
| 标题 | {task.get("subject", _ai("subject"))} |
| 作者 | {task.get("author", _ai("author"))} |
| 影响文件数 | {len(task.get("files_changed", []))} |
| 涉改文件 | {_list_val(task.get("files_changed"), "无")} |
| 合入动作 | {task.get("action", "?")} |
| 合入状态 | {_status_cn(task.get("status", "?"))} |
| 风险等级 | {task.get("risk_level", "?")} |
| Review 紧急性 | {task.get("review_required", "?")} |
"""


def generate_section_2(analysis: dict) -> str:
    summary = _dict_val(analysis, "summary", _ai("summary"))
    modules = _dict_val(analysis, "modules", _ai("modules"))
    target_status = _dict_val(analysis, "status_in_target", _ai("status_in_target"))
    return f"""## 2. 功能描述与关联模块

{summary}

**关联模块**：{modules}

**目标仓库现状**：{target_status}
"""


def generate_section_3(task: dict, analysis: dict) -> str:
    lines = ["## 3. 依赖分析", ""]

    lines.append("### 3.1 高版本依赖（上游版本差异）")
    deps = analysis.get("high_version_deps", []) if analysis else []
    if deps:
        for d in deps:
            lines.append(f"- {d}")
    else:
        lines.append("未找到依赖")

    lines.append("")
    lines.append("### 3.2 Bugfix 依赖（git blame 追溯）")
    bugs = task.get("blame_hits", [])
    if bugs:
        for b in bugs:
            lines.append(f"- {b}")
    else:
        lines.append("未找到 blame 记录")

    lines.append("")
    lines.append("### 3.3 前置 patch 依赖（本 patchset 内）")
    internal = analysis.get("internal_deps", []) if analysis else []
    depends = task.get("depends_on", [])
    all_internal = list(set(internal + depends))
    if all_internal:
        for d in all_internal:
            lines.append(f"- {d}")
    else:
        lines.append("无内部依赖")

    lines.append("")
    lines.append("### 3.4 目标仓库重复/等效 patch")
    dup = task.get("duplicate_info", {})
    level = dup.get("level", "无重复")
    detail = dup.get("detail", "")
    if level == "无重复":
        lines.append(f"{level}")
    else:
        lines.append(f"{level}: {detail}")

    return "\n".join(lines)


def generate_section_4(analysis: dict) -> str:
    level = _dict_val(analysis, "revert_level", _ai("revert_level")) if analysis else _ai("revert_level")
    commits = _list_val(analysis.get("revert_commits", []) if analysis else [], "无")
    reason = _dict_val(analysis, "revert_reason", _ai("revert_reason")) if analysis else _ai("revert_reason")
    return f"""## 4. Revert 需求评估

| 必要性等级 | {level} |
|-----------|-------------|
| 要 revert 的 commit | {commits} |
| 理由 | {reason} |
"""


def generate_section_5(analysis: dict) -> str:
    risk = _dict_val(analysis, "risk", _ai("risk")) if analysis else _ai("risk")
    detail = _dict_val(analysis, "risk_detail", _ai("risk_detail")) if analysis else _ai("risk_detail")
    return f"""## 5. 风险程度

**{risk}**
{detail}
"""


def generate_section_6(analysis: dict) -> str:
    req = _dict_val(analysis, "review_required", _ai("review_required")) if analysis else _ai("review_required")
    reason = _dict_val(analysis, "review_reason", _ai("review_reason")) if analysis else _ai("review_reason")
    return f"""## 6. 人工 Review 需求度

**{req}**
{reason}
"""


def generate_section_7(analysis: dict) -> str:
    tests = analysis.get("smoke_tests", []) if analysis else []
    items = "\n".join(f"- {t}" for t in tests) if tests else _ai("smoke_tests")
    return f"""## 7. 建议验证冒烟内容
{items}
"""


def generate_section_8(execution_log: list) -> str:
    conflict_info = ""
    build_info = ""
    conflict_count = 0
    build_count = 0

    for entry in execution_log:
        action = entry.get("action", "")
        detail = entry.get("detail", "")

        if action in ("conflict", "冲突"):
            conflict_info += f"- {detail}\n"
            conflict_count += 1
        elif action in ("build_fix", "编译修复"):
            build_info += f"- {detail}\n"
            build_count += 1

    if not conflict_info:
        conflict_info = _ai("conflict_info")
    if not build_info:
        build_info = _ai("build_info")

    return f"""## 8. 合入实际经验

- 冲突解决：
{conflict_info.rstrip()}
- 编译修复：
{build_info.rstrip()}
- 重试次数：冲突 {conflict_count} 次 / 编译 {build_count} 次
"""


def generate_section_9(diff_content: str) -> str:
    if not diff_content or diff_content.strip() == "":
        diff_content = _ai("diff_content")
    return f"""## 9. 与源 Patch/Commit 的差异对比

{diff_content}
"""


def generate_section_10(task: dict, execution_log: list) -> str:
    error_count = 0
    product = _ai("product")
    retry = 0

    for entry in execution_log:
        if entry.get("result") == "pass" and entry.get("step") == "BUILD":
            error_count = entry.get("error_count", 0)
            product = entry.get("product", product)
        if entry.get("step") == "BUILD":
            retry += 1

    return f"""## 10. 编译验证记录

```
编译结果：
  错误数: {error_count}
  产物:   {product}
  重试:   {retry} 次
```
"""


def generate_section_11() -> str:
    return f"""## 11. Review 建议与改进方向

### 功能改进建议
{_ai("review_improvement")}

### 潜在 Bug 提示
{_ai("review_bug_hint")}

### 代码质量建议
{_ai("review_code_quality")}

### 适配建议
{_ai("review_adapter")}
"""


def run_diff_script(diff_script: str, merge_tasks_path: str,
                    repo_path: str, task_id: str,
                    patch_file: str, commit_hash: str,
                    mode: str = "merge") -> str:
    if mode == "merge":
        source = f"patch:{patch_file}"
    else:
        source = f"commit:{commit_hash}"

    cmd = [
        sys.executable, diff_script,
        "--source", source,
        "--target", commit_hash or "HEAD",
        "--repo-path", repo_path,
        "--execution-log", merge_tasks_path,
        "--task-id", task_id,
    ]
    if mode == "revert":
        cmd.extend(["--mode", "revert"])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return _ai("diff_result")


def generate_analyse_md(analysis_cache: dict, merge_data: dict,
                        task_id: str, merge_tasks_path: str,
                        diff_script: str, repo_path: str,
                        patch_dir: str, commit_hash: str = "",
                        mode: str = "merge") -> str:
    task = find_task(merge_data, task_id)
    analysis = find_analysis(analysis_cache, task_id)

    if task is None:
        print(f"task {task_id} 未找到", file=sys.stderr)
        sys.exit(2)

    subject = task.get("subject", task_id)
    patch_file = task.get("patch_file", "")

    execution_log = task.get("execution_log", [])

    diff_content = run_diff_script(
        diff_script, merge_tasks_path,
        repo_path, task_id, patch_file, commit_hash, mode,
    )

    sections = [
        f"# Patch {task_id}: {subject}",
        "",
        generate_section_1(task),
        generate_section_2(analysis or {}),
        generate_section_3(task, analysis or {}),
        generate_section_4(analysis or {}),
        generate_section_5(analysis or {}),
        generate_section_6(analysis or {}),
        generate_section_7(analysis or {}),
        generate_section_8(execution_log),
        generate_section_9(diff_content),
        generate_section_10(task, execution_log),
        generate_section_11(),
    ]

    return "\n\n".join(sections)


def main():
    parser = argparse.ArgumentParser(description="生成 analyse.md")
    parser.add_argument("--analysis-cache", required=True, help="analysis_cache.json 路径")
    parser.add_argument("--merge-tasks", required=True, help="merge_tasks.json 路径")
    parser.add_argument("--task-id", required=True, help="task_id")
    parser.add_argument("--diff-script", required=True, help="generate_diff_report.py 路径")
    parser.add_argument("--repo-path", required=True, help="内核仓库路径")
    parser.add_argument("--patch-dir", default="/tmp/patches", help="patch 文件目录")
    parser.add_argument("--commit", default="HEAD", help="commit hash（merge 默认为 HEAD）")
    parser.add_argument("--mode", default="merge", choices=["merge", "revert"])
    parser.add_argument("--output", required=True, help="输出文件路径")
    args = parser.parse_args()

    analysis_cache = load_json(args.analysis_cache)
    merge_data = load_json(args.merge_tasks)

    content = generate_analyse_md(
        analysis_cache, merge_data, args.task_id,
        args.merge_tasks, args.diff_script, args.repo_path, args.patch_dir,
        args.commit, args.mode,
    )

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        f.write(content)

    AI_PREFIX = "{REQUIRES_AI_"
    placeholder_count = content.count(AI_PREFIX)
    print(f"[GEN] {args.output} 已生成 ({placeholder_count} 个 AI 待填字段)")
    sys.exit(0)


if __name__ == "__main__":
    main()
