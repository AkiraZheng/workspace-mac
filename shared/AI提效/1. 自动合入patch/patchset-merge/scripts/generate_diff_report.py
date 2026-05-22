#!/usr/bin/env python3
"""Generate diff comparison report: source patch/commit vs actual commit.

比较源 patch/commit 的意图与实际 commit 的结果，只输出差异（偏离）部分。

source 格式:
  patch:<path>   — merge 场景：原始 .patch 文件
  commit:<hash>  — revert 场景：被 revert 的原 commit
"""

from __future__ import annotations

import sys
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
        # 检测文件头
        if line.startswith("diff --git"):
            if current:
                files.append(current)
            m = re.match(r"diff --git a/(.*) b/(.*)", line)
            fname = m.group(1) if m else ""
            current = FileDiff(file_path=fname)
            continue

        if current is None:
            continue

        # 跳过 diff 元数据行（index, ---, +++, @@）
        if (line.startswith("index ")
                or line.startswith("--- ")
                or line.startswith("+++ ")
                or line.startswith("@@")):
            continue

        # 收集 +/- 行
        if line.startswith("+") and not line.startswith("+++"):
            current.added.append("\t" + line)
        elif line.startswith("-") and not line.startswith("---"):
            current.removed.append("\t" + line)

    if current:
        files.append(current)

    return files


def build_line_index(files: list[FileDiff], which: str) -> dict[str, dict[str, set[str]]]:
    """构建文件→行集合索引。

    which: 'added' or 'removed' — 专注看添加的行还是删除的行。
    返回: {file_path: {operator_sign: set(line_content)}}
    """
    idx: dict[str, dict[str, set[str]]] = {}
    for f in files:
        if not f.file_path:
            continue
        idx[f.file_path] = idx.get(f.file_path, {"+": set(), "-": set()})
        for a in f.added:
            idx[f.file_path]["+"].add(a[1:].strip())
        for r in f.removed:
            idx[f.file_path]["-"].add(r[1:].strip())
    return idx


def compare_diffs(src_files: list[FileDiff], tgt_files: list[FileDiff],
                  src_label: str, tgt_label: str) -> list[Deviation]:
    """比较源文件和目标文件的差异，返回偏离列表"""
    src_idx = build_line_index(src_files, "src")
    tgt_idx = build_line_index(tgt_files, "tgt")

    deviations: list[Deviation] = []

    all_files = set(src_idx.keys()) | set(tgt_idx.keys())
    for fpath in sorted(all_files):
        src_signs = src_idx.get(fpath, {"+": set(), "-": set()})
        tgt_signs = tgt_idx.get(fpath, {"+": set(), "-": set()})

        # 比较添加的行：源有目标无
        only_src_added = src_signs["+"] - tgt_signs["+"]
        for line in sorted(only_src_added):
            deviations.append(Deviation(
                file_path=fpath,
                src_line=line,
                src_label=f"源 {src_label}",
                target_label="实际 commit 无此行",
            ))

        # 比较删除的行：源有目标无
        only_src_removed = src_signs["-"] - tgt_signs["-"]
        for line in sorted(only_src_removed):
            deviations.append(Deviation(
                file_path=fpath,
                src_line=line,
                src_label=f"源 {src_label}",
                target_label="实际 commit 无此行",
            ))

        # 比较添加的行：目标有源无
        only_tgt_added = tgt_signs["+"] - src_signs["+"]
        for line in sorted(only_tgt_added):
            deviations.append(Deviation(
                file_path=fpath,
                src_label=f"源 {src_label} 无此行",
                target_line=line,
                target_label=f"实际 commit {tgt_label}",
            ))

        # 比较删除的行：目标有源无
        only_tgt_removed = tgt_signs["-"] - src_signs["-"]
        for line in sorted(only_tgt_removed):
            deviations.append(Deviation(
                file_path=fpath,
                src_label=f"源 {src_label} 无此行",
                target_line=line,
                target_label=f"实际 commit {tgt_label}",
            ))

    return deviations


# ── report ──


def generate_report(devs: list[Deviation], src_desc: str, tgt_desc: str) -> str:
    """生成差异对比报告（只输出偏离部分）"""

    sections: list[str] = []
    sections.append("=" * 60)
    sections.append("差异对比报告")
    sections.append("=" * 60)
    sections.append(f"源:   {src_desc}")
    sections.append(f"目标: {tgt_desc}")
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

    # 偏离分类统计
    src_only = [d for d in devs if d.target_line is None]
    tgt_only = [d for d in devs if d.src_line is None]

    sections.append(f"\n偏离分类:")
    sections.append(f"  源有目标无（跳过/删除）: {len(src_only)} 处")
    sections.append(f"  目标有源无（新增/适配）: {len(tgt_only)} 处")
    sections.append("=" * 60)

    return "\n".join(sections)


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
    args = parser.parse_args()

    src_content = get_diff_content(args.repo_path, args.source)
    tgt_content = get_diff_content(args.repo_path, f"commit:{args.target}")

    src_files = parse_diff_per_file(src_content)
    tgt_files = parse_diff_per_file(tgt_content)

    # 构建源/目标标签
    if args.source.startswith("patch:"):
        src_label = "patch"
        src_desc = f"patch ({args.source[6:]})"
    else:
        src_label = "commit"
        src_desc = f"commit {args.source[7:]}"
    tgt_desc = f"commit {args.target}"

    devs = compare_diffs(src_files, tgt_files, src_label, tgt_desc)

    report = generate_report(devs, src_desc, tgt_desc)
    print(report)


if __name__ == "__main__":
    main()
