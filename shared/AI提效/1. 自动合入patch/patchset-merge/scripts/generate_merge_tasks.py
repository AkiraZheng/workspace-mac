#!/usr/bin/env python3
"""
generate_merge_tasks.py — 确定性生成 merge_tasks.json

从 L1+L2 的结构化 JSON 组装完整的 merge_tasks.json。

输入:
  - analysis_cache.json   (L1 extract_patch_symbols.py + agent_analysis 补全)
  - duplicate_analysis.json (Phase 0.5 detect_duplicate.py --version-upgrade)
  - revert_audit.json     (agent_revert 输出, 可选)

输出:
  - merge_tasks.json       (完整 schema, 所有必填字段不可为空)

用法:
  python3 generate_merge_tasks.py \
    --analysis-cache patch_analysis/analysis_cache.json \
    --duplicate-analysis patch_analysis/duplicate_analysis.json \
    --revert-audit patch_analysis/revert_audit.json \
    --patch-dir /tmp/patches/ \
    --output patch_analysis/merge_tasks.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import re
from pathlib import Path


REQUIRED_TASK_FIELDS = [
    "seq", "task_id", "status", "patch_file", "subject",
    "files_changed", "功能分类", "introduced_symbols", "referenced_symbols",
    "action", "pre_revert", "depends_on", "risk_level", "review_required",
    "blame_hits", "duplicate_info", "conflicts_predicted",
    "special_notes", "build_checkpoint",
    "pr_mapping", "execution_log",
]


def load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def extract_patch_metadata(patch_dir: str) -> dict[str, dict]:
    """Extract subject and author from .patch files."""
    results = {}
    for f in sorted(Path(patch_dir).glob("0*.patch")):
        task_id = f.stem.split("-")[0]
        content = f.read_text(errors="replace")
        subject = ""
        author = ""
        for line in content.split("\n"):
            if line.startswith("Subject:"):
                subject = line.replace("Subject:", "").strip()
                subject = re.sub(r'\[PATCH[^\]]*\]\s*', '', subject)
            elif line.startswith("From:"):
                author = line.replace("From:", "").strip()
            if subject and author:
                break
        results[task_id] = {
            "patch_file": str(f.absolute()),
            "subject": subject or f.stem,
            "author": author or "unknown",
        }
    return results


def build_merge_tasks(analysis: dict, duplicates: dict,
                      revert_audit: dict | None,
                      patch_meta: dict[str, dict]) -> dict:
    merge_order = []
    revert_order_entries = duplicates.get("global_revert_order", [])
    revert_rulings = (revert_audit or {}).get("revert_rulings", {})
    pr_aggregation = duplicates.get("pr_aggregation", {})
    thresholds = duplicates.get("thresholds", {})

    # Build patch-level pre_revert mapping from revert_audit
    patch_pre_revert_map = (revert_audit or {}).get("patch_pre_revert", {})

    for seq, (task_id, meta) in enumerate(patch_meta.items(), 1):
        ac = analysis.get(task_id, {})
        dup_list = duplicates.get("patch_duplicate_map", {}).get(task_id, [])

        # ── pre_revert: from revert_audit (AI) or from duplicate_analysis (script)
        pre_revert = list(patch_pre_revert_map.get(task_id, []))

        # ── duplicate_info from duplicate_analysis
        dup_info = []
        for d in dup_list[:5]:
            dup_info.append({
                "commit": d.get("commit", ""),
                "similarity": d.get("similarity", 0),
                "level": d.get("level", ""),
                "pr_info": d.get("pr_info"),
            })

        # ── pr_mapping from duplicate_analysis pr_aggregation
        pr_mapping = {"upstream_deps": [], "bugfix_deps": [], "revert_candidates": []}
        for pr_id, group in pr_aggregation.items():
            decision = group.get("decision", {})
            if decision.get("urgency") in ("必须", "建议"):
                rev_targets = decision.get("revert_targets", [])
                rev_cmd = generate_revert_cmds_for_pr(pr_id, group, revert_rulings)
                pr_mapping["revert_candidates"].append({
                    "pr_id": pr_id,
                    "commits": rev_targets[:10],
                    "revert_cmd": rev_cmd,
                    "urgency": decision.get("urgency"),
                    "coverage_rate": decision.get("coverage_rate", 0),
                })

        # ── blame_hits from analysis_cache
        blame_hits = ac.get("blame_hits", [])
        if isinstance(blame_hits, str) and blame_hits:
            blame_hits = [blame_hits]
        elif not isinstance(blame_hits, list):
            blame_hits = []

        # ── conflicts_predicted
        conflicts = ac.get("conflicts_predicted", [])
        if isinstance(conflicts, str) and conflicts:
            conflicts = [conflicts]
        elif not isinstance(conflicts, list):
            conflicts = []

        task = {
            "seq": seq,
            "task_id": task_id,
            "status": "pending",
            "patch_file": meta["patch_file"],
            "subject": meta["subject"],
            "author": meta.get("author", "unknown"),
            "files_changed": ac.get("changed_files", []),
            "功能分类": ac.get("功能分类", "core"),
            "introduced_symbols": ac.get("introduced_symbols", []),
            "referenced_symbols": ac.get("referenced_symbols", []),
            "action": "apply",  # 硬编码，禁止 skip（所有 patch 必须合入）
            "skip_reason": "",  # 保留字段，不再使用
            "pre_revert": pre_revert,
            "depends_on": ac.get("depends_on", []),
            "risk_level": ac.get("risk_level", "中"),
            "risk_detail": ac.get("risk_detail", ""),
            "review_required": ac.get("review_required", "中"),
            "review_reason": ac.get("review_reason", ""),
            "blame_hits": blame_hits,
            "duplicate_info": dup_info,
            "conflicts_predicted": conflicts,
            "special_notes": ac.get("special_notes", ""),
            "smoke_tests": ac.get("smoke_tests", []),
            "status_in_target": ac.get("status_in_target", ""),
            "build_checkpoint": False,
            "checkpoint_reason": {},
            "pr_mapping": pr_mapping,
            "execution_log": [],
        }
        merge_order.append(task)

    # Build deps_order from analysis_cache dep entries
    deps_order = []
    for task_id, ac in analysis.items():
        if ac.get("is_dep") and task_id.startswith("dep-"):
            deps_order.append({
                "seq": 0,
                "task_id": task_id,
                "status": "pending",
                "patch_file": ac.get("patch_file", ""),
                "subject": ac.get("subject", task_id),
                "author": ac.get("author", "unknown"),
                "files_changed": ac.get("changed_files", []),
                "功能分类": ac.get("功能分类", "core"),
                "introduced_symbols": ac.get("introduced_symbols", []),
                "referenced_symbols": ac.get("referenced_symbols", []),
                "action": "dep",
                "skip_reason": "",
                "pre_revert": [],
                "depends_on": ac.get("depends_on", []),
                "risk_level": "中",
                "review_required": "中",
                "blame_hits": [],
                "duplicate_info": [],
                "conflicts_predicted": [],
                "special_notes": "上游依赖",
                "build_checkpoint": False,
                "checkpoint_reason": {},
                "pr_mapping": {"upstream_deps": [], "bugfix_deps": [], "revert_candidates": []},
                "execution_log": [],
            })

    return {
        "patchset_info": {
            "source": duplicates.get("patchset_info", {}).get("source", ""),
            "thresholds": thresholds,
            "version_upgrade": duplicates.get("version_upgrade", {}).get("enabled", False),
        },
        "global_revert_order": revert_order_entries,
        "deps_order": deps_order,
        "merge_order": merge_order,
        "current_state": {
            "phase": 1.5,
            "task_id": "",
            "step": "pending",
            "status": "ready",
        },
        "workflow_hints": {
            "phase1_complete": True,
            "generated_by": "generate_merge_tasks.py",
        },
    }


def generate_revert_cmds_for_pr(pr_id: str, group: dict,
                                revert_rulings: dict) -> list[str]:
    """Generate revert commands from PR group info and AI rulings."""
    decision = group.get("decision", {})
    strategy = decision.get("strategy", "")
    revert_targets = decision.get("revert_targets", [])
    if not revert_targets or not strategy:
        return []

    ruling = revert_rulings.get(pr_id, {})
    if ruling.get("ruling") == "reject":
        return []

    # AI may override the command
    if ruling.get("revert_cmd"):
        return [ruling["revert_cmd"]]

    # Fallback from duplicate_analysis
    return []


def validate_tasks(merge_tasks: dict, strict: bool = True) -> list[str]:
    """Validate that all tasks have required fields filled.

    Returns list of errors. Empty list means all good.
    """
    errors = []
    all_tasks = merge_tasks.get("merge_order", []) + merge_tasks.get("deps_order", [])
    if not all_tasks:
        errors.append("merge_order 和 deps_order 均为空，无任务可执行")
        return errors

    for task in all_tasks:
        tid = task.get("task_id", "?")
        for field in REQUIRED_TASK_FIELDS:
            val = task.get(field)
            if val is None:
                if strict:
                    errors.append(f"{tid}: 必填字段 '{field}' 为 None")
                else:
                    task[field] = _default_for_field(field)
            elif isinstance(val, str) and val == "":
                if field in ("special_notes", "skip_reason", "checkpoint_reason",
                             "execution_log"):
                    continue
                if field == "action" and task.get("action") == "apply":
                    continue

    if merge_tasks.get("merge_order"):
        task_ids = [t["task_id"] for t in merge_tasks["merge_order"]]
        seqs = [t.get("seq", 0) for t in merge_tasks["merge_order"]]
        if list(seqs) != list(range(1, len(seqs) + 1)):
            errors.append(f"seq 不连续: {seqs}")
        if len(task_ids) != len(set(task_ids)):
            errors.append("task_id 有重复")

    return errors


def _default_for_field(field: str):
    defaults = {
        "pre_revert": [],
        "depends_on": [],
        "blame_hits": [],
        "duplicate_info": [],
        "conflicts_predicted": [],
        "special_notes": "",
        "skip_reason": "",
        "execution_log": [],
        "checkpoint_reason": {},
        "功能分类": "core",
    }
    return defaults.get(field, "")


def main():
    parser = argparse.ArgumentParser(
        description="确定性生成 merge_tasks.json"
    )
    parser.add_argument("--analysis-cache", required=True,
                        help="analysis_cache.json 路径")
    parser.add_argument("--duplicate-analysis", required=True,
                        help="duplicate_analysis.json 路径")
    parser.add_argument("--revert-audit", default="",
                        help="revert_audit.json 路径 (agent_revert 输出, 可选)")
    parser.add_argument("--patch-dir", required=True,
                        help="/tmp/patches/ 路径")
    parser.add_argument("--output", required=True,
                        help="输出 merge_tasks.json 路径")
    args = parser.parse_args()

    for f, name in [
        (args.analysis_cache, "analysis_cache.json"),
        (args.duplicate_analysis, "duplicate_analysis.json"),
    ]:
        if not os.path.exists(f):
            print(f"错误: {name} 不存在: {f}", file=sys.stderr)
            sys.exit(2)

    if not os.path.isdir(args.patch_dir):
        print(f"错误: patch 目录不存在: {args.patch_dir}", file=sys.stderr)
        sys.exit(2)

    analysis = load_json(args.analysis_cache)
    duplicates = load_json(args.duplicate_analysis)
    revert_audit = load_json(args.revert_audit) if args.revert_audit else None
    patch_meta = extract_patch_metadata(args.patch_dir)

    if not patch_meta:
        print("错误: /tmp/patches/ 下无 .patch 文件", file=sys.stderr)
        sys.exit(2)

    merge_tasks = build_merge_tasks(
        analysis, duplicates, revert_audit, patch_meta
    )

    errors = validate_tasks(merge_tasks)
    if errors:
        print("字段校验失败:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(merge_tasks, f, indent=2, ensure_ascii=False)
        f.write("\n")

    merge_count = len(merge_tasks.get("merge_order", []))
    dep_count = len(merge_tasks.get("deps_order", []))
    rev_count = len(merge_tasks.get("global_revert_order", []))
    print(f"merge_tasks.json 生成完成: "
          f"{merge_count} merge + {dep_count} dep, "
          f"{rev_count} revert 项")


if __name__ == "__main__":
    main()
