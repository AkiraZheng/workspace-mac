# Architecture v2.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 merge-patchset skill 从 v2.0（按 patch 数量平摊 Agent）升级到 v2.1（按职责分工 Agent + revert checkpoint + Phase 0 场景问询）

**Architecture:** 4 个文件变更：2 个新建、2 个修改。新建 agent-design.md（Agent 职责定义）和 extract_patch_symbols.py（L1 符号提取）；修改 SKILL.md（场景问询+Agent 分工）和 calculate_build_checkpoints.py（revert checkpoint 规则）

**Tech Stack:** Python 3 + Bash (内核脚本)，Markdown (skill 文档)

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `references/agent-design.md` | ★新建。Agent 职责定义（agent_analysis / agent_revert / agent_review 的输入/输出/约束） |
| `scripts/extract_patch_symbols.py` | ★新建。L1 确定性脚本：从 .patch 文件提取 introduced_symbols / referenced_symbols / 功能分类 / feature_signature，输出 analysis_cache.json 骨架 |
| `scripts/calculate_build_checkpoints.py` | 修改。增加规则 1c：最后一个 revert task 强制 checkpoint |
| `SKILL.md` | 修改。Phase 0 场景问询 + Phase 1 Agent 角色分工 + Phase 1.5 revert checkpoint 规则 + 文件清单更新 |

---

### Task 1: 新建 `references/agent-design.md`

**Files:**
- Create: `references/agent-design.md`

- [ ] **Step 1: 创建目录并写入文件**

```bash
mkdir -p references
```

写入 `references/agent-design.md`：

```markdown
# Agent 职责定义

merge-patchset skill 采用三层架构：脚本层（L1，确定性）→ 语义层（L2，AI 并行）→ 主 Agent（L3，裁决）。L2 按职责分工为 2 个专职 Agent。

## L2 Agent 职责

### agent_analysis

| 维度 | 定义 |
|------|------|
| 输入 | `/tmp/patches/000N-*.patch`（全部），`$KERNEL_REPO_PATH`，`analysis_cache.json`（L1 `extract_patch_symbols.py` 已填充 introduced_symbols / referenced_symbols / feature_signature / 功能分类） |
| 输出 | 屏幕输出结构化分析结果（`analyzed_notes` 含功能描述/模块关联/风险，`dep_hints` 含依赖线索），由主 Agent 在 Phase 1.5 汇总写入 `analysis_cache.json` |
| 规则 | 优先读 commit message 再读 diff；功能分类沿用现有规则；风险: 高(核心路径/锁/内存) / 中(驱动逻辑) / 低(doc/log) |
| 约束 | 只读，不调 git write，不写 merge_tasks |
| 数量 | 固定 1 个（处理全部 patch，不论数量） |

### agent_revert

| 维度 | 定义 |
|------|------|
| 输入 | `duplicate_analysis.json`（L1 脚本初筛候选），场景（upgrade/backport），`$KERNEL_REPO_PATH`，`feature_signature.keywords` + `scope_dirs`（由主 Agent 在 L1→L2 过渡时从 patch 提取后传入） |
| 输出 | 屏幕输出结构化 `revert_ruling`（confirm/reject）+ `revert_ruling_note`（理由），由主 Agent 在 Phase 1.5 汇总写入 `duplicate_analysis.json` |
| 核心职责 | upgrade 模式：AI 自主深度搜索旧版本全貌，确保清理干净。backport 模式：严格审核 L1 候选 |
| 数量 | 固定 1 个（与 agent_analysis 一条消息并行启动） |

#### upgrade 模式执行流程

不使用阈值匹配。以 L1 候选 commit 为起点，自主做 5 步深度搜索：

| 步骤 | 操作 | 工具 |
|------|------|------|
| 1. 扩展搜索 | 用 `feature_signature.keywords` 在涉改目录 `scope_dirs` 下 `git log --grep=<kw>` 搜索所有相关 commit（不限阈值、不限时间范围，仅当前分支） | `git log --grep` |
| 2. 符号追溯 | 对 patch 的 `introduced_symbols`，用 `git log -S=<sym>` 在涉改目录找所有引入该符号的 commit | `git log -S` |
| 3. 文件追溯 | 对 patch 的 `changed_files`，用 `git log -- <file>` 找出所有修改过这些文件的 commit | `git log -- <file>` |
| 4. 深入理解 | 读取每个候选 commit 的 message + diff，AI 判断：是否确实是旧版本的功能实现？还是无关修改（格式/doc/cleanup/无关 bugfix）？ | 读 commit |
| 5. 清理干净 | 将确认的旧版本 commit 按时间逆序排列，确保无遗漏、无多余 | AI 裁决 |

核心原则：
- 不靠阈值判定 —— AI 理解代码语义后做判断
- L1 脚本只提供起点线索，不做最终决策
- 排除项：无关格式化、无关 bugfix、doc 修改
- 输出：完整的 revert_ruling 列表，每个 entry 含 confirm + 理由

#### backport 模式执行流程

| diff 相似度 | 判定 |
|------------|------|
| ≥90% | 暂停，展示给用户确认是否 revert |
| <90% | reject |

不启动 AI 深度搜索。纯新增场景不存在旧版本需要清理。

### agent_review（Phase 2 中）

| 维度 | 定义 |
|------|------|
| 触发 | 每 commit 后 |
| 实现 | 调用 code-review-expert skill |
| 处理 | Must Fix → 标记需 rebase amend；Suggest → 记录不阻塞 |
```

