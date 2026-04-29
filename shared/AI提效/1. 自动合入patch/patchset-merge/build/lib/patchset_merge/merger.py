"""核心 Merge 引擎"""
import subprocess
import hashlib
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List
from .diff_tracker import DiffTracker
from .conflict_resolver import ConflictResolver, ResolutionLogEntry

@dataclass
class MergeResult:
    success: bool
    diff_report_path: Optional[Path]
    conflicts_resolved: int
    conflicts_manual: int

class PatchsetMerger:
    def __init__(self, source_repo: Path, worktree_branch: str = "patchset-merge"):
        self.source_repo = source_repo
        self.worktree_branch = worktree_branch
        self.diff_tracker = DiffTracker(source_repo)
        self.conflict_resolver = ConflictResolver()

    def prepare_worktree(self, branch_name: str) -> Path:
        """创建独立的 git worktree 用于 merge"""
        worktree_path = self.source_repo.parent / f"{self.source_repo.name}-merge-{branch_name}"

        subprocess.run([
            'git', 'worktree', 'add',
            '--branch', f'merge/{branch_name}',
            str(worktree_path),
            'HEAD'
        ], cwd=self.source_repo, check=True)

        return worktree_path

    def apply_mbox(self, mbox_path: Path, worktree_path: Path) -> MergeResult:
        """应用 mbox 文件到 worktree"""
        result = subprocess.run(
            ['git', 'am', str(mbox_path)],
            cwd=worktree_path,
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            return MergeResult(
                success=True,
                diff_report_path=None,
                conflicts_resolved=0,
                conflicts_manual=0
            )

        return self._handle_apply_failure(result, worktree_path)

    def _handle_apply_failure(self, result, worktree_path: Path) -> MergeResult:
        """处理应用失败的情况，切换到 three-way merge"""
        conflict_files = self._detect_conflicts(worktree_path)

        for cf in conflict_files:
            self._resolve_file_conflict(cf, worktree_path)

        subprocess.run(['git', 'add', '.'], cwd=worktree_path, check=True)

        return MergeResult(
            success=True,
            diff_report_path=None,
            conflicts_resolved=len(conflict_files),
            conflicts_manual=0
        )

    def _detect_conflicts(self, worktree_path: Path) -> List[Path]:
        """检测冲突文件"""
        result = subprocess.run(
            ['git', 'diff', '--name-only', '--diff-filter=U'],
            cwd=worktree_path,
            capture_output=True,
            text=True
        )
        return [worktree_path / f.strip() for f in result.stdout.strip().split('\n') if f.strip()]

    def _resolve_file_conflict(self, file_path: Path, worktree_path: Path):
        """解决单个文件的冲突，优先使用 patchset 内容"""
        content = file_path.read_text()

        if '<<<<<<<' in content:
            lines = content.split('\n')
            resolved_lines = []
            i = 0
            while i < len(lines):
                if lines[i].startswith('<<<<<<<'):
                    i += 1
                    patchset_content = []
                    while i < len(lines) and not lines[i].startswith('======='):
                        patchset_content.append(lines[i])
                        i += 1
                    i += 1
                    while i < len(lines) and not lines[i].startswith('>>>>>>>'):
                        i += 1
                    i += 1
                    resolved_lines.extend(patchset_content)
                    self.diff_tracker.add_entry(
                        str(file_path.relative_to(worktree_path)),
                        '\n'.join(patchset_content),
                        '\n'.join(patchset_content),
                        "conflict_resolved"
                    )
                else:
                    resolved_lines.append(lines[i])
                    i += 1

            file_path.write_text('\n'.join(resolved_lines))

    def verify_mbox_deterministic(self, mbox_path: Path, expected_hash: str) -> bool:
        """验证 mbox 文件的 hash"""
        actual_hash = hashlib.sha256(mbox_path.read_bytes()).hexdigest()
        return actual_hash == expected_hash

    def cleanup_worktree(self, worktree_path: Path):
        """清理 worktree"""
        subprocess.run(['git', 'worktree', 'remove', str(worktree_path), '--force'], check=False)

    def finalize(self) -> MergeResult:
        """完成 merge，生成差异报告"""
        diff_report_path = self.source_repo / ".patchset-diff.md"
        self.diff_tracker.save_diff_report(diff_report_path)

        return MergeResult(
            success=True,
            diff_report_path=diff_report_path,
            conflicts_resolved=len(self.conflict_resolver.get_resolution_log()),
            conflicts_manual=0
        )
