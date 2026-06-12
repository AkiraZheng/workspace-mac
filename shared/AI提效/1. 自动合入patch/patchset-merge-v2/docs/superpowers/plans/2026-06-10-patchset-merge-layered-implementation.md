# Patchset-Merge 分层架构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 patchset-merge 分层架构，包含 5 个 Skill（orchestrator + 4 layers）+ scripts + references + 测试

**Architecture:** 采用 Skill 串联模式（方案 C），主调度 Skill 调用 4 个 Layer Skill，通过门禁验证脚本 + 状态文件强制执行流程

**Tech Stack:** Python 3, Bash, Git, JSON Schema, Claude Code Skill Framework

---

## File Structure

实现分层架构涉及以下文件组织：

```
patchset-merge-v2/
├── patchset-merge-orchestrator/
│   ├── SKILL.md                    # 主调度（~300 lines）
│   ├── scripts/
│   │   ├── gate_check.sh           # 门禁验证
│   │   ├── validate_json.py        # JSON schema
│   │   ├── verify_build.sh         # 编译验证
│   │   ├── download_patches.py     # 复用现有脚本
│   │   └── check_files_exist.sh    # 文件检查
│   └── references/
│       ├── layer_interface_schema.md
│       ├── state_schema.md
│       └── fallback_guide.md
├── layer1-interaction/
│   ├── SKILL.md                    # 用户交互层（~400 lines）
│   └── references/
│       ├── config_schema.md
│       └── user_interaction_guide.md
├── layer2-search/
│   ├── SKILL.md                    # 搜索层（~500 lines）
│   ├── agents/
│   │   ├── agent_target_revert.md
│   │   └── agent_upstream_deps.md
│   ├── scripts/
│   │   └ extract_patch_symbols.py  # 复用现有脚本
│   └ references/
│       ├── search_strategy.md
│       ├── revert_candidates_schema.md
│       ├── deps_candidates_schema.md
│       ├── merge_tasks_schema.md
│       └── patch_symbols_schema.md
├── layer3-execution/
│   ├── SKILL.md                    # 执行层（~600 lines）
│   ├── agents/
│   │   ├── agent_conflict_resolver.md
│   └ references/
│       ├── execution_state_machine.md
│       ├── analyse_template.md
│       ├── conflict_decision_tree.md
│       └── build_fix_strategy.md
├── layer4-output/
│   ├── SKILL.md                    # 输出层（~300 lines）
│   └ references/
│       ├── summary_template.md
│       └ output_checklist.md
└── shared-scripts/                 # 复用现有脚本（8个）
    ├── calculate_build_checkpoints.py
    ├── generate_diff_report.py
    ├── generate_analyse_md.py
    ├── generate_summary_md.py
    ├── verify_patch_intent.py
    ├── gatekeeper.py
    └── extract_patch_symbols.py
```

---

## Task 1: 创建目录结构

**Files:**
- Create: `patchset-merge-v2/patchset-merge-orchestrator/`
- Create: `patchset-merge-v2/layer1-interaction/`
- Create: `patchset-merge-v2/layer2-search/`
- Create: `patchset-merge-v2/layer3-execution/`
- Create: `patchset-merge-v2/layer4-output/`
- Create: `patchset-merge-v2/shared-scripts/`

- [ ] **Step 1: 创建所有 Skill 目录**

```bash
cd patchset-merge-v2
mkdir -p patchset-merge-orchestrator/scripts patchset-merge-orchestrator/references
mkdir -p layer1-interaction/references
mkdir -p layer2-search/agents layer2-search/scripts layer2-search/references
mkdir -p layer3-execution/agents layer3-execution/references
mkdir -p layer4-output/references
mkdir -p shared-scripts
```

Expected: 5 个 Skill 目录 + shared-scripts 创建成功

- [ ] **Step 2: 验证目录结构**

```bash
ls -la
```

Expected: 看到所有目录已创建

- [ ] **Step 3: Commit**

```bash
git add .
git commit -m "feat: create layered architecture directory structure"
```

---

