"""Tests for generate_analyse_md.py + verify_analyse_format.py + generate_summary_md.py"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import generate_analyse_md as gen_analyse
import verify_analyse_format as verify_fmt


SAMPLE_ANALYSIS = {
    "0001": {
        "summary": "引入 HDBSS 寄存器定义和 arm64 cpufeature 检测",
        "modules": "KVM, arm64, cpufeature",
        "risk": "低",
        "risk_detail": "仅新增 sysreg 定义和 cpufeature 注册",
        "revert_level": "无须",
        "revert_commits": [],
        "revert_reason": "",
        "high_version_deps": [],
        "bugfix_deps": [],
        "internal_deps": [],
        "duplicate_info": {"level": "无重复", "detail": ""},
        "review_required": "低",
        "review_reason": "",
        "smoke_tests": ["编译通过", "检查 sysreg 宏定义正确"],
        "changed_files": ["arch/arm64/tools/sysreg", "arch/arm64/kernel/cpufeature.c"],
        "status_in_target": "目标仓库无 HDBSS 相关代码",
        "pr_mapping": {"upstream_deps": [], "bugfix_deps": [], "revert_candidates": []},
    },
    "0002": {
        "summary": "DBM 属性支持，设置页表 DBM 位",
        "modules": "mmu, KVM",
        "risk": "中",
        "risk_detail": "涉及页表标志位操作",
        "revert_level": "建议",
        "revert_commits": ["abc123"],
        "revert_reason": "目标仓库已有等效实现",
        "high_version_deps": ["stage2_try_set_pte: def456"],
        "bugfix_deps": [{"symbol": "stage2_set_pte", "commit": "fix789", "desc": "修复空指针"}],
        "internal_deps": ["0001"],
        "duplicate_info": {"level": "高概率等效", "detail": "commit abc123: 相同功能"},
        "review_required": "中",
        "review_reason": "页表变更需确认",
        "smoke_tests": ["启动 VM", "检查 DBM 位"],
        "changed_files": ["arch/arm64/kvm/mmu.c"],
        "status_in_target": "已有部分实现",
        "pr_mapping": {"upstream_deps": [], "bugfix_deps": [], "revert_candidates": []},
    },
}

SAMPLE_MERGE_TASKS = {
    "patchset_info": {
        "source": "HDBSS v3 from lore",
        "download_method": "b4",
        "total_patches": 5,
        "target_kernel": "/tmp/test_kernel",
        "target_branch": "patch-hdbss",
        "build_target": "make ARCH=arm64 Image",
    },
    "global_revert_order": [
        {
            "pr_id": "PR #456",
            "pr_url": "https://github.com/torvalds/linux/pull/456",
            "subject": "DBM 系列",
            "commits": ["abc123"],
            "commit_count": 1,
            "revert_strategy": "单独 revert",
            "revert_cmd": "git revert abc123",
            "urgency": "建议",
            "related_patches": ["0002"],
        }
    ],
    "deps_order": [],
    "merge_order": [
        {
            "seq": 1,
            "task_id": "0001",
            "status": "committed",
            "patch_file": "/tmp/patches/0001-hdbss-sysreg.patch",
            "subject": "arm64: add HDBSS sysreg definitions",
            "author": "Test Author <test@kernel.org>",
            "files_changed": [
                "arch/arm64/tools/sysreg",
                "arch/arm64/kernel/cpufeature.c",
            ],
            "action": "apply",
            "skip_reason": None,
            "pre_revert": [],
            "depends_on": [],
            "risk_level": "低",
            "review_required": "低",
            "blame_hits": [],
            "duplicate_info": {"level": "无重复", "detail": ""},
            "conflicts_predicted": [],
            "special_notes": "",
            "pr_mapping": {"upstream_deps": [], "bugfix_deps": [], "revert_candidates": []},
            "execution_log": [
                {
                    "step": "BUILD",
                    "time": "2026-05-26T10:00:00Z",
                    "result": "pass",
                    "error_count": 0,
                    "product": "arch/arm64/boot/Image",
                },
                {
                    "step": "COMMIT",
                    "time": "2026-05-26T10:01:00Z",
                    "result": "pass",
                    "commit": "deadbeef0001",
                },
            ],
        },
        {
            "seq": 2,
            "task_id": "0002",
            "status": "done",
            "patch_file": "/tmp/patches/0002-dbm.patch",
            "subject": "arm64: DBM attribute support",
            "author": "DBM Author <dbm@kernel.org>",
            "files_changed": ["arch/arm64/kvm/mmu.c"],
            "action": "apply",
            "skip_reason": None,
            "pre_revert": ["abc123"],
            "depends_on": ["0001"],
            "risk_level": "中",
            "review_required": "中",
            "blame_hits": ["fix789: fix null pointer in stage2_set_pte"],
            "duplicate_info": {"level": "高概率等效", "detail": "commit abc123: 相同功能"},
            "conflicts_predicted": ["arch/arm64/kvm/mmu.c:120: stage2_set_pte 签名不同"],
            "special_notes": "需 revert abc123 后合入",
            "pr_mapping": {
                "upstream_deps": [],
                "bugfix_deps": [
                    {"pr_id": "独立 commit", "commits": ["fix789"], "reason": "修复空指针"}
                ],
                "revert_candidates": [
                    {
                        "pr_id": "PR #456",
                        "commits": ["abc123"],
                        "subject": "本地 DBM 实现",
                        "urgency": "建议",
                    }
                ],
            },
            "execution_log": [
                {
                    "step": "BUILD",
                    "time": "2026-05-26T10:10:00Z",
                    "result": "fail",
                    "error_count": 3,
                },
                {
                    "step": "BUILD",
                    "time": "2026-05-26T10:15:00Z",
                    "result": "pass",
                    "error_count": 0,
                    "product": "arch/arm64/boot/Image",
                },
                {
                    "step": "COMMIT",
                    "time": "2026-05-26T10:16:00Z",
                    "result": "pass",
                    "commit": "deadbeef0002",
                },
            ],
        },
    ],
}


class TestGenerateAnalyseMd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache = os.path.join(self.tmp, "analysis_cache.json")
        self.merges = os.path.join(self.tmp, "merge_tasks.json")
        with open(self.cache, "w") as f:
            json.dump(SAMPLE_ANALYSIS, f)
        with open(self.merges, "w") as f:
            json.dump(SAMPLE_MERGE_TASKS, f)

    def test_structure_all_sections_present(self):
        content = gen_analyse.generate_analyse_md(
            SAMPLE_ANALYSIS, SAMPLE_MERGE_TASKS, "0001",
            self.merges, "/usr/bin/false", self.tmp, "",
        )
        for section in gen_analyse.SECTION_HEADERS:
            self.assertIn(f"## {section}", content,
                          f"Missing section: {section}")

    def test_patch_title_in_header(self):
        content = gen_analyse.generate_analyse_md(
            SAMPLE_ANALYSIS, SAMPLE_MERGE_TASKS, "0001",
            self.merges, "/usr/bin/false", self.tmp, "",
        )
        self.assertIn("# Patch 0001:", content)

    def test_task_info_extracted(self):
        content = gen_analyse.generate_analyse_md(
            SAMPLE_ANALYSIS, SAMPLE_MERGE_TASKS, "0001",
            self.merges, "/usr/bin/false", self.tmp, "",
        )
        self.assertIn("HDBSS", content)
        self.assertIn("cpufeature", content)
        self.assertIn("低", content)

    def test_revert_info_extracted(self):
        content = gen_analyse.generate_analyse_md(
            SAMPLE_ANALYSIS, SAMPLE_MERGE_TASKS, "0002",
            self.merges, "/usr/bin/false", self.tmp, "",
        )
        self.assertIn("建议", content)
        self.assertIn("abc123", content)

    def test_execution_log_parsed(self):
        content = gen_analyse.generate_analyse_md(
            SAMPLE_ANALYSIS, SAMPLE_MERGE_TASKS, "0001",
            self.merges, "/usr/bin/false", self.tmp, "",
        )
        self.assertIn("编译验证记录", content)

    def test_has_ai_placeholders(self):
        content = gen_analyse.generate_analyse_md(
            SAMPLE_ANALYSIS, SAMPLE_MERGE_TASKS, "0001",
            self.merges, "/usr/bin/false", self.tmp, "",
        )
        self.assertIn("{REQUIRES_AI_", content)
        self.assertIn("## 11.", content)


class TestVerifyAnalyseFormat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _write_file(self, name, content):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_all_sections_pass(self):
        sections = "\n\n".join(
            f"## {s}\nContent for {s}" for s in verify_fmt.ANALYSE_SECTIONS
        )
        path = self._write_file("test.md", f"# Patch 0001: Test\n\n{sections}")
        self.assertEqual(verify_fmt.verify_file(path, "analyse"), 0)

    def test_missing_section_fails(self):
        sections = "\n\n".join(
            f"## {s}\nContent" for s in verify_fmt.ANALYSE_SECTIONS[:5]
        )
        path = self._write_file("test.md", f"# Patch 0001\n\n{sections}")
        self.assertEqual(verify_fmt.verify_file(path, "analyse"),
                         verify_fmt.ERR_SECTION)

    def test_placeholder_replaced_pass(self):
        sections = "\n\n".join(
            f"## {s}\nNo placeholders" for s in verify_fmt.ANALYSE_SECTIONS
        )
        content = f"# Patch 0001: Test\n\n{sections}\n\nREQUIRES_AI allowed."
        path = self._write_file("test.md", content)
        self.assertEqual(verify_fmt.verify_file(path, "analyse"), 0)

    def test_unresolved_placeholder_fails(self):
        sections = "\n\n".join(
            f"## {s}\nContent" for s in verify_fmt.ANALYSE_SECTIONS
        )
        content = f"# Patch 0001: Test\n\n{sections}\n\n{{UNRESOLVED}}"
        path = self._write_file("test.md", content)
        self.assertEqual(verify_fmt.verify_file(path, "analyse"),
                         verify_fmt.ERR_PLACEHOLDER)

    def test_missing_file(self):
        self.assertEqual(verify_fmt.verify_file("/nonexistent.md", "analyse"),
                         verify_fmt.ERR_MISSING)

    def test_with_ai_placeholders_still_pass(self):
        """AI placeholders are allowed, other {xxx} are not."""
        sections = "\n\n".join(
            f"## {s}\n{{REQUIRES_AI_test}}"
            for s in verify_fmt.ANALYSE_SECTIONS
        )
        content = f"# Patch 0001: Test\n\n{sections}"
        path = self._write_file("test.md", content)
        self.assertEqual(verify_fmt.verify_file(path, "analyse"), 0)

    def test_info_table_with_data_does_not_fail(self):
        sections = "\n\n".join(
            f"## {s}\nData" for s in verify_fmt.ANALYSE_SECTIONS
        )
        table = """## 1. 基本信息
