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

# 版本升级模式阈值（相同功能不同实现 → 降低匹配门槛）
UPGRADE_SIMILARITY_HIGH = 30
UPGRADE_SIMILARITY_MEDIUM = 15
# 同作者时间窗口（秒）：此窗口内的提交视为同一批旧版本
AUTHOR_TIME_WINDOW = 86400 * 3  # 3 天


def run_git(repo_path: str, *args, timeout: int = 10) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path] + list(args),
            capture_output=True, text=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print(f"  [WARN] git {' '.join(list(args)[:4])}... timed out ({timeout}s)", file=sys.stderr)
        return ""


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


def compute_combined_similarity(diff_sim: float, symbol_sim: float,
                                high: int = SIMILARITY_HIGH,
                                medium: int = SIMILARITY_MEDIUM) -> float:
    """综合相似度：以 diff 为主，symbol 为辅。

    语义：
    - diff >= high → 代码几乎相同（高匹配）
    - diff >= medium 且 symbol >= high → 功能相同但实现略有差异（高匹配）
    - diff == 0 → symbol 无论多高都不可能是真实匹配（最多返回 medium-1）
    - 其他 → 取两者均值作为参考
    """
    if diff_sim >= high:
        return max(diff_sim, symbol_sim)
    if diff_sim >= medium and symbol_sim >= high:
        return max(diff_sim, symbol_sim)
    if diff_sim == 0.0:
        return min((diff_sim + symbol_sim) / 2, float(medium - 1))
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


def _common_dirs(files: list[str], max_depth: int | None = None) -> list[str]:
    """从文件列表中提取公共目录。

    max_depth=None  → 取直接父目录（rsplit），适合精准搜索
    max_depth=N    → 截断到 N 层深度，适合宽泛搜索
    """
    dirs = set()
    for f in files:
        if max_depth is None:
            parts = f.rsplit("/", 1)
            if len(parts) == 2:
                dirs.add(parts[0] + "/")
            else:
                dirs.add(f)
        else:
            parts = f.split("/")
            depth = min(len(parts) - 1, max_depth)
            if depth > 0:
                dirs.add("/".join(parts[:depth]) + "/")
            else:
                dirs.add(f)
    return sorted(dirs)[:10]


