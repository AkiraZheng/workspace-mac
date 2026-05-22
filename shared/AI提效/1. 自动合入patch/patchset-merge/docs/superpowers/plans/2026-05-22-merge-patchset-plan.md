# Merge-Patchset Skill 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个 OpenCode Skill，实现 Linux 内核 patchset 的多 Agent 深度分析→串行合入→编译验证→review 完整工作流。

**Architecture:** SKILL.md（主入口）+ scripts/（确定性脚本）+ references/（参考文档）。外部编排，Skill 描述工作流，JSON 文件驱动各阶段。

**Tech Stack:** Python 3（scripts）、Markdown（SKILL.md / references）、git / b4 / make（运行时工具）

---

## 文件结构

```
merge-patchset/
├── SKILL.md                              # 新建：主 Skill 文件
├── AGENTS.md                             # 已存在
├── scripts/
│   ├── download_patches.py               # 新建：统一下载入口
│   └── generate_diff_report.py           # 新建：diff 对比生成
├── references/
│   ├── code-review-expert/
│   │   └── SKILL.md                      # 新建：捆绑的 review skill
│   ├── output-templates.md               # 新建：analyse.md 模板
│   └── diagnostic-guide.md               # 新建：冲突诊断决策树
├── tests/
│   ├── test_download_patches.py          # 新建
│   └── test_generate_diff_report.py      # 新建
└── docs/superpowers/
    ├── specs/2026-05-22-merge-patchset-design.md  # 已存在
    └── plans/2026-05-22-merge-patchset-plan.md    # 本文件
```

---

## Task 1: 目录结构初始化

**Files:**
- Create: `scripts/` (目录)
- Create: `references/code-review-expert/` (目录)
- Create: `tests/` (目录)

- [ ] **Step 1: 创建目录**

```bash
mkdir -p /mnt/shared/AI提效/1.\ 自动合入patch/patchset-merge/scripts
mkdir -p /mnt/shared/AI提效/1.\ 自动合入patch/patchset-merge/references/code-review-expert
mkdir -p /mnt/shared/AI提效/1.\ 自动合入patch/patchset-merge/tests
```

- [ ] **Step 2: 创建 tests/__init__.py（空文件）**

```bash
touch /mnt/shared/AI提效/1.\ 自动合入patch/patchset-merge/tests/__init__.py
```

- [ ] **Step 3: 提交**

```bash
git add scripts/ references/ tests/
git commit -m "chore: init directory structure for merge-patchset skill"
```

---

## Task 2: references/diagnostic-guide.md — 冲突诊断决策树

**Files:**
- Create: `references/diagnostic-guide.md`

> 无 pytest 测试——这是给 LLM 读取的参考文档，验证方式：对照 spec 中定义的决策树逐条确认覆盖。

- [ ] **Step 1: 写入诊断指南**

写入文件 `references/diagnostic-guide.md`，内容包括：Ours vs Theirs 决策表（7 种场景 + 2 种无法判定）、APPLY 降级链流程图、最小化修改 4 原则、编译修复 3 类处理方式。全文见 spec 第 6 节。

- [ ] **Step 2: 提交**

```bash
git add references/diagnostic-guide.md
git commit -m "docs: add conflict resolution diagnostic guide"
```

---

## Task 3: references/output-templates.md — 输出模板

**Files:**
- Create: `references/output-templates.md`

- [ ] **Step 1: 写入固定模板**

写入文件 `references/output-templates.md`，内容包括：
1. `analyse.md` 固定模板（10 节，含 {placeholder} 占位符和 NOT_FOUND 标记）
2. `summary.md` 固定模板（8 节）
3. Phase 1 分析 Agent 屏幕输出结构化格式

全文见 spec 第 7 节。

- [ ] **Step 2: 提交**

```bash
git add references/output-templates.md
git commit -m "docs: add output templates for analyse.md and summary.md"
```

---

## Task 4: references/code-review-expert/SKILL.md — 捆绑 Review Skill

**Files:**
- Create: `references/code-review-expert/SKILL.md`

- [ ] **Step 1: 检查是否有现成 skill 可复制**

```bash
ls /root/.agents/skills/code-review-expert/SKILL.md 2>/dev/null && echo "EXISTS" || echo "NOT_FOUND"
```

- [ ] **Step 2: 若存在则复制，否则新建简化版**

若 `/root/.agents/skills/code-review-expert/SKILL.md` 存在 → 复制到 `references/code-review-expert/SKILL.md`

若不存在 → 创建简化版，包含 4 个 review 维度：
1. Correctness（逻辑正确性）
2. Security（安全审计：溢出/空指针/锁/内存分配）
3. Style（内核编码风格）
4. Review Output Format（MUST FIX / SUGGEST / 结论三段式）

