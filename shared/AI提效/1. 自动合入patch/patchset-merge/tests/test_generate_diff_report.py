"""Tests for generate_diff_report.py - source vs target diff comparison."""

import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import generate_diff_report as gdr


# ── parse_diff_per_file ──


class TestParseDiffPerFile(unittest.TestCase):
    def test_single_file_add(self):
        diff = (
            "diff --git a/file.c b/file.c\n"
            "--- a/file.c\n"
            "+++ b/file.c\n"
            "@@ -1,3 +1,3 @@\n"
            " unchanged\n"
            "+added line\n"
        )
        files = gdr.parse_diff_per_file(diff)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].file_path, "file.c")
        self.assertTrue(any("added line" in a for a in files[0].added))

    def test_multiple_files(self):
        diff = (
            "diff --git a/bar.c b/bar.c\n"
            "--- a/bar.c\n"
            "+++ b/bar.c\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
            "diff --git a/foo.c b/foo.c\n"
            "--- a/foo.c\n"
            "+++ b/foo.c\n"
            "@@ -1,1 +1,1 @@\n"
            "+only_add\n"
        )
        files = gdr.parse_diff_per_file(diff)
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0].file_path, "bar.c")
        self.assertEqual(files[1].file_path, "foo.c")


# ── compare_diffs (merge mode) ──


class TestCompareDiffsMerge(unittest.TestCase):
    def setUp(self):
        self.mode = "merge"

    def test_no_deviation(self):
        src = [gdr.FileDiff("f.c", added=["+same line"], removed=[])]
        tgt = [gdr.FileDiff("f.c", added=["+same line"], removed=[])]
        devs = gdr.compare_diffs(src, tgt, "patch", "commit", mode=self.mode)
        self.assertEqual(len(devs), 0)

    def test_source_added_target_missing(self):
        src = [gdr.FileDiff("f.c", added=["+only in src"], removed=[])]
        tgt = [gdr.FileDiff("f.c", added=[], removed=[])]
        devs = gdr.compare_diffs(src, tgt, "patch", "commit", mode=self.mode)
        self.assertEqual(len(devs), 1)
        self.assertIn("only in src", devs[0].src_line)

    def test_target_added_source_missing(self):
        src = [gdr.FileDiff("f.c", added=[], removed=[])]
        tgt = [gdr.FileDiff("f.c", added=["+only in tgt"], removed=[])]
        devs = gdr.compare_diffs(src, tgt, "patch", "commit", mode=self.mode)
        self.assertEqual(len(devs), 1)
        self.assertIn("only in tgt", devs[0].target_line)

    def test_mixed_deviation(self):
        src = [gdr.FileDiff("f.c", added=["+keep"], removed=["-remove"])]
        tgt = [gdr.FileDiff("f.c", added=["+keep", "+extra"], removed=[])]
        devs = gdr.compare_diffs(src, tgt, "patch", "commit", mode=self.mode)
        self.assertGreater(len(devs), 0)


# ── compare_diffs (revert mode - mirror comparison) ──


class TestCompareDiffsRevert(unittest.TestCase):
    def setUp(self):
        self.mode = "revert"

    def test_revert_perfect_match(self):
        """完美 revert：源添加 2 行，目标删除 2 行（镜像匹配）"""
        src = [gdr.FileDiff("f.c", added=["+line_a", "+line_b"], removed=[])]
        tgt = [gdr.FileDiff("f.c", added=[], removed=["-line_a", "-line_b"])]
        devs = gdr.compare_diffs(src, tgt, "commit", "revert", mode=self.mode)
        self.assertEqual(len(devs), 0)

    def test_revert_incomplete_missing_removal(self):
        """不完整 revert：源添加了 2 行，目标只删了 1 行"""
        src = [gdr.FileDiff("f.c", added=["+line_a", "+line_b"], removed=[])]
        tgt = [gdr.FileDiff("f.c", added=[], removed=["-line_a"])]
        devs = gdr.compare_diffs(src, tgt, "commit", "revert", mode=self.mode)
        self.assertEqual(len(devs), 1)
        self.assertIn("line_b", devs[0].src_line)

    def test_revert_missing_restore(self):
        """不完整 revert：源删除了 2 行，目标只恢复了 1 行"""
        src = [gdr.FileDiff("f.c", added=[], removed=["-line_a", "-line_b"])]
        tgt = [gdr.FileDiff("f.c", added=["+line_a"], removed=[])]
        devs = gdr.compare_diffs(src, tgt, "commit", "revert", mode=self.mode)
        self.assertEqual(len(devs), 1)
        self.assertIn("line_b", devs[0].src_line)

    def test_revert_over_delete(self):
        """过度回退：revert 删除了源没有的行"""
        src = [gdr.FileDiff("f.c", added=["+line_a"], removed=[])]
        tgt = [gdr.FileDiff("f.c", added=[], removed=["-line_a", "-extra_line"])]
        devs = gdr.compare_diffs(src, tgt, "commit", "revert", mode=self.mode)
        self.assertEqual(len(devs), 1)
        self.assertIn("extra_line", devs[0].target_line)
        self.assertIn("过度回退", devs[0].target_label)

    def test_revert_over_add(self):
        """过度回退：revert 添加了源没有的行"""
        src = [gdr.FileDiff("f.c", added=[], removed=["-line_a"])]
        tgt = [gdr.FileDiff("f.c", added=["+line_a", "+extra"], removed=[])]
        devs = gdr.compare_diffs(src, tgt, "commit", "revert", mode=self.mode)
        self.assertEqual(len(devs), 1)
        self.assertIn("extra", devs[0].target_line)
        self.assertIn("过度回退", devs[0].target_label)

    def test_revert_full_scenario(self):
        """综合场景：源 +a,+b,-c,-d → 目标 -a,+c (b未删除, d未恢复)"""
        src = [gdr.FileDiff("f.c", added=["+a", "+b"], removed=["-c", "-d"])]
        tgt = [gdr.FileDiff("f.c", added=["+c"], removed=["-a"])]
        devs = gdr.compare_diffs(src, tgt, "commit", "revert", mode=self.mode)
        # b 未删除: src signed "+" - tgt signed "-" → +b → 1 偏离
        # d 未恢复: src signed "-" - tgt signed "+" → -d → 1 偏离
        # 共 2 处 (a已删除匹配, c已恢复匹配)
        self.assertEqual(len(devs), 2)


