"""追踪 patchset 应用后的差异"""
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import List

@dataclass
class DiffEntry:
    file_path: str
    original_patchset_content: str
    applied_content: str
    reason: str  # "conflict_resolved" | "manual_adjustment" | "auto_merged"
    patch_hash: str = ""  # 来自哪个 patch
    line_range: tuple[int, int] = (0, 0)  # 在原文件中的位置

class DiffTracker:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.diff_entries: List[DiffEntry] = []

    def add_entry(self, file_path: str, original: str, applied: str, reason: str,
                  patch_hash: str = "", line_range: tuple[int, int] = (0, 0)):
        """添加差异条目"""
        self.diff_entries.append(DiffEntry(
            file_path=file_path,
            original_patchset_content=original,
            applied_content=applied,
            reason=reason,
            patch_hash=patch_hash,
            line_range=line_range
        ))

    def generate_diff(self) -> str:
        """生成与原 patchset 的差异报告"""
        lines = ["# Patchset 应用差异报告\n"]
        lines.append(f"**生成时间**: {datetime.now().isoformat()}\n")
        lines.append("---\n\n")

        if not self.diff_entries:
            lines.append("*无差异*\n")
            return "".join(lines)

        for entry in self.diff_entries:
            lines.append(f"## {entry.file_path}\n")
            lines.append(f"**原因**: {entry.reason}\n")
            if entry.patch_hash:
                lines.append(f"**Patch Hash**: `{entry.patch_hash[:16]}...`\n")
            if entry.line_range != (0, 0):
                lines.append(f"**行范围**: {entry.line_range[0]}-{entry.line_range[1]}\n")
            lines.append("\n")

            if entry.reason == "patch_not_applied":
                lines.append("*此文件未被 patch 修改（patch 未成功应用）*\n\n")
                lines.append("**当前代码内容**:\n```\n")
                lines.append(entry.applied_content)
                lines.append("\n```\n\n")
            else:
                lines.append("**原 patchset 内容**:\n```\n")
                lines.append(entry.original_patchset_content)
                lines.append("\n```\n\n")
                lines.append("**实际应用内容**:\n```\n")
                lines.append(entry.applied_content)
                lines.append("\n```\n\n")
            lines.append("---\n\n")

        return "".join(lines)

    def generate_html_diff(self) -> str:
        """生成 HTML 格式的差异报告"""
        html_parts = [
            "<!DOCTYPE html>",
            "<html><head><meta charset='utf-8'><title>Patchset Diff Report</title>",
            "<style>",
            "body { font-family: monospace; margin: 20px; }",
            ".added { background-color: #d4edda; }",
            ".removed { background-color: #f8d7da; }",
            ".modified { background-color: #fff3cd; }",
            ".file { margin-bottom: 20px; border: 1px solid #ddd; padding: 10px; }",
            "</style></head><body>",
            "<h1>Patchset 应用差异报告</h1>"
        ]

        for entry in self.diff_entries:
            css_class = "modified"
            if entry.reason == "conflict_resolved":
                css_class = "removed"
            elif entry.reason == "manual_adjustment":
                css_class = "modified"

            html_parts.append(f"<div class='file {css_class}'>")
            html_parts.append(f"<h3>{entry.file_path}</h3>")
            html_parts.append(f"<p><strong>原因:</strong> {entry.reason}</p>")
            if entry.patch_hash:
                html_parts.append(f"<p><strong>Patch:</strong> {entry.patch_hash[:16]}...</p>")
            html_parts.append(f"<pre>原内容:\n{entry.original_patchset_content}\n\n")
            html_parts.append(f"应用后:\n{entry.applied_content}</pre>")
            html_parts.append("</div>")

        html_parts.append("</body></html>")
        return "\n".join(html_parts)

    def save_diff_report(self, output_path: Path):
        """保存差异报告到文件"""
        output_path.write_text(self.generate_diff())