def search_candidates(repo_path: str, subject: str,
                      files_changed: list[str],
                      symbols: set[str]) -> list[str]:
    candidates = set()
    path_scope = _common_dirs(files_changed) if files_changed else []

    # 方法 1: subject 关键词匹配（限定涉改目录）
    keywords = subject.strip().replace(":", " ").replace("/", " ")
    keyword_list = [k for k in keywords.split() if len(k) >= 4]
    grep_args = ["log", "--oneline", "--format=%H", "-n", "5"]
    for kw in keyword_list[:5]:
        result = run_git(
            repo_path, *grep_args, f"--grep={kw}", *path_scope,
        )
        for line in result.split("\n"):
            if line:
                candidates.add(line.strip())

    # 方法 2: 搜索引入的符号（限定涉改文件，搜完整历史）
    pickaxe_args = ["log", "--oneline", "--format=%H", "-n", "3"]
    for sym in sorted(symbols)[:5]:
        result = run_git(
            repo_path, *pickaxe_args, f"-S={sym}", *path_scope,
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
    # Parse !XXXXX openEuler PR format from commit body or subject
    subject = run_git(repo_path, "log", "--format=%s", "-1", commit_hash)
    # Try !XXXXX format in body first, then subject
    m = re.search(r'^!(\d{4,6})\b', body, re.MULTILINE)
    if not m:
        m = re.search(r'!(\d{4,6})\b', subject)
    if m:
        return {"pr_id": f"PR!{m.group(1)}", "source": "openEuler_MR"}
    # Also try standard Link: tag
    m = re.search(r'Link:\s*(https?://\S+)', body)
    if m:
        return {"pr_id": m.group(1), "source": "commit_msg_link"}
    return None


# ── Version-upgrade expansion ──


def _get_commit_author_and_date(repo_path: str, commit_hash: str) -> tuple[str, int]:
    """返回 (author, unix_timestamp)。"""
    ts = run_git(repo_path, "log", "--format=%at", "-1", commit_hash)
    author = run_git(repo_path, "log", "--format=%an", "-1", commit_hash)
    return author, int(ts) if ts.lstrip("-").isdigit() else 0


def _search_keyword_commits(repo_path: str,
                             keywords: list[str],
                             path_scope: list[str]) -> set[str]:
    """搜索涉改目录下含有关键词的 commit（不限作者，仅当前分支）。
    只用专用关键词（大写缩写），排除通用词（arm64/kvm/support 等）。"""
    specific = [k for k in keywords
                if k.isupper() and len(k) >= 3
                and k.lower() not in {
                    "support", "enable", "handle", "kvm", "arm64", "arm",
                }]
    if not specific:
        return set()
    commits = set()
    # 用高匹配 commit 时间范围限制搜索窗口
    for kw in specific[:4]:
        result = run_git(
            repo_path, "log", "--oneline", "--format=%H",
            "-n", "100", "-i",
            "--since=2024-01-01",
            f"--grep={kw}", *path_scope,
            timeout=10,
        )
        for line in result.split("\n"):
            if line.strip():
                commits.add(line.strip())
        if len(commits) >= 30:
            break
    return commits


def expand_old_version_batches(repo_path: str,
                                candidates: dict,
                                path_scope: list[str],
                                keywords: list[str],
                                sim_high: int = SIMILARITY_HIGH) -> dict:
    """版本升级模式：关键词 + 时间窗口聚合旧版本全部 commit。

    不再依赖作者——同特性可能由不同作者完成（离职/交接/bugfix）。

    返回: {"batches": [...], "all_old_commits": set()}
    """
    if not candidates:
        return {"batches": [], "all_old_commits": set()}

    # Step 1: 收集高匹配 commit 的时间范围
    high_match_commits = {}
    for commit_hash, info in candidates.items():
        if info.get("similarity", 0) >= sim_high:
            _, ts = _get_commit_author_and_date(repo_path, commit_hash)
            high_match_commits[commit_hash] = ts

    if not high_match_commits:
        return {"batches": [], "all_old_commits": set()}

    # Step 2: 搜索涉改目录下含关键词的全部 commit（不限作者）
    more_commits = _search_keyword_commits(repo_path, keywords, path_scope)
    all_items = []
    for c in more_commits:
        _, ts = _get_commit_author_and_date(repo_path, c)
        subject = run_git(repo_path, "log", "--format=%s", "-1", c)
        all_items.append((c, ts, subject))
    all_items.sort(key=lambda x: x[1])

    if not all_items:
        return {"batches": [], "all_old_commits": set()}

    # Step 3: 按时间窗口拆分
    window_groups = []
    current_group = [all_items[0]]
    for item in all_items[1:]:
        prev_ts = current_group[-1][1]
        if item[1] - prev_ts <= AUTHOR_TIME_WINDOW:
            current_group.append(item)
        else:
            window_groups.append(current_group)
            current_group = [item]
    if current_group:
        window_groups.append(current_group)

    # Step 4: 对每个窗口组，直接用关键词匹配结果（不扩展 ancestry-path）
    batches = []
    seen_commits = set()

    for wg in window_groups:
        if len(wg) < 2:
            continue

        commits_in_group = [c for c, _, _ in wg]
        for c in commits_in_group:
            seen_commits.add(c)

        subjects = {c: run_git(repo_path, "log", "--format=%s", "-1", c)
                    for c in commits_in_group}

        batches.append({
            "commits": commits_in_group,
            "commit_count": len(commits_in_group),
            "first_commit": commits_in_group[0] if commits_in_group else "",
            "last_commit": commits_in_group[-1] if commits_in_group else "",
            "subjects": subjects,
        })

    return {
        "batches": batches,
        "all_old_commits": seen_commits,
    }


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


def group_candidates_by_pr(candidates: dict, repo_path: str = "",
                            sim_high: int = SIMILARITY_HIGH) -> dict:
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
                "matched": info.get("similarity", 0) >= sim_high,
            }
            commit_pr_map[commit_hash] = pr_id
        else:
            pr_groups[commit_hash]["pr_info"] = {"pr_id": "独立 commit"}
            pr_groups[commit_hash]["commits"][commit_hash] = {
                "subject": info.get("commit_subject", ""),
                "similarity": info.get("similarity", 0),
                "matched": info.get("similarity", 0) >= sim_high,
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
                              repo_path: str, sim_high: int = SIMILARITY_HIGH) -> list[dict]:
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
                if p.get("similarity", 0) >= sim_high
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


