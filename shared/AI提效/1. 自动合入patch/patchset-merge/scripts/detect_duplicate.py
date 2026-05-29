#!/usr/bin/env python3
"""
detect_duplicate.py — 重复/等效 patch 检测 + PR 聚合 + revert 决策

功能:
  1. 候选 commit 搜索（subject/symbol/文件区域）
  2. diff 相似度计算（patch add lines vs commit add lines）
  3. PR 聚合（解析 commit message Link 标签）
  4. PR 覆盖率计算 + revert 决策

判定规则:
  单 commit 相似度 >= 80%  → 高匹配（计入 PR 覆盖率）
  单 commit 相似度 50-79% → 中匹配（不计入，标记可能冲突）
  单 commit 相似度 < 50%  → 低匹配（忽略）

  PR 覆盖率 >= 75%  → revert 整个 PR
  PR 覆盖率 50-74% → revert 匹配的 commits（逐个）
  PR 覆盖率 < 50%  → 不自动 revert（合入时冲突解决）

重新策略:
  - 检测到重复/等效 → 写入 pre_revert，不写 action: skip
  - 必须合入的 patch 绝对不允许跳过

用法:
  python3 detect_duplicate.py \
    --patch-dir /tmp/patches/ \
    --repo-path $KERNEL_REPO_PATH \
    --output duplicate_analysis.json

退出码:
  0 = 全部成功
  1 = 部分失败
  2 = 参数错误
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


# ── Thresholds ──

SIMILARITY_HIGH = 80   # 高于此值才算高匹配
SIMILARITY_MEDIUM = 50  # 高于此值为中匹配（标记可能冲突）
PR_COVERAGE_WHOLE = 75  # PR 覆盖率 >= 此值→revert 整个 PR


def run_git(repo_path: str, *args) -> str:
    result = subprocess.run(
        ["git", "-C", repo_path] + list(args),
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def extract_add_lines_from_patch(patch_path: str) -> set[str]:
    lines = set()
    try:
        with open(patch_path) as f:
            for line in f:
                if line.startswith("+") and not line.startswith("+++"):
                    stripped = line[1:].strip()
                    if stripped:
                        lines.add(stripped)
    except (FileNotFoundError, IOError):
        pass
    return lines


def extract_add_lines_from_commit(repo_path: str, commit_hash: str,
                                  file_path: str = "") -> set[str]:
    cmd = ["show", commit_hash]
    if file_path:
        cmd.extend(["--", file_path])
    text = run_git(repo_path, *cmd)
    lines = set()
    for line in text.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            stripped = line[1:].strip()
            if stripped:
                lines.add(stripped)
    return lines


def compute_similarity(patch_add_lines: set[str],
                       commit_add_lines: set[str]) -> float:
    if not patch_add_lines:
        return 0.0
    intersection = patch_add_lines & commit_add_lines
    return len(intersection) / len(patch_add_lines) * 100


def compute_symbol_similarity(patch_symbols: set[str],
                              commit_symbols: set[str]) -> float:
    if not patch_symbols:
        return 0.0
    intersection = patch_symbols & commit_symbols
    return len(intersection) / len(patch_symbols) * 100


def compute_combined_similarity(diff_sim: float, symbol_sim: float) -> float:
    """综合相似度：取 diff 和 symbol 中较高的（任一高匹配即可）。
    
    语义：
    - diff >= 80% → 代码几乎相同（high match）
    - symbol >= 80% → 相同功能、不同版本实现（high match，需 revert v1）
    - 都不高 → 取两者均值作为参考
    """
    if diff_sim >= SIMILARITY_HIGH or symbol_sim >= SIMILARITY_HIGH:
        return max(diff_sim, symbol_sim)
    return (diff_sim + symbol_sim) / 2


def extract_symbols_from_diff(diff: str) -> set[str]:
    symbols = set()
    for line in diff.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            content = line[1:].strip()
            m = re.match(r'(?:static\s+|inline\s+)?(?:\w+\s+)*\**(\w+)\s*\(', content)
            if m:
                symbols.add(m.group(1))
                continue
            m = re.match(r'#define\s+(\w+)', content)
            if m:
                symbols.add(m.group(1))
                continue
            m = re.match(r'(?:struct|enum|union)\s+(\w+)', content)
            if m:
                symbols.add(m.group(1))
                continue
            m = re.match(r'typedef\s+(?:\S+\s+)+(\w+)', content)
            if m:
                symbols.add(m.group(1))
    return symbols


def search_candidates(repo_path: str, subject: str,
                      files_changed: list[str],
                      symbols: set[str]) -> list[str]:
    candidates = set()

    # 方法 1: subject 关键词匹配
    keywords = subject.strip().replace(":", " ").replace("/", " ")
    keyword_list = [k for k in keywords.split() if len(k) >= 4]
    for kw in keyword_list[:5]:
        result = run_git(
            repo_path, "log", "--oneline", "--format=%H",
            f"--grep={kw}",
        )
        for line in result.split("\n"):
            if line:
                candidates.add(line.strip())

    # 方法 2: 搜索引入的符号（仅当前分支）
    for sym in sorted(symbols)[:10]:
        result = run_git(
            repo_path, "log", "--oneline", "--format=%H",
            "-n", "3", f"-S={sym}",
        )
        for line in result.split("\n"):
            if line:
                candidates.add(line.strip())

    # 方法 3: 涉改文件的最近修改
    for f in files_changed[:5]:
        result = run_git(
            repo_path, "log", "--oneline", "--format=%H",
            "-1", "--", f,
        )
        for line in result.split("\n"):
            if line:
                candidates.add(line.strip())

    if not candidates:
        return []

    return list(candidates)[:20]


def resolve_pr_affiliation(repo_path: str, commit_hash: str) -> dict | None:
    body = run_git(repo_path, "log", "--format=%b", "-1", commit_hash)
    if not body:
        return None

    pr_pattern = re.compile(
        r'(?:Link|Pull|pull|PR|pr).*?(?:github\.com/\S+/(?:pull|pull-requests)/(\d+)'
        r'|lore\.kernel\.org/\S+/(\d+)(?:-\S+)?@)',
        re.IGNORECASE
    )

    for line in body.split("\n"):
        m = pr_pattern.search(line)
        if m:
            pr_num = m.group(1) or m.group(2) or ""
            if pr_num:
                return {"pr_id": f"PR #{pr_num}", "source": "commit_msg_link"}
            return {"pr_id": "独立 commit", "source": "lore_link"}

    return None


def get_pr_all_commits(repo_path: str,
                       known_commits: list[str]) -> list[str]:
    """通过 ancestry-path 获取 PR 全部 commits（按时间排序，最早→最新）."""
    if len(known_commits) < 2:
        return known_commits

    sorted_commits = sort_commits_by_time(repo_path, known_commits)
    first = sorted_commits[0]
    last = sorted_commits[-1]

    result = run_git(repo_path, "log", "--ancestry-path",
                     "--format=%H", f"{first}^..{last}")
    all_commits = [c.strip() for c in result.split("\n") if c.strip()]

    if not all_commits:
        return sorted_commits

    return sort_commits_by_time(repo_path, all_commits)


def sort_commits_by_time(repo_path: str, commits: list[str]) -> list[str]:
    """按 commit 时间排序（最早→最新）."""
    times = {}
    for c in commits:
        ts = run_git(repo_path, "log", "--format=%ct", "-1", c)
        times[c] = int(ts) if ts.lstrip("-").isdigit() else 0
    return sorted(commits, key=lambda c: times.get(c, 0))


def find_dependent_commits(repo_path: str,
                           commit_hash: str) -> list[str]:
    """查找 commit 之后可能依赖它的 commits."""
    result = run_git(repo_path, "log", "--ancestry-path",
                     "--format=%H", f"{commit_hash}..HEAD")
    commits = [c.strip() for c in result.split("\n") if c.strip()]
    return commits[:20]  # 最多 20 个


def group_candidates_by_pr(candidates: dict, repo_path: str = "") -> dict:
    """Group commit candidates by PR affiliation.

    Input: {commit_hash: {pr_id, similarity, matched_patch, ...}}
    Output: {pr_id: {commits: dict, matched_patches: [...], pr_info: ...}}
    """
    pr_groups = defaultdict(lambda: {
        "commits": {},
        "matched_patches": [],
        "pr_info": None,
    })

    commit_pr_map = {}

    for commit_hash, info in candidates.items():
        pr_info = info.get("pr_info")
        if pr_info and pr_info.get("pr_id") and pr_info["pr_id"] != "独立 commit":
            pr_id = pr_info["pr_id"]
            pr_groups[pr_id]["pr_info"] = pr_info
            pr_groups[pr_id]["commits"][commit_hash] = {
                "subject": info.get("commit_subject", ""),
                "similarity": info.get("similarity", 0),
                "matched": info.get("similarity", 0) >= SIMILARITY_HIGH,
            }
            commit_pr_map[commit_hash] = pr_id
        else:
            pr_groups[commit_hash]["pr_info"] = {"pr_id": "独立 commit"}
            pr_groups[commit_hash]["commits"][commit_hash] = {
                "subject": info.get("commit_subject", ""),
                "similarity": info.get("similarity", 0),
                "matched": info.get("similarity", 0) >= SIMILARITY_HIGH,
            }
            commit_pr_map[commit_hash] = commit_hash

    # 获取 PR 完整 commits 列表
    for pr_id, group in pr_groups.items():
        if group["pr_info"].get("pr_id") != "独立 commit" and repo_path:
            all_commits = get_pr_all_commits(
                repo_path, list(group["commits"].keys())
            )
            for c in all_commits:
                if c not in group["commits"]:
                    subject = run_git(repo_path, "log",
                                      "--format=%s", "-1", c)
                    group["commits"][c] = {
                        "subject": subject,
                        "similarity": 0,
                        "matched": False,
                    }

    for commit_hash, info in candidates.items():
        pr_id = commit_pr_map.get(commit_hash, commit_hash)
        pr_groups[pr_id]["matched_patches"].append(info)

    return dict(pr_groups)


def calculate_pr_coverage(pr_group: dict) -> dict:
    matched_patches = pr_group["matched_patches"]
    commits_dict = pr_group.get("commits", {})
    total_commits_in_pr = len(commits_dict)

    high_match_count = sum(
        1 for c in commits_dict.values()
        if c.get("matched", False)
    )

    coverage = (high_match_count / total_commits_in_pr * 100
                if total_commits_in_pr > 0 else 0)

    revert_commits = [
        ch for ch, cinfo in commits_dict.items()
        if cinfo.get("matched", False)
    ]

    if total_commits_in_pr == 1 and high_match_count == 1:
        strategy = "direct_revert"
        urgency = "必须"
        revert_targets = list(commits_dict.keys())
    elif coverage >= PR_COVERAGE_WHOLE:
        strategy = "revert_whole_pr"
        urgency = "必须"
        revert_targets = list(commits_dict.keys())
    elif coverage >= 50:
        strategy = "revert_matched"
        urgency = "建议"
        revert_targets = revert_commits
    else:
        strategy = "no_revert"
        urgency = "无须"
        revert_targets = []

    return {
        "strategy": strategy,
        "urgency": urgency,
        "coverage_rate": round(coverage, 1),
        "total_commits": total_commits_in_pr,
        "high_match_count": high_match_count,
        "revert_targets": revert_targets,
    }


def generate_revert_cmd(revert_targets: list[str],
                        strategy: str, repo_path: str) -> list[str]:
    if not revert_targets:
        return []

    if strategy == "revert_whole_pr":
        if len(revert_targets) >= 2:
            sorted_targets = sort_commits_by_time(repo_path, revert_targets)
            first = sorted_targets[0]
            last = sorted_targets[-1]
            return [f"git revert --ancestry-path {first}^..{last}"]
        else:
            return [f"git revert {revert_targets[0]}"]

    elif strategy in ("revert_matched", "direct_revert"):
        sorted_targets = sort_commits_by_time(repo_path, revert_targets)
        return [f"git revert {c}" for c in reversed(sorted_targets)]

    return []


def build_global_revert_order(pr_groups: dict, decisions: dict,
                              repo_path: str) -> list[dict]:
    order = []
    for pr_id, decision in decisions.items():
        if decision["urgency"] == "无须":
            continue

        group = pr_groups[pr_id]
        revert_cmds = generate_revert_cmd(
            decision["revert_targets"], decision["strategy"], repo_path
        )

        sorted_targets = sort_commits_by_time(
            repo_path, decision["revert_targets"]
        )

        commits_info = group.get("commits", {})
        dep_commits = []
        if decision["revert_targets"]:
            dep_commits = find_dependent_commits(
                repo_path, decision["revert_targets"][-1]
            )

        all_files = set()
        for info in group.get("matched_patches", []):
            all_files.update(info.get("affected_files", []))

        item = {
            "pr_id": pr_id,
            "pr_info": group.get("pr_info"),
            "commits": commits_info,
            "commit_count": len(commits_info),
            "revert_strategy": decision["strategy"],
            "revert_cmd": revert_cmds,
            "revert_order": sorted_targets,
            "revert_targets": decision["revert_targets"],
            "urgency": decision["urgency"],
            "coverage_rate": decision["coverage_rate"],
            "high_match_count": decision["high_match_count"],
            "related_patches": [
                p.get("matched_patch") for p in group["matched_patches"]
                if p.get("similarity", 0) >= SIMILARITY_HIGH
            ],
            "risk_assessment": {
                "dependent_commits": dep_commits,
                "affected_files": sorted(all_files),
                "estimated_conflict_risk": (
                    "高" if dep_commits else
                    "中" if len(all_files) > 5 else "低"
                ),
            },
        }
        order.append(item)

    order.sort(key=lambda x: (
        0 if x["urgency"] == "必须" else 1,
        -x["coverage_rate"],
    ))
    return order


def detect_duplicates(patch_dir: str, repo_path: str) -> dict:
    patch_dir = Path(patch_dir)
    if not patch_dir.is_dir():
        print(f"错误: patch 目录不存在: {patch_dir}", file=sys.stderr)
        sys.exit(2)

    patches = sorted(
        [f for f in patch_dir.iterdir() if f.suffix == ".patch"],
        key=lambda f: f.name,
    )

    if not patches:
        print(f"错误: {patch_dir} 下没有 .patch 文件", file=sys.stderr)
        sys.exit(2)

    patch_duplicate_map = {}
    all_pr_groups = {}
    candidate_cache = {}

    for patch_file in patches:
        task_id = patch_file.stem.split("-")[0]
        patch_content = patch_file.read_text(errors="replace")

        subject = ""
        files_changed = []
        for line in patch_content.split("\n"):
            if line.startswith("Subject:"):
                subject = line.replace("Subject:", "").strip()
                if subject.startswith("[PATCH"):
                    subject = re.sub(r'\[PATCH[^\]]*\]\s*', '', subject)
            elif line.startswith("---") and not files_changed:
                break

        # Extract files from diff
        diff_lines = patch_content.split("\n")
        for line in diff_lines:
            if line.startswith("diff --git"):
                m = re.search(r'diff --git a/(\S+) b/', line)
                if m:
                    files_changed.append(m.group(1))

        symbols = extract_symbols_from_diff(patch_content)
        add_lines = extract_add_lines_from_patch(str(patch_file))

        print(f"[SCAN] {task_id}: {subject[:60]}")

        # Search candidates
        candidates = search_candidates(
            repo_path, subject, files_changed, symbols,
        )

        patch_results = []

        for commit_hash in candidates:
            if not commit_hash or len(commit_hash) < 7:
                continue

            # Deduplicate candidate processing
            if commit_hash in candidate_cache:
                pr_info = candidate_cache[commit_hash].get("pr_info")
            else:
                pr_info = resolve_pr_affiliation(repo_path, commit_hash)
                candidate_cache[commit_hash] = {"pr_info": pr_info}

            commit_add_lines = extract_add_lines_from_commit(
                repo_path, commit_hash,
            )
            diff_similarity = compute_similarity(add_lines, commit_add_lines)

            commit_diff = run_git(repo_path, "show", commit_hash)
            commit_symbols = extract_symbols_from_diff(commit_diff)
            symbol_similarity = compute_symbol_similarity(symbols, commit_symbols)

            combined_similarity = compute_combined_similarity(
                diff_similarity, symbol_similarity
            )

            if combined_similarity < SIMILARITY_MEDIUM:
                continue

            level = "高匹配" if combined_similarity >= SIMILARITY_HIGH else "中匹配"

            commit_subject = run_git(
                repo_path, "log", "--format=%s", "-1", commit_hash,
            )

            affected_files = []
            for line in commit_diff.split("\n"):
                if line.startswith("diff --git"):
                    m = re.search(r'diff --git a/(\S+) b/', line)
                    if m:
                        affected_files.append(m.group(1))

            result = {
                "commit": commit_hash,
                "commit_subject": commit_subject,
                "diff_similarity": round(diff_similarity, 1),
                "symbol_similarity": round(symbol_similarity, 1),
                "combined_similarity": round(combined_similarity, 1),
                "similarity": round(combined_similarity, 1),
                "level": level,
                "pr_info": pr_info,
                "matched_patch": task_id,
                "patch_add_line_count": len(add_lines),
                "common_lines": int(len(add_lines & commit_add_lines)),
                "patch_symbols": sorted(symbols)[:20],
                "matched_symbols": sorted(symbols & commit_symbols)[:20],
                "affected_files": affected_files,
            }
            patch_results.append(result)
            print(f"  → {commit_hash[:12]}: diff={diff_similarity:.1f}% "
                  f"symbol={symbol_similarity:.1f}% → combined={combined_similarity:.1f}% ({level})")

        if patch_results:
            patch_results.sort(key=lambda x: -x["similarity"])
            patch_duplicate_map[task_id] = patch_results
        else:
            patch_duplicate_map[task_id] = []

    # ── PR Aggregation ──
    all_candidates = {}
    for task_id, results in patch_duplicate_map.items():
        for r in results:
            commit = r["commit"]
            if commit not in all_candidates:
                all_candidates[commit] = r

    pr_groups = group_candidates_by_pr(all_candidates, repo_path)

    decisions = {}
    for pr_id, group in pr_groups.items():
        decisions[pr_id] = calculate_pr_coverage(group)

    global_revert_order = build_global_revert_order(
        pr_groups, decisions, repo_path
    )

    return {
        "patch_duplicate_map": patch_duplicate_map,
        "pr_aggregation": {
            pr_id: {
                "commits": g["commits"],
                "matched_patches": [
                    {
                        "commit": p["commit"],
                        "similarity": p["similarity"],
                        "level": p["level"],
                        "matched_patch": p["matched_patch"],
                    }
                    for p in g["matched_patches"]
                ],
                "decision": decisions.get(pr_id, {}),
            }
            for pr_id, g in pr_groups.items()
        },
        "global_revert_order": global_revert_order,
        "thresholds": {
            "single_similarity_high": SIMILARITY_HIGH,
            "single_similarity_medium": SIMILARITY_MEDIUM,
            "pr_coverage_whole": PR_COVERAGE_WHOLE,
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="重复/等效 patch 检测 + PR 聚合 + revert 决策"
    )
    parser.add_argument("--patch-dir", required=True,
                        help="patch 文件目录")
    parser.add_argument("--repo-path", required=True,
                        help="目标内核仓库路径")
    parser.add_argument("--output", required=True,
                        help="输出 JSON 文件路径")
    args = parser.parse_args()

    if not os.path.isdir(args.patch_dir):
        print(f"错误: patch 目录不存在: {args.patch_dir}", file=sys.stderr)
        sys.exit(2)

    if not os.path.isdir(args.repo_path):
        print(f"错误: 仓库路径不存在: {args.repo_path}", file=sys.stderr)
        sys.exit(2)

    print("=" * 60)
    print("  重复/等效 Patch 检测 + PR 聚合")
    print("=" * 60)
    print(f"  Patch 目录: {args.patch_dir}")
    print(f"  目标仓库:   {args.repo_path}")
    print(f"  单 commit 高匹配阈值: >= {SIMILARITY_HIGH}%")
    print(f"  PR 整体 revert 阈值:  >= {PR_COVERAGE_WHOLE}%")
    print("=" * 60)
    print()

    result = detect_duplicates(args.patch_dir, args.repo_path)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print()
    print("=" * 60)
    print(f"  输出: {args.output}")
    print(f"  检测到的匹配: {len(result['patch_duplicate_map'])} 个 patch")
    print(f"  PR 聚合组:    {len(result['pr_aggregation'])} 组")
    print(f"  Revert 建议:  {len(result['global_revert_order'])} 项")
    for item in result["global_revert_order"]:
        print(f"    {item['pr_id']}: {item['revert_strategy']} "
              f"(覆盖率 {item['coverage_rate']}%, urgency={item['urgency']})")
    print("=" * 60)

    sys.exit(0)


if __name__ == "__main__":
    main()