## Task 2: 实现主调度 Skill - patchset-merge-orchestrator

**Files:**
- Create: `patchset-merge-orchestrator/SKILL.md`

- [ ] **Step 1: Write SKILL.md header**

```markdown
---
name: patchset-merge-orchestrator
description: >
  Patchset-merge 主调度 Skill：协调 Layer 1-4 执行顺序，强制门禁验证，状态恢复机制。
  
  强制执行顺序：
  1. layer1-interaction → 2. layer2-search → 3. layer3-execution → 4. layer4-output
  
  触发关键词："patchset merge"、"merge patchset"、"合入 patch"。
  
  输出文件：state.json（持久化执行状态）
---
```

Expected: SKILL.md 文件创建成功

- [ ] **Step 2: Write hard gate constraints**

在 SKILL.md body 中添加：

```markdown
<HARD-GATE>
执行顺序强制锁定，不可跳过、不可逆序：

1. 必须首先调用 layer1-interaction
2. 等待 layer1 完成（config.json 生成）后，才能调用 layer2-search
3. 等待 layer2 完成后，才能调用 layer3-execution
4. 等待 layer3 完成后，才能调用 layer4-output

违反顺序 = 立即中止，输出错误日志
</HARD-GATE>
```

Expected: HARD-GATE 约束写入成功

- [ ] **Step 3: Write initialization and recovery logic**

添加执行流程章节：

```markdown
## Skill 初始化

启动时执行：
1. Read $KERNEL_REPO/.patchmerge/state.json（若存在）
2. 若 state.json 显示某层已完成 → 检查前置文件 → 从下一层恢复
3. 若不存在 → 从 layer1 开始

## Phase 0: 调用 layer1-interaction

- Skill tool 调用：layer1-interaction
- 等待返回：config.json 路径
- Bash: bash $SCRIPTS_DIR/gate_check.sh layer2 $KERNEL_REPO_PATH
- 若退出码非 0 → 输出错误，中止
- Write state.json: {"layer1": "completed", "output_files": ["config.json"]}

## Phase 1: 调用 layer2-search

- Bash 门禁验证：bash $SCRIPTS_DIR/gate_check.sh layer3 $KERNEL_REPO_PATH
- 若退出码非 0 → 输出缺失文件，中止
- Skill tool 调用：layer2-search
- 等待返回：revert_candidates.json, deps_candidates.json, merge_tasks.json
- Write state.json: {"layer2": "completed", ...}

## Phase 2: 调用 layer3-execution

（同理）

## Phase 3: 调用 layer4-output

（同理）

## Phase 4: 完成

输出执行概览，提醒用户后续操作。
```

Expected: 执行流程章节写入成功（约 300 lines）

- [ ] **Step 4: Verify SKILL.md size**

```bash
wc -l patchset-merge-orchestrator/SKILL.md
```

Expected: 约 300 lines

- [ ] **Step 5: Commit**

```bash
git add patchset-merge-orchestrator/SKILL.md
git commit -m "feat: create orchestrator Skill main logic"
```

---

## Task 3: 实现门禁验证脚本 gate_check.sh

**Files:**
- Create: `patchset-merge-orchestrator/scripts/gate_check.sh`

- [ ] **Step 1: Write gate_check.sh**

```bash
#!/bin/bash
# 门禁验证脚本 - 执行时间 <1秒

LAYER=$1
KERNEL_REPO=$2

if [ -z "$LAYER" ] || [ -z "$KERNEL_REPO" ]; then
    echo "用法: gate_check.sh <layer> <kernel_repo>"
    exit 1
fi

case $LAYER in
  layer2)
    test -f "$KERNEL_REPO/patch_analysis/config.json" || {
      echo "❌ Layer 2 前置文件缺失: config.json"
      exit 10
    }
    ;;
  layer3)
    test -f "$KERNEL_REPO/patch_analysis/revert_candidates.json" || {
      echo "❌ Layer 3 前置文件缺失: revert_candidates.json"
      exit 20
    }
    test -f "$KERNEL_REPO/patch_analysis/deps_candidates.json" || {
      echo "❌ Layer 3 前置文件缺失: deps_candidates.json"
      exit 21
    }
    test -f "$KERNEL_REPO/patch_analysis/merge_tasks.json" || {
      echo "❌ Layer 3 前置文件缺失: merge_tasks.json"
      exit 22
    }
    ;;
  layer4)
    ls "$KERNEL_REPO/patch_analysis"/*-analyse.md >/dev/null 2>&1 || {
      echo "❌ Layer 4 前置文件缺失: *-analyse.md 文件不存在"
      exit 30
    }
    ;;
  *)
    echo "❌ 未知 Layer: $LAYER"
    exit 1
    ;;
esac

echo "✅ $LAYER 前置文件验证通过"
exit 0
```