def detect_duplicates(patch_dir: str, repo_path: str,
                      version_upgrade: bool = False,
                      ai_keywords: list[str] | None = None) -> dict:
    # 版本升级模式：降低阈值
    sim_high = UPGRADE_SIMILARITY_HIGH if version_upgrade else SIMILARITY_HIGH
    sim_medium = UPGRADE_SIMILARITY_MEDIUM if version_upgrade else SIMILARITY_MEDIUM

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
                diff_similarity, symbol_similarity, sim_high, sim_medium
            )

            if combined_similarity < sim_medium:
                continue

            level = "高匹配" if combined_similarity >= sim_high else "中匹配"

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

    pr_groups = group_candidates_by_pr(all_candidates, repo_path, sim_high=sim_high)

    decisions = {}
    for pr_id, group in pr_groups.items():
        decisions[pr_id] = calculate_pr_coverage(group)

    global_revert_order = build_global_revert_order(
        pr_groups, decisions, repo_path, sim_high=sim_high
    )

    # ── Version-upgrade expansion ──
    old_version_batches = None
    if version_upgrade and patches:
        # 计算涉改目录（所有策略共用）
        all_files = set()
        for patch_file in patches:
            patch_content = patch_file.read_text(errors="replace")
            for line in patch_content.split("\n"):
                if line.startswith("diff --git"):
                    m = re.search(r'diff --git a/(\S+) b/', line)
                    if m:
                        all_files.add(m.group(1))
        path_scope = _common_dirs(list(all_files), max_depth=2) if all_files else []

        keywords = ai_keywords or _build_keywords_from_patches(patch_dir)
        if keywords:
            print(f"\n[UPGRADE] 涉改目录: {', '.join(path_scope[:4])}")
            source = "AI" if ai_keywords else "自动提取"
            print(f"[UPGRADE] 关键词({source}): {', '.join(keywords[:8])}")

            # 策略 1: 关键词+时间窗口聚合 (主策略, 不限作者, 限定涉改目录)
            batch_result = expand_old_version_batches(
                repo_path, all_candidates, path_scope, keywords, sim_high=sim_high)
            old_version_batches = batch_result["batches"]
            all_old = set(batch_result.get("all_old_commits", set()))
            if old_version_batches:
                total = sum(b.get("commit_count", 0) for b in old_version_batches)
                print(f"[UPGRADE] 关键词聚合: {len(old_version_batches)} 批次, {total} commits")

            # 策略 2: revert commit 追溯 (补充, 仅当前分支)
            revert_results = _search_revert_commits(repo_path, keywords, path_scope)
            for r in revert_results:
                if any(r["reverted_commit"] in b.get("commits", []) for b in old_version_batches):
                    continue  # 已包含, 跳过
                print(f"  + revert 补充: {r['revert_commit'][:12]} → {len(r['old_commits'])} commits")
                batch = {
                    "author": "from_revert",
                    "commits": r["old_commits"],
                    "commit_count": len(r["old_commits"]),
                    "first_commit": r["old_commits"][0] if r["old_commits"] else "",
                    "last_commit": r["old_commits"][-1] if r["old_commits"] else "",
                    "first_date": 0, "last_date": 0,
                    "subjects": {
                        c: run_git(repo_path, "log", "--format=%s", "-1", c)
                        for c in r["old_commits"]
                    },
                    "source_revert": r["revert_commit"],
                    "source_revert_msg": r["revert_subject"],
                }
                old_version_batches.append(batch)
                all_old.update(r["old_commits"])

            # 策略 3: 向前搜索 bugfix（补充，同目录 + 关键词）
            if old_version_batches:
                last_core = max(
                    (b["last_commit"] for b in old_version_batches),
                    default="",
                )
                if last_core:
                    bugfix_commits = _search_forward_bugfixes(
                        repo_path, last_core, path_scope,
                        [k for k in keywords if k.isupper() and len(k) >= 3],
                    )
                    new_bugfixes = bugfix_commits - all_old
                    if new_bugfixes:
                        print(f"  + bugfix 补充: {len(new_bugfixes)} commits")
                        subjects = {
                            c: run_git(repo_path, "log", "--format=%s", "-1", c)
                            for c in new_bugfixes
                        }
                        old_version_batches.append({
                            "author": "from_bugfix",
                            "commits": list(new_bugfixes),
                            "commit_count": len(new_bugfixes),
                            "first_commit": "",
                            "last_commit": "",
                            "first_date": 0, "last_date": 0,
                            "subjects": subjects,
                        })
                        all_old.update(new_bugfixes)

            # 合并所有旧 commit 到 candidates
            # 策略 3.5: 搜索关键词匹配的 merge commit，提取子 commit 用于 PR 分组
            for kw in [k for k in keywords if k.isupper() and len(k) >= 3][:3]:
                merge_result = run_git(
                    repo_path, "log", "--merges", "--format=%H", "-i",
                    "-n", "10", f"--grep={kw}", *path_scope, timeout=10,
                )
                for line in merge_result.split("\n"):
                    merge_hash = line.strip()
                    if not merge_hash or merge_hash in all_old:
                        continue
                    merge_subject = run_git(repo_path, "log", "--format=%s", "-1", merge_hash)
                    sub_commits = _extract_merge_commits(repo_path, merge_hash)
                    if len(sub_commits) >= 2:
                        print(f"  + merge PR 补充: {merge_hash[:12]} ({merge_subject[:60]}) → {len(sub_commits)} commits")
                        all_old.add(merge_hash)
                        all_old.update(sub_commits)
                        subjects = {
                            c: run_git(repo_path, "log", "--format=%s", "-1", c)
                            for c in [merge_hash] + sub_commits
                        }
                        old_version_batches.append({
                            "author": "from_merge",
                            "commits": [merge_hash] + sub_commits,
                            "commit_count": 1 + len(sub_commits),
                            "first_commit": sub_commits[0] if sub_commits else merge_hash,
                            "last_commit": sub_commits[-1] if sub_commits else merge_hash,
                            "first_date": 0, "last_date": 0,
                            "subjects": subjects,
                            "merge_commit": merge_hash,
                        })

            # 合并所有旧 commit 到 candidates
            for commit_hash in all_old:
                if commit_hash not in all_candidates:
                    subject = run_git(repo_path, "log", "--format=%s", "-1", commit_hash)
                    all_candidates[commit_hash] = {
                        "commit": commit_hash, "commit_subject": subject,
                        "similarity": float(sim_high),
                        "level": "版本升级批次成员", "pr_info": None,
                        "matched_patch": "", "source": "version_upgrade",
                    }
                else:
                    all_candidates[commit_hash]["similarity"] = max(
                        all_candidates[commit_hash].get("similarity", 0),
                        float(sim_high))

            # 重建 PR 聚合
            pr_groups = group_candidates_by_pr(all_candidates, repo_path, sim_high=sim_high)
            decisions = {}
            for pr_id, group in pr_groups.items():
                decisions[pr_id] = calculate_pr_coverage(group)
            global_revert_order = build_global_revert_order(
                pr_groups, decisions, repo_path, sim_high=sim_high)

    return {
        "patch_duplicate_map": patch_duplicate_map,
        "pr_aggregation": {
            pr_id: {
                "commits": g["commits"],
                "matched_patches": [
                    {"commit": p["commit"], "similarity": p["similarity"],
                     "level": p["level"], "matched_patch": p["matched_patch"]}
                    for p in g["matched_patches"]
                ],
                "decision": decisions.get(pr_id, {}),
            }
            for pr_id, g in pr_groups.items()
        },
        "global_revert_order": global_revert_order,
        "thresholds": {
            "single_similarity_high": sim_high,
            "single_similarity_medium": sim_medium,
            "pr_coverage_whole": PR_COVERAGE_WHOLE,
        },
        "version_upgrade": {
            "enabled": version_upgrade,
        } | ({"batches": old_version_batches} if old_version_batches else {}),
    }


