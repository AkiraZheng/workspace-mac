# Revert 机制设计 — 混合模式：用户确认 + 自动执行 + 安全回滚

## 1. 问题背景

当前 revert 机制存在以下问题：

| 问题 | 说明 |
|------|------|
| PR commits 列表不完整 | `detect_duplicate.py` 只收集 matched commits，PR 内其他 commits 被漏掉 |
| revert 顺序不确定 | `--ancestry-path` 要求时间排序，当前按列表加入顺序 |
| 无预执行验证 | 直接 `git revert`，失败后无保障 |
| 无回滚机制 | revert 失败后无法恢复 |
| 单 commit 依赖缺失 | 单 commit 有后续依赖 commits 时未检测 |
| 无用户确认环节 | revert 决策自动执行，用户无介入点 |

核心策略：**要合入的 patch 绝不跳过**。重复/等效 → `pre_revert` → revert v1 → 合入 v2。

## 2. 整体架构

```
Phase 1 步骤 5 — detect_duplicate.py → duplicate_analysis.json
  (patch 匹配矩阵 + PR 聚合 + revert 建议)

Phase 1.5 步骤 3 — generate_revert_plan.py → revert_plan.json
  (从分析结果生成执行计划)

Phase 1.5 步骤 5 — 用户确认 revert 方案
  (展示完整信息: commit diff, 影响范围, 风险评估, 执行预览)

Phase 2 PRE_REVERT — execute_revert.py
  (读取 revert_plan.json, 预执行 → 正式执行 → 失败处理)
```

### 文件职责

| 文件 | 阶段 | 职责 |
|------|------|------|
| `duplicate_analysis.json` | Phase 1 | 分析结果（只读输入） |
| `revert_plan.json` | Phase 1.5 | 用户确认后的执行计划（Phase 2 输入） |
| `revert_plan.sh` | Phase 1.5 | 手动执行备选脚本 |

## 3. 数据 Schema

### 3.1 revert_plan.json

```json
{
  "generated_at": "ISO8601",
  "target_repo": "$KERNEL_REPO_PATH",
  "target_branch": "$KERNEL_BRANCH",
  "revert_items": [
    {
      "seq": 1,
      "type": "pr_whole | pr_partial | single_commit",
      "pr_id": "PR #123 或 commit hash",
      "pr_info": {"source": "commit_msg_link 或 null"},
      "commits": {
        "abc123": {"subject": "arm64: HDBSS sysreg 定义", "similarity": 95.0, "matched": true},
        "def456": {"subject": "arm64: HDBSS 特性检测",  "similarity": 85.0, "matched": true},
        "ghi789": {"subject": "arm64: 不相关修复",      "similarity": 20.0, "matched": false}
      },
      "commit_count": 3,
      "matched_count": 2,
      "coverage_rate": 66.7,
      "strategy": "revert_whole_pr | revert_matched | direct_revert",
      "revert_targets": ["按时间排序的 revert 目标 commits"],
      "revert_order": ["逆序排列的 commits（最新→最早）"],
      "revert_cmds": ["具体 git revert 命令"],
      "urgency": "必须 | 建议",
      "risk_assessment": {
        "dependent_commits": ["通过 git log --ancestry-path 检测到的后续依赖"],
        "affected_files": ["所有 revert commits 涉及的文件的并集"],
        "estimated_conflict_risk": "高 | 中 | 低"
      },
      "related_patches": ["关联的 patchset task_id"]
    }
  ]
}
```

> **说明**：
> - `type: pr_whole` 或 `pr_partial`：`commits` 包含 PR 的**全部 commits**（通过 `git log --ancestry-path` 获取），不只是 matched commits
> - `type: single_commit`：`commits` 只有一个 commit，`commit_count=1`
> - `revert_targets` 按 commit 时间排序（最早→最新），`revert_order` 按逆序（最新→最早）
> - `dependent_commits` 检测方法：`git log --ancestry-path <commit>..HEAD --format=%H`（查找该 commit 之后、可能依赖该 commit 的 commits）

## 4. 用户确认展示

### 4.1 Phase 1.5 预览模板

