"""Patchset Merge Skill - 用于合入 lore.kernel.org 上的 patchset

【核心约束】
1. 逐个合入：源 patchset 有多少个 patch，就必须逐个合入
2. 逐个 commit：每个成功的 patch 必须单独 commit
3. 解决问题：遇到冲突、版本不匹配等问题必须解决，不能跳过
4. 保留分支：合入结果分支必须保留，不删除
5. 中文输出：所有思考、解释、输出必须使用中文
"""

from .skill import (
    execute_patchset_merge,
    split_mbox_to_patches,
    apply_patchset_one_by_one,
    compile_project,
    add_compilation_diff_entries,
    apply_single_patch_with_retry,
    resolve_conflicts_and_commit,
    try_git_apply,
    try_manual_apply_and_commit,
    PatchApplyFailed,
    PatchInfo,
    PatchsetMergeResult,
    CompilationResult,
)

from .diff_tracker import DiffTracker, DiffEntry

__all__ = [
    "execute_patchset_merge",
    "split_mbox_to_patches",
    "apply_patchset_one_by_one",
    "compile_project",
    "add_compilation_diff_entries",
    "apply_single_patch_with_retry",
    "resolve_conflicts_and_commit",
    "try_git_apply",
    "try_manual_apply_and_commit",
    "PatchApplyFailed",
    "PatchInfo",
    "PatchsetMergeResult",
    "CompilationResult",
    "DiffTracker",
    "DiffEntry",
]