# ── generate_report ──


class TestReportGeneration(unittest.TestCase):
    def test_no_deviation_report(self):
        report = gdr.generate_report([], "patch (test.patch)", "commit abc123")
        self.assertIn("完全一致", report)

    def test_with_deviation_report(self):
        devs = [
            gdr.Deviation(
                file_path="file.c",
                src_line="+old_func",
                src_label="源 patch",
                target_label="实际 commit 无此行",
            )
        ]
        report = gdr.generate_report(devs, "patch (test.patch)", "commit abc123")
        self.assertIn("[file.c]", report)
        self.assertIn("1 处偏离", report)

    def test_report_does_not_contain_raw_diff(self):
        report = gdr.generate_report([], "patch (x.patch)", "commit y")
        self.assertNotIn("## 原始 patch", report)

    def test_revert_mode_label(self):
        report = gdr.generate_report([], "commit aaa", "commit bbb", mode="revert")
        self.assertIn("revert 模式", report)

    def test_report_with_root_cause(self):
        devs = [
            gdr.Deviation(
                file_path="file.c",
                src_line="+old_func",
                src_label="源 patch",
                target_label="实际 commit 无此行",
                root_cause="冲突解决时选择保留 ours",
            )
        ]
        report = gdr.generate_report(devs, "patch (x.patch)", "commit y")
        self.assertIn("根因: 冲突解决时选择保留 ours", report)

    def test_report_with_execution_log_summary(self):
        log = [{"step": "CONFLICT", "detail": "arch/arm64/tools/sysreg 冲突"}]
        report = gdr.generate_report(
            [], "patch (x.patch)", "commit y", execution_log=log,
        )
        self.assertIn("合入经验: 1 条记录", report)

    def test_report_no_root_cause_warning(self):
        devs = [
            gdr.Deviation(
                file_path="f.c", src_line="+x",
                src_label="源", target_label="目标",
            )
        ]
        report = gdr.generate_report(devs, "patch (x.patch)", "commit y")
        self.assertIn("有根因标注: 0/1", report)


# ── get_diff_content ──


class TestGetDiffContent(unittest.TestCase):
    def test_source_patch_format(self):
        with patch("builtins.open", unittest.mock.mock_open(read_data="+added\n")):
            content = gdr.get_diff_content("/repo", "patch:/tmp/test.patch")
            self.assertIn("+added", content)

    def test_source_commit_format(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="commit diff")
            content = gdr.get_diff_content("/repo", "commit:abc123")
            self.assertEqual(content, "commit diff")

    def test_source_invalid_format(self):
        with self.assertRaises(ValueError):
            gdr.get_diff_content("/repo", "invalid")

    @patch("subprocess.run")
    def test_source_commit_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="bad object")
        with self.assertRaises(RuntimeError):
            gdr.get_diff_content("/repo", "commit:badhash")


# ── execution log ──