- [ ] **Step 3: 提交**

```bash
git add references/code-review-expert/SKILL.md
git commit -m "feat: bundle code-review-expert skill for merge-patchset"
```

---

## Task 5: scripts/download_patches.py — TDD

**Files:**
- Create: `tests/test_download_patches.py`
- Create: `scripts/download_patches.py`

### 5.1: 写失败的测试

- [ ] **Step 1: 创建 tests/test_download_patches.py**

```python
"""Tests for download_patches.py - unified patchset download script."""

import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import download_patches as dp


class TestParseArgs(unittest.TestCase):
    def test_parse_message_id(self):
        result = dp.detect_source_type(
            "<20240501000000.12345-1-user@kernel.org>"
        )
        self.assertEqual(result, "message-id")

    def test_parse_url_lore(self):
        result = dp.detect_source_type(
            "https://lore.kernel.org/all/20240501000000.12345-1-user@kernel.org/"
        )
        self.assertEqual(result, "url")

    def test_parse_url_patchwork(self):
        result = dp.detect_source_type(
            "https://patchwork.kernel.org/project/linux-arm-kernel/patch/12345/"
        )
        self.assertEqual(result, "url")

    def test_parse_local_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = dp.detect_source_type(tmpdir)
            self.assertEqual(result, "local")

    def test_parse_local_file(self):
        with tempfile.NamedTemporaryFile(suffix=".patch") as tmpfile:
            result = dp.detect_source_type(tmpfile.name)
            self.assertEqual(result, "local")

    def test_parse_invalid(self):
        with self.assertRaises(ValueError):
            dp.detect_source_type("not_a_valid_source")


class TestB4Download(unittest.TestCase):
    @patch("subprocess.run")
    def test_b4_command_constructed(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="OK")
        result = dp.download_via_b4(
            "<20240501000000.12345-1-user@kernel.org>",
            "/tmp/test_patches",
        )
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("b4", cmd)
        self.assertIn("am", cmd)
        self.assertIn("20240501000000.12345-1-user@kernel.org", cmd)
        self.assertIn("/tmp/test_patches", cmd)

    @patch("subprocess.run")
    def test_b4_not_installed(self, mock_run):
        mock_run.side_effect = FileNotFoundError("b4 not found")
        with self.assertRaises(RuntimeError) as ctx:
            dp.download_via_b4("<msg-id>", "/tmp/test_patches")
        self.assertIn("b4", str(ctx.exception).lower())


class TestProxyDetection(unittest.TestCase):
    def setUp(self):
        self.saved_env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved_env)

    def test_proxy_from_env(self):
        os.environ["http_proxy"] = "http://proxy:8080"
        proxy = dp.detect_proxy()
        self.assertEqual(proxy, "http://proxy:8080")

    def test_https_proxy_preferred(self):
        os.environ["http_proxy"] = "http://proxy:8080"
        os.environ["https_proxy"] = "https://secure-proxy:8443"
        proxy = dp.detect_proxy()
        self.assertEqual(proxy, "https://secure-proxy:8443")

    def test_no_proxy(self):
        os.environ.pop("http_proxy", None)
        os.environ.pop("https_proxy", None)
        proxy = dp.detect_proxy()
        self.assertIsNone(proxy)


class TestOutputNaming(unittest.TestCase):
    def test_pad_number(self):
        self.assertEqual(dp.pad_patch_number(1), "0001")
        self.assertEqual(dp.pad_patch_number(42), "0042")
        self.assertEqual(dp.pad_patch_number(9999), "9999")

    def test_sanitize_filename(self):
        result = dp.sanitize_filename(
            "KVM: arm64: Support 5-level paging in stage-2?"
        )
        self.assertNotIn(":", result)
        self.assertNotIn("?", result)
        self.assertNotIn(" ", result)
        self.assertEqual(result, "KVM-arm64-Support-5-level-paging-in-stage-2")

    def test_generate_output_name(self):
        result = dp.generate_output_name(1, "KVM: arm64: Fix mmu bug")
        self.assertEqual(result, "0001-KVM-arm64-Fix-mmu-bug.patch")


class TestMetadataGeneration(unittest.TestCase):
    def test_generate_metadata(self):
        patches = [{
            "id": "0001",
            "file": "/tmp/patches/0001-test.patch",
            "subject": "Test patch",
            "author": "test@kernel.org",
            "date": "2024-05-01",
            "upstream_commit": "abc123",
        }]
        metadata = dp.generate_metadata(
            source="<test-msg-id>",
            method="b4",
            total=1,
            target_kernel="/home/user/kernel",
            target_branch="main",
            build_target="make ARCH=arm64 Image",
            patches=patches,
        )
        self.assertEqual(metadata["source"], "<test-msg-id>")
        self.assertEqual(metadata["download_method"], "b4")
        self.assertEqual(metadata["total_patches"], 1)
        self.assertEqual(len(metadata["patches"]), 1)
        self.assertEqual(metadata["patches"][0]["id"], "0001")


class TestLocalCopy(unittest.TestCase):
    def test_copy_patch_files(self):
        with tempfile.TemporaryDirectory() as srcdir:
            with tempfile.TemporaryDirectory() as dstdir:
                src = os.path.join(srcdir, "some-patch.patch")
                with open(src, "w") as f:
                    f.write("dummy patch content\n")
                results = dp.copy_from_local(srcdir, dstdir)
                self.assertEqual(len(results), 1)
                dest = os.path.join(dstdir, os.path.basename(src))
                self.assertTrue(os.path.exists(dest))
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd "/mnt/shared/AI提效/1. 自动合入patch/patchset-merge"
python3 -m pytest tests/test_download_patches.py -v
```

