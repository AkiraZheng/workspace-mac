"""Claude Code Skill 入口"""
from pathlib import Path
from .b4_installer import ensure_b4
from .patchset_downloader import download_patchset
from .merger import PatchsetMerger

def execute_patchset_merge(patch_url: str, source_repo: Path, branch_name: str):
    """执行 patchset merge 工作流"""
    if not ensure_b4():
        raise RuntimeError("Failed to install b4")

    temp_dir = Path("/tmp/patchset-merge")
    temp_dir.mkdir(exist_ok=True)

    mbox_path, mbox_hash = download_patchset(patch_url, temp_dir)
    print(f"Downloaded patchset: {mbox_hash[:16]}...")

    merger = PatchsetMerger(source_repo, branch_name)
    worktree_path = merger.prepare_worktree(branch_name)

    result = merger.apply_mbox(mbox_path, worktree_path)

    if result.success:
        final_result = merger.finalize()
        print(f"Merge completed. Diff report: {final_result.diff_report_path}")
        return final_result
    else:
        raise RuntimeError(f"Merge failed with conflicts")
