"""Tests for generate_all_analyses.py — batch analyse.md generation."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import generate_all_analyses as ga


class TestSlugify(unittest.TestCase):
    def test_simple(self):
        slug = ga.slugify_subject("arm64: Add HDBSS support")
        self.assertIn("arm64", slug)
        self.assertIn("HDBSS", slug)
        self.assertIn("Add", slug)

    def test_special_chars(self):
        slug = ga.slugify_subject("KVM: fix stage-2/page table")
        self.assertIn("KVM", slug)
        self.assertIn("fix", slug)
        self.assertNotIn(":", slug)
        self.assertNotIn("/", slug)

    def test_long_subject(self):
        slug = ga.slugify_subject("a" * 80)
        self.assertLessEqual(len(slug), 40)

    def test_empty_result(self):
        slug = ga.slugify_subject("!!!")
        self.assertEqual(slug, "patch")


class TestGenerateAll(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write_json(self, filename, data):
        path = os.path.join(self.tmpdir, filename)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return path

    def test_empty_merge_tasks(self):
        """Empty merge_order and deps_order → exit 2."""
        merge_path = self._write_json("merge_tasks.json", {
            "merge_order": [],
            "deps_order": [],
        })
        cache_path = self._write_json("analysis_cache.json", {})

        with self.assertRaises(SystemExit) as ctx:
            ga.generate_all(
                cache_path, merge_path,
                "/fake/diff.py", "/fake/repo", os.path.join(self.tmpdir, "out"),
            )
        self.assertEqual(ctx.exception.code, 2)

    def test_single_task_generates_file(self):
        """Single task → one analyse.md generated."""
        merge_path = self._write_json("merge_tasks.json", {
            "merge_order": [
                {
                    "task_id": "0001",
                    "subject": "test patch",
                    "author": "test",
                    "status": "done",
                    "action": "apply",
                    "risk_level": "低",
                    "review_required": "低",
                    "files_changed": [],
                    "depends_on": [],
                    "pre_revert": [],
                    "blame_hits": [],
                    "duplicate_info": {"level": "无重复", "detail": ""},
                    "conflicts_predicted": [],
                    "special_notes": "",
                    "execution_log": [],
                    "commit": "HEAD",
                }
            ],
            "deps_order": [],
        })
        cache_path = self._write_json("analysis_cache.json", {
            "0001": {
                "summary": "test",
                "modules": "test",
                "risk": "低",
                "risk_detail": "",
                "revert_level": "无须",
                "revert_commits": [],
                "revert_reason": "",
                "high_version_deps": [],
                "bugfix_deps": [],
                "internal_deps": [],
                "duplicate_info": {"level": "无重复", "detail": ""},
                "review_required": "低",
                "review_reason": "",
                "smoke_tests": [],
                "changed_files": [],
                "status_in_target": "not tested",
            }
        })
        out_dir = os.path.join(self.tmpdir, "out")

        success, skipped, failed = ga.generate_all(
            cache_path, merge_path,
            "/fake/diff.py", "/fake/repo", out_dir,
        )
        self.assertEqual(len(success), 1)
        self.assertEqual(success[0][0], "0001")
        self.assertTrue(os.path.exists(success[0][1]))
        self.assertEqual(len(failed), 0)

    def test_skip_without_log(self):
        """Skip task without execution_log → skipped."""
        merge_path = self._write_json("merge_tasks.json", {
            "merge_order": [
                {
                    "task_id": "0001",
                    "subject": "skip patch",
                    "action": "skip",
                    "execution_log": [],
                }
            ],
            "deps_order": [],
        })
        cache_path = self._write_json("analysis_cache.json", {})

        success, skipped, failed = ga.generate_all(
            cache_path, merge_path,
            "/fake/diff.py", "/fake/repo", os.path.join(self.tmpdir, "out"),
        )
        self.assertEqual(len(success), 0)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0][0], "0001")
        self.assertEqual(len(failed), 0)

    def test_deps_order_included(self):
        """Tasks in deps_order are also generated."""
        merge_path = self._write_json("merge_tasks.json", {
            "merge_order": [],
            "deps_order": [
                {
                    "task_id": "dep-001",
                    "subject": "dep patch",
                    "author": "test",
                    "status": "done",
                    "action": "apply",
                    "risk_level": "低",
                    "review_required": "低",
                    "files_changed": [],
                    "depends_on": [],
                    "pre_revert": [],
                    "blame_hits": [],
                    "duplicate_info": {"level": "无重复", "detail": ""},
                    "conflicts_predicted": [],
                    "special_notes": "",
                    "execution_log": [],
                    "commit": "HEAD",
                }
            ],
        })
        cache_path = self._write_json("analysis_cache.json", {
            "dep-001": {
                "summary": "dep",
                "modules": "test",
                "risk": "低",
                "risk_detail": "",
                "revert_level": "无须",
                "revert_commits": [],
                "revert_reason": "",
                "high_version_deps": [],
                "bugfix_deps": [],
                "internal_deps": [],
                "duplicate_info": {"level": "无重复", "detail": ""},
                "review_required": "低",
                "review_reason": "",
                "smoke_tests": [],
                "changed_files": [],
                "status_in_target": "dep",
            }
        })
        out_dir = os.path.join(self.tmpdir, "out")

        success, skipped, failed = ga.generate_all(
            cache_path, merge_path,
            "/fake/diff.py", "/fake/repo", out_dir,
        )
        self.assertEqual(len(success), 1)
        self.assertEqual(success[0][0], "dep-001")


if __name__ == "__main__":
    unittest.main()
