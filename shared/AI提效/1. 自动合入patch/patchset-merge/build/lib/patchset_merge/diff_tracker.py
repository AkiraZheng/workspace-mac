"""追踪 patchset 应用后的差异"""
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

@dataclass
class DiffEntry:
    file_path: str
    original_patchset_content: str
    applied_content: str
    reason: str  # "conflict_resolved" | "manual_adjustment"

class DiffTracker:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.diff_entries: List[DiffEntry] = field(default_factory=list)

    def add_entry(self, file_path: str, original: str, applied: str, reason: str):
        """添加差异条目"""
        self.diff_entries.append(DiffEntry(
            file_path=file_path,
            original_patchset_content=original,
            applied_content=applied,
            reason=reason
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
            lines.append(f"**原因**: {entry.reason}\n\n")
            lines.append("**原 patchset 内容**:\n```\n")
            lines.append(entry.original_patchset_content)
            lines.append("\n```\n\n")
            lines.append("**实际应用内容**:\n```\n")
            lines.append(entry.applied_content)
            lines.append("\n```\n\n")
            lines.append("---\n\n")

        return "".join(lines)

    def save_diff_report(self, output_path: Path):
        """保存差异报告到文件"""
        output_path.write_text(self.generate_diff())