- [ ] **Step 2: 验证文件存在**

```bash
wc -l references/agent-design.md
```

---

### Task 2: 新建 `scripts/extract_patch_symbols.py`

**Files:**
- Create: `scripts/extract_patch_symbols.py`

- [ ] **Step 3: 编写脚本**

写入 `scripts/extract_patch_symbols.py`：

```python
#!/usr/bin/env python3
"""
L1 确定性脚本：从 .patch 文件提取符号和元数据，生成 analysis_cache.json 骨架。

提取内容：
  - introduced_symbols: patch 新增/修改的函数名、宏名、结构体名、类型名
  - referenced_symbols: patch 调用/引用的外部符号
  - 功能分类: 按文件路径 + diff 内容判定
  - feature_signature: 关键词 + 涉改目录（从 patch 路径推断）
  - changed_files: 涉改文件列表

输出: analysis_cache.json（按 patch task_id 组织的结构化数据）
"""

import argparse
import json
import os
import re
import sys


def extract_from_patch(patch_file: str) -> dict:
    """从单个 .patch 文件提取符号和元数据。"""
    result = {
        "subject": "",
        "introduced_symbols": [],
        "referenced_symbols": [],
        "changed_files": [],
        "功能分类": "core",
        "feature_signature": {"keywords": [], "scope_dirs": []},
    }

    try:
        with open(patch_file, 'r') as f:
            content = f.read()
    except Exception:
        return result

    lines = content.split('\n')
    current_file = ""
    all_files = set()
    add_lines = []
    header_done = False
    in_diff = False

    for line in lines:
        # Subject extraction
        if not header_done:
            m = re.match(r'^Subject:\s*(.+)', line)
            if m:
                result["subject"] = m.group(1).strip()
                header_done = True
            continue

        # File tracking
        m = re.match(r'^\+\+\+\s+b/(.+)', line)
        if m:
            current_file = m.group(1)
            if current_file not in ('/dev/null', ''):
                all_files.add(current_file)
            in_diff = True
            continue

        # Collect added lines from diff hunks
        if in_diff and line.startswith('+') and not line.startswith('+++'):
            add_lines.append(line[1:].strip())

    result["changed_files"] = sorted(all_files)

    # Extract symbols from added lines
    introduced = set()
    referenced = set()

    for line in add_lines:
        # Function definitions: return_type func_name(...)
        m = re.match(r'^(static\s+)?(inline\s+)?(\w+[\s*]+)+(\w+)\s*\(', line)
        if m:
            introduced.add(m.group(4))

        # Macro definitions: #define MACRO_NAME
        m = re.match(r'^#define\s+(\w+)', line)
        if m:
            introduced.add(m.group(1))

        # Struct/union/enum definitions
        m = re.match(r'^(struct|union|enum)\s+(\w+)', line)
        if m:
            introduced.add(m.group(2))

        # Type alias: typedef ... type_name;
        m = re.match(r'^typedef\s+.+\s+(\w+)\s*;', line)
        if m:
            introduced.add(m.group(1))

        # Function calls: func_name(...)
        for match in re.finditer(r'\b(\w+)\s*\(', line):
            name = match.group(1)
            if name not in introduced and name not in ('if', 'while', 'for', 'switch',
                                                        'return', 'sizeof', 'typeof'):
                referenced.add(name)

        # Macro usage: non-definition pattern
        for match in re.finditer(r'\b([A-Z][A-Z0-9_]{3,})\b', line):
            macro = match.group(1)
            if macro not in introduced:
                referenced.add(macro)

    # Remove common noise
    noise = {"void", "int", "char", "long", "short", "unsigned", "signed",
             "const", "static", "inline", "extern", "volatile", "register",
             "bool", "size_t", "u8", "u16", "u32", "u64", "s8", "s16",
             "s32", "s64", "phys_addr_t", "gfp_t", "pgd_t", "pud_t",
             "pmd_t", "pte_t", "spinlock_t", "NULL", "true", "false"}
    introduced -= noise
    referenced -= noise

    result["introduced_symbols"] = sorted(introduced)
    result["referenced_symbols"] = sorted(referenced)

    # Feature classification
    result["功能分类"] = _classify(all_files, add_lines, result["subject"])

    # Feature signature
    keywords, scope_dirs = _extract_signature(
        add_lines, all_files, result["subject"]
    )
    result["feature_signature"]["keywords"] = sorted(keywords)
    result["feature_signature"]["scope_dirs"] = sorted(scope_dirs)

    return result


def _classify(files: set, add_lines: list, subject: str) -> str:
    """判定功能分类。优先级：文件路径 > diff 内容 > commit message 关键词。"""
    for f in files:
        if any(f.startswith(p) for p in (
            "include/linux/", "include/uapi/", "arch/", "tools/include/"
        )):
            # 检查是否宏定义密集
            define_count = sum(1 for l in add_lines if l.startswith("#define"))
            typedef_count = sum(1 for l in add_lines if l.startswith("typedef"))
            struct_count = sum(1 for l in add_lines if l.startswith("struct "))
            total = len(add_lines) if add_lines else 1
            if (define_count + typedef_count + struct_count) / total > 0.3:
                return "infra"
        if f.startswith("Documentation/"):
            return "doc"
        if f.startswith("sound/"):
            return "sound"
        if f.startswith("net/"):
            return "net"
        if f.startswith("fs/"):
            return "fs"
        if f.startswith("drivers/"):
            return "driver"
        if any(f.startswith(p) for p in (
            "kernel/", "mm/", "init/",
        )):
            return "core"

    # Fallback: commit message
    sl = subject.lower()
    if any(kw in sl for kw in ("fix", "bug", "error", "patch")):
        return "bugfix"
    if any(kw in sl for kw in ("doc", "comment", "documentation")):
        return "doc"

    return "core"


def _extract_signature(add_lines: list, files: set, subject: str) -> tuple:
    """提取特性签名：关键词 + 涉改目录。"""
    keywords = set()
    scope_dirs = set()

    # Extract uppercase acronyms from subject and code
    for line in [subject] + add_lines[:50]:
        for match in re.finditer(r'\b([A-Z][A-Z0-9_]{2,})\b', line):
            kw = match.group(1)
            if kw not in ("NULL", "BUG", "TODO", "FIXME", "GPL",
                          "ARCH", "CONFIG", "BIT", "GENMASK", "FIELD_PREP",
                          "FIELD_GET", "SYSREG", "ARM", "ARM64", "KVM"):
                keywords.add(kw)

    # Common scope prefixes
    for f in files:
        parts = f.split('/')
        if len(parts) >= 2:
            scope_dirs.add('/'.join(parts[:2]) + '/')
    if not scope_dirs:
        for f in files:
            parts = f.split('/')
            if parts:
                scope_dirs.add(parts[0] + '/')

    return keywords, scope_dirs


def main():
    parser = argparse.ArgumentParser(
        description='从 patch 文件提取符号和元数据'
    )
    parser.add_argument('--patch-dir', required=True,
                        help='patch 文件目录')
    parser.add_argument('--output', required=True,
                        help='输出 analysis_cache.json 路径')
    args = parser.parse_args()

    patch_dir = args.patch_dir
    if not os.path.isdir(patch_dir):
        print(f"错误: 目录不存在: {patch_dir}", file=sys.stderr)
        sys.exit(1)

    patch_files = sorted([
        f for f in os.listdir(patch_dir)
        if f.endswith('.patch') and f.startswith('0')
    ])

    if not patch_files:
        print(f"警告: {patch_dir} 中无 .patch 文件", file=sys.stderr)
        sys.exit(1)

    cache = {}
    for pf in patch_files:
        task_id = pf[:4]
        full_path = os.path.join(patch_dir, pf)
        entry = extract_from_patch(full_path)
        entry["patch_file"] = full_path
        cache[task_id] = entry

    with open(args.output, 'w') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

    print(f"[extract_patch_symbols] {len(cache)} patches → {args.output}")
    for tid, e in cache.items():
        print(f"  {tid}: {e['功能分类']:<8} intro={len(e['introduced_symbols']):>2} ref={len(e['referenced_symbols']):>2} files={len(e['changed_files'])}")


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: 验证脚本可运行**

```bash
chmod +x scripts/extract_patch_symbols.py
python3 scripts/extract_patch_symbols.py --patch-dir /tmp/patches/ --output /tmp/test_cache.json 2>&1
cat /tmp/test_cache.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d)} entries')"
```

---

### Task 3: 修改 `scripts/calculate_build_checkpoints.py` — 增加规则 1c

**Files:**
- Modify: `scripts/calculate_build_checkpoints.py:1-15` (docstring)
- Modify: `scripts/calculate_build_checkpoints.py:155-167` (after rule 1b, insert rule 1c)

- [ ] **Step 5: 更新文件头 docstring**

修改 `scripts/calculate_build_checkpoints.py` 第 1-15 行，将：

```
# calculate_build_checkpoints.py
"""
Calculate build_checkpoint for each task in merge_tasks.json.

Rules (priority order, short-circuit):
  1a. 反向依赖者                                        → False（完全排除）
  1b. 反向依赖的被依赖者                                 → True（强制）
  1.  功能分类 == 'infra'                                → True
  2.  introduced_symbols referenced by >= 3 later patches → True
  3.  risk_level == '高' or conflicts_predicted non-empty → True
  4.  Last patch overall (max seq)                        → True (forced, 含最后一个 revert)
  5.  action == 'skip' or 功能分类 == 'doc'               → False
  6.  Last patch in its (功能分类, path_prefix) group     → True
  7.  All others                                          → False
"""
```

改为：

```
# calculate_build_checkpoints.py  (checkpoint with v2/fixup rules)
"""
Calculate build_checkpoint for each task in merge_tasks.json.

Rules (priority order, short-circuit):
  1a. 反向依赖者                                        → False（完全排除）
  1b. 反向依赖的被依赖者                                 → True（强制）
  1c. 最后一个 revert task（revert 序列中 seq 最大）       → True（强制）
  1.  功能分类 == 'infra'                                → True
  2.  introduced_symbols referenced by >= 3 later patches → True
  3.  risk_level == '高' or conflicts_predicted non-empty → True
  4.  Last patch overall (max seq)                        → True (forced, 含最后一个 revert)
  5.  action == 'skip' or 功能分类 == 'doc'               → False
  6.  Last patch in its (功能分类, path_prefix) group     → True
  7.  All others                                          → False
"""
```

- [ ] **Step 6: 在 calculate_checkpoints 函数中插入规则 1c 逻辑**

在 `calculate_checkpoints` 函数开头（第 131 行 `results = []` 之前），增加查找最后一个 revert task 的逻辑：

修改第 129-131 行处，将：

```python
    last_patch_overall = max(all_patches, key=lambda p: p.get('seq', 0))
    last_patch_seq = last_patch_overall.get('seq', 0)

    results = []