# ── Version-upgrade expansion helpers ──


def _files_overlap(reverted_files: list[str], path_scope: list[str]) -> bool:
    """检查 revert commit 的涉改文件是否与 patchset 的目录有交集。"""
    for f in reverted_files:
        for p in path_scope:
            if f.startswith(p):
                return True
    return False


def _search_revert_commits(repo_path: str, keywords: list[str],
                            path_scope: list[str]) -> list[dict]:
    """在**当前分支**上搜索 revert commit，从中提取旧版本 commit 列表。

    策略：git log --grep="Revert" 限定涉改目录，仅查当前分支。
    解析 "This reverts commit <hash>" → 跟踪被 revert 的 merge → 获取全部子 commit。

    返回: [{"revert_commit": hash, "reverted_commit": hash, "old_commits": [hash,...]}, ...]
    """
    results = []

    # 在当前分支搜 revert commit（限定涉改目录）
    candidate_hashes = set()
    # 提取专用关键词（大写缩写，排除通用词）
    specific_keywords = [k for k in keywords if k.isupper() and len(k) >= 3]
    if not specific_keywords:
        # fallback：取非通用关键词（排除 support, enable, arm64 等）
        generic = {k.lower() for k in keywords if k.lower() in
                    {"support", "enable", "add", "arm64", "kvm", "handle", "register", "memory"}}
        specific_keywords = [k for k in keywords if k.lower() not in generic]

    for kw in specific_keywords[:3]:
        result = run_git(
            repo_path, "log", "--oneline", "--format=%H",
            f"--grep=^Revert",
            f"--grep={kw}",
            "-i", "--all-match",
            "-n", "50", "HEAD", *path_scope,
            timeout=10,
        )
        for line in result.split("\n"):
            h = line.strip()
            if h and len(h) >= 40:
                candidate_hashes.add(h)

    if not candidate_hashes:
        return results

    # 对每个候选检查是否是真正的 revert commit
    for ch in list(candidate_hashes)[:30]:
        subject = run_git(repo_path, "log", "--format=%s", "-1", ch, timeout=5)

        # 过滤：subject 必须以 "Revert" 开头且含有专用关键词
        if not subject.startswith("Revert "):
            continue
        if not any(kw.lower() in subject.lower() for kw in specific_keywords):
            continue

        body = run_git(repo_path, "log", "--format=%B", "-1", ch, timeout=5)
        if not body or "This reverts commit" not in body:
            continue

        # 提取被 revert 的 commit hash
        m = re.search(r'This reverts commit\s+([0-9a-f]{40})', body)
        if not m:
            continue
        reverted_hash = m.group(1)

        # 检查被 revert 的 commit 是否在当前分支上
        if not run_git(repo_path, "log", "--format=%H", "-1", reverted_hash, timeout=5):
            continue

        # 检查被 revert commit 是否与 patchset 涉改文件有交集
        reverted_files = run_git(
            repo_path, "diff", "--name-only",
            f"{reverted_hash}~1..{reverted_hash}",
            timeout=5,
        )
        if not _files_overlap(reverted_files.split("\n"), path_scope):
            continue

        # 获取被 revert commit 包含的全部子 commit
        old_commits = _extract_merge_commits(repo_path, reverted_hash)

        if old_commits:
            results.append({
                "revert_commit": ch,
                "revert_subject": subject.strip(),
                "reverted_commit": reverted_hash,
                "old_commits": old_commits,
            })

    # 去重：多个 revert 可能指向同一个 merge
    seen_reverted = set()
    unique_results = []
    for r in results:
        if r["reverted_commit"] not in seen_reverted:
            seen_reverted.add(r["reverted_commit"])
            unique_results.append(r)

    return unique_results


