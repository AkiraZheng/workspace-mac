"""Tests for merge_order_sort.py — combined ordering."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import merge_order_sort as mos


SAMPLE_DEPS = [
    {
        "seq": 1, "task_id": "dep-001", "status": "pending",
        "subject": "stage2 refactor", "action": "apply",
        "pre_revert": [], "depends_on": [], "files_changed": [],
    },
    {
        "seq": 2, "task_id": "dep-002", "status": "pending",
        "subject": "helper function", "action": "apply",
        "pre_revert": [], "depends_on": [], "files_changed": [],
    },
]

SAMPLE_MERGE = [
    {
        "seq": 1, "task_id": "0001", "status": "pending",
        "subject": "HDBSS sysreg", "action": "apply",
        "pre_revert": [], "depends_on": ["dep-001"], "files_changed": [],
    },
    {
        "seq": 2, "task_id": "0002", "status": "pending",
        "subject": "DBM attr", "action": "apply",
        "pre_revert": ["abc123"], "depends_on": ["0001", "dep-002"],
        "files_changed": [],
    },
    {
        "seq": 3, "task_id": "0003", "status": "pending",
        "subject": "FEAT cpufeat", "action": "apply",
        "pre_revert": [], "depends_on": ["0001"], "files_changed": [],
    },
    {
        "seq": 4, "task_id": "0004", "status": "pending",
        "subject": "HDBSS core", "action": "apply",
        "pre_revert": [], "depends_on": ["0003"], "files_changed": [],
    },
]


class TestInsertDeps(unittest.TestCase):
    def test_dep_inserted_before_first_dependent(self):
        result = mos.insert_deps_into_merge(SAMPLE_MERGE, SAMPLE_DEPS)
        ids = [t["task_id"] for t in result]
        self.assertLess(ids.index("dep-001"), ids.index("0001"))
        self.assertLess(ids.index("dep-002"), ids.index("0002"))

    def test_no_deps_no_change(self):
        result = mos.insert_deps_into_merge(SAMPLE_MERGE, [])
        self.assertEqual(len(result), len(SAMPLE_MERGE))

    def test_dep_no_dependent_goes_front(self):
        deps = [{"task_id": "dep-003", "depends_on": [], "action": "apply"}]
        result = mos.insert_deps_into_merge(SAMPLE_MERGE, deps)
        self.assertEqual(result[0]["task_id"], "dep-003")

    def test_original_order_preserved(self):
        result = mos.insert_deps_into_merge(SAMPLE_MERGE, SAMPLE_DEPS)
        ids = [t["task_id"] for t in result]
        self.assertLess(ids.index("0001"), ids.index("0003"))
        self.assertLess(ids.index("0003"), ids.index("0004"))


class TestAssignSeq(unittest.TestCase):
    def test_reassign(self):
        order = [{"task_id": "0001", "seq": 99}, {"task_id": "0002", "seq": 88}]
        result = mos.assign_seq(order)
        self.assertEqual(result[0]["seq"], 1)
        self.assertEqual(result[1]["seq"], 2)


class TestFullSort(unittest.TestCase):
    def test_full_sort_result(self):
        data = {
            "deps_order": SAMPLE_DEPS,
            "merge_order": SAMPLE_MERGE,
        }
        result = mos.sort_merge_order(dict(data))
        merged = result["merge_order"]

        self.assertEqual(len(result["deps_order"]), 0)
        self.assertGreater(len(merged), len(SAMPLE_MERGE))

        ids = [t["task_id"] for t in merged]

        # revert group first: dep-002 (dep for 0002), 0002
        revert_group_start = 0
        self.assertIn("dep-002", ids[:2])
        self.assertIn("0002", ids[:2])

        # apply group:
        # dep-001 before 0001
        self.assertLess(ids.index("dep-001"), ids.index("0001"))
        # 0001 before 0003 before 0004 (original order)
        self.assertLess(ids.index("0001"), ids.index("0003"))
        self.assertLess(ids.index("0003"), ids.index("0004"))

        # revert group comes before apply group
        apply_start = ids.index("dep-001")
        for rid in ids[:2]:
            self.assertIn(rid, ["dep-002", "0002"])
        for aid in ids[2:]:
            self.assertIn(aid, ["dep-001", "0001", "0003", "0004"])

        # seq numbers are contiguous
        for i, t in enumerate(merged, 1):
            self.assertEqual(t["seq"], i)

    def test_no_deps_or_reverts_no_change(self):
        merge = [t for t in SAMPLE_MERGE
                 if not t.get("pre_revert") and t.get("task_id") != "0002"]
        for t in merge:
            t["depends_on"] = []
        data = {"deps_order": [], "merge_order": merge}
        result = mos.sort_merge_order(dict(data))
        self.assertEqual(len(result["merge_order"]), len(merge))
        self.assertEqual([t["task_id"] for t in result["merge_order"]],
                         ["0001", "0003", "0004"])


class TestBuildReport(unittest.TestCase):
    def test_report_not_empty(self):
        report = mos.build_report(SAMPLE_MERGE, SAMPLE_MERGE, 2)
        self.assertIn("deps", report.lower() or "deps")
        self.assertIn("0001", report)


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.input_path = os.path.join(self.tmp, "merge_tasks.json")

    def test_end_to_end(self):
        data = {
            "patchset_info": {"source": "test"},
            "global_revert_order": [],
            "deps_order": SAMPLE_DEPS,
            "merge_order": SAMPLE_MERGE,
        }
        with open(self.input_path, "w") as f:
            json.dump(data, f)

        sorted_data = mos.sort_merge_order(dict(data))
        output_path = os.path.join(self.tmp, "merge_tasks_sorted.json")
        mos.save_json(output_path, sorted_data)

        with open(output_path) as f:
            saved = json.load(f)

        self.assertEqual(len(saved["deps_order"]), 0)
        merged = saved["merge_order"]
        ids = [t["task_id"] for t in merged]

        self.assertIn("dep-001", ids)
        self.assertIn("dep-002", ids)

        # dep-002 before 0002 (revert group)
        self.assertLess(ids.index("dep-002"), ids.index("0002"))
        # dep-001 before 0001 (apply group)
        self.assertLess(ids.index("dep-001"), ids.index("0001"))
        # 0001 before 0003 before 0004 (original order)
        self.assertLess(ids.index("0001"), ids.index("0003"))
        self.assertLess(ids.index("0003"), ids.index("0004"))


if __name__ == "__main__":
    unittest.main()