```

改为：

```python
    last_patch_overall = max(all_patches, key=lambda p: p.get('seq', 0))
    last_patch_seq = last_patch_overall.get('seq', 0)

    # Rule 1c: last revert task (forced checkpoint)
    revert_tasks = [p for p in all_patches if p.get('action') == 'revert']
    last_revert_seq = -1
    if revert_tasks:
        last_revert = max(revert_tasks, key=lambda p: p.get('seq', 0))
        last_revert_seq = last_revert.get('seq', 0)

    results = []
```

- [ ] **Step 7: 在规则判定循环中插入规则 1c 判定**

在规则 1b 判定后（第 166 行 `# ── Rule 1: infra → true ──` 之前），插入规则 1c 判定代码。找到：

```python
        # ── Rule 1: infra → true ──
```

在前面插入：

```python
        # ── Rule 1c: last revert task (FORCED) ──
        if checkpoint is None and last_revert_seq > 0 and seq == last_revert_seq:
            checkpoint = True
            rules_triggered.append("Rule_1c")
            forced_by.append("last_revert")
            reason_parts.append('最后一个 revert task（强制编译验证）')
            # Also check: if this revert happens to be last overall patch,
            # note it's both (rule 4 will also trigger, but that's fine)
            if seq == last_patch_seq:
                reason_parts[-1] = '最后一个 revert;末 patch 强制'

```