def _extract_merge_commits(repo_path: str, commit_hash: str) -> list[str]:
    """提取 merge commit 包含的全部子 commit（最早→最新）。"""
    parents = run_git(repo_path, "log", "--format=%P", "-1", commit_hash, timeout=5)
    parent_list = parents.split()
    if len(parent_list) < 2:
        return [commit_hash]

    # 用 merge~1..merge 获取合并引入的全部 commit
    result = run_git(
        repo_path, "log", "--format=%H",
        f"{commit_hash}~1..{commit_hash}",
        timeout=10,
    )
    commits = [c.strip() for c in result.split("\n") if c.strip()]
    if not commits:
        commits = [commit_hash]
    return sort_commits_by_time(repo_path, commits)


def _search_forward_bugfixes(repo_path: str, last_core_commit: str,
                              path_scope: list[str],
                              specific_keywords: list[str]) -> set[str]:
    """向前搜索 bugfix commit（当前分支，限定涉改目录 + 专用关键词）。

    从最后一个核心 commit 向更新方向搜索，找同目录下含关键词的后续修复提交。
    """
    commits = set()
    for kw in specific_keywords[:3]:
        result = run_git(
            repo_path, "log", "--oneline", "--format=%H",
            "-n", "10", f"{last_core_commit}..HEAD",
            f"--grep={kw}",
            "--no-merges",
            *path_scope,
            timeout=10,
        )
        for line in result.split("\n"):
            h = line.strip()
            if h and len(h) >= 40:
                commits.add(h)
    return commits


