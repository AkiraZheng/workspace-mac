#!/usr/bin/env python3
"""Topological sort for patchset merge order based on symbol dependencies.

Each patch declares:
  introduced_symbols: symbols this patch adds/modifies
  referenced_symbols: symbols this patch calls/uses

If patch B references a symbol introduced by patch A, then A must merge before B.
Kahn's algorithm detects cycles (circular symbol dependencies).
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict, deque


def build_dependency_graph(patches: dict) -> tuple[dict, dict]:
    """Build adjacency list and in-degree table from patch symbol info.

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
            if owner is None:
                continue
            if owner == pid:
                continue          # self-reference, skip
            if owner not in graph:
                graph[owner] = set()
            if pid not in graph[owner]:
                graph[owner].add(pid)
                in_degree[pid] += 1

    return graph, in_degree


def kahn_sort(graph: dict, in_degree: dict) -> tuple[list[str], list[str]]:
    """Kahn's algorithm: BFS topological sort.

    Returns:
      order:  sorted list of patch IDs
      cycles: list of patch IDs in cycles (empty if DAG)
    """
    indeg = dict(in_degree)
    queue: deque[str] = deque(
        pid for pid, d in indeg.items() if d == 0
    )
    order: list[str] = []

    while queue:
        pid = queue.popleft()
        order.append(pid)
        for neighbor in sorted(graph.get(pid, set())):
            indeg[neighbor] -= 1
            if indeg[neighbor] == 0:
                queue.append(neighbor)

    cycles = sorted(pid for pid, d in indeg.items() if d > 0)
    return order, cycles


def build_cycle_report(graph: dict, in_degree: dict) -> dict:
    """Extract cycle details for user diagnosis."""
    remaining = {pid for pid, d in in_degree.items() if d > 0}
    cycle_graph: dict[str, list[str]] = {}
    for pid in sorted(remaining):
        deps = sorted(d for d in graph.get(pid, set()) if d in remaining)
        if deps:
            cycle_graph[pid] = deps
    return cycle_graph


def main() -> None:
    if len(sys.argv) < 2:
        data = json.load(sys.stdin)
    else:
        with open(sys.argv[1]) as f:
            data = json.load(f)

    graph, in_degree = build_dependency_graph(data)
    order, cycles = kahn_sort(graph, in_degree)

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

    deps = {
        pid: sorted(d) for pid, d in graph.items() if d
    }
    result = {
        "合入顺序": order,
        "依赖关系": deps if deps else None,
    }
    if deps is None:
        result["说明"] = "所有 patch 独立，无符号依赖"
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