预期：全部 FAIL（`ModuleNotFoundError: No module named 'download_patches'`）

### 5.2: 实现 scripts/download_patches.py

- [ ] **Step 3: 创建 scripts/download_patches.py**

实现以下函数：
- `detect_source_type(source)` — 识别 message-id/URL/local
- `detect_proxy()` — 检测环境变量中的代理
- `download_via_b4(msg_id, out_dir, proxy)` — b4 am 下载
- `download_via_url(url, out_dir, proxy)` — wget 下载
- `copy_from_local(src, out_dir)` — 本地复制 .patch 文件
- `pad_patch_number(n)` — 补零到 4 位
- `sanitize_filename(subject)` — 安全文件名
- `generate_output_name(idx, subject)` — 生成 "0001-xxx.patch"
- `generate_metadata(...)` — 生成 metadata.json
- `main()` — CLI 入口

注意：`str | None` 语法需要 `from __future__ import annotations`。

- [ ] **Step 4: 运行测试确认通过**

```bash
python3 -m pytest tests/test_download_patches.py -v
```

预期：全部 PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/download_patches.py tests/test_download_patches.py
git commit -m "feat: add download_patches.py with unified b4/wget/local support"
```

---

## Task 6: scripts/generate_diff_report.py — TDD

**Files:**
- Create: `tests/test_generate_diff_report.py`
- Create: `scripts/generate_diff_report.py`

### 6.1: 写失败的测试

- [ ] **Step 1: 创建 tests/test_generate_diff_report.py**

```python
"""Tests for generate_diff_report.py - diff comparison generator."""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import generate_diff_report as gdr


class TestDiffParsing(unittest.TestCase):
    def test_parse_patch_changed_lines(self):
        patch_content = (
            "--- a/file.c\n"
            "+++ b/file.c\n"
            "@@ -10,6 +10,8 @@\n"
            " unchanged line\n"
            "-deleted line\n"
            "+added line\n"
            " another unchanged\n"
        )
        lines = gdr.parse_changed_lines(patch_content)
        self.assertIn("-deleted line", lines)
        self.assertIn("+added line", lines)
        self.assertNotIn("unchanged line", lines)

    def test_parse_patch_ignores_context(self):
        patch_content = (
            "@@ -1,3 +1,3 @@\n"
            " context\n"
            "+new\n"
            "-context\n"
            " old\n"
        )
        lines = gdr.parse_changed_lines(patch_content)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0], "+new")


class TestDiffComparison(unittest.TestCase):
    def test_compare_no_changes(self):
        original = ["+added_function()"]
        actual = ["+added_function()"]
        differences = gdr.compare_diffs(original, actual)
        self.assertEqual(len(differences), 0)

    def test_compare_deviations(self):
        original = ["+func_with_param(int x)"]
        actual = ["+func_with_param(int x, int y)"]
        differences = gdr.compare_diffs(original, actual)
        self.assertGreater(len(differences), 0)

    def test_compare_missing_lines(self):
        original = ["+line_one", "+line_two"]
        actual = ["+line_one"]
        differences = gdr.compare_diffs(original, actual)
        self.assertGreater(len(differences), 0)


class TestReportGeneration(unittest.TestCase):
    def test_generate_report_structure(self):
        report = gdr.generate_report("+test_func()\n", "+test_func()\n")
        self.assertIn("原始 patch", report)
        self.assertIn("实际应用 diff", report)

    def test_generate_report_with_deviations(self):
        report = gdr.generate_report("+test_func()\n", "+test_func_renamed()\n")
        self.assertIn("差异对比", report)


