"""Tests for topo_sort.py - symbol dependency topological sort."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import topo_sort as ts


class TestBuildGraph(unittest.TestCase):
    def test_simple_chain(self):
        """0002 references func from 0001 -> 0001 before 0002."""
        patches = {
            "0001": {
                "introduced_symbols": ["func_a"],
                "referenced_symbols": [],
            },
            "0002": {
                "introduced_symbols": [],
                "referenced_symbols": ["func_a"],
            },
        }
        graph, indeg = ts.build_dependency_graph(patches)
        self.assertIn("0002", graph.get("0001", set()))
        self.assertEqual(indeg["0002"], 1)
        self.assertEqual(indeg["0001"], 0)

    def test_no_dependency(self):
        """Independent patches have no edges."""
        patches = {
            "0001": {"introduced_symbols": ["a"], "referenced_symbols": []},
            "0002": {"introduced_symbols": ["b"], "referenced_symbols": []},
        }
        graph, indeg = ts.build_dependency_graph(patches)
        self.assertEqual(len(graph), 0)

    def test_self_reference_ignored(self):
        """Patch referencing its own symbol should not create edge."""
        patches = {
            "0001": {
                "introduced_symbols": ["func_a"],
                "referenced_symbols": ["func_a"],
            },
        }
        graph, indeg = ts.build_dependency_graph(patches)
        self.assertNotIn("0001", graph.get("0001", set()))
        self.assertEqual(indeg["0001"], 0)

    def test_transitive_chain(self):
        """0001->0003->0002."""
        patches = {
            "0001": {"introduced_symbols": ["a"], "referenced_symbols": []},
            "0002": {"introduced_symbols": [], "referenced_symbols": ["b"]},
            "0003": {"introduced_symbols": ["b"], "referenced_symbols": ["a"]},
        }
        graph, indeg = ts.build_dependency_graph(patches)
        self.assertIn("0003", graph["0001"])
        self.assertIn("0002", graph["0003"])
        self.assertEqual(indeg["0003"], 1)
        self.assertEqual(indeg["0002"], 1)
        self.assertEqual(indeg["0001"], 0)


class TestKahnSort(unittest.TestCase):
    def test_linear_chain(self):
        graph = {"0001": {"0002"}, "0002": {"0003"}}
        indeg = {"0001": 0, "0002": 1, "0003": 1}
        order, cycles = ts.kahn_sort(graph, indeg)
        self.assertEqual(order, ["0001", "0002", "0003"])
        self.assertEqual(cycles, [])

    def test_parallel_independent(self):
        graph = {"0001": {"0003"}, "0002": {"0003"}}
        indeg = {"0001": 0, "0002": 0, "0003": 2}
        order, cycles = ts.kahn_sort(graph, indeg)
        self.assertEqual(len(order), 3)
        self.assertEqual(set(order[:2]), {"0001", "0002"})
        self.assertEqual(order[2], "0003")

    def test_cycle_detection(self):
        graph = {"0001": {"0002"}, "0002": {"0001"}}
        indeg = {"0001": 1, "0002": 1}
        order, cycles = ts.kahn_sort(graph, indeg)
        self.assertEqual(set(cycles), {"0001", "0002"})

    def test_all_zero_degree(self):
        """All nodes have indeg 0 -> any order is valid."""
        graph = {}
        indeg = {"0001": 0, "0002": 0, "0003": 0}
        order, cycles = ts.kahn_sort(graph, indeg)
        self.assertEqual(len(order), 3)
        self.assertEqual(cycles, [])


class TestCycleReport(unittest.TestCase):
    def test_build_cycle_report(self):
        graph = {"0001": {"0002"}, "0002": {"0001"}}
        indeg = {"0001": 1, "0002": 1}
        report = ts.build_cycle_report(graph, indeg)
        self.assertIn("0001", report)
        self.assertIn("0002", report["0001"])
        self.assertIn("0001", report["0002"])