- [ ] **Step 8: 验证脚本逻辑**

```bash
# 创建测试数据
cat > /tmp/test_merge_tasks.json << 'EOF'
{
  "patchset_info": {},
  "merge_order": [
    {"seq": 1, "task_id": "0002", "action": "revert", "功能分类": "driver", "introduced_symbols": [], "referenced_symbols": [], "files_changed": ["drivers/test.c"]},
    {"seq": 2, "task_id": "0001", "action": "revert", "功能分类": "infra", "introduced_symbols": ["MACRO_A"], "referenced_symbols": [], "files_changed": ["arch/arm64/include/test.h"]},
    {"seq": 3, "task_id": "0003", "action": "apply", "功能分类": "core", "introduced_symbols": [], "referenced_symbols": ["MACRO_A"], "files_changed": ["kernel/test.c"]},
    {"seq": 4, "task_id": "0005", "action": "apply", "功能分类": "driver", "introduced_symbols": ["func_main"], "referenced_symbols": ["MACRO_A"], "files_changed": ["drivers/test.c"]}
  ],
  "deps_order": []
}
EOF

python3 scripts/calculate_build_checkpoints.py \
  --merge-tasks /tmp/test_merge_tasks.json \
  --output /tmp/test_output.json 2>&1

# 验证：seq=2 (task 0001) 应显示 验证点=✅，原因含"最后一个 revert"
python3 -c "
import json
d = json.load(open('/tmp/test_output.json'))
for t in d['merge_order']:
    cp = t.get('build_checkpoint', False)
    reason = t.get('checkpoint_reason', {}).get('primary_reason', '')
    print(f\"{t['task_id']} checkpoint={cp} reason={reason}\")
"
# 期望: 0002 checkpoint=False, 0001 checkpoint=True (revert), 0003 checkpoint=False, 0005 checkpoint=True (last)
```

