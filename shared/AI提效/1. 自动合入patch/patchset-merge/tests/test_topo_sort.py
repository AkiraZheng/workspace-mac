"""Tests for topo_sort.py — stable topological sort."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import topo_sort as ts


class TestBuildGraph(unittest.TestCase):
    def test_simple_chain(self):
        patches = {
            "0001": {"introduced_symbols": ["func_a"], "referenced_symbols": []},
            "0002": {"introduced_symbols": [], "referenced_symbols": ["func_a"]},
        }
        graph, indeg = ts.build_dependency_graph(patches)
        self.assertIn("0002", graph.get("0001", set()))
        self.assertEqual(indeg["0002"], 1)
        self.assertEqual(indeg["0001"], 0)

    def test_no_dependency(self):
        patches = {
            "0001": {"introduced_symbols": ["a"], "referenced_symbols": []},
            "0002": {"introduced_symbols": ["b"], "referenced_symbols": []},
        }
        graph, indeg = ts.build_dependency_graph(patches)
        self.assertEqual(len(graph), 0)

    def test_self_reference_ignored(self):
        patches = {
            "0001": {"introduced_symbols": ["func_a"], "referenced_symbols": ["func_a"]},
        }
        graph, indeg = ts.build_dependency_graph(patches)
        self.assertNotIn("0001", graph.get("0001", set()))
        self.assertEqual(indeg["0001"], 0)


class TestStableKahnSort(unittest.TestCase):
    def test_no_dependency_keeps_original_order(self):
        """无依赖 → 保持原始顺序"""
        graph = {}
        indeg = {"0001": 0, "0002": 0, "0003": 0}
        orig = ["0001", "0002", "0003"]
        order, cycles, reordered = ts.stable_kahn_sort(graph, indeg, orig)
        self.assertEqual(order, ["0001", "0002", "0003"])
        self.assertEqual(cycles, [])
        self.assertEqual(reordered, [])

    def test_reverse_original_order_still_stable(self):
        """原始顺序反序但无依赖 → 保持稳定输出（按原始顺序）"""
        graph = {}
        indeg = {"0003": 0, "0002": 0, "0001": 0}
        orig = ["0003", "0002", "0001"]
        order, cycles, reordered = ts.stable_kahn_sort(graph, indeg, orig)
        self.assertEqual(order, ["0003", "0002", "0001"])

    def test_forward_dep_preserves_order(self):
        """0001→0003 + 0002→0003, 原始顺序 0001<0002<0003 → 保持"""
        graph = {"0001": {"0003"}, "0002": {"0003"}}
        indeg = {"0001": 0, "0002": 0, "0003": 2}
        orig = ["0001", "0002", "0003"]
        order, cycles, reordered = ts.stable_kahn_sort(graph, indeg, orig)
        self.assertEqual(len(order), 3)
        self.assertIn(order[2], ["0003", "0003"])  # 0003 is last (highest indeg)
        self.assertEqual(set(order[:2]), {"0001", "0002"})
        # 0001, 0002 in original order (1 < 2)
        self.assertEqual(order[0], "0001")
        self.assertEqual(order[1], "0002")
        self.assertEqual(order[2], "0003")

    def test_reverse_dep_forces_reorder(self):
        """0002 introduces func_a, 0001 references func_a
           → 0002 must come before 0001 (breaks original order)"""
        graph = {"0002": {"0001"}}
        indeg = {"0001": 1, "0002": 0}
        orig = ["0001", "0002"]
        order, cycles, reordered = ts.stable_kahn_sort(graph, indeg, orig)
        self.assertEqual(order, ["0002", "0001"])
        self.assertEqual(cycles, [])
        self.assertIn("0001", reordered)
        self.assertIn("0002", reordered)

    def test_chain_keeps_order(self):
        """0001→0002→0003 (forward chain) → 顺序不变"""
        graph = {"0001": {"0002"}, "0002": {"0003"}}
        indeg = {"0001": 0, "0002": 1, "0003": 1}
        orig = ["0001", "0002", "0003"]
        order, cycles, reordered = ts.stable_kahn_sort(graph, indeg, orig)
        self.assertEqual(order, ["0001", "0002", "0003"])

    def test_cycle_detection(self):
        graph = {"0001": {"0002"}, "0002": {"0001"}}
        indeg = {"0001": 1, "0002": 1}
        orig = ["0001", "0002"]
        order, cycles, reordered = ts.stable_kahn_sort(graph, indeg, orig)
        self.assertEqual(set(cycles), {"0001", "0002"})

    def test_dep_insert_does_not_shift_unrelated(self):
        """0003 需要 0001 但当原始顺序是 0001→0002→0003，无需调整"""
        graph = {"0001": {"0003"}}
        indeg = {"0001": 0, "0002": 0, "0003": 1}
        orig = ["0001", "0002", "0003"]
        order, cycles, reordered = ts.stable_kahn_sort(graph, indeg, orig)
        self.assertEqual(order, ["0001", "0002", "0003"])

    def test_irrelevant_noises_not_reordered(self):
        """无关 patch 不产生位置变动"""
        graph = {"0001": {"0005"}, "0003": {"0005"}}
        indeg = {"0001": 0, "0002": 0, "0003": 0, "0004": 0, "0005": 2}
        orig = ["0001", "0002", "0003", "0004", "0005"]
        order, cycles, reordered = ts.stable_kahn_sort(graph, indeg, orig)
        self.assertEqual(order[:4], ["0001", "0002", "0003", "0004"])
        self.assertEqual(order[4], "0005")
        self.assertEqual(cycles, [])
        # 无 patch 被移动（因为依赖方向与原始顺序一致）
        self.assertEqual(reordered, [])

    def test_partial_reorder_only_affected(self):
        """只有反向依赖的 patch 对才调整"""
        graph = {"0003": {"0001"}}
        indeg = {"0001": 1, "0002": 0, "0003": 0, "0004": 0}
        orig = ["0001", "0002", "0003", "0004"]
        order, cycles, reordered = ts.stable_kahn_sort(graph, indeg, orig)
        # 0003 → 0001, 所以 0003 必须在 0001 之前
        # 0002, 0004 应保持在原位附近
        pos_0002 = order.index("0002")
        pos_0004 = order.index("0004")
        # 0002 should be before 0004 (original order)
        self.assertLess(pos_0002, pos_0004)
        # 0003 should be before 0001
        self.assertLess(order.index("0003"), order.index("0001"))

    def test_unknown_pid_gets_lowest_priority(self):
        """不在 original_order 中的 pid 排在最后"""
        graph = {}
        indeg = {"0001": 0, "dep-001": 0}
        orig = ["0001"]
        order, cycles, reordered = ts.stable_kahn_sort(graph, indeg, orig)
        self.assertEqual(order[0], "0001")
        self.assertEqual(order[1], "dep-001")


class TestReorderReport(unittest.TestCase):
    def test_no_reorder(self):
        report = ts.build_reorder_report(["0001", "0002"], ["0001", "0002"])
        self.assertIn("原始顺序不变", report)

    def test_reorder_listed(self):
        report = ts.build_reorder_report(["0001", "0002"], ["0002", "0001"])
        self.assertIn("[调整]", report)
        self.assertIn("0001", report)
        self.assertIn("0002", report)

    def test_inserted_pid(self):
        report = ts.build_reorder_report(["0001"], ["dep-001", "0001"])
        self.assertIn("[新增]", report)
        self.assertIn("dep-001", report)


class TestCycleReport(unittest.TestCase):
    def test_build_cycle_report(self):
        graph = {"0001": {"0002"}, "0002": {"0001"}}
        indeg = {"0001": 1, "0002": 1}
        report = ts.build_cycle_report(graph, indeg)
        self.assertIn("0001", report)
        self.assertIn("0002", report["0001"])
        self.assertIn("0001", report["0002"])


if __name__ == "__main__":
    unittest.main()
