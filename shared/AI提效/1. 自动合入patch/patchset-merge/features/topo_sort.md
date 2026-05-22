# scripts/topo_sort.py 实现计划

> **Goal:** 确定性拓扑排序脚本：根据 patch 间的符号依赖计算合入顺序，检测循环依赖。

**Architecture:** 读取 JSON → Kahn 算法 → 输出合并顺序。纯 Python，无外部依赖。

**Tech Stack:** Python 3（stdlib only）

---

## 文件

| 文件 | 动作 |
|------|------|
| `scripts/topo_sort.py` | 新建 |
| `tests/test_topo_sort.py` | 新建 |
| `references/output-templates.md` | 修改：屏幕输出格式 + 字段说明 加两行 |
| `SKILL.md` | 修改：Phase 1.5 步骤 2 引用脚本 |

---

## Task 1: tests/test_topo_sort.py — 写测试

```python
"""Tests for topo_sort.py - symbol dependency topological sort."""

import json
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import topo_sort as ts


class TestBuildGraph(unittest.TestCase):
    def test_simple_chain(self):
        """0002 references func from 0001 → 0001 before 0002."""
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
        """0001→0003→0002."""
        patches = {
            "0001": {"introduced_symbols": ["a"], "referenced_symbols": []},
            "0002": {"introduced_symbols": [], "referenced_symbols": ["b"]},
            "0003": {"introduced_symbols": ["b"], "referenced_symbols": ["a"]},
        }
        graph, indeg = ts.build_dependency_graph(patches)
        self.assertIn("0003", graph["0001"])    # 0003 refs a→edge 0001→0003
        self.assertIn("0002", graph["0003"])    # 0002 refs b→edge 0003→0002
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
        self.assertEqual(order[0:2], ["0001", "0002"])
        self.assertEqual(order[2], "0003")

    def test_cycle_detection(self):
        graph = {"0001": {"0002"}, "0002": {"0001"}}
        indeg = {"0001": 1, "0002": 1}
        order, cycles = ts.kahn_sort(graph, indeg)
        self.assertEqual(cycles, ["0001", "0002"])

    def test_all_zero_degree(self):
        """All nodes have indeg 0 → any order is valid."""
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
```

## Task 2: scripts/topo_sort.py — 实现

核心函数（完整代码见上述设计）：

- `build_dependency_graph(patches)` — 遍历 `introduced_symbols` 和 `referenced_symbols`，构建邻接表和入度
- `kahn_sort(graph, in_degree)` — BFS 拓扑排序，返回顺序 + 环中节点
- `build_cycle_report(graph, in_degree)` — 提取环详情
- `main()` — CLI 入口，支持文件路径或 stdin

## Task 3: 联动修改

### output-templates.md — 屏幕输出增加符号字段

在分析 Agent 屏幕输出格式末尾加：

```
引入符号=func_a,func_b,MACRO_X
引用符号=hyp_alloc_private_va_range,kvm_pgtable_walk
```

### SKILL.md — Phase 1.5 步骤 2 改为引用脚本

```
步骤 2: 依赖图 + 拓扑排序
→ 调用 scripts/topo_sort.py < /tmp/patches/analysis_cache.json
→ 若有环：在屏幕上输出环详情，由用户裁定处理方式
→ 输出 merge_order
```

---

## 验证

```bash
python3 -m pytest tests/test_topo_sort.py -v
```

预期：全部 PASS（~10 tests）
