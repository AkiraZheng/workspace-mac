"""Tests for verify_patch_intent.py — patch intent verification."""

import os
import sys
import json
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import verify_patch_intent as vpi


class TestParsePatch(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write_patch(self, content):
        path = os.path.join(self.tmpdir, "test.patch")
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_single_file_single_hunk(self):
        content = """diff --git a/kernel/sched.c b/kernel/sched.c
index 123..456 100644
--- a/kernel/sched.c
+++ b/kernel/sched.c
@@ -10,6 +10,8 @@
 context line
+new_function() {
+    int x = 1;
+}
 another context
"""
        path = self._write_patch(content)
        result = vpi.parse_patch(path)
        self.assertIn("kernel/sched.c", result)
        adds = [h for h in result["kernel/sched.c"] if h["type"] == "add"]
        self.assertEqual(len(adds), 3)
        self.assertIn("new_function() {", [h["content"] for h in adds])

    def test_multiple_files(self):
        content = """diff --git a/fs/file.c b/fs/file.c
--- a/fs/file.c
+++ b/fs/file.c
@@ -1,0 +1,3 @@
+// new
+int helper(void) { return 0; }
diff --git a/include/linux/file.h b/include/linux/file.h
--- a/include/linux/file.h
+++ b/include/linux/file.h
@@ -5,0 +5,1 @@
+int helper(void);
"""
        path = self._write_patch(content)
        result = vpi.parse_patch(path)
        self.assertEqual(len(result), 2)
        self.assertIn("fs/file.c", result)
        self.assertIn("include/linux/file.h", result)
        # Count add lines
        total_adds = sum(
            len([h for h in hunks if h["type"] == "add"])
            for hunks in result.values()
        )
        self.assertEqual(total_adds, 3)

    def test_delete_lines_parsed(self):
        content = """--- a/kernel/sched.c
+++ b/kernel/sched.c
@@ -10,3 +10,2 @@
-removed_function();
+replacement();
"""
        path = self._write_patch(content)
        result = vpi.parse_patch(path)
        adds = [h for h in result["kernel/sched.c"] if h["type"] == "add"]
        deletes = [h for h in result["kernel/sched.c"] if h["type"] == "delete"]
        self.assertEqual(len(adds), 1)
        self.assertEqual(len(deletes), 1)

    def test_empty_add_lines_skipped(self):
        content = """--- a/kernel/sched.c
+++ b/kernel/sched.c
@@ -1,0 +1,1 @@
+
"""
        path = self._write_patch(content)
        result = vpi.parse_patch(path)
        adds = [h for h in result["kernel/sched.c"] if h["type"] == "add"]
        # Empty + line should be parsed but content is empty
        self.assertEqual(len(adds), 1)
        self.assertEqual(adds[0]["content"], "")


class TestCheckAddedLines(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_all_lines_present(self):
        patch_data = {"kernel/sched.c": [
            {"type": "add", "lineno": 1, "content": "int helper(void) {"},
            {"type": "add", "lineno": 2, "content": "    return 0;"},
        ]}
        os.makedirs(os.path.join(self.tmpdir, "kernel"))
        with open(os.path.join(self.tmpdir, "kernel/sched.c"), "w") as f:
            f.write("int helper(void) {\n    return 0;\n}\n")

        present, missing = vpi.check_added_lines_in_worktree(
            patch_data, self.tmpdir
        )
        self.assertEqual(len(present), 2)
        self.assertEqual(len(missing), 0)

    def test_line_missing(self):
        patch_data = {"kernel/sched.c": [
            {"type": "add", "lineno": 1, "content": "int helper(void) {"},
            {"type": "add", "lineno": 2, "content": "ThisLineWasDeleted!"},
        ]}
        os.makedirs(os.path.join(self.tmpdir, "kernel"))
        with open(os.path.join(self.tmpdir, "kernel/sched.c"), "w") as f:
            f.write("int helper(void) {\n    return 0;\n}\n")

        present, missing = vpi.check_added_lines_in_worktree(
            patch_data, self.tmpdir
        )
        self.assertEqual(len(present), 1)
        self.assertEqual(len(missing), 1)
        self.assertIn("ThisLineWasDeleted!", missing[0][2])

    def test_file_not_exist(self):
        patch_data = {"nonexistent.c": [
            {"type": "add", "lineno": 1, "content": "int x;"},
        ]}
        present, missing = vpi.check_added_lines_in_worktree(
            patch_data, self.tmpdir
        )
        self.assertEqual(len(present), 0)
        self.assertEqual(len(missing), 1)


class TestCheckIntroducedSymbols(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_symbol_found(self):
        task = {
            "introduced_symbols": ["helper_func"],
            "files_changed": ["kernel/sched.c"],
        }
        os.makedirs(os.path.join(self.tmpdir, "kernel"))
        with open(os.path.join(self.tmpdir, "kernel/sched.c"), "w") as f:
            f.write("void helper_func(void) { return; }\n")

        found, missing = vpi.check_introduced_symbols(task, self.tmpdir)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], "helper_func")
        self.assertEqual(len(missing), 0)

    def test_symbol_missing(self):
        task = {
            "introduced_symbols": ["critical_function"],
            "files_changed": ["kernel/sched.c"],
        }
        os.makedirs(os.path.join(self.tmpdir, "kernel"))
        with open(os.path.join(self.tmpdir, "kernel/sched.c"), "w") as f:
            f.write("void unrelated(void) { return; }\n")

        found, missing = vpi.check_introduced_symbols(task, self.tmpdir)
        self.assertEqual(len(found), 0)
        self.assertEqual(len(missing), 1)
        self.assertIn("critical_function", missing)

    def test_no_introduced_symbols(self):
        task = {"introduced_symbols": [], "files_changed": []}
        found, missing = vpi.check_introduced_symbols(task, self.tmpdir)
        self.assertEqual(len(found), 0)
        self.assertEqual(len(missing), 0)

    def test_comment_line_skipped(self):
        task = {
            "introduced_symbols": ["myfunc"],
            "files_changed": ["kernel/sched.c"],
        }
        os.makedirs(os.path.join(self.tmpdir, "kernel"))
        with open(os.path.join(self.tmpdir, "kernel/sched.c"), "w") as f:
            f.write("// myfunc is defined below\n")
            f.write("void myfunc(void) {}\n")

        found, missing = vpi.check_introduced_symbols(task, self.tmpdir)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], "myfunc")


class TestFindTask(unittest.TestCase):
    def test_find_in_merge_order(self):
        merge_data = {
            "merge_order": [{"task_id": "0001", "subject": "test"}],
            "deps_order": [],
        }
        task = vpi.find_task(merge_data, "0001")
        self.assertIsNotNone(task)
        self.assertEqual(task["task_id"], "0001")

    def test_find_in_deps_order(self):
        merge_data = {
            "merge_order": [],
            "deps_order": [{"task_id": "dep-001", "subject": "dep"}],
        }
        task = vpi.find_task(merge_data, "dep-001")
        self.assertIsNotNone(task)

    def test_not_found(self):
        merge_data = {
            "merge_order": [],
            "deps_order": [],
        }
        task = vpi.find_task(merge_data, "9999")
        self.assertIsNone(task)


if __name__ == "__main__":
    unittest.main()