---

### Task 4: 修改 `SKILL.md` — Phase 0 场景问询

**Files:**
- Modify: `SKILL.md:206-208`（恢复检查后插入场景问询）

- [ ] **Step 9: 在恢复检查后插入场景问询**

找到 `SKILL.md` 第 206-207 行（Phase 0 恢复检查部分的结尾），在 `--restore --clear` 代码块和 `---` 分隔线之间插入场景问询部分：

原内容：
```
   ...--restore --clear
   ```**

---

## Phase 1：并行分析（只读，不写文件）
```

改为：

```
   ...--restore --clear
   ```**

---

### 场景问询（★v2.1 新增）

Phase 0 下载完成后、正式进入 Phase 1 前，检测目标仓库是否存在旧版本实现，让用户选择合入场景。

**步骤 1：初筛检测**

```bash
python3 "$SCRIPTS_DIR/detect_duplicate.py" \
  --patch-dir /tmp/patches/ \
  --repo-path "$KERNEL_REPO_PATH" \
  --output "$KERNEL_REPO_PATH/patch_analysis/duplicate_analysis.json"
```

**步骤 2：根据结果分流**

- 若 `duplicate_analysis.json` 中 `global_revert_order` 为空 → 无 revert 候选，直接进入 Phase 1（默认 backport 模式）
- 若存在 revert 候选 → 展示摘要给用户，询问场景

```
═══════════════════════════════════════════════
  场景问询 — 检测到目标仓库中可能存在旧版本实现
═══════════════════════════════════════════════

