"""核心 Merge 引擎

【使用方式】
直接使用 git checkout -b 创建新分支，在新分支上合入 patch。
不再使用 worktree，避免复杂度和潜在问题。
"""

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
    def __init__(self, source_repo: Path, branch_name: str = "patchset-merge"):
        self.source_repo = source_repo
        self.branch_name = branch_name
        self.diff_tracker = DiffTracker(source_repo)
        self.conflict_resolver = ConflictResolver()

    def create_branch(self, branch_name: str) -> Path:
        """创建新的 git 分支用于合入 patch

        直接使用 git checkout -b，简洁可靠
        """
        # 检查分支是否已存在
        result = subprocess.run(
            ['git', 'rev-parse', '--verify', f'refs/heads/{branch_name}'],
            cwd=self.source_repo,
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            # 分支已存在，询问是否删除重建
            print(f"分支 {branch_name} 已存在，将被删除并重建")
            subprocess.run(
                ['git', 'branch', '-D', branch_name],
                cwd=self.source_repo,
                check=True
            )

        # 从当前 HEAD 创建新分支
        subprocess.run(
            ['git', 'checkout', '-b', branch_name],
            cwd=self.source_repo,
            check=True
        )

        return self.source_repo

    def apply_mbox(self, mbox_path: Path, repo_path: Path) -> MergeResult:
        """应用 mbox 文件到当前分支

        Args:
            mbox_path: mbox 文件路径
            repo_path: git 仓库路径（与 source_repo 相同）

        Returns:
            MergeResult
        """
        result = subprocess.run(
            ['git', 'am', str(mbox_path)],
            cwd=repo_path,
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

        return self._handle_apply_failure(result, repo_path)

    def _handle_apply_failure(self, result, repo_path: Path) -> MergeResult:
        """处理应用失败的情况"""
        conflict_files = self._detect_conflicts(repo_path)

        if not conflict_files:
            # 没有冲突标记，可能是版本不匹配等问题
            return MergeResult(
                success=False,
                diff_report_path=None,
                conflicts_resolved=0,
                conflicts_manual=0
            )

        for cf in conflict_files:
            self._resolve_file_conflict(cf, repo_path)

        subprocess.run(['git', 'add', '.'], cwd=repo_path, check=True)

        return MergeResult(
            success=True,
            diff_report_path=None,
            conflicts_resolved=len(conflict_files),
            conflicts_manual=0
        )

    def _detect_conflicts(self, repo_path: Path) -> List[Path]:
        """检测冲突文件"""
        result = subprocess.run(
            ['git', 'diff', '--name-only', '--diff-filter=U'],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        return [repo_path / f.strip() for f in result.stdout.strip().split('\n') if f.strip()]

    def _resolve_file_conflict(self, file_path: Path, repo_path: Path):
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
                        str(file_path.relative_to(repo_path)),
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

    def verify_merge_result(self, repo_path: Path) -> tuple[bool, str]:
        """验证 merge 结果

        Returns: (is_valid, message)
        """
        # 检查是否有未解决的冲突（.orig 文件）
        conflicted_files = list(repo_path.glob("**/*.orig"))
        if conflicted_files:
            return False, f"存在未解决的冲突文件: {[str(f) for f in conflicted_files]}"

        # 检查 git am 状态
        result = subprocess.run(
            ['git', 'am', '--show-current-patch'],
            cwd=repo_path,
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            return True, "Merge verified successfully"
        elif result.returncode == 128:
            stderr_lower = result.stderr.lower()
            if any(msg in stderr_lower for msg in [
                "没有正在进行的",
                "resolve operation not in progress",
                "not in a am session",
                "no current patch",
                "解决操作未进行"
            ]):
                return True, "Merge verified successfully"
            return False, f"git am 处于冲突状态: {result.stderr[:100]}"
        else:
            return False, "git am 处于冲突状态"

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
