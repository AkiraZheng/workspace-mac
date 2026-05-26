#!/usr/bin/env python3
"""Stable topological sort for patchset merge order.

原则:
  1. 原始 patch 相对顺序不变（无依赖冲突时）
  2. 只有 B 引用 A 的符号 AND 原始顺序 A > B 时才调整
  3. deps_order（上游依赖）和 revert 的插入由 Phase 1.5 主 Agent 处理

算法:
  稳定 Kahn's 排序 —— 当多个节点 in_degree=0 时，按原始顺序出队。
  这样只有真正存在反向依赖时才打破原始顺序。

输入:
  {
    "0001": {"introduced_symbols": ["func_a"], "referenced_symbols": []},
    "0002": {"introduced_symbols": [], "referenced_symbols": ["func_a"]},
    ...
  }
  或从 stdin 读 JSON，或 -f <file>

  可选: 顶层 key "original_order": ["0001","0002","0003"]
    未提供时从 patches dict 的 key 顺序推断（Python 3.7+ 保序）
"""

from __future__ import annotations

import heapq
import json
import sys
from collections import defaultdict


def build_dependency_graph(patches: dict) -> tuple[dict, dict]:
    """Build adjacency list and in-degree table.

    Returns:
      graph:      {pid: set of pids that depend on pid}
      in_degree:  {pid: number of incoming edges}
    """
    symbol_owner: dict[str, str] = {}
    for pid, info in patches.items():
        for sym in info.get("introduced_symbols", []):
            symbol_owner[sym] = pid

    graph: dict[str, set[str]] = {}
    in_degree: dict[str, int] = {pid: 0 for pid in patches}

    for pid, info in patches.items():
        for sym in info.get("referenced_symbols", []):
            owner = symbol_owner.get(sym)
            if owner is None or owner == pid:
                continue
            if owner not in graph:
                graph[owner] = set()
            if pid not in graph[owner]:
                graph[owner].add(pid)
                in_degree[pid] += 1

    return graph, in_degree


def stable_kahn_sort(graph: dict, in_degree: dict,
                     original_order: list[str]) -> tuple[list[str], list[str]]:
    """Stable Kahn's: when multiple nodes ready, pick earliest in original order.

    Returns:
      order:        sorted list of patch IDs (stable)
      cycles:       list of patch IDs in cycles (empty if DAG)
      reordered:    list of patch IDs that were moved from original position
    """
    indeg = dict(in_degree)
    order_map = {pid: i for i, pid in enumerate(original_order)}

    pq: list[tuple[int, str]] = []
    for pid, d in indeg.items():
        if d == 0:
            idx = order_map.get(pid, len(original_order) + 999)
            heapq.heappush(pq, (idx, pid))

    order: list[str] = []
    while pq:
        _, pid = heapq.heappop(pq)
        order.append(pid)
        for neighbor in sorted(graph.get(pid, set())):
            indeg[neighbor] -= 1
            if indeg[neighbor] == 0:
                idx = order_map.get(neighbor, len(original_order) + 999)
                heapq.heappush(pq, (idx, neighbor))

    cycles = sorted(pid for pid, d in indeg.items() if d > 0)

    reordered = []
    for i, pid in enumerate(order):
        if pid in order_map and i != order_map[pid]:
            reordered.append(pid)

    return order, cycles, reordered


def build_reorder_report(original_order, sorted_order) -> str:
    """Explain which patches changed position and why."""
    lines = []
    orig_pos = {pid: i for i, pid in enumerate(original_order)}

    for i, pid in enumerate(sorted_order):
        if pid not in orig_pos:
            lines.append(f"  [新增] {pid} (不在原始 patchset 中)")
        elif i != orig_pos[pid]:
            direction = "后移" if i > orig_pos[pid] else "前移"
            delta = abs(i - orig_pos[pid])
            lines.append(
                f"  [调整] {pid}: 原位置 #{orig_pos[pid]+1} → 新位置 #{i+1}"
                f" ({direction} {delta} 位)"
            )

    return "\n".join(lines) if lines else "  原始顺序不变"


def build_cycle_report(graph: dict, in_degree: dict) -> dict:
    remaining = {pid for pid, d in in_degree.items() if d > 0}
    cycle_graph: dict[str, list[str]] = {}
    for pid in sorted(remaining):
        deps = sorted(d for d in graph.get(pid, set()) if d in remaining)
        if deps:
            cycle_graph[pid] = deps
    return cycle_graph


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    if len(sys.argv) >= 2:
        with open(sys.argv[1]) as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    patches = {k: v for k, v in data.items()
               if k not in ("original_order",)}
    original_order = data.get("original_order", list(patches.keys()))

    graph, in_degree = build_dependency_graph(patches)
    order, cycles, reordered = stable_kahn_sort(graph, in_degree, original_order)

    if cycles:
        report = {
            "error": "发现循环依赖",
            "环中节点": cycles,
            "环详情": build_cycle_report(graph, in_degree),
            "提示": (
                "以上 patch 存在循环引用，符号依赖互为引用。"
                "建议检查 patch 内容，确定实际合入顺序。"
            ),
        }
        json.dump(report, sys.stderr, ensure_ascii=False, indent=2)
        sys.stderr.write("\n")
        sys.exit(1)

    deps = {pid: sorted(d) for pid, d in graph.items() if d}

    reorder_detail = build_reorder_report(original_order, order)

    result = {
        "合入顺序": order,
        "原始顺序": original_order,
        "顺序说明": "原始 patch 相对顺序不变（无反向依赖时）",
        "调整清单": reordered if reordered else [],
    }
    if reorder_detail.strip():
        result["调整详情"] = reorder_detail
    if deps:
        result["依赖关系"] = deps
    else:
        result["说明"] = "所有 patch 独立，无符号依赖"

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