class TestExecutionLog(unittest.TestCase):
    def test_load_execution_log_found(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "merge_order": [
                    {"task_id": "0001", "execution_log": [
                        {"step": "CONFLICT", "detail": "sysreg conflict"}
                    ]}
                ]
            }, f)
            tmp_path = f.name

        try:
            log = gdr.load_execution_log(tmp_path, "0001")
            self.assertEqual(len(log), 1)
            self.assertEqual(log[0]["step"], "CONFLICT")
        finally:
            os.unlink(tmp_path)

    def test_load_execution_log_not_found(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"merge_order": []}, f)
            tmp_path = f.name

        try:
            log = gdr.load_execution_log(tmp_path, "0001")
            self.assertEqual(log, [])
        finally:
            os.unlink(tmp_path)

    def test_load_execution_log_file_missing(self):
        log = gdr.load_execution_log("/nonexistent/path.json", "0001")
        self.assertEqual(log, [])

    def test_extract_root_causes_file_match(self):
        log = [
            {"step": "CONFLICT", "detail": "arch/arm64/tools/sysreg: missing entry"},
            {"step": "BUILD", "detail": "passed"},
        ]
        causes = gdr.extract_root_causes(log, "arch/arm64/tools/sysreg")
        self.assertEqual(len(causes), 1)
        self.assertIn("sysreg", causes[0])

    def test_extract_root_causes_basename_match(self):
        log = [
            {"step": "FIX", "detail": "fixed mm/mmu.c: HDBSS guard macro"},
        ]
        causes = gdr.extract_root_causes(log, "arch/arm64/mm/mmu.c")
        self.assertEqual(len(causes), 1)
        self.assertIn("mmu.c", causes[0])

    def test_extract_root_causes_no_match(self):
        log = [{"step": "BUILD", "detail": "passed"}]
        causes = gdr.extract_root_causes(log, "unrelated.c")
        self.assertEqual(causes, [])

    def test_annotate_deviation_root_causes(self):
        devs = [
            gdr.Deviation(file_path="mm/memory.c", src_line="+x",
                          src_label="src", target_label="tgt"),
        ]
        log = [
            {"step": "CONFLICT", "detail": "mm/memory.c: Ours/Theirs resolved"},
        ]
        gdr.annotate_deviation_root_causes(devs, log)
        self.assertIn("mm/memory.c", devs[0].root_cause)
        self.assertIn("Ours/Theirs", devs[0].root_cause)

    def test_annotate_fallback_to_conflict_keyword(self):
        devs = [
            gdr.Deviation(file_path="other.c", src_line="+x",
                          src_label="src", target_label="tgt"),
        ]
        log = [
            {"step": "CONFLICT", "detail": "冲突在 sysreg 文件"},
        ]
        gdr.annotate_deviation_root_causes(devs, log)
        self.assertIn("冲突在 sysreg", devs[0].root_cause)

    def test_annotate_empty_log(self):
        devs = [gdr.Deviation(file_path="f.c")]
        gdr.annotate_deviation_root_causes(devs, [])
        self.assertEqual(devs[0].root_cause, "")


# ── auto_detect_mode ──


class TestAutoDetectMode(unittest.TestCase):
    def test_patch_source_is_merge(self):
        mode = gdr.auto_detect_mode("patch:/t.patch", "/repo", "abc")
        self.assertEqual(mode, "merge")

    @patch("subprocess.run")
    def test_commit_revert_message_detected(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="Revert xyz12345 patch")
        mode = gdr.auto_detect_mode("commit:xyz1234567890", "/repo", "target")
        self.assertEqual(mode, "revert")

    @patch("subprocess.run")
    def test_commit_regular_message_is_merge(self, mock_run):
        # 第一次调用: git log (commit message)
        # 第二次调用: git diff (检查是否有 + 行)
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="arm64: add HDBSS support"),
            MagicMock(returncode=0, stdout="+new_function()"),
        ]
        mode = gdr.auto_detect_mode("commit:abc", "/repo", "target")
        self.assertEqual(mode, "merge")


# ── main CLI ──


class TestMainCLI(unittest.TestCase):
    @patch("sys.argv", ["cmd", "--source", "patch:/t.patch",
                        "--target", "abc", "--repo-path", "/r"])
    @patch("builtins.open", unittest.mock.mock_open(read_data="+main\n"))
    @patch("subprocess.run")
    def test_merge_scenario(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=(
            "diff --git a/file.c b/file.c\n"
            "--- a/file.c\n"
            "+++ b/file.c\n"
            "@@ -1,1 +1,1 @@\n"
            "+main\n"
        ))
        try:
            gdr.main()
        except SystemExit:
            pass

    @patch("sys.argv", ["cmd", "--source", "commit:src123",
                        "--target", "tgt456", "--repo-path", "/r",
                        "--mode", "revert"])
    @patch("subprocess.run")
    def test_revert_scenario(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=(
            "diff --git a/file.c b/file.c\n"
            "--- a/file.c\n"
            "+++ b/file.c\n"
            "@@ -1,1 +1,1 @@\n"
            "-reverted\n"
        ))
        try:
            gdr.main()
        except SystemExit:
            pass

    @patch("sys.argv", ["cmd", "--source", "patch:/t.patch",
                        "--target", "abc", "--repo-path", "/r",
                        "--execution-log", "/tmp/merge_tasks.json",
                        "--task-id", "0001"])
    @patch("builtins.open", unittest.mock.mock_open(read_data="+main\n"))
    @patch("subprocess.run")
    def test_with_execution_log(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=(
            "diff --git a/file.c b/file.c\n"
            "--- a/file.c\n"
            "+++ b/file.c\n"
            "@@ -1,1 +1,1 @@\n"
            "+main\n"
        ))
        # Mock the merge_tasks.json file read inside load_execution_log
        with patch.object(
            gdr, 'load_execution_log', return_value=[]
        ):
            try:
                gdr.main()
            except SystemExit:
                pass