class TestGitShowMock(unittest.TestCase):
    @patch("subprocess.run")
    def test_get_commit_diff(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="diff output")
        output = gdr.get_commit_diff("/path/to/repo", "abc123")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("git", cmd)
        self.assertIn("show", cmd)
        self.assertIn("abc123", cmd)
        self.assertEqual(output, "diff output")

    @patch("subprocess.run")
    def test_get_commit_diff_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stderr="fatal: bad object"
        )
        with self.assertRaises(RuntimeError):
            gdr.get_commit_diff("/path/to/repo", "badhash")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python3 -m pytest tests/test_generate_diff_report.py -v
```

预期：全部 FAIL

### 6.2: 实现 scripts/generate_diff_report.py

- [ ] **Step 3: 创建 scripts/generate_diff_report.py**

实现以下函数：
- `parse_changed_lines(patch_content)` — 提取 +/- 行
- `read_patch_file(patch_path)` — 读取 .patch 文件
- `get_commit_diff(repo_path, commit_hash)` — git show
- `compare_diffs(original_lines, actual_lines)` — 比较差异
- `generate_report(original, actual, path, commit)` — 三节报告
- `main()` — CLI 入口

- [ ] **Step 4: 运行测试确认通过**

```bash
python3 -m pytest tests/test_generate_diff_report.py -v
```

预期：全部 PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/generate_diff_report.py tests/test_generate_diff_report.py
git commit -m "feat: add generate_diff_report.py for patch vs actual diff comparison"
```

---

## Task 7: SKILL.md — 主 Skill 文件

**Files:**
- Create: `SKILL.md`

> 这是 prompt 驱动的核心文件，不可 pytest 测试。验证方式：逐条对照 spec 检查覆盖。

- [ ] **Step 1: 写入 SKILL.md**

写入 `SKILL.md`，YAML frontmatter + 章节结构：

```yaml
---
name: merge-patchset
description: >
  Linux 内核 patchset 多 Agent 自动合入与冲突解决。
  触发：用户提到"合入 patch"、"merge patchset"、"backport patch"、
  "合并内核补丁"、"apply kernel patch"、"git am" 等关键词。
---
```

章节内容（按 spec 实现）：
1. **概述** — 一句话说明 skill 做什么
2. **运行环境** — 表格（目标内核/分支/架构/编译命令/工具路径）
3. **硬性约束** — 11 条，编号列表
4. **工作流总览** — Phase 0~3 概览
5. **文件清单** — 所有 bundled 文件路径
6. **Phase 0：下载** — `scripts/download_patches.py` 调用方式 + 参数说明
7. **Phase 1：并行分析** — 分配策略表 + 5 步流程 + 屏幕输出格式
8. **Phase 1.5：主 Agent 汇总** — 5 步流程
9. **Phase 2：串行 Merge** — 状态机 + 7 个状态详解 + 10 轮失败处理
10. **跨 Patch 修复** — rebase + amend 完整流程
11. **Phase 3：汇总落盘** — 3 步流程
12. **任务恢复** — 3 种情况处理
13. **两大场景处理** — 场景 A/B

- [ ] **Step 2: 逐条验证 SKILL.md 覆盖 spec**

对照 spec 检查清单，逐条确认 22 个检查项全部覆盖。

- [ ] **Step 3: 提交**

```bash
git add SKILL.md
git commit -m "feat: add merge-patchset SKILL.md with full workflow"
```

---

## Task 8: 部署到 skill 目录 + 整体验证

**Files:**
- Modify: `/root/.claude/skills/merge-patchset/SKILL.md` （同步）
- `/root/.agents/skills/merge-patchset/` （symlink 自动同步）

- [ ] **Step 1: 同步 SKILL.md 到部署目录**

```bash
cp "/mnt/shared/AI提效/1. 自动合入patch/patchset-merge/SKILL.md" \
   /root/.claude/skills/merge-patchset/SKILL.md
```

- [ ] **Step 2: 同步 references 到部署目录**

```bash
cp -r "/mnt/shared/AI提效/1. 自动合入patch/patchset-merge/references/"* \
      /root/.claude/skills/merge-patchset/references/
```

- [ ] **Step 3: 运行全部单元测试**

```bash
python3 -m pytest tests/ -v
```

预期：全部 PASS

- [ ] **Step 4: 验证 scripts 可独立运行**

```bash
python3 scripts/download_patches.py --help
python3 scripts/generate_diff_report.py --help
```

预期：两个脚本输出 help 信息，无报错。

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "chore: deploy skill to Claude Code directories, final verification"
```

---

**Plan complete.**
