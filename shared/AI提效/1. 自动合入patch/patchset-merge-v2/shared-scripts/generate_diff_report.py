#!/usr/bin/env python3
"""Generate diff comparison report: source patch/commit vs actual commit.

比较源 patch/commit 的意图与实际 commit 的结果，只输出差异（偏离）部分。

source 格式:
  patch:<path>   — merge 场景：原始 .patch 文件
  commit:<hash>  — revert 场景：被 revert 的原 commit

mode:
  merge   — 标准对比（源 + vs 目标 +，源 - vs 目标 -）
  revert  — 镜像对比（源 + vs 目标 -，源 - vs 目标 +）
  auto    — 根据 source/target 自动推断（默认）
"""

from __future__ import annotations

import json
import os
import re
import argparse
import subprocess
from dataclasses import dataclass, field


# ── data classes ──


@dataclass
class Deviation:
    """一条偏离记录"""
    file_path: str
    src_line: str | None = None
    src_label: str = ""
    target_line: str | None = None
    target_label: str = ""
    root_cause: str = ""


@dataclass
class FileDiff:
    """一个文件的 diff 解析结果"""
    file_path: str = ""
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


# ── helpers ──


def get_diff_content(repo_path: str, source: str) -> str:
    """获取 diff 内容：patch 文件或 git commit"""
    if source.startswith("patch:"):
        path = source[6:]
        with open(path, "r") as f:
            return f.read()
    elif source.startswith("commit:"):
        commit = source[7:]
        result = subprocess.run(
            ["git", "-C", repo_path, "show", "--format=", commit],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git show {commit} failed: {result.stderr.strip()}")
        return result.stdout
    else:
        raise ValueError(f"无效的 source 格式: {source}，应为 patch:<path> 或 commit:<hash>")


def parse_diff_per_file(diff_content: str) -> list[FileDiff]:
    """解析 diff 内容，按文件分组提取 +/- 行"""
    files: list[FileDiff] = []
    current: FileDiff | None = None

    for line in diff_content.split("\n"):
        if line.startswith("diff --git"):
            if current:
                files.append(current)
            m = re.match(r"diff --git a/(.*) b/(.*)", line)
            fname = m.group(1) if m else ""
            current = FileDiff(file_path=fname)
            continue

        if current is None:
            continue

        if (line.startswith("index ")
                or line.startswith("--- ")
                or line.startswith("+++ ")
                or line.startswith("@@")):
            continue

        if line.startswith("+") and not line.startswith("+++"):
            current.added.append(line)
        elif line.startswith("-") and not line.startswith("---"):
            current.removed.append(line)

    if current:
        files.append(current)

    return files


def build_line_index(files: list[FileDiff]) -> dict[str, dict[str, set[str]]]:
    """构建文件→行集合索引。

    返回: {file_path: {"+": set(line_content), "-": set(line_content)}}
    """
    idx: dict[str, dict[str, set[str]]] = {}
    for f in files:
        if not f.file_path:
            continue
        idx[f.file_path] = idx.get(f.file_path, {"+": set(), "-": set()})
        for a in f.added:
            idx[f.file_path]["+"].add(a[1:].strip() if a.startswith("+") else a.strip())
        for r in f.removed:
            idx[f.file_path]["-"].add(r[1:].strip() if r.startswith("-") else r.strip())
    return idx


def compare_diffs(src_files: list[FileDiff], tgt_files: list[FileDiff],
                  src_label: str, tgt_label: str,
                  mode: str = "merge") -> list[Deviation]:
    """比较源文件和目标文件的差异，返回偏离列表。

    mode="merge":  同向比较（源 + vs 目标 +，源 - vs 目标 -）
    mode="revert": 镜像比较（源 + vs 目标 -，源 - vs 目标 +）
    """
    src_idx = build_line_index(src_files)
    tgt_idx = build_line_index(tgt_files)

    deviations: list[Deviation] = []

    all_files = set(src_idx.keys()) | set(tgt_idx.keys())
    for fpath in sorted(all_files):
        src_signs = src_idx.get(fpath, {"+": set(), "-": set()})
        tgt_signs = tgt_idx.get(fpath, {"+": set(), "-": set()})

        if mode == "revert":
            # 镜像比较：源 + 应匹配目标 -，源 - 应匹配目标 +
            _compare_mirror(
                deviations, fpath,
                src_signs, tgt_signs, src_label, tgt_label,
            )
        else:
            # 标准比较：源 + 应匹配目标 +，源 - 应匹配目标 -
            _compare_standard(
                deviations, fpath,
                src_signs, tgt_signs, src_label, tgt_label,
            )

    return deviations


def _compare_standard(deviations: list[Deviation], fpath: str,
                      src: dict[str, set[str]], tgt: dict[str, set[str]],
                      src_label: str, tgt_label: str):
    """标准比较：同向对比"""

    only_src_added = src["+"] - tgt["+"]
    for line in sorted(only_src_added):
        deviations.append(Deviation(
            file_path=fpath,
            src_line=line,
            src_label=f"源 {src_label}",
            target_label="实际 commit 无此行",
        ))

    only_src_removed = src["-"] - tgt["-"]
    for line in sorted(only_src_removed):
        deviations.append(Deviation(
            file_path=fpath,
            src_line=line,
            src_label=f"源 {src_label}",
            target_label="实际 commit 无此行",
        ))

    only_tgt_added = tgt["+"] - src["+"]
    for line in sorted(only_tgt_added):
        deviations.append(Deviation(
            file_path=fpath,
            src_label=f"源 {src_label} 无此行",
            target_line=line,
            target_label=f"实际 commit {tgt_label}",
        ))

    only_tgt_removed = tgt["-"] - src["-"]
    for line in sorted(only_tgt_removed):
        deviations.append(Deviation(
            file_path=fpath,
            src_label=f"源 {src_label} 无此行",
            target_line=line,
            target_label=f"实际 commit {tgt_label}",
        ))


def _compare_mirror(deviations: list[Deviation], fpath: str,
                    src: dict[str, set[str]], tgt: dict[str, set[str]],
                    src_label: str, tgt_label: str):
    """镜像比较（revert 模式）：源 + 应匹配目标 -，源 - 应匹配目标 +"""

    # 源 + 应在目标 - 中出现（原添加的行应在 revert 中被删除）
    src_added_not_in_tgt_removed = src["+"] - tgt["-"]
    for line in sorted(src_added_not_in_tgt_removed):
        deviations.append(Deviation(
            file_path=fpath,
            src_line=line,
            src_label=f"源 {src_label} 添加",
            target_label=f"revert 中未删除此行（回退不完整）",
        ))

    # 源 - 应在目标 + 中出现（原删除的行应在 revert 中被恢复）
    src_removed_not_in_tgt_added = src["-"] - tgt["+"]
    for line in sorted(src_removed_not_in_tgt_added):
        deviations.append(Deviation(
            file_path=fpath,
            src_line=line,
            src_label=f"源 {src_label} 删除",
            target_label=f"revert 中未恢复此行（回退不完整）",
        ))

    # 目标 - 但源没有 +（revert 多删了行）
    tgt_removed_not_in_src_added = tgt["-"] - src["+"]
    for line in sorted(tgt_removed_not_in_src_added):
        deviations.append(Deviation(
            file_path=fpath,
            target_line=line,
            src_label=f"源 {src_label} 无此行",
            target_label=f"revert 多删了此行（过度回退）",
        ))

    # 目标 + 但源没有 -（revert 多加了行）
    tgt_added_not_in_src_removed = tgt["+"] - src["-"]
    for line in sorted(tgt_added_not_in_src_removed):
        deviations.append(Deviation(
            file_path=fpath,
            target_line=line,
            src_label=f"源 {src_label} 无此行",
            target_label=f"revert 多加了此行（过度回退）",
        ))


# ── execution log / root cause ──


def load_execution_log(merges_json_path: str, task_id: str) -> list[dict]:
    """从 merge_tasks.json 中提取指定 task 的 execution_log"""
    if not merges_json_path or not os.path.exists(merges_json_path):
        return []

    try:
        with open(merges_json_path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

    for section in ["deps_order", "merge_order"]:
        for task in data.get(section, []):
            if task.get("task_id") == task_id:
                return task.get("execution_log", [])

    return []


def extract_root_causes(execution_log: list[dict], file_path: str) -> list[str]:
    """从 execution_log 中提取与指定文件相关的根因"""
    causes: list[str] = []
    fname = os.path.basename(file_path)

    for entry in execution_log:
        detail = ""
        if isinstance(entry, str):
            detail = entry
        elif isinstance(entry, dict):
            detail = entry.get("detail", "") or entry.get("step", "")

        if not detail:
            continue

        # 匹配文件名或完整路径
        if fname in detail or file_path in detail:
            causes.append(detail)

    return causes


def annotate_deviation_root_causes(deviations: list[Deviation],
                                    execution_log: list[dict]) -> None:
    """为偏离记录标注根因"""
    for d in deviations:
        causes = extract_root_causes(execution_log, d.file_path)
        if causes:
            # 取首条最相关的原因
            d.root_cause = causes[0]

    # 为缺失文件级别的偏离统一标注
    for d in deviations:
        if not d.root_cause and execution_log:
            for entry in execution_log:
                detail = ""
                if isinstance(entry, dict):
                    detail = entry.get("detail", "")
                if detail and ("冲突" in detail or "conflict" in detail.lower()):
                    d.root_cause = detail
                    break


# ── report ──


def generate_report(devs: list[Deviation], src_desc: str, tgt_desc: str,
                    mode: str = "merge",
                    execution_log: list[dict] | None = None) -> str:
    """生成差异对比报告（只输出偏离部分）"""

    sections: list[str] = []
    mode_label = {"merge": "merge 模式", "revert": "revert 模式（镜像对比）"}
    sections.append("=" * 60)
    sections.append(f"差异对比报告 ({mode_label.get(mode, mode)})")
    sections.append("=" * 60)
    sections.append(f"源:   {src_desc}")
    sections.append(f"目标: {tgt_desc}")
    sections.append("")

    if execution_log:
        sections.append(f"合入经验: {len(execution_log)} 条记录")
        sections.append("")

    if not devs:
        sections.append("实际 commit 与源完全一致，无任何偏离。")
        sections.append("=" * 60)
        return "\n".join(sections)

    # 按文件分组
    by_file: dict[str, list[Deviation]] = {}
    for d in devs:
        by_file.setdefault(d.file_path, []).append(d)

    file_count = len(by_file)
    total_devs = len(devs)
    sections.append(f"差异汇总: {file_count} 个文件有偏离，共 {total_devs} 处")
    sections.append("")

    for fpath in sorted(by_file.keys()):
        fdevs = by_file[fpath]
        sections.append(f"  [{fpath}] {len(fdevs)} 处偏离")
    sections.append("")

    sections.append("-" * 60)
    sections.append("偏离详情")
    sections.append("-" * 60)

    for fpath in sorted(by_file.keys()):
        fdevs = by_file[fpath]
        sections.append(f"\n## 文件: {fpath} ({len(fdevs)} 处偏离)")
        for i, d in enumerate(fdevs, 1):
            sections.append(f"\n  [{i}] {d.src_label}")
            if d.src_line:
                sections.append(f"      源行: {d.src_line}")
            if d.target_line:
                sections.append(f"      目标: {d.target_line}")
            sections.append(f"      结论: {d.target_label}")
            if d.root_cause:
                sections.append(f"      根因: {d.root_cause}")

    # 偏离分类统计
    src_only = [d for d in devs if d.target_line is None]
    tgt_only = [d for d in devs if d.src_line is None]

    sections.append(f"\n偏离分类:")
    sections.append(f"  源有目标无（跳过/删除）: {len(src_only)} 处")
    sections.append(f"  目标有源无（新增/适配）: {len(tgt_only)} 处")

    # 根因覆盖度
    annotated = [d for d in devs if d.root_cause]
    sections.append(f"\n根因分析:")
    sections.append(f"  有根因标注: {len(annotated)}/{total_devs} 处")
    if not annotated:
        sections.append("  ⚠️ 无根因数据：请检查 execution_log 是否正确记录")

    sections.append("=" * 60)

    return "\n".join(sections)


# ── auto-detect mode ──


def auto_detect_mode(source: str, repo_path: str, target: str) -> str:
    """自动检测是比较模式还是 revert 模式"""
    if source.startswith("patch:"):
        return "merge"

    if source.startswith("commit:"):
        src_hash = source[7:]
        # 检查 target 的 commit message 是否包含 Revert 且引用 source
        try:
            msg = subprocess.run(
                ["git", "-C", repo_path, "log", "-1", "--format=%s", target],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            if "revert" in msg.lower() and src_hash[:8] in msg.lower():
                return "revert"
        except Exception:
            pass

        # 检查 target 是否只做删除操作（父→子的 diff 全是 -）
        try:
            tgt_diff = subprocess.run(
                ["git", "-C", repo_path, "diff", f"{target}~1", target],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            if tgt_diff and not re.search(r"^\+[^+]", tgt_diff, re.MULTILINE):
                return "revert"
        except Exception:
            pass

        return "merge"

    return "merge"


# ── main ──


def main():
    parser = argparse.ArgumentParser(
        description="生成源 patch/commit 与实际 commit 的差异对比报告"
    )
    parser.add_argument(
        "--source", required=True,
        help="源: patch:<path> | commit:<hash>",
    )
    parser.add_argument(
        "--target", required=True,
        help="目标 commit hash（合入/revert 后的实际 commit）",
    )
    parser.add_argument(
        "--repo-path", required=True,
        help="目标内核仓库路径",
    )
    parser.add_argument(
        "--mode", choices=["merge", "revert", "auto"], default="auto",
        help="对比模式（默认 auto 自动推断）",
    )
    parser.add_argument(
        "--execution-log",
        help="merge_tasks.json 路径（用于提取 execution_log 做根因分析）",
    )
    parser.add_argument(
        "--task-id",
        help="task_id（如 0001），用于从 merge_tasks.json 查找 execution_log",
    )
    parser.add_argument(
        "--output",
        help="输出文件路径（不指定则输出到 stdout）",
    )

    args = parser.parse_args()

    src_content = get_diff_content(args.repo_path, args.source)
    tgt_content = get_diff_content(args.repo_path, f"commit:{args.target}")

    src_files = parse_diff_per_file(src_content)
    tgt_files = parse_diff_per_file(tgt_content)

    # 模式
    mode = args.mode
    if mode == "auto":
        mode = auto_detect_mode(args.source, args.repo_path, args.target)

    # 构建源/目标标签
    if args.source.startswith("patch:"):
        src_label = "patch"
        src_desc = f"patch ({args.source[6:]})"
    else:
        src_label = "commit"
        src_desc = f"commit {args.source[7:]}"
    tgt_desc = f"commit {args.target}"

    # execution log
    exec_log: list[dict] | None = None
    if args.execution_log and args.task_id:
        exec_log = load_execution_log(args.execution_log, args.task_id)

    devs = compare_diffs(src_files, tgt_files, src_label, tgt_desc, mode=mode)

    if exec_log:
        annotate_deviation_root_causes(devs, exec_log)

    report = generate_report(devs, src_desc, tgt_desc, mode=mode, execution_log=exec_log)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(report)
        print(f"[DIFF] {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
