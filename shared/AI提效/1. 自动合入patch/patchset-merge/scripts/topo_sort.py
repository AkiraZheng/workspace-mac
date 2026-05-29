#!/usr/bin/env python3
"""反向依赖检测与循环依赖检测。

原则:
  1. 原始 patch 相对顺序不变 —— 不做任何自动调整
  2. 检测反向依赖（前面的 patch 引用后面的 patch 符号）→ 报告给用户
  3. 检测循环依赖 → 暂停等用户决策
  4. 顺序调整由 Phase 1.5 用户交互决定（保持原始顺序 vs 调整顺序）

输入:
  {
    "0001": {"introduced_symbols": ["func_a"], "referenced_symbols": []},
    "0002": {"introduced_symbols": [], "referenced_symbols": ["func_a"]},
    ...
  }
  或从 stdin 读 JSON

  可选: 顶层 key "original_order": ["0001","0002","0003"]
    未提供时从 patches dict 的 key 顺序推断（Python 3.7+ 保序）
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict


def build_dependency_graph(patches: dict) -> tuple[dict, dict]:
    """Build adjacency list and in-degree table.

    Returns:
      graph:      {pid: set of pids that depend on pid}
      in_degree:  {pid: number of incoming edges}
      symbol_owner: {symbol: pid}
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

    return graph, in_degree, symbol_owner


def detect_reverse_dependencies(graph: dict, original_order: list[str],
                                 patches: dict) -> list[dict]:
    """Find reverse dependencies: earlier patches that reference later patches' symbols.

    Returns:
      list of {depender, provider, symbols, depender_pos, provider_pos}
    """
    order_map = {pid: i for i, pid in enumerate(original_order)}

    # Build symbol → owner mapping
    symbol_owner: dict[str, str] = {}
    for pid, info in patches.items():
        for sym in info.get("introduced_symbols", []):
            symbol_owner[sym] = pid

    reverse_deps: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    for pid, info in patches.items():
        depender_pos = order_map.get(pid, 9999)
        for sym in info.get("referenced_symbols", []):
            owner = symbol_owner.get(sym)
            if owner is None or owner == pid:
                continue

            owner_pos = order_map.get(owner, 9999)
            # Reverse: depender (引用者) comes before provider (定义者)
            if depender_pos < owner_pos:
                pair = (pid, owner)
                if pair not in seen_pairs:
                    seen_pairs.add(pair)

                    # Collect all symbols tied to this pair
                    pair_symbols = []
                    for s in info.get("referenced_symbols", []):
                        s_owner = symbol_owner.get(s)
                        if s_owner == owner:
                            pair_symbols.append(s)

                    reverse_deps.append({
                        "depender": pid,
                        "provider": owner,
                        "symbols": pair_symbols,
                        "depender_pos": depender_pos + 1,
                        "provider_pos": owner_pos + 1,
                    })

    return reverse_deps


def detect_cycles(graph: dict, in_degree: dict) -> list[str]:
    """Detect cycles: simulate Kahn's algorithm and return nodes left with indeg > 0.

    Nodes remaining after processing all reachable zero-indeg nodes are part of a cycle.
    """
    indeg = dict(in_degree)
    # Collect all nodes with indeg=0 as starting points
    queue = [pid for pid, d in indeg.items() if d == 0]

    # Process reachable nodes
    for pid in queue:
        for neighbor in graph.get(pid, set()):
            indeg[neighbor] -= 1
            if indeg[neighbor] == 0:
                queue.append(neighbor)

    # Remaining nodes with indeg > 0 are in cycles
    return sorted(pid for pid, d in indeg.items() if d > 0)


def build_cycle_report(graph: dict, in_degree: dict) -> dict:
    """Build cycle detail report."""
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

    graph, in_degree, symbol_owner = build_dependency_graph(patches)

    # 1. Detect cycles (must handle first, fatal)
    cycles = detect_cycles(graph, in_degree)
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

    # 2. Detect reverse dependencies
    reverse_deps = detect_reverse_dependencies(graph, original_order, patches)

    deps = {pid: sorted(d) for pid, d in graph.items() if d}

    result = {
        "合入顺序": original_order,
        "原始顺序": original_order,
        "顺序说明": "原始 patch 顺序不变，反向依赖通过编译验证点机制解决",
    }

    if reverse_deps:
        result["反向依赖"] = reverse_deps
        result["说明"] = (
            "发现反向依赖（前面的 patch 引用后面 patch 的符号），"
            "建议在被依赖者加编译验证点，依赖者不加验证点"
        )
    else:
        result["说明"] = "所有引用均为正向依赖（定义在前，引用在后），无需特殊处理"

    if deps:
        result["依赖关系"] = deps

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