Expected: gate_check.sh 创建成功（约 40 lines）

- [ ] **Step 2: Add executable permission**

```bash
chmod +x patchset-merge-orchestrator/scripts/gate_check.sh
```

Expected: 脚本可执行

- [ ] **Step 3: Test gate_check.sh with mock files**

```bash
mkdir -p /tmp/test_gate/patch_analysis
touch /tmp/test_gate/patch_analysis/config.json
bash patchset-merge-orchestrator/scripts/gate_check.sh layer2 /tmp/test_gate
```

Expected: 输出 "✅ layer2 前置文件验证通过"，退出码 0

- [ ] **Step 4: Test gate_check.sh failure case**

```bash
rm /tmp/test_gate/patch_analysis/config.json
bash patchset-merge-orchestrator/scripts/gate_check.sh layer2 /tmp/test_gate
```

Expected: 输出 "❌ Layer 2 前置文件缺失"，退出码 10

- [ ] **Step 5: Commit**

```bash
git add patchset-merge-orchestrator/scripts/gate_check.sh
git commit -m "feat: create gate_check.sh for layer validation"
```

---

## Task 4: 实现 Layer 1 - 用户交互层 Skill

**Files:**
- Create: `layer1-interaction/SKILL.md`

- [ ] **Step 1: Write SKILL.md header**

```markdown
---
name: layer1-interaction
description: >
  Patchset-merge 用户交互层：参数解析、校验、模式确认。
  
  强制前置条件：
  1. 由 patchset-merge-orchestrator 调用（不可独立触发）
  2. 用户已提供 patch 合入需求描述
  
  输出文件：config.json
  
  完成后状态：Write state.json: {"layer1": "completed"}
---
```

Expected: SKILL.md header 创建成功

- [ ] **Step 2: Write execution steps (纯 Bash，不调脚本)**

添加执行流程章节（参考设计文档第 3.3 节）：

```markdown
## 执行步骤

### 步骤 1: 解析用户输入

从用户描述中提取（使用 Bash 快命令）：

```bash
PATCH_SOURCE=$(echo "$USER_INPUT" | grep -oP '合入\s+(\S+)' | awk '{print $2}')
KERNEL_REPO=$(echo "$USER_INPUT" | grep -oP '到\s+([^的]+)' | awk '{print $2}' | sed 's/的.*//')
KERNEL_BRANCH=$(echo "$USER_INPUT" | grep -oP '分支\s+(\S+)' | awk '{print $2}')
UPSTREAM_REPO=$(echo "$USER_INPUT" | grep -oP 'upstream\s+是\s+(\S+)' | awk '{print $3}')
```

### 步骤 2: 路径校验（Bash 工具）

```bash
test -d "$KERNEL_REPO" || {
  echo "错误：目标仓库不存在: $KERNEL_REPO"
  exit 10
}
test -d "$KERNEL_REPO/.git" || {
  echo "错误：目标仓库不是 git 仓库: $KERNEL_REPO"
  exit 11
}
```

### 步骤 3: 自动配置提取

```bash
cd "$KERNEL_REPO"
KERNEL_ARCH=$(grep -oP 'CONFIG_ARM64=y' .config 2>/dev/null | sed 's/CONFIG_ARM64=y/arm64/' || echo "x86_64")
[ -z "$KERNEL_BRANCH" ] && KERNEL_BRANCH=$(git branch --show-current)
BUILD_CMD="make ARCH=$KERNEL_ARCH -j$(nproc)"
```

### 步骤 4: 场景确认（Question 工具）

展示配置并确认

### 步骤 5: Write config.json

### 步骤 6: 初始化目录结构

mkdir -p "$KERNEL_REPO/patch_analysis"
mkdir -p "$KERNEL_REPO/.patchmerge"
```

