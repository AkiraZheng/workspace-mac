"""Tests for generate_diff_report.py - diff comparison generator."""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import generate_diff_report as gdr


class TestDiffParsing(unittest.TestCase):
    def test_parse_patch_changed_lines(self):
        patch_content = (
            "--- a/file.c\n"
            "+++ b/file.c\n"
            "@@ -10,6 +10,8 @@\n"
            " unchanged line\n"
            "-deleted line\n"
            "+added line\n"
            " another unchanged\n"
        )
        lines = gdr.parse_changed_lines(patch_content)
        self.assertIn("-deleted line", lines)
        self.assertIn("+added line", lines)
        self.assertNotIn("unchanged line", lines)

    def test_parse_patch_ignores_context(self):
        """Lines without +/- prefix should be excluded."""
        patch_content = (
            "@@ -1,4 +1,4 @@\n"
            " plain context\n"
            "+new\n"
            "-removed\n"
            " more context\n"
        )
        lines = gdr.parse_changed_lines(patch_content)
        self.assertEqual(len(lines), 2)
        self.assertIn("+new", lines)
        self.assertIn("-removed", lines)
        self.assertNotIn("plain context", lines)
        self.assertNotIn("more context", lines)


class TestDiffComparison(unittest.TestCase):
    def test_compare_no_changes(self):
        original = ["+added_function()"]
        actual = ["+added_function()"]
        differences = gdr.compare_diffs(original, actual)
        self.assertEqual(len(differences), 0)

    def test_compare_deviations(self):
        original = ["+func_with_param(int x)"]
        actual = ["+func_with_param(int x, int y)"]
        differences = gdr.compare_diffs(original, actual)
        self.assertGreater(len(differences), 0)

    def test_compare_missing_lines(self):
        original = ["+line_one", "+line_two"]
        actual = ["+line_one"]
        differences = gdr.compare_diffs(original, actual)
        self.assertGreater(len(differences), 0)


class TestReportGeneration(unittest.TestCase):
    def test_generate_report_structure(self):
        report = gdr.generate_report("+test_func()\n", "+test_func()\n")
        self.assertIn("原始 patch", report)
        self.assertIn("实际应用 diff", report)

    def test_generate_report_with_deviations(self):
        report = gdr.generate_report("+test_func()\n", "+test_func_renamed()\n")
        self.assertIn("差异对比", report)


class TestGitShowMock(unittest.TestCase):
    @patch("subprocess.run")
    def test_get_commit_diff(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="diff output")
        output = gdr.get_commit_diff("/path/to/repo", "abc123")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("git", cmd)
        self.assertIn("show", cmd)
        self.assertIn("abc123", cmd)
        self.assertEqual(output, "diff output")

    @patch("subprocess.run")
    def test_get_commit_diff_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stderr="fatal: bad object"
        )
        with self.assertRaises(RuntimeError):
            gdr.get_commit_diff("/path/to/repo", "badhash")
