#!/usr/bin/env python3
"""
Calculate build_checkpoint for each task in merge_tasks.json.

Rules (priority order):
  1. 功能分类 == 'infra'                          → True
  2. introduced_symbols referenced by >= 3 later patches → True
  3. risk_level == '高' or conflicts_predicted non-empty → True
  4. Last patch in its (功能分类, path_prefix) group   → True
  5. Last patch overall (max seq)                   → True (forced)
  6. action == 'skip' or 功能分类 == 'doc'          → False
  7. All others                                     → False
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


def calculate_checkpoints(merge_tasks):
    all_patches = merge_tasks.get('merge_order', []) + merge_tasks.get('deps_order', [])
    if not all_patches:
        return merge_tasks

    # Sort by seq to establish order
    all_patches.sort(key=lambda p: p.get('seq', 9999))

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

    results = []
    for idx, patch in enumerate(all_patches):
        seq = patch.get('seq', 0)
        func_class = patch.get('功能分类', 'core')
        reason_parts = []
        checkpoint = None

        # Rule 1: infra → true
        if func_class == 'infra':
            checkpoint = True
            reason_parts.append('基础设施（公共头文件/宏定义）')

        # Rule 2: referenced by >= 3 later patches
        if checkpoint is None:
            later_patches = all_patches[idx + 1:]
            ref_count = count_references(
                patch.get('introduced_symbols', []), later_patches
            )
            if ref_count >= 3:
                checkpoint = True
                reason_parts.append(f'被 ≥3 个后续 patch 依赖（{ref_count} 个）')

        # Rule 3: risk_level == "高" or conflicts_predicted non-empty
        if checkpoint is None:
            if (patch.get('risk_level') == '高' or
                    patch.get('conflicts_predicted')):
                checkpoint = True
                reason_parts.append('高风险或有预判冲突')

        # Rule 4: skip or doc → false (early exit, pointless to check further)
        if checkpoint is None:
            if patch.get('action') == 'skip' or func_class == 'doc':
                checkpoint = False
                reason_parts.append('跳过或文档类型')

        # Rule 5: last in group (only when group size > 1)
        if checkpoint is None:
            group_key = (func_class, common_path_prefix(patch.get('files_changed', [])))
            group_patches = groups.get(group_key, [])
            if len(group_patches) > 1 and last_in_group.get(id(patch)):
                checkpoint = True
                path_prefix = common_path_prefix(patch.get('files_changed', []))
                reason_parts.append(f'功能模块最后 patch（{func_class}/{path_prefix} 组）')

        # Rule 6: last patch overall (forced)
        if seq == last_patch_seq:
            if checkpoint is None:
                checkpoint = True
                reason_parts.append('最后一个 patch（强制）')
            elif checkpoint:
                # Already a checkpoint, append forced flag
                reason_parts.append('(也是最后一个 patch)')

        # Rule 7: default → false
        if checkpoint is None:
            checkpoint = False

        if not reason_parts and checkpoint is False and (patch.get('action') != 'skip' and func_class != 'doc'):
            pass  # no reason needed for default false
        elif not reason_parts and checkpoint is False:
            reason_parts.append('跳过或文档类型')

        results.append({
            'task_id': patch.get('task_id', ''),
            'seq': seq,
            '功能分类': func_class,
            'checkpoint': checkpoint,
            'reason': '; '.join(reason_parts) if reason_parts else ''
        })

        # Update patch in-place
        patch['build_checkpoint'] = checkpoint

    return merge_tasks, results


def print_results(results):
    """Print formatted results table."""
    print()
    print('\U0001f4ca 编译验证点计算结果：')
    print()
    header = f"{'Seq':<5} {'Task':<10} {'功能分类':<10} {'被引用数':<8} {'验证点':<6} {'原因'}"
    print(header)
    print('-' * len(header))

    # Re-count references for display
    all_patches_buf = []
    for r in results:
        mark = '\u2705' if r['checkpoint'] else '\u2014'
        print(f"{r['seq']:<5} {r['task_id']:<10} {r['功能分类']:<10} {'':<8} {mark:<6} {r['reason']}")

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