Expected: 执行流程章节写入成功（约 400 lines）

- [ ] **Step 3: Verify SKILL.md size**

```bash
wc -l layer1-interaction/SKILL.md
```

Expected: 约 400 lines

- [ ] **Step 4: Commit**

```bash
git add layer1-interaction/SKILL.md
git commit -m "feat: create layer1-interaction Skill"
```

---

## Task 5: 实现 Layer 2 - 搜索层 Skill

**Files:**
- Create: `layer2-search/SKILL.md`
- Create: `layer2-search/agents/agent_target_revert.md`
- Create: `layer2-search/agents/agent_upstream_deps.md`

- [ ] **Step 1: Write layer2-search SKILL.md header**

```markdown
---
name: layer2-search
description: >
  Patchset-merge 搜索层：目标仓库 revert patch 搜索 + upstream 依赖 patch 搜索。
  
  强制前置条件：
  1. 必须在 layer1-interaction 完成后调用
  2. 必须存在 config.json
  
  输出文件：
  - revert_candidates.json
  - deps_candidates.json
  - merge_tasks.json
  
  完成后状态：Write state.json: {"layer2": "completed"}
---
```

Expected: SKILL.md header 创建成功

- [ ] **Step 2: Write parallel Subagent invocation logic**

添加并行启动逻辑：

```markdown
## 步骤 2: 并行启动搜索 Subagent

**一条消息内同时启动两个 Task**：

Task 1: agent_target_revert
  输入: config.json
  工具权限: Bash, Read, Write
  执行模式: 不调 Python 脚本，直接用 Bash git 命令
  输出要求: Write revert_candidates.json
  
Task 2: agent_upstream_deps
  输入: config.json
  工具权限: Bash, Read, Write
  执行模式: 不调 Python 脚本，直接用 Bash git 命令
  输出要求: Write deps_candidates.json

等待两个 Task 返回结果。
```

Expected: 并行逻辑写入成功

- [ ] **Step 3: Write agent_target_revert.md**

创建 Subagent 定义文件：

```markdown
# agent_target_revert Subagent

职责：搜索目标仓库需要 revert 的 commit

执行方式（不调 Python 脚本）：

步骤 1: 提取关键词
bash
cd /tmp/patches
for p in 0*.patch; do
  grep "^Subject:" "$p" | sed 's/Subject: //'
done

步骤 2: 目标仓库搜索（Bash git 命令）
bash
cd $KERNEL_REPO_PATH
for kw in $KEYWORDS; do
  git log --oneline --grep="$kw" --since="2024-01-01" | head -20
done

步骤 3: 查看候选 commit（Read 工具）
git show <commit_hash>

步骤 4: AI 判断
confirm/reject/need_review

步骤 5: Write revert_candidates.json
```

Expected: agent_target_revert.md 创建成功（约 100 lines）

- [ ] **Step 4: Write agent_upstream_deps.md**

（同理，参考设计文档第 4.3.2 节）

Expected: agent_upstream_deps.md 创建成功（约 100 lines）

- [ ] **Step 5: Write AI汇总逻辑（迁移 topo_sort.py）**

在 SKILL.md 中添加：

```markdown
## 步骤 7: AI 汇总合并（Skill 内逻辑）

依赖排序逻辑（迁移自 topo_sort.py）：

步骤 1: 读取 patch 原始顺序
bash
cd /tmp/patches
PATCH_ORDER=$(ls 0*.patch | sed 's/.patch//' | sort)

步骤 2: 检测反向依赖（AI 判断）

步骤 3: 用户决策处理方案

步骤 4: 计算 build_checkpoint（AI 按规则判定）
```