检测到以下 commit 可能与要合入的 patch 相关：
  <commit_hash1> <subject_line> (相似度 XX%)
  <commit_hash2> <subject_line> (相似度 XX%)
  ...

请选择合入场景：

[1] 版本升级（upgrade）
    要合入的 patchset 是旧版本的新版本。
    AI 将深度搜索目标仓库中所有相关旧版本 commit，
    确认后逐个回退，确保清理干净不留残留。

[2] 纯新增（backport）
    目标仓库无相关实现，上述匹配为误报或极相似代码。
    仅当 diff ≥90% 时才暂停让用户确认，其余全部跳过。
    不进行深度搜索，不会自动 revert。

  请选择: [1] 版本升级 / [2] 纯新增
```

**步骤 3：用户选择后的行为**

| 选择 | 后续 |
|------|------|
| [1] 版本升级 | 记录场景为 `upgrade`，进入 Phase 1。agent_revert 在 L2 做 AI 深度搜索 |
| [2] 纯新增 | 记录场景为 `backport`，进入 Phase 1。agent_revert 只做严格审核（diff ≥90% → 暂停让用户确认） |

---

## Phase 1：并行分析（只读，不写文件）
```

---

### Task 5: 修改 `SKILL.md` — Phase 1 Agent 改为按职责分工

**Files:**
- Modify: `SKILL.md:213-245`（替换"分析 Agent 分配策略"和"并行启动方式"）
- Modify: `SKILL.md:257-377`（调整"分析 Agent 执行流程"步骤）

- [ ] **Step 10: 替换 Agent 分配策略**

找到 `SKILL.md` 第 213 行开始的 "### 分析 Agent 分配策略" 部分，将整个分配策略和并行启动方式（第 213-245 行）替换为按职责分工的描述。

找到以下两节：

```
### 分析 Agent 分配策略

| Patch 总数 | 每 Agent 负责 | Agent 数 |
...
### 并行启动方式

**主 Agent 必须在一条消息中同时启动所有分析 Agent**（使用多个 Task tool 调用），而不是逐个串行启动。
...
每个 Agent 收到以下信息：
- 负责的 patch 文件列表（绝对路径 `/tmp/patches/000N-*.patch`）
- 目标仓库路径 `$KERNEL_REPO_PATH` 和目标分支 `$KERNEL_BRANCH`
- 上游仓库路径 `$UPSTREAM_REPO_PATH`（如不可用，明确告知降级模式）
- 输出格式：严格按 `references/output-templates.md` 中 "Phase 1 分析 Agent 屏幕输出格式" 输出
```

替换为：

```
### L2 Agent 分工（★v2.1：按职责分工）

不再按 patch 数量平分 Agent。改为 **2 个专职 Agent**，一条消息并行启动：

```
主 Agent 在 L1 脚本全部完成后，一条消息同时启动 2 个 Agent：
  Task(agent_analysis, 全部 patch + analysis_cache.json)
  Task(agent_revert, duplicate_analysis.json + 场景 + keywords)
```

**agent_analysis**：全量语义分析
- 输入：`/tmp/patches/000N-*.patch`（全部），`$KERNEL_REPO_PATH`，`analysis_cache.json`（L1 `extract_patch_symbols.py` 已填充骨架）
- 输出：屏幕输出结构化分析结果——功能描述、模块关联、风险等级、review 需求、依赖线索
- 详见 `references/agent-design.md`

**agent_revert**：revert 审核（★v2.1 新增独立 Agent）
- 输入：`duplicate_analysis.json`（L1 初筛），场景（upgrade/backport），`$KERNEL_REPO_PATH`，`feature_signature.keywords` + `scope_dirs`
- 输出：屏幕输出 `revert_ruling`（confirm/reject）+ 理由
- upgrade 模式：AI 自主深度搜索旧版本全貌（不限阈值），确保清理干净
- backport 模式：diff ≥90% → 暂停让用户确认；<90% → reject
- 详见 `references/agent-design.md`

> ★ 两个 Agent 必须在**同一条消息**中并行启动（使用多个 Task tool 调用），禁止串行。
```

- [ ] **Step 11: 调整"分析 Agent 执行流程"**

找到 `SKILL.md` 第 257 行开始的 "### 分析 Agent 执行流程"。这个流程现在拆分为两个 Agent 的独立流程。保留 "### agent_analysis 执行流程" 并调整内容，新增 "### agent_revert 执行流程"。

