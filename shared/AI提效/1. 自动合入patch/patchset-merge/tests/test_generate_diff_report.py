"""Tests for generate_diff_report.py - source vs target diff comparison."""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import generate_diff_report as gdr


# ── parse_diff_per_file ──


class TestParseDiffPerFile(unittest.TestCase):
    def test_single_file_add(self):
        diff = (
            "diff --git a/file.c b/file.c\n"
            "index abc..def 100644\n"
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


# ── compare_diffs ──


class TestCompareDiffs(unittest.TestCase):
    def test_no_deviation(self):
        src = [
            gdr.FileDiff("f.c", added=["\t+same line"], removed=[]),
        ]
        tgt = [
            gdr.FileDiff("f.c", added=["\t+same line"], removed=[]),
        ]
        devs = gdr.compare_diffs(src, tgt, "patch", "commit")
        self.assertEqual(len(devs), 0)

    def test_source_added_target_missing(self):
        src = [gdr.FileDiff("f.c", added=["\t+only in src"], removed=[])]
        tgt = [gdr.FileDiff("f.c", added=[], removed=[])]
        devs = gdr.compare_diffs(src, tgt, "patch", "commit")
        self.assertEqual(len(devs), 1)
        self.assertIn("only in src", devs[0].src_line)

    def test_target_added_source_missing(self):
        src = [gdr.FileDiff("f.c", added=[], removed=[])]
        tgt = [gdr.FileDiff("f.c", added=["\t+only in tgt"], removed=[])]
        devs = gdr.compare_diffs(src, tgt, "patch", "commit")
        self.assertEqual(len(devs), 1)
        self.assertIn("only in tgt", devs[0].target_line)

    def test_mixed_deviation(self):
        src = [gdr.FileDiff("f.c", added=["\t+keep"], removed=["\t-remove"])]
        tgt = [gdr.FileDiff("f.c", added=["\t+keep", "\t+extra"], removed=[])]
        devs = gdr.compare_diffs(src, tgt, "patch", "commit")
        self.assertGreater(len(devs), 0)


# ── generate_report ──


class TestReportGeneration(unittest.TestCase):
    def test_no_deviation_report(self):
        report = gdr.generate_report([], "patch (test.patch)", "commit abc123")
        self.assertIn("完全一致", report)
        self.assertIn("patch (test.patch)", report)
        self.assertIn("commit abc123", report)

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
        self.assertIn("old_func", report)
        self.assertIn("1 处偏离", report)

    def test_report_does_not_contain_raw_diff(self):
        """新增报告不应包含完整的原始 patch 或实际 diff 内容"""
        report = gdr.generate_report([], "patch (x.patch)", "commit y")
        self.assertNotIn("## 原始 patch", report)
        self.assertNotIn("## 实际应用 diff", report)


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
                        "--target", "tgt456", "--repo-path", "/r"])
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
