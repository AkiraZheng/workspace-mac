"""Tests for topo_sort.py — reverse dependency detection and cycle detection."""

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
        graph, indeg, sym_owner = ts.build_dependency_graph(patches)
        self.assertIn("0002", graph.get("0001", set()))
        self.assertEqual(indeg["0002"], 1)
        self.assertEqual(indeg["0001"], 0)
        self.assertEqual(sym_owner["func_a"], "0001")

    def test_no_dependency(self):
        patches = {
            "0001": {"introduced_symbols": ["a"], "referenced_symbols": []},
            "0002": {"introduced_symbols": ["b"], "referenced_symbols": []},
        }
        graph, indeg, sym_owner = ts.build_dependency_graph(patches)
        self.assertEqual(len(graph), 0)
        self.assertEqual(sym_owner["a"], "0001")
        self.assertEqual(sym_owner["b"], "0002")

    def test_self_reference_ignored(self):
        patches = {
            "0001": {"introduced_symbols": ["func_a"],
                     "referenced_symbols": ["func_a"]},
        }
        graph, indeg, sym_owner = ts.build_dependency_graph(patches)
        self.assertNotIn("0001", graph.get("0001", set()))
        self.assertEqual(indeg["0001"], 0)


class TestReverseDependencyDetection(unittest.TestCase):
    def make_patches(self, *ids, **kwargs):
        patches = {}
        for pid in ids:
            patches[pid] = {
                "introduced_symbols": kwargs.get(f"{pid}_intro", []),
                "referenced_symbols": kwargs.get(f"{pid}_ref", []),
            }
        return patches

    def test_no_dependency(self):
        """无符号依赖 → 无反向依赖"""
        patches = {
            "0001": {"introduced_symbols": ["a"], "referenced_symbols": []},
            "0002": {"introduced_symbols": ["b"], "referenced_symbols": []},
        }
        graph, indeg, _ = ts.build_dependency_graph(patches)
        reverse = ts.detect_reverse_dependencies(graph, ["0001", "0002"], patches)
        self.assertEqual(reverse, [])

    def test_forward_dependency_not_reverse(self):
        """0001 定义 func_a，0002 引用 func_a → 正向依赖，不是反向"""
        patches = {
            "0001": {"introduced_symbols": ["func_a"], "referenced_symbols": []},
            "0002": {"introduced_symbols": [], "referenced_symbols": ["func_a"]},
        }
        graph, indeg, _ = ts.build_dependency_graph(patches)
        reverse = ts.detect_reverse_dependencies(graph, ["0001", "0002"], patches)
        self.assertEqual(reverse, [])

    def test_reverse_dependency_detected(self):
        """0002 定义 func_a，0001 引用 func_a（原始顺序 0001→0002）
           → 反向依赖：0001 引用 0002 的符号"""
        patches = {
            "0001": {"introduced_symbols": [], "referenced_symbols": ["func_a"]},
            "0002": {"introduced_symbols": ["func_a"], "referenced_symbols": []},
        }
        graph, indeg, _ = ts.build_dependency_graph(patches)
        reverse = ts.detect_reverse_dependencies(graph, ["0001", "0002"], patches)
        self.assertEqual(len(reverse), 1)
        self.assertEqual(reverse[0]["depender"], "0001")
        self.assertEqual(reverse[0]["provider"], "0002")
        self.assertIn("func_a", reverse[0]["symbols"])
        self.assertEqual(reverse[0]["depender_pos"], 1)
        self.assertEqual(reverse[0]["provider_pos"], 2)

    def test_multi_symbol_reverse(self):
        """0003 定义 func_a, func_b；0001 引用 func_a, func_b → 反向依赖"""
        patches = {
            "0001": {"introduced_symbols": [], "referenced_symbols": ["func_a", "func_b"]},
            "0002": {"introduced_symbols": ["other"], "referenced_symbols": []},
            "0003": {"introduced_symbols": ["func_a", "func_b"], "referenced_symbols": []},
        }
        graph, indeg, _ = ts.build_dependency_graph(patches)
        reverse = ts.detect_reverse_dependencies(graph, ["0001", "0002", "0003"],
                                                  patches)
        self.assertEqual(len(reverse), 1)
        self.assertEqual(reverse[0]["depender"], "0001")
        self.assertEqual(reverse[0]["provider"], "0003")
        self.assertIn("func_a", reverse[0]["symbols"])
        self.assertIn("func_b", reverse[0]["symbols"])

    def test_multiple_dependers(self):
        """0003 define func_a, 0001 and 0002 both reference it → 两个反向依赖"""
        patches = {
            "0001": {"introduced_symbols": [], "referenced_symbols": ["func_a"]},
            "0002": {"introduced_symbols": [], "referenced_symbols": ["func_a"]},
            "0003": {"introduced_symbols": ["func_a"], "referenced_symbols": []},
        }
        graph, indeg, _ = ts.build_dependency_graph(patches)
        reverse = ts.detect_reverse_dependencies(graph, ["0001", "0002", "0003"],
                                                  patches)
        self.assertEqual(len(reverse), 2)
        depender_ids = {r["depender"] for r in reverse}
        self.assertEqual(depender_ids, {"0001", "0002"})


class TestCycleDetection(unittest.TestCase):
    def test_no_cycle(self):
        graph = {"0001": {"0002"}}
        indeg = {"0001": 0, "0002": 1}
        cycles = ts.detect_cycles(graph, indeg)
        self.assertEqual(cycles, [])

    def test_cycle_detected(self):
        graph = {"0001": {"0002"}, "0002": {"0001"}}
        indeg = {"0001": 1, "0002": 1}
        cycles = ts.detect_cycles(graph, indeg)
        self.assertEqual(set(cycles), {"0001", "0002"})

    def test_self_cycle(self):
        graph = {"0001": {"0001"}}
        indeg = {"0001": 1}
        cycles = ts.detect_cycles(graph, indeg)
        self.assertEqual(cycles, ["0001"])


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
