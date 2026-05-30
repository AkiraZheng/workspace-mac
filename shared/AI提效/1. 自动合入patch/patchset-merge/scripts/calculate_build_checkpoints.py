#!/usr/bin/env python3
"""
Calculate build_checkpoint for each task in merge_tasks.json.

Rules (priority order, short-circuit):
  1a. 反向依赖者                                        → False（完全排除）
  1b. 反向依赖的被依赖者                                 → True（强制）
  1c. 最后一个 revert task（revert 序列中 seq 最大）       → True（强制）
  1.  功能分类 == 'infra'                                → True
  2.  introduced_symbols referenced by >= 3 later patches → True
  3.  risk_level == '高' or conflicts_predicted non-empty → True
  4.  Last patch overall (max seq)                        → True (forced)
  5.  action == 'skip' or 功能分类 == 'doc'               → False
  6.  Last patch in its (功能分类, path_prefix) group     → True
  7.  All others                                          → False
"""

import argparse
import json
import sys
import os
from pathlib import Path
from collections import defaultdict


def common_path_prefix(files_changed):
    """Extract common path prefix (first 3 directory levels)."""
    if not files_changed:
        return "unknown"
    parts = files_changed[0].split('/')
    if len(parts) >= 3:
        return '/'.join(parts[:3])
    elif len(parts) >= 1:
        return parts[0]
    return "unknown"


def count_references(introduced_symbols, later_patches):
    """Count how many later patches reference any of the introduced symbols."""
    if not introduced_symbols:
        return 0
    intro_set = set(introduced_symbols)
    count = 0
    for patch in later_patches:
        refs = set(patch.get('referenced_symbols', []))
        if intro_set & refs:
            count += 1
    return count


def detect_reverse_dependencies(all_patches):
    """Detect reverse dependencies in patch order.

    A reverse dependency occurs when a patch at an EARLIER position (lower seq)
    references symbols introduced by a patch at a LATER position (higher seq).

    Returns:
      reverse_dependers: dict {task_id: {symbol: provider_task_id}}
      reverse_providers: dict {task_id: {symbol: [depender_task_ids]}}
    """
    symbol_owner = {}
    for patch in all_patches:
        for sym in patch.get('introduced_symbols', []):
            symbol_owner[sym] = patch['task_id']

    reverse_dependers = defaultdict(dict)
    reverse_providers = defaultdict(lambda: defaultdict(list))

    for patch in all_patches:
        pid = patch['task_id']
        for sym in patch.get('referenced_symbols', []):
            owner = symbol_owner.get(sym)
            if owner is None or owner == pid:
                continue

            owner_seq = None
            pid_seq = None
            for p in all_patches:
                if p['task_id'] == owner:
                    owner_seq = p.get('seq', 0)
                if p['task_id'] == pid:
                    pid_seq = p.get('seq', 0)

            if owner_seq is None or pid_seq is None:
                continue

            if pid_seq < owner_seq:
                reverse_dependers[pid][sym] = owner
                reverse_providers[owner][sym].append(pid)

    # Convert defaultdict to plain dict for JSON serialization
    reverse_dependers_out = {
        k: dict(v) for k, v in reverse_dependers.items()
    }
    reverse_providers_out = {
        k: {sym: sorted(pids) for sym, pids in v.items()}
        for k, v in reverse_providers.items()
    }

    return reverse_dependers_out, reverse_providers_out


