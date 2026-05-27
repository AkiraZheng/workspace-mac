"""Tests for verify_analyse_format.py — expected files check."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import verify_analyse_format as vf


class TestSlugifySubject(unittest.TestCase):
    def test_normal(self):
        slug = vf.slugify_subject("arm64: Add HDBSS")
        self.assertIn("arm64", slug)
        self.assertIn("Add", slug)
        self.assertNotIn(":", slug)

    def test_empty_result(self):
        slug = vf.slugify_subject("!!!")
        self.assertEqual(slug, "patch")


class TestBuildExpectedFiles(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write_merge_tasks(self, data):
        path = os.path.join(self.tmpdir, "merge_tasks.json")
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return path

    def test_build_from_merge_order(self):
        merge_path = self._write_merge_tasks({
            "merge_order": [
                {
                    "task_id": "0001",
                    "subject": "First patch",
                },
                {
                    "task_id": "0002",
                    "subject": "Second patch",
                },
            ],
            "deps_order": [],
        })
        expected = vf.build_expected_files(merge_path, self.tmpdir)
        self.assertEqual(len(expected), 2)
        self.assertIn("0001-First-patch-analys.md", expected[0])
        self.assertIn("0002-Second-patch-analys.md", expected[1])

    def test_includes_deps_order(self):
        merge_path = self._write_merge_tasks({
            "merge_order": [
                {"task_id": "0001", "subject": "patch A"},
            ],
            "deps_order": [
                {"task_id": "dep-001", "subject": "dep patch"},
            ],
        })
        expected = vf.build_expected_files(merge_path, self.tmpdir)
        self.assertEqual(len(expected), 2)
        names = [os.path.basename(f) for f in expected]
        self.assertTrue(any("0001" in n for n in names))
        self.assertTrue(any("dep-001" in n for n in names))


class TestCheckExpectedFiles(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_all_present(self):
        """All expected files exist → present, no missing."""
        f1 = os.path.join(self.tmpdir, "0001-test-analys.md")
        f2 = os.path.join(self.tmpdir, "0002-test-analys.md")
        open(f1, "w").close()
        open(f2, "w").close()

        present, missing = vf.check_expected_files([f1, f2])
        self.assertEqual(len(present), 2)
        self.assertEqual(len(missing), 0)

    def test_some_missing(self):
        """One file missing → detected."""
        f1 = os.path.join(self.tmpdir, "0001-test-analys.md")
        f2 = os.path.join(self.tmpdir, "0002-missing-analys.md")
        open(f1, "w").close()

        present, missing = vf.check_expected_files([f1, f2])
        self.assertEqual(len(present), 1)
        self.assertEqual(len(missing), 1)
        self.assertIn(f2, missing)

    def test_all_missing(self):
        """All files missing → all detected."""
        f1 = os.path.join(self.tmpdir, "0001-test-analys.md")
        f2 = os.path.join(self.tmpdir, "0002-test-analys.md")

        present, missing = vf.check_expected_files([f1, f2])
        self.assertEqual(len(present), 0)
        self.assertEqual(len(missing), 2)


if __name__ == "__main__":
    unittest.main()