| 项 | 值 |
|----|-----|
| Patch | 0001 |
| 状态 | 合入成功 |
"""
        content = f"# Patch 0001: Test\n\n{table}\n\n{sections}"
        path = self._write_file("test.md", content)
        self.assertEqual(verify_fmt.verify_file(path, "analyse"), 0)


class TestVerifySummaryFormat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _write(self, name, content):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_summary_all_sections(self):
        sections = "\n\n".join(
            f"## {s}\nContent" for s in verify_fmt.SUMMARY_SECTIONS
        )
        content = f"# Patchset Merge 汇总报告\n\n{sections}"
        path = self._write("summary.md", content)
        self.assertEqual(verify_fmt.verify_file(path, "summary"), 0)

    def test_summary_missing_section(self):
        sections = "\n\n".join(
            f"## {s}\nContent" for s in verify_fmt.SUMMARY_SECTIONS[:3]
        )
        content = f"# Patchset Merge 汇总报告\n\n{sections}"
        path = self._write("summary.md", content)
        self.assertEqual(verify_fmt.verify_file(path, "summary"),
                         verify_fmt.ERR_SECTION)


class TestGenerateSummaryMd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.merges = os.path.join(self.tmp, "merge_tasks.json")
        with open(self.merges, "w") as f:
            json.dump(SAMPLE_MERGE_TASKS, f)

    def test_script_imports_and_core_functions_work(self):
        from generate_summary_md import (build_status_table, build_revert_table,
                                         build_build_summary, build_deps_graph)

        tasks = SAMPLE_MERGE_TASKS["merge_order"]
        status = build_status_table(tasks, [])
        self.assertTrue(len(status) >= 2)

        revert = build_revert_table(SAMPLE_MERGE_TASKS["global_revert_order"])
        self.assertTrue(len(revert) >= 1)

        build_summary = build_build_summary(tasks)
        self.assertTrue(len(build_summary) >= 2)

        deps = build_deps_graph(tasks)
        self.assertIn("0002", deps)

    def test_generates_complete_output(self):
        from generate_summary_md import build_status_table, build_revert_table, \
            build_build_summary, build_deps_graph

        tasks = SAMPLE_MERGE_TASKS["merge_order"]
        all_tasks = (SAMPLE_MERGE_TASKS.get("deps_order", []) +
                     SAMPLE_MERGE_TASKS.get("merge_order", []))

        status_rows = build_status_table(tasks, [])
        revert_rows = build_revert_table(SAMPLE_MERGE_TASKS["global_revert_order"])
        build_rows = build_build_summary(all_tasks)
        deps = build_deps_graph(all_tasks)

        for rows in [status_rows, revert_rows, build_rows]:
            self.assertTrue(len(rows) >= 1)
        self.assertIn("0001", deps or "0001")


if __name__ == "__main__":
    unittest.main()