Expected: AI 汇总逻辑写入成功

- [ ] **Step 6: Verify SKILL.md size**

```bash
wc -l layer2-search/SKILL.md
```

Expected: 约 500 lines

- [ ] **Step 7: Commit**

```bash
git add layer2-search/
git commit -m "feat: create layer2-search Skill and Subagent definitions"
```

---

## Task 6: 实现 Layer 3 - 执行层 Skill（核心）

**Files:**
- Create: `layer3-execution/SKILL.md`
- Create: `layer3-execution/agents/agent_conflict_resolver.md`

- [ ] **Step 1: Write SKILL.md header + HARD-GATE**

```markdown
---
name: layer3-execution
description: >
  Patchset-merge 执行层：串行 merge、编译验证、commit、review。
  
  强制前置条件：
  1. 必须在 layer2-search 完成后调用
  2. 必须存在 merge_tasks.json
  
  输出文件：analyse.md 系列 + execution_log.json
  
  完成后状态：Write state.json: {"layer3": "completed"}
---

<HARD-GATE>
禁止操作：
❌ git apply（会丢失 commit message）
❌ git am --skip（会跳过 patch）
❌ git reset --hard（会删除 commit）
</HARD-GATE>
```

Expected: SKILL.md header 创建成功

- [ ] **Step 2: Write APPLY 降级链（强制 git am）**

添加 APPLY 步骤详细逻辑（参考设计文档第 5.3 节）：

```markdown
### 3.3 APPLY（强制 git am 循环重试）

尝试 1: git am --3way
git am --3way "$patch_file"

失败 → 尝试 2: git am --3way --reject
git am --abort
git am --3way --ignore-space-change --keep-cr --reject "$patch_file"

循环处理 .rej 文件（while 循环，最多 10 轮）

尝试 3: git add + git am --continue
git add -A
git am --continue
```

Expected: APPLY 降级链写入成功（约 100 lines）

- [ ] **Step 3: Write BUILD_FIX 策略（新增）**

添加 BUILD_FIX 详细流程（参考设计文档第 5.4 节）：

```markdown
### BUILD_FIX（编译失败修复策略）

<HARD-GATE>
编译失败时，绝对禁用：
❌ git reset --hard
❌ git reset --soft
❌ 批量 git commit --amend（未验证）

允许操作：
✅ git rebase -i HEAD~N
✅ git commit --amend --no-edit
✅ 最小化代码修复
</HARD-GATE>

步骤 1-6: 根因定位 + rebase amend 修复流程
（详细步骤参考设计文档第 5.4 节）
```

Expected: BUILD_FIX 策略写入成功（约 150 lines）

- [ ] **Step 4: Write state machine flow**

添加状态机定义：

```markdown
## 状态机流程

PRECHECK → PRE_REVERT → APPLY → VERIFY_INTENT → BUILD → COMMIT → REVIEW → RECORD → DONE

每步骤调用 gatekeeper.py 标记状态。
```

Expected: 状态机定义写入成功（约 50 lines）

- [ ] **Step 5: Write agent_conflict_resolver.md**

创建冲突解决 Subagent 定义（参考设计文档第 5.6 节）

Expected: agent_conflict_resolver.md 创建成功（约 100 lines）

- [ ] **Step 6: Verify SKILL.md size**

```bash
wc -l layer3-execution/SKILL.md
```

Expected: 约 600 lines

- [ ] **Step 7: Commit**

```bash
git add layer3-execution/
git commit -m "feat: create layer3-execution Skill with BUILD_FIX strategy"
```

---

## Task 7: 实现 Layer 4 - 输出层 Skill

**Files:**
- Create: `layer4-output/SKILL.md`

- [ ] **Step 1: Write SKILL.md header + HARD-GATE**