def _build_keywords_from_patches(patch_dir: Path) -> list[str]:
    """从 patchset 提取特征关键词（大写缩写 + 共享词）。"""
    subjects = []
    for f in sorted(patch_dir.iterdir()):
        if not f.suffix == ".patch":
            continue
        content = f.read_text(errors="replace")
        for line in content.split("\n"):
            if line.startswith("Subject:"):
                s = line.replace("Subject:", "").strip()
                s = re.sub(r'\[PATCH[^\]]*\]\s*', '', s)
                subjects.append(s)
                break

    # 提取大写缩写（如 HDBSS, FEAT_HDBSS, DBM, HDBSSF）
    caps = set()
    shared = set()
    word_counts = defaultdict(int)

    for s in subjects:
        words = s.replace(":", " ").replace("/", " ").replace("-", " ").split()
        for w in words:
            w = w.strip(".,;")
            if len(w) >= 3:
                word_counts[w.lower()] += 1
                if w.isupper() and len(w) >= 3:
                    caps.add(w)

    # 共享关键词（在 ≥2 个 patch 中出现）
    for w, cnt in word_counts.items():
        if cnt >= 2 and len(w) >= 4:
            shared.add(w)

    # 合并去重，优先大写缩写
    all_keywords = sorted(caps | shared, key=lambda x: len(x), reverse=True)[:10]
    return all_keywords


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
    parser.add_argument("--version-upgrade", action="store_true",
                        help="版本升级模式：降低匹配阈值，关键词+时间窗口聚合")
    parser.add_argument("--analysis-cache",
                        help="analysis_cache.json 路径，读取 AI 提供的 feature_signature.keywords")
    args = parser.parse_args()

    if not os.path.isdir(args.patch_dir):
        print(f"错误: patch 目录不存在: {args.patch_dir}", file=sys.stderr)
        sys.exit(2)

    if not os.path.isdir(args.repo_path):
        print(f"错误: 仓库路径不存在: {args.repo_path}", file=sys.stderr)
        sys.exit(2)

    mode_str = "[版本升级模式]" if args.version_upgrade else "[普通模式]"
    sim_high = UPGRADE_SIMILARITY_HIGH if args.version_upgrade else SIMILARITY_HIGH
    sim_medium = UPGRADE_SIMILARITY_MEDIUM if args.version_upgrade else SIMILARITY_MEDIUM

    print("=" * 60)
    print(f"  重复/等效 Patch 检测 + PR 聚合 {mode_str}")
    print("=" * 60)
    print(f"  Patch 目录: {args.patch_dir}")
    print(f"  目标仓库:   {args.repo_path}")
    print(f"  单 commit 高匹配阈值: >= {sim_high}%")
    print(f"  单 commit 中匹配阈值: >= {sim_medium}%")
    print(f"  PR 整体 revert 阈值:  >= {PR_COVERAGE_WHOLE}%")
    if args.version_upgrade:
        print(f"  同作者时间窗口:       {AUTHOR_TIME_WINDOW // 86400} 天")
    print("=" * 60)
    print()

    # 读取 AI 提供的关键词（优先于自动提取）
    ai_keywords = None
    if args.version_upgrade and args.analysis_cache:
        try:
            with open(args.analysis_cache) as f:
                cache = json.load(f)
            sig = cache.get("feature_signature", {})
            if sig.get("keywords"):
                ai_keywords = sig["keywords"]
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    result = detect_duplicates(args.patch_dir, args.repo_path,
                               version_upgrade=args.version_upgrade,
                               ai_keywords=ai_keywords)

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
    if args.version_upgrade and "batches" in result.get("version_upgrade", {}):
        print()
        print(f"  旧版本批次: {len(result['version_upgrade']['batches'])} 个")
        for i, b in enumerate(result["version_upgrade"]["batches"]):
            print(f"    批次 {i+1}: {b['commit_count']} commits ")
    print("=" * 60)

    sys.exit(0)


if __name__ == "__main__":
    main()