找到：

```
### 分析 Agent 执行流程

**步骤 1: 理解 commit message（优先）**
...
```

替换为：

```
### agent_analysis 执行流程

以下流程由 agent_analysis 执行，agent_revert 的流程见下一节。

**步骤 1: 理解 commit message（优先）**
```

保留原有步骤 1-7 内容不变（步骤 2.5 提取 feature_signature 也保留——作为 AI 层面的补充，L1 脚本已提供骨架），在步骤 7 屏幕输出结束后新增 section：

```
---

### agent_revert 执行流程（★v2.1 新增）

agent_revert 根据场景（upgrade / backport）走不同流程。

#### upgrade 模式（AI 深度搜索）

1. 读取 `duplicate_analysis.json` 中的 L1 初筛 commit 列表（作为搜索起点）
2. 读取 `analysis_cache.json` 中的 `feature_signature.keywords` 和 `scope_dirs`
3. **扩展搜索**：用 keywords 在 scope_dirs 下 `git log --grep=<kw>` 搜全部相关 commit（仅当前分支，不限阈值、不限时间范围）
4. **符号追溯**：用 `git log -S=<sym>` 在 scope_dirs 找所有引入 key symbol 的 commit
5. **文件追溯**：用 `git log -- <file>` 找出修改过涉改文件的所有 commit
6. **深入理解**：读取每个候选 commit 的 message + diff，AI 判断：
   - 是否是旧版本的功能实现？ → confirm
   - 是否是无关注释/格式/doc/无关 bugfix？ → reject
7. **去重合并**：将 L1 初筛结果和步骤 3-5 的搜索结果合并去重
8. 输出：每个 commit 的 `revert_ruling`（confirm/reject）+ `revert_ruling_note` + 按时间逆序排列

> 核心原则：不靠阈值判定，AI 理解代码语义后做判断。L1 脚本只提供起点线索。排除无关格式化/doc/无关 bugfix。确保找到所有旧版本 commit，一个不多一个不少。

#### backport 模式（严格审核）

1. 读取 L1 的 `duplicate_analysis.json`
2. 对每个候选：
   - diff ≥90% → 暂停，展示 commit 给用户确认是否 revert
   - diff <90% → reject
3. **不启动扩展搜索**（纯新增场景，深度搜索仅限 upgrade 模式）
```

---

### Task 6: 修改 `SKILL.md` — Phase 1.5 revert checkpoint 规则

**Files:**
- Modify: `SKILL.md:650-664`（Phase 1.5 步骤 8 计算规则表）

- [ ] **Step 12: 在 checkpoint 计算规则表中增加规则 1c**

找到 `SKILL.md` Phase 1.5 步骤 8 的计算规则表（第 652-663 行附近），在规则 1b 后增加规则 1c：

原规则表：
```
| 优先级 | 条件 | build_checkpoint | 说明 |
|--------|------|:---:|------|
| 1a | 反向依赖者 | `false` | **完全排除** |
| 1b | 反向依赖的被依赖者 | `true` | 强制验证 |
| 2 | `功能分类` == `infra` | `true` | 基础设施 |
| ...
```

在 1b 后插入 1c：
```
| 优先级 | 条件 | build_checkpoint | 说明 |
|--------|------|:---:|------|
| 1a | 反向依赖者（前面的 patch 引用后面 patch 的符号） | `false` | **完全排除**，即使满足 infra/高风险等规则也不验证；代码静默写入，等被依赖者定义符号后在 checkpoint 统一验证 |
| 1b | 反向依赖的被依赖者（定义符号被前面 patch 引用） | `true` | 强制验证确保符号定义正确，验证时依赖者的代码已写入仓库 |
| 1c | **最后一个 revert task**（revert 序列中 seq 最大） | `true`（强制） | 所有 revert 完成后必定编译一次，确保回退后代码编译通过 |
| 2 | `功能分类` == `infra` | `true` | 基础设施/公共头文件/宏定义，影响面最广 |
| ...
```

- [ ] **Step 13: 更新统计规则编号**

规则表中原规则 2-8 的编号需要检查是否与实际 `calculate_build_checkpoints.py` 中的编号一致。当前脚本使用 `Rule_1c`，文档中规则编号从 2 开始无误（1a/1b/1c 是子规则）。