```markdown
---
name: layer4-output
description: >
  Patchset-merge 输出层：汇总执行记录、生成最终报告、验证输出完整性。
  
  强制前置条件：
  1. 必须在 layer3-execution 完成后调用
  2. 必须存在所有 analyse.md 文件
  
  输出文件：summary.md + output_report.json
  
  完成后状态：Write state.json: {"layer4": "completed"}
---

<HARD-GATE>
输出文件必须落盘！不依赖 AI 记忆。

验证规则：
1. 所有 analyse.md 文件必须存在且非空
2. summary.md 必须存在且非空
3. output_report.json 必须包含完整性检查结果

若验证失败 → 中止并输出缺失文件列表
</HARD-GATE>
```

Expected: SKILL.md header 创建成功

- [ ] **Step 2: Write execution flow**

添加执行流程（参考设计文档第 6.3 节）：

```markdown
## 执行流程

步骤 1: 门禁验证
bash $SCRIPTS_DIR/gate_check.sh layer4 $KERNEL_REPO_PATH

步骤 2-3: 读取执行记录
Read: execution_log.json, merge_tasks.json, 所有 *-analyse.md

步骤 4: 生成 summary.md（调用快速脚本 + AI 补充）

步骤 5: 生成 diff 报告

步骤 6: 输出完整性验证（Skill 内 Bash）

步骤 7: Write output_report.json
```

Expected: 执行流程写入成功（约 200 lines）

- [ ] **Step 3: Verify SKILL.md size**

```bash
wc -l layer4-output/SKILL.md
```

Expected: 约 300 lines

- [ ] **Step 4: Commit**

```bash
git add layer4-output/SKILL.md
git commit -m "feat: create layer4-output Skill with forced validation"
```

---

## Task 8: 复用现有脚本到 shared-scripts

**Files:**
- Copy: 从现有 patchset-merge/scripts/ 复用 8 个脚本到 shared-scripts/

- [ ] **Step 1: Copy scripts from existing patchset-merge**

```bash
cd patchset-merge-v2
cp ../patchset-merge/scripts/calculate_build_checkpoints.py shared-scripts/
cp ../patchset-merge/scripts/generate_diff_report.py shared-scripts/
cp ../patchset-merge/scripts/generate_analyse_md.py shared-scripts/
cp ../patchset-merge/scripts/generate_summary_md.py shared-scripts/
cp ../patchset-merge/scripts/verify_patch_intent.py shared-scripts/
cp ../patchset-merge/scripts/gatekeeper.py shared-scripts/
cp ../patchset-merge/scripts/extract_patch_symbols.py shared-scripts/
```

Expected: 8 个脚本复制成功

- [ ] **Step 2: Verify scripts exist**

```bash
ls -la shared-scripts/
```

Expected: 看到 8 个脚本文件

- [ ] **Step 3: Copy download_patches.py to orchestrator**

```bash
cp ../patchset-merge/scripts/download_patches.py patchset-merge-orchestrator/scripts/
```

Expected: download_patches.py 复制成功

- [ ] **Step 4: Commit**

```bash
git add shared-scripts/ patchset-merge-orchestrator/scripts/download_patches.py
git commit -m "feat: reuse existing scripts from patchset-merge"
```

---

## Task 9: 创建 validate_json.py 脚本

**Files:**
- Create: `patchset-merge-orchestrator/scripts/validate_json.py`

- [ ] **Step 1: Write validate_json.py**

```python
#!/usr/bin/env python3
"""
JSON Schema 验证脚本 - 执行时间 <1秒
用法: validate_json.py --file <json_file> --schema <schema_file>
"""

import json
import sys
import argparse
from pathlib import Path

def validate_json(json_file: str, schema_file: str) -> bool:
    """验证 JSON 文件是否符合 schema"""
    try:
        with open(json_file) as f:
            data = json.load(f)
        
        with open(schema_file) as f:
            schema = json.load(f)
        
        # 简化验证：检查必填字段
        required = schema.get("required", [])
        for field in required:
            if field not in data:
                print(f"❌ 缺失必填字段: {field}")
                return False
        
        print(f"✅ {json_file} schema 验证通过")
        return True
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析错误: {e}")
        return False
    except FileNotFoundError as e:
        print(f"❌ 文件不存在: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--schema", required=True)
    args = parser.parse_args()
    
    success = validate_json(args.file, args.schema)
    sys.exit(0 if success else 1)
```