```
═══════════════════════════════════════════════
  Revert 方案预览
═══════════════════════════════════════════════

[1] PR #123（3 commits, 2 个匹配, 覆盖率 66.7%, urgency=建议）
    ┌─────┬──────────────────────┬──────────┬──────────────────────────┐
    │ Seq │ Commit               │ 相似度   │ Subject                  │
    ├─────┼──────────────────────┼──────────┼──────────────────────────┤
    │  1  │ abc123               │ 95.0% ✓  │ arm64: HDBSS sysreg 定义  │
    │  2  │ def456               │ 85.0% ✓  │ arm64: HDBSS 特性检测     │
    │  3  │ ghi789               │ 20.0% ✗  │ arm64: 其他不相关修复     │
    └─────┴──────────────────────┴──────────┴──────────────────────────┘

    策略：逐个 revert 匹配的 commits（逆序）
      git revert def456  # "HDBSS 特性检测"
      git revert abc123  # "HDBSS sysreg 定义"
    影响文件：drivers/gpu/arm/core.c, include/linux/kvm_host.h
    关联 patch：0001, 0002
    风险：低（无后续依赖 commits）

[2] 独立 commit jkl012（相似度 90.0%, urgency=必须）
    策略：直接 revert
      git revert jkl012  # "修复 KVM 内存泄漏"
    影响文件：virt/kvm/kvm_main.c
    关联 patch：0004
    风险：低

═══════════════════════════════════════════════
  请选择：
  [1] 确认执行全部
  [2] 跳过某项
  [3] 调整某项的 revert 范围
  [4] 查看某项详细信息
  [5] 中止
```

## 5. Phase 2 PRE_REVERT 执行流程

### 5.1 状态机

```
                        ┌─────────────┐
            start ───→  │ 检查 revert │ ─→ revert_plan 为空 → 跳过
                        │ _plan.json  │
                        └──────┬──────┘
                               ↓ (有 items)
                        ┌──────────────┐
                        │ 创建 checkpoint│
                        │ BACKUP_PRE_   │
                        │ REVERT        │
                        └──────┬───────┘
                               ↓
                    ┌──────────────────────┐
          ┌───────→│  对每个 item (按 seq) │
          │        └──────────┬───────────┘
          │                   ↓
          │        ┌───────────────────┐
          │        │ 对 item 内每个     │
          │        │ commit (逆序):     │
          │        └────────┬──────────┘
          │                 ↓
          │        ┌──────────────────┐
          │        │ 预执行 check:     │
          │        │ git revert        │
          │        │ --no-commit       │
          │        └────┬─────────────┘
          │        成功  │  失败
          │    ┌─────────┴──────────┐
          │    ↓                    ↓
          │ ┌──────────┐   ┌────────────────┐
          │ │ 正式执行： │   │ 失败处理：      │
          │ │ git commit │   │ (参见 5.3)     │
          │ └─────┬─────┘   └────────────────┘
          │       │
          │  成功  │  失败 ─→ 失败处理 (5.3)
          │       ↓
          │ ┌───────────┐
          │ │ 记录成功   │
          │ │ 到 state_log│
          │ └─────┬─────┘
          │       ↓
          │ next commit ──→ 循环
          │       ↓ (item 内全部完成)
          │ next item ──→ 循环
          │       ↓ (全部完成)
          │ ┌───────────┐
          └─│ DONE       │
            └───────────┘
```

### 5.2 预执行检查

```bash
if git revert --no-commit <commit> 2>&1; then
    # 预执行成功，无冲突
    if git commit -m "Revert <commit>" --no-edit; then
        echo "[PASS] revert <commit> 成功"
    else
        # 正式 commit 失败（极少见，可能被hook拦截，或提交信息冲突）
        handle_failure(<commit>, "commit失败")
    fi
else
    # 预执行失败，有冲突或无法 revert
    handle_failure(<commit>, "预执行冲突")
fi
```

### 5.3 失败处理

#### 自动降级策略

```
revert 整个 PR 失败：
  → 降级为"逐个 revert matched commits"
     └─ 逐个 revert 也失败：
        → 降级为"跳过此项，记录原因到 execution_log"

单个 commit revert 失败：
  → 降级为"尝试 --strategy=recursive 重试"
     └─ 仍失败：
        → 暂停，进入用户决策
```

#### 用户决策选项

| 选项 | 操作 | 何时使用 |
|------|------|---------|
| **[1] 跳过此项** | `git checkout -- .` 清理 → 继续下一个 item | 非关键的独立 commit |
| **[2] 回退全部** | `git reset --hard BACKUP_PRE_REVERT` | 回退方案需整体重新设计 |
| **[3] 中止导出** | 保存状态到 revert_plan.json → 退出 | 需离线分析冲突原因 |
| **[4] 手动修复** | 用户解决冲突 → 执行 `git commit` | 冲突小、可快速解决 |

### 5.4 回滚 checkpoint 机制