---

### Task 7: 修改 `SKILL.md` — 文件清单更新

**Files:**
- Modify: `SKILL.md:104-118`（文件清单部分）

- [ ] **Step 14: 在文件清单中增加两个新文件**

找到 `SKILL.md` 第 104-118 行的文件清单，增加 `extract_patch_symbols.py`：

在 `download_patches.py` 行后插入：
```
- `scripts/extract_patch_symbols.py` — L1 确定性脚本：从 .patch 提取符号/功能分类/feature_signature → analysis_cache.json 骨架
```

在 references 部分增加（可选——agent-design.md 不是运行文件但作为参考文档）：
```
- `references/agent-design.md` — Agent 职责定义参考文档
```

---

### Task 8: 修改 `SKILL.md` — Phase 1 L1 增加 extract_patch_symbols

**Files:**
- Modify: `SKILL.md:122-209`（Phase 1 开头，增加 L1 脚本调用）

- [ ] **Step 15: 在 agent_analysis 描述前插入 L1 脚本调用指令**

找到 Phase 1 开头部分（恢复检查之后、Agent 分工之前），增加 L1 脚本调用说明。在 "## Phase 1：并行分析（只读，不写文件）" 的标题后、"### L2 Agent 分工" 前，插入 L1 初始化步骤：

```
## Phase 1：并行分析（只读，不写文件）

### L1 脚本初始化（★v2.1：先跑确定性脚本）

在启动 L2 Agent 前，先并行运行两个 L1 确定性脚本：

```bash
# L1a: 重复检测（初筛线索）
python3 "$SCRIPTS_DIR/detect_duplicate.py" \
  --patch-dir /tmp/patches/ \
  --repo-path "$KERNEL_REPO_PATH" \
  --output "$KERNEL_REPO_PATH/patch_analysis/duplicate_analysis.json"

# L1b: 符号提取（生成 analysis_cache.json 骨架）
python3 "$SCRIPTS_DIR/extract_patch_symbols.py" \
  --patch-dir /tmp/patches/ \
  --output "$KERNEL_REPO_PATH/patch_analysis/analysis_cache.json"
```

产出：
- `duplicate_analysis.json` — L2 agent_revert 消费
- `analysis_cache.json` — L2 agent_analysis 消费（含骨架：introduced_symbols / referenced_symbols / 功能分类 / feature_signature）

> 这两个脚本是完全确定性的，不依赖 AI。并行运行或串行均可。

### L2 Agent 分工（★v2.1：按职责分工）

...（后续内容保持不变）
```

---

### Task 9: 运行测试验证

**Files:**
- Test files in `tests/`

- [ ] **Step 16: 运行现有测试确保不改坏**

```bash
cd /mnt/shared/shared/AI提效/1. 自动合入patch/patchset-merge
python3 -m pytest tests/ -q 2>&1
```

- [ ] **Step 17: 验证 calculate_build_checkpoints 的 revert 测试**

```bash
python3 -m pytest tests/test_calculate_checkpoints.py -v 2>&1
```

---

### Task 10: 部署同步

**Files:**
- Modify: `install.sh:262-280`（增加新文件到部署清单）

- [ ] **Step 18: 更新 install.sh 的 REQUIRED_FILES 和 copy 部分**

在 `install.sh` 的 `REQUIRED_FILES` 数组中增加（第 196 行后）：
```bash
    "$WORKSPACE/scripts/extract_patch_symbols.py"
    "$WORKSPACE/references/agent-design.md"
```

在 copy 部分（第 262-282 行）增加：
```bash
copy_or_fail "$WORKSPACE/scripts/extract_patch_symbols.py"    "scripts/extract_patch_symbols.py"
copy_or_fail "$WORKSPACE/references/agent-design.md"           "references/agent-design.md"
```

- [ ] **Step 19: 部署到 skill 目录**

```bash
bash install.sh
```

- [ ] **Step 20: 提交所有变更**

```bash
git add SKILL.md references/agent-design.md references/output-templates.md
git add scripts/extract_patch_symbols.py scripts/calculate_build_checkpoints.py
git add install.sh
git commit -m "feat: architecture v2.1 - Agent按职责分工 + revert checkpoint + Phase 0场景问询"
```