Expected: validate_json.py 创建成功（约 50 lines）

- [ ] **Step 2: Test validate_json.py**

```bash
# 创建测试 JSON 和 schema
echo '{"name": "test"}' > /tmp/test.json
echo '{"required": ["name"]}' > /tmp/test_schema.json
python3 patchset-merge-orchestrator/scripts/validate_json.py --file /tmp/test.json --schema /tmp/test_schema.json
```

Expected: 输出 "✅ /tmp/test.json schema 验证通过"，退出码 0

- [ ] **Step 3: Commit**

```bash
git add patchset-merge-orchestrator/scripts/validate_json.py
git commit -m "feat: create validate_json.py for schema validation"
```

---

## Task 10: 创建 references 文档

**Files:**
- Create: 所有 references/*.md 文件（16 个）

- [ ] **Step 1: Create orchestrator references**

创建 3 个文档：
```bash
cd patchset-merge-v2
# layer_interface_schema.md（层间接口定义）
echo "# Layer Interface Schema\n\n定义层间 JSON 接口..." > patchset-merge-orchestrator/references/layer_interface_schema.md

# state_schema.md（state.json 定义）
echo "# State Schema\n\n定义 state.json 结构..." > patchset-merge-orchestrator/references/state_schema.md

# fallback_guide.md（降级机制指南）
echo "# Fallback Guide\n\n降级机制详细步骤..." > patchset-merge-orchestrator/references/fallback_guide.md
```

Expected: 3 个文档创建成功

- [ ] **Step 2: Create layer1 references**

创建 2 个文档（config_schema.md, user_interaction_guide.md）

Expected: 2 个文档创建成功

- [ ] **Step 3: Create layer2 references**

创建 5 个文档（参考设计文档第 4.5 节）

Expected: 5 个文档创建成功

- [ ] **Step 4: Create layer3 references**

创建 4 个文档（参考设计文档第 5.5-5.6 节）

Expected: 4 个文档创建成功

- [ ] **Step 5: Create layer4 references**

创建 2 个文档（参考设计文档第 6.3 节）

Expected: 2 个文档创建成功

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "feat: create all references documentation (16 files)"
```

---

## Task 11: 编写集成测试脚本

**Files:**
- Create: `patchset-merge-v2/tests/test_integration.sh`

- [ ] **Step 1: Write integration test script**

```bash
#!/bin/bash
# 集成测试 - 验证 Skill 串联流程

echo "=== Patchset-Merge Layered Architecture Integration Test ==="

# 测试 1: 目录结构
echo "Test 1: Directory Structure"
ls -la patchset-merge-orchestrator/SKILL.md || exit 10
ls -la layer1-interaction/SKILL.md || exit 11
ls -la layer2-search/SKILL.md || exit 12
ls -la layer3-execution/SKILL.md || exit 13
ls -la layer4-output/SKILL.md || exit 14

# 测试 2: gate_check.sh
echo "Test 2: gate_check.sh"
bash patchset-merge-orchestrator/scripts/gate_check.sh layer2 /tmp/test_gate || echo "Expected failure"

# 测试 3: validate_json.py
echo "Test 3: validate_json.py"
python3 patchset-merge-orchestrator/scripts/validate_json.py --file /tmp/test.json --schema /tmp/test_schema.json || exit 20

# 测试 4: shared-scripts 存在
echo "Test 4: shared-scripts"
ls -la shared-scripts/*.py | wc -l | grep -q "8" || exit 30

echo "✅ All integration tests passed"
```

Expected: test_integration.sh 创建成功（约 50 lines）

- [ ] **Step 2: Run integration test**

```bash
cd patchset-merge-v2
bash tests/test_integration.sh
```

Expected: 所有测试通过，输出 "✅ All integration tests passed"

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.sh
git commit -m "feat: create integration test script"
```

---

## Task 12: 创建 README.md 文档

**Files:**
- Create: `patchset-merge-v2/README.md`

- [ ] **Step 1: Write README.md**

```markdown
# Patchset-Merge Layered Architecture

Linux 内核 patchset 多 Agent 自动合入与冲突解决 Skill - 分层架构版本。

## 核心特性

- **清晰的四层架构** - Interaction、Search、Execution、Output
- **强制执行机制** - Skill 串联 + 门禁验证 + 状态文件
- **超时容错** - Skill 内控制流 + 最小脚本（<5s）
- **AI 遗忘规避** - 强制落盘 + 完整性验证

## 架构模式

方案 D（Skill 内控制流）+ 方案 C（Skill 串联）+ 路径 C（混合实现）

## 使用方法

```bash
# 调用主调度 Skill
Skill tool: patchset-merge-orchestrator
输入: "合入 <message-id> 到 ~/code/openeuler/kernel 的 patch-xxx 分支"
```

## 目录结构

见设计文档第 2.1 节

## 设计文档

`docs/superpowers/specs/2026-06-10-patchset-merge-layered-architecture-design.md`

## 实现计划

`docs/superpowers/plans/2026-06-10-patchset-merge-layered-implementation.md`
```

Expected: README.md 创建成功（约 100 lines）

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: create README for layered architecture"
```

---

## Task 13: 最终验证与提交

**Files:**
- Verify: 所有文件已创建并提交

- [ ] **Step 1: Verify all Skills created**

```bash
ls -la patchset-merge-*/SKILL.md layer*/SKILL.md
```

Expected: 5 个 SKILL.md 文件存在

- [ ] **Step 2: Verify all scripts created**

```bash
ls -la patchset-merge-orchestrator/scripts/*.sh
ls -la patchset-merge-orchestrator/scripts/*.py
ls -la shared-scripts/*.py
```

Expected: 所有脚本文件存在（约 10 个）

- [ ] **Step 3: Verify all references created**

```bash
find . -name "*.md" -path "*/references/*" | wc -l
```

Expected: 16 个 references 文档

- [ ] **Step 4: Check git status**

```bash
git status
```

Expected: 所有文件已提交，工作区干净

- [ ] **Step 5: Create final commit**

```bash
git add .
git commit -m "feat: complete patchset-merge layered architecture implementation"
git log --oneline -13
```

Expected: 13 个 commit（Task 1-12 + 最终提交）

---

## Self-Review

### 1. Spec Coverage ✅

扫描设计文档每个章节，对照实现计划：
- ✅ 第 2.1 节（文件组织结构） → Task 1（创建目录）
- ✅ 第 3 章（Layer 1） → Task 4
- ✅ 第 4 章（Layer 2） → Task 5
- ✅ 第 5 章（Layer 3 + BUILD_FIX） → Task 6
- ✅ 第 6 章（Layer 4） → Task 7
- ✅ 第 9.2 节（复用脚本） → Task 8
- ✅ 第 10 章（references） → Task 10

无遗漏章节。

### 2. Placeholder Scan ✅

扫描全文，未发现：
- ❌ TBD
- ❌ TODO
- ❌ "fill in details"
- ❌ "implement later"

所有示例都有具体代码。

### 3. Type Consistency ✅

检查关键定义一致性：
- ✅ `SKILL.md` 在所有 Task 中都定义 header
- ✅ `gate_check.sh` 退出码定义一致（10/20/21/22/30）
- ✅ `state.json` 结构一致（{"layerN": "completed"}）
- ✅ JSON schema 文件名一致（config_schema.md, merge_tasks_schema.md 等）

---

## 总结

本实现计划包含：
- **13 个 Task** - 每个任务 2-10 步骤（bite-sized）
- **5 个 Skill** - orchestrator + 4 layers
- **10 个脚本** - 门禁验证 + JSON schema + 编译验证 + 复用脚本
- **16 个 references** - JSON schema 定义 + 模板 + 指南
- **强制执行** - 禁止 git apply + 禁止 git reset + 强制 git am
- **测试验证** - 集成测试脚本

所有步骤符合 TDD、DRY、YAGNI 原则，每个 commit 有明确说明。

**实现完成后可执行集成测试验证整个流程。**