def calculate_checkpoints(merge_tasks):
    all_patches = merge_tasks.get('merge_order', []) + merge_tasks.get('deps_order', [])
    if not all_patches:
        return merge_tasks, []

    # Sort by seq to establish original order
    all_patches.sort(key=lambda p: p.get('seq', 9999))

    # Detect reverse dependencies BEFORE rule evaluation
    reverse_dependers, reverse_providers = detect_reverse_dependencies(all_patches)

    # Group by (功能分类, path_prefix)
    groups = defaultdict(list)
    for patch in all_patches:
        func_class = patch.get('功能分类', 'core')
        path_prefix = common_path_prefix(patch.get('files_changed', []))
        group_key = (func_class, path_prefix)
        groups[group_key].append(patch)

    # Determine last patch per group (by seq)
    last_in_group = {}
    for group_key, patches in groups.items():
        last_patch = max(patches, key=lambda p: p.get('seq', 0))
        last_in_group[id(last_patch)] = True

    # Determine last patch overall
    last_patch_overall = max(all_patches, key=lambda p: p.get('seq', 0))
    last_patch_seq = last_patch_overall.get('seq', 0)

    # Rule 1c: last revert task (has non-empty pre_revert list, forced checkpoint)
    revert_tasks = [p for p in all_patches if p.get('pre_revert')]
    last_revert_seq = -1
    if revert_tasks:
        last_revert = max(revert_tasks, key=lambda p: p.get('seq', 0))
        last_revert_seq = last_revert.get('seq', 0)

    results = []
    for idx, patch in enumerate(all_patches):
        seq = patch.get('seq', 0)
        task_id = patch.get('task_id', '')
        func_class = patch.get('功能分类', 'core')
        reason_parts = []
        rules_triggered = []
        forced_by = []
        checkpoint = None
        reverse_dep_detail = None

        # ── Rule 1a: 反向依赖者 → 完全排除 ──
        if task_id in reverse_dependers:
            checkpoint = False
            rules_triggered.append("Rule_1a")
            rd = reverse_dependers[task_id]
            depender_symbols = [f"{sym}→{owner}" for sym, owner in rd.items()]
            reason_parts.append(f'反向依赖者（引用后面 patch 的符号: {";".join(depender_symbols[:3])}）')
            reverse_dep_detail = {
                "type": "depender",
                "referenced_symbols": {sym: owner for sym, owner in rd.items()},
                "depender_symbols_list": depender_symbols
            }

        # ── Rule 1b: 反向依赖的被依赖者 → 强制验证 ──
        if checkpoint is None and task_id in reverse_providers:
            checkpoint = True
            rules_triggered.append("Rule_1b")
            forced_by.append("reverse_provider")
            rp = reverse_providers[task_id]
            sym_list = sorted(rp.keys())
            reason_parts.append(f'反向依赖：定义符号 {", ".join(sym_list[:3])}（被前面 patch 引用）')
            reverse_dep_detail = {
                "type": "provider",
                "provided_symbols": rp
            }

        # ── Rule 1c: last revert task (FORCED) ──
        if checkpoint is None and last_revert_seq > 0 and seq == last_revert_seq:
            checkpoint = True
            rules_triggered.append("Rule_1c")
            forced_by.append("last_revert")
            if seq == last_patch_seq:
                reason_parts.append('最后一个 revert;末 patch 强制')
            else:
                reason_parts.append('最后一个 revert task（强制编译验证）')

        # ── Rule 1: infra → true ──
        if checkpoint is None and func_class == 'infra':
            checkpoint = True
            rules_triggered.append("Rule_1")
            forced_by.append("infra")
            reason_parts.append('基础设施（公共头文件/宏定义）')

        # ── Rule 2: referenced by >= 3 later patches ──
        if checkpoint is None:
            later_patches = all_patches[idx + 1:]
            ref_count = count_references(
                patch.get('introduced_symbols', []), later_patches
            )
            if ref_count >= 3:
                checkpoint = True
                rules_triggered.append("Rule_2")
                forced_by.append(">=3_refs")
                reason_parts.append(f'被 ≥3 个后续 patch 依赖（{ref_count} 个）')

        # ── Rule 4: risk_level == "高" or conflicts_predicted ──
        if checkpoint is None:
            if (patch.get('risk_level') == '高' or
                    patch.get('conflicts_predicted')):
                checkpoint = True
                rules_triggered.append("Rule_3")
                forced_by.append("high_risk")
                reason_parts.append('高风险或有预判冲突')

        # ── Rule 5: last patch overall (FORCED) ──
        if seq == last_patch_seq:
            checkpoint = True
            rules_triggered.append("Rule_4")
            forced_by.append("last_patch")
            if patch.get('action') == 'skip' or func_class == 'doc':
                reason_parts.append('最后一个 patch（强制，skip/doc 也验证）')
            else:
                reason_parts.append('最后一个 patch（强制）')

        # ── Rule 6: skip or doc → false ──
        if checkpoint is None:
            if patch.get('action') == 'skip' or func_class == 'doc':
                checkpoint = False
                rules_triggered.append("Rule_5")
                reason_parts.append('跳过或文档类型')

        # ── Rule 7: last in group ──
        if checkpoint is None:
            group_key = (func_class, common_path_prefix(patch.get('files_changed', [])))
            group_patches = groups.get(group_key, [])
            if len(group_patches) > 1 and last_in_group.get(id(patch)):
                checkpoint = True
                rules_triggered.append("Rule_6")
                forced_by.append("group_last")
                path_prefix = common_path_prefix(patch.get('files_changed', []))
                reason_parts.append(f'功能模块最后 patch（{func_class}/{path_prefix} 组）')

        # ── Rule 8: default → false ──
        if checkpoint is None:
            checkpoint = False
            rules_triggered.append("Rule_7")

        primary_reason = '; '.join(reason_parts) if reason_parts else '默认（无特殊条件触发）'

        checkpoint_reason = {
            "rules_triggered": rules_triggered,
            "primary_reason": primary_reason,
            "excluded": not checkpoint,
            "forced_by": forced_by if forced_by else None,
            "reverse_dep_detail": reverse_dep_detail,
        }

        results.append({
            'task_id': task_id,
            'seq': seq,
            '功能分类': func_class,
            'checkpoint': checkpoint,
            'reason': primary_reason
        })

        # Update patch in-place
        patch['build_checkpoint'] = checkpoint
        patch['checkpoint_reason'] = checkpoint_reason

    return merge_tasks, results


def print_results(results):
    """Print formatted results table."""
    print()
    print('\U0001f4ca 编译验证点计算结果：')
    print()
    header = f"{'Seq':<5} {'Task':<10} {'功能分类':<10} {'验证点':<6} {'原因'}"
    print(header)
    print('-' * len(header))

    for r in results:
        mark = '\u2705' if r['checkpoint'] else '\u2014'
        print(f"{r['seq']:<5} {r['task_id']:<10} {r['功能分类']:<10} {mark:<6} {r['reason']}")

    checkpoint_count = sum(1 for r in results if r['checkpoint'])
    total = len(results)
    print()
    print(f"统计: \u2705={checkpoint_count} 处验证点，预计编译 {checkpoint_count} 次（共 {total} 个 patch）")


def main():
    parser = argparse.ArgumentParser(
        description='Calculate build_checkpoint for merge_tasks.json'
    )
    parser.add_argument('--merge-tasks', required=True,
                        help='Path to merge_tasks.json')
    parser.add_argument('--output', default=None,
                        help='Output path (defaults to overwrite input)')
    args = parser.parse_args()

    merge_file = args.merge_tasks
    output_file = args.output or merge_file

    if not os.path.exists(merge_file):
        print(f"Error: {merge_file} not found", file=sys.stderr)
        sys.exit(1)

    with open(merge_file, 'r') as f:
        data = json.load(f)

    updated, results = calculate_checkpoints(data)

    with open(output_file, 'w') as f:
        json.dump(updated, f, indent=2, ensure_ascii=False)
        f.write('\n')

    print(f"已更新 {output_file}")
    print_results(results)


if __name__ == '__main__':
    main()
