"""单元测试"""
import pytest
from pathlib import Path
from patchset_merge.b4_installer import check_b4_installed
from patchset_merge.diff_tracker import DiffTracker, DiffEntry
from patchset_merge.conflict_resolver import ConflictResolver, ConflictResolution

def test_b4_check():
    """测试 b4 安装检查"""
    result = check_b4_installed()
    assert isinstance(result, bool)

def test_diff_tracker():
    """测试差异追踪"""
    tracker = DiffTracker(Path("/tmp/test"))
    tracker.add_entry(
        file_path="kernel/sched.c",
        original="+patch_content",
        applied="+modified_content",
        reason="conflict_resolved"
    )

    report = tracker.generate_diff()
    assert "kernel/sched.c" in report
    assert "conflict_resolved" in report

def test_conflict_resolver_prefers_patchset():
    """测试冲突解决策略 - 优先 patchset"""
    resolver = ConflictResolver()
    resolved, reason = resolver.resolve_conflict(
        our_content="+our_change",
        their_content="+their_change",
        patchset_content="+patchset_change",
        context={}
    )

    assert resolved == "+patchset_change"
    assert "patchset_preferred" in reason

def test_diff_entry_dataclass():
    """测试 DiffEntry 数据类"""
    entry = DiffEntry(
        file_path="test.c",
        original_patchset_content="+old",
        applied_content="+new",
        reason="test"
    )
    assert entry.file_path == "test.c"
    assert entry.reason == "test"

def test_diff_entry_with_metadata():
    """测试 DiffEntry 支持 patch_hash 和 line_range"""
    from patchset_merge.diff_tracker import DiffEntry

    entry = DiffEntry(
        file_path="kernel/sched.c",
        original_patchset_content="+old",
        applied_content="+new",
        reason="conflict_resolved",
        patch_hash="abc123def456",
        line_range=(10, 20)
    )
    assert entry.patch_hash == "abc123def456"
    assert entry.line_range == (10, 20)

def test_diff_tracker_with_metadata():
    """测试 DiffTracker 支持新参数"""
    from patchset_merge.diff_tracker import DiffTracker

    tracker = DiffTracker(Path("/tmp/test"))
    tracker.add_entry(
        file_path="kernel/sched.c",
        original="+patch_content",
        applied="+modified_content",
        reason="conflict_resolved",
        patch_hash="abc123",
        line_range=(100, 110)
    )

    report = tracker.generate_diff()
    assert "abc123" in report
    assert "100-110" in report

def test_generate_html_diff():
    """测试 HTML 差异报告生成"""
    from patchset_merge.diff_tracker import DiffTracker

    tracker = DiffTracker(Path("/tmp/test"))
    tracker.add_entry(
        file_path="test.c",
        original="+old",
        applied="+new",
        reason="conflict_resolved"
    )

    html = tracker.generate_html_diff()
    assert "<!DOCTYPE html>" in html
    assert "test.c" in html
    assert "conflict_resolved" in html

def test_verify_mbox_deterministic(tmp_path):
    """测试 mbox hash 校验"""
    from patchset_merge.merger import PatchsetMerger
    import hashlib

    # 创建测试 mbox 文件
    mbox_file = tmp_path / "test.mbox"
    content = "test patch content"
    mbox_file.write_text(content)

    expected_hash = hashlib.sha256(content.encode()).hexdigest()

    merger = PatchsetMerger(source_repo=tmp_path)
    result = merger.verify_mbox_deterministic(mbox_file, expected_hash)
    assert result is True

    # 测试错误 hash
    result = merger.verify_mbox_deterministic(mbox_file, "wrong_hash")
    assert result is False

def test_verify_merge_result(tmp_path):
    """测试 merge 结果校验"""
    from patchset_merge.merger import PatchsetMerger
    import subprocess

    # 创建测试 git 仓库
    repo = tmp_path / "test_repo"
    repo.mkdir()
    subprocess.run(['git', 'init'], cwd=repo, check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=repo, check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=repo, check=True, capture_output=True)

    # 创建初始提交
    (repo / "test.txt").write_text("initial")
    subprocess.run(['git', 'add', '.'], cwd=repo, check=True, capture_output=True)
    subprocess.run(['git', 'commit', '-m', 'initial'], cwd=repo, check=True, capture_output=True)

    merger = PatchsetMerger(source_repo=repo)

    # 验证 merge 结果（直接在 repo 上验证，不再用 worktree）
    is_valid, msg = merger.verify_merge_result(repo)
    assert is_valid is True
    assert "successfully" in msg
