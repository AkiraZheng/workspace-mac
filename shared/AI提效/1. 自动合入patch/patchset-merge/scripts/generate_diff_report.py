#!/usr/bin/env python3
"""Generate diff comparison report between original patch and applied commit.

Output sections:
  1. 原始 patch（source patch content）
  2. 实际应用 diff（git show of the commit）
  3. 差异对比（diff of diffs: lines that deviated from original）
"""

from __future__ import annotations

import sys
import argparse
import subprocess


def parse_changed_lines(patch_content: str) -> list[str]:
    """Extract only the +/- changed lines from a patch string."""
    lines = []
    in_hunk = False
    for line in patch_content.split("\n"):
        if line.startswith("@@") and "@@" in line[2:]:
            in_hunk = True
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            in_hunk = False
            continue
        if line.startswith("diff --git") or line.startswith("index "):
            in_hunk = False
            continue
        if in_hunk and (line.startswith("+") or line.startswith("-")):
            lines.append(line)
    return lines


def read_patch_file(patch_path: str) -> str:
    """Read the content of a .patch file."""
    with open(patch_path, "r") as f:
        return f.read()


def get_commit_diff(repo_path: str, commit_hash: str) -> str:
    """Run git show to get the diff of a specific commit."""
    result = subprocess.run(
        ["git", "-C", repo_path, "show", commit_hash],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git show failed: {result.stderr.strip()}")
    return result.stdout


def compare_diffs(original_lines: list[str], actual_lines: list[str]) -> list[str]:
    """Compare two lists of changed lines and report differences."""
    differences = []

    org_clean = set()
    for line in original_lines:
        if line[0] in "+-":
            org_clean.add(line[1:])

    act_clean = set()
    for line in actual_lines:
        stripped = line.strip()
        if stripped and stripped[0] in "+-":
            act_clean.add(stripped[1:])

    only_in_original = org_clean - act_clean
    only_in_actual = act_clean - org_clean

    for line in sorted(only_in_original):
        differences.append(f"- [仅源 patch] {line}")
    for line in sorted(only_in_actual):
        differences.append(f"+ [仅实际应用] {line}")

    return differences


def generate_report(
    original_content: str,
    actual_content: str,
    original_path: str | None = None,
    commit: str | None = None,
) -> str:
    """Generate the full diff comparison report."""
    sections = []

    sections.append("=" * 60)
    sections.append("## 原始 patch")
    if original_path:
        sections.append(f"来源: {original_path}")
    sections.append("=" * 60)
    sections.append(original_content)
    sections.append("")

    sections.append("=" * 60)
    sections.append("## 实际应用 diff")
    if commit:
        sections.append(f"Commit: {commit}")
    sections.append("=" * 60)
    sections.append(actual_content)
    sections.append("")

    orig_changed = parse_changed_lines(original_content)
    actual_changed = []
    in_diff_section = False
    for line in actual_content.split("\n"):
        if (
            line.startswith("diff --git")
            or line.startswith("--- ")
            or line.startswith("@@ ")
        ):
            in_diff_section = True
            continue
        if (
            in_diff_section
            and line.startswith(("+", "-"))
            and not line.startswith(("--- ", "+++ "))
        ):
            actual_changed.append(line)

    differences = compare_diffs(orig_changed, actual_changed)

    sections.append("=" * 60)
    sections.append("## 差异对比")
    if differences:
        sections.append("以下行在原始 patch 和实际应用之间存在差异：")
        sections.extend(differences)
    else:
        sections.append("实际应用与原始 patch 完全一致（无冲突解决导致的代码偏离）。")
    sections.append("=" * 60)

    return "\n".join(sections)


def main():
    parser = argparse.ArgumentParser(
        description="Generate patch diff comparison report"
    )
    parser.add_argument(
        "--patch-file", required=True,
        help="Path to original .patch file",
    )
    parser.add_argument(
        "--repo-path", required=True,
        help="Path to kernel repo",
    )
    parser.add_argument(
        "--commit", required=True,
        help="Commit hash of the applied patch",
    )
    args = parser.parse_args()

    original_content = read_patch_file(args.patch_file)
    actual_content = get_commit_diff(args.repo_path, args.commit)
    report = generate_report(
        original_content, actual_content, args.patch_file, args.commit
    )
    print(report)


if __name__ == "__main__":
    main()