```bash
# Phase 2 PRE_REVERT 开始前
git branch -f BACKUP_PRE_REVERT HEAD

# 每个 item 成功后更新状态
item["state"] = "completed"

# 回滚时
git reset --hard BACKUP_PRE_REVERT
git branch -D BACKUP_PRE_REVERT
```

## 6. revert_plan.sh 生成

由 `generate_revert_plan.py` 生成供用户手动执行的脚本：

```bash
#!/bin/bash
# revert_plan.sh — revert 执行脚本（自动生成）
# 用法: bash revert_plan.sh <repo_path>

set -euo pipefail
REPO="${1:?需要指定仓库路径}"
BACKUP_REF="BACKUP_PRE_REVERT"

cd "$REPO" || exit 1

git branch -f "$BACKUP_REF" HEAD
echo "[CHECKPOINT] $BACKUP_REF"

# [1/2] revert def456 (PR #123, 相似度 85%)
echo "[REVERT 1/2] git revert def456"
if git revert --no-commit def456; then
    git commit -m "Revert def456 (PR #123 arm64: HDBSS 特性检测)"
    echo "  PASS"
else
    echo "  FAIL: 预执行冲突"
    echo "  手动修复: git checkout -- . && git revert --continue"
    echo "  或回退:   git reset --hard $BACKUP_REF"
    exit 1
fi

# [2/2] revert abc123 (PR #123, 相似度 95%)
echo "[REVERT 2/2] git revert abc123"
if git revert --no-commit abc123; then
    git commit -m "Revert abc123 (PR #123 arm64: HDBSS sysreg 定义)"
    echo "  PASS"
else
    echo "  FAIL: 预执行冲突, 请手动修复"
    exit 2
fi

echo "[DONE] 全部 revert 完成"
```

## 7. 脚本清单

### 7.1 新增脚本

| 脚本 | 功能 | 调用时机 |
|------|------|---------|
| `scripts/generate_revert_plan.py` | 从 duplicate_analysis.json 生成 revert_plan.json + revert_plan.sh | Phase 1.5 步骤 3 |
| `scripts/execute_revert.py` | 读取 revert_plan.json，预执行+正式执行+失败处理 | Phase 2 PRE_REVERT |

### 7.2 修改现有脚本

| 脚本 | 改动 |
|------|------|
| `scripts/detect_duplicate.py` | 扩展符号提取（struct/enum/typedef）；获取 PR 完整 commits（ancestry-path）；时间排序；增加 dependent_commits 检测 |

### 7.3 修改文档

| 文件 | 改动 |
|------|------|
| `SKILL.md` | Phase 1.5 步骤 3 改为调用 generate_revert_plan.py + 展示方案 + 用户确认；Phase 2 PRE_REVERT 改为调用 execute_revert.py |
| `references/output-templates.md` | 新增 revert_plan.json schema；新增 checkpoint/回滚说明 |

## 8. revert 策略判定规则

### 8.1 候选匹配

| 条件 | 判定 |
|------|------|
| 综合相似度 >= 80% | 高匹配（计入 PR 覆盖率） |
| 综合相似度 50-79% | 中匹配（不计入覆盖率，标记可能冲突） |
| 综合相似度 < 50% | 低匹配（忽略） |

综合相似度 = max(diff_similarity, symbol_similarity)，任一 >= 80% 即为高匹配。

### 8.2 PR 级别决策

| coverage | 策略 | urgency |
|----------|------|---------|
| >= 75% | revert 整个 PR（所有 commits） | 必须 |
| 50-74% | revert 匹配的 commits（逐个逆序） | 建议 |
| < 50% | 不自动 revert, 合入时冲突解决 | 无须 |

### 8.3 单 commit 决策

| 条件 | 策略 |
|------|------|
| 高匹配 + 无后续依赖 commits | direct_revert |
| 高匹配 + 有后续依赖 commits | 标记"需确认"，展示关联 commits |

## 9. 测试计划

### 9.1 单元测试

| 测试 | 覆盖 |
|------|------|
| 符号提取（struct/enum/typedef） | detect_duplicate.extract_symbols_from_diff |
| PR 完整 commits 获取 | detect_duplicate 的新方法 |
| 时间排序 | sort_commits_by_time |
| revert 判定逻辑 | calculate_pr_coverage / 单 commit 决策 |

### 9.2 集成测试

| 测试 | 覆盖 |
|------|------|
| 完整 flow 测试 | detect_duplicate → generate_revert_plan → execute_revert |
| 失败降级测试 | 预执行冲突 → 自动降级 → 用户决策 |
| 回滚测试 | 部分成功 → 用户回退 → 验证干净状态 |
| 脚本生成测试 | revert_plan.sh 可执行性验证 |
