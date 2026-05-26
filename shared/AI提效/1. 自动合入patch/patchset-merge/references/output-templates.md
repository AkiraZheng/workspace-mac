# 输出模板定义

## analyse.md 固定模板

复制以下模板，将 `{占位符}` 替换为实际值。Phase 2 落盘时使用。

```markdown
# Patch {补丁编号}: {补丁标题}

## 1. 基本信息
| 项 | 值 |
|----|-----|
| 来源 commit | {上游提交} |
| 作者 | {作者} |
| 涉改文件数 | {文件数} |
| 合入状态 | {合入状态} |

## 2. 功能描述与关联模块

{功能描述}
关联模块：{关联模块}

## 3. 依赖分析

### 3.1 高版本依赖（上游版本差异）
{高版本依赖}
<!-- 如无，填写：未找到依赖 -->

### 3.2 Bugfix 依赖（git blame 追溯）
{bugfix 依赖}
<!-- 如无，填写：未找到 blame 记录 -->

### 3.3 前置 patch 依赖（本 patchset 内）
{内部依赖}
<!-- 如无，填写：无内部依赖 -->

### 3.4 目标仓库重复/等效 patch
{重复检测}
<!-- 如无，填写：未找到重复 patch -->
<!-- 若有：精确重复: <commit_hash> | 高概率等效: <commit_hash>:<原因> | 可能冲突: <原因> -->

## 4. Revert 需求评估

| 必要性等级 | {revert 等级} |
|-----------|-------------|
| 要 revert 的 commit | {revert 提交列表} |
| 理由 | {revert 理由} |

## 5. 风险程度

**{风险等级}**
{风险详述}

## 6. 人工 Review 需求度

**{review 需求}**
{review 理由}

## 7. 建议验证冒烟内容
{验证项}

## 8. 合入实际经验
（Phase 2 完成后填充，包含冲突解决过程、编译修复记录、重试次数）

- 冲突解决：{冲突详情}
- 编译修复：{编译修复详情}
- 重试次数：冲突 {冲突轮数} 次 / 编译 {编译轮数} 次

## 9. 与源 Patch/Commit 的差异对比

**对比对象**：
- **merge 场景**：原始 `.patch` 文件（下载的 patch 意图）vs 合入后的 commit（`git show <commit>` 的实际落地的代码）
- **revert 场景**：被 revert 的原 commit（回退目标）vs revert commit（回退操作产生的 commit）

**输出焦点**：只展示偏离部分，不重复完整内容。由 `scripts/generate_diff_report.py` 生成。

**脚本调用**：
```bash
# merge 场景
python3 scripts/generate_diff_report.py \
  --source "patch:/tmp/patches/0001-xxx.patch" \
  --target <commit_hash> --repo-path "$KERNEL_REPO_PATH" \
  --execution-log "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "0001"

# revert 场景（镜像对比）
python3 scripts/generate_diff_report.py \
  --source "commit:<被_revert_的_commit>" \
  --target <revert_commit_hash> --repo-path "$KERNEL_REPO_PATH" \
  --mode revert \
  --execution-log "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "0001"
```

**偏离类型标注**：
- 源有目标无：patch/原 commit 有此行，实际 commit 无（因冲突跳过/被删除）
- 目标有源无：实际 commit 有此行，源 patch/原 commit 无（因适配新增/git am 自动调整）
- revert 模式：源添加→目标应删除，源删除→目标应恢复（镜像匹配）

**根因分析**：
偏离标注后会从 execution_log 中提取根因（来自 Phase 2 的合入经验：冲突解决过程/编译修复记录/适配原因）。

```diff
{差异对比内容，由 generate_diff_report.py 生成}
```

## 10. 编译验证记录

```
编译命令结果：
  错误数: {错误数量}
  产物: {产物路径及状态}
  重试: {编译轮数} 次
```

## 11. Review 建议与改进方向
（Phase 3 汇总时由主 Agent 填入，基于对 patch 的深度理解）

### 功能改进建议
{功能改进}
<!-- 如无，填写：无 -->

### 潜在 Bug 提示
{潜在 bug}
<!-- 基于 blame 追溯和依赖分析标记的隐患 -->
<!-- 如无，填写：无 -->

### 代码质量建议
{代码质量}
<!-- 代码结构、命名、错误处理、锁使用等 -->
<!-- 如无，填写：无 -->

### 适配建议
{适配建议}
<!-- 针对目标仓库的适配注意事项，如后续 clean-up、upstream 跟进等 -->
<!-- 如无，填写：无 -->
```

## summary.md 固定模板

Phase 3 汇总落盘时使用，由主 Agent 读取所有 analyse.md 后填入。

```markdown
# Patchset Merge 汇总报告

## 基本信息
| 项 | 值 |
|----|-----|
| 来源 | {来源} |
| Patch 总数 | {总数} |
| 合入成功 | {成功数} |
| 跳过 | {跳过数} |
| 失败 | {失败数} |
| 目标分支 | {分支} |
| 操作时间 | {开始时间} ~ {结束时间} |

## 合入顺序与状态
| 序号 | Patch | 状态 | 风险 | Review | 备注 |
|-----|-------|------|------|--------|------|
{合入状态表格}

## 依赖关系图
{依赖关系}

## Revert 记录
| Commit | 原因 | 关联 Patch |
|--------|------|-----------|
{revert 记录}

## 编译验证总览
| Patch | 编译结果 | 错误数 | 修复次数 |
|-------|---------|-------|---------|
{编译总览}

## 跨 Patch 修复记录
{跨 patch 修复}

## 目标仓库重复 patch 汇总
{重复 patch 汇总}

## 全局改进建议
（主 Agent 汇总各 patch 第 11 节的建议，去重提炼）

### 高优先级
{高优建议}
<!-- 跨 patch 共性问题，建议优先处理 -->

### 中优先级
{中优建议}
<!-- 单个 patch 的关键改进 -->

### 低优先级 / 长期
{低优建议}
<!-- 代码风格统一、upstream 跟进等 -->

## 全局风险汇总
- 高风险 patch：{高风险列表}
- 建议重点人工 review：{review 推荐列表}

## 待处理事项
{待处理}
```

## merge_tasks.json 固定 Schema

Phase 1.5 主 Agent 生成，Phase 2 merge agent 消费。**必须严格按此 schema，不可自行增减或重命名字段。**

> **存储路径**：`$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json`
> **辅助文件**：`$KERNEL_REPO_PATH/patch_analysis/analysis_cache.json`

```json
{
  "patchset_info": {
    "source": "<来源描述>",
    "download_method": "b4|wget|local",
    "total_patches": 5,
    "target_kernel": "$KERNEL_REPO_PATH",
    "target_branch": "$KERNEL_BRANCH",
    "build_target": "$BUILD_CMD"
  },
  "workflow_hints": {
    "BUILD_FIX": "只修改 patch 相关文件；config 问题临时修改后 git restore；错误超过 10 个时暂停等待用户决策",
    "COMMIT_ORDER": "必须按 merge_order 顺序，每个 patch 一个 commit",
    "REVERT_POLICY": "逆序 revert（最新→最旧），每 revert 一个就 commit 一个",
    "BUILD_REQUIREMENT": "编译整个仓库 $BUILD_CMD -j$(nproc)，error=0 + 产物存在"
  },
  "current_state": null,
  "global_revert_order": [
    {
      "pr_id": "PR #123",
      "pr_url": "https://github.com/torvalds/linux/pull/123",
      "subject": "HDBSS 功能系列",
      "commits": ["abc123", "def456"],
      "commit_count": 2,
      "revert_strategy": "整体 revert PR #123",
      "revert_cmd": "git revert --ancestry-path abc123^..def456",
      "urgency": "必须",
      "related_patches": ["0001", "0003"]
    }
  ],
  "deps_order": [
    {
      "seq": 1,
      "task_id": "dep-001",
      "source_pr": "PR #456",
      "status": "pending",
      "patch_file": "/tmp/patches/deps/0001-dep.patch",
      "subject": "stage2 页表重构",
      "author": "upstream author",
      "files_changed": ["file1.c"],
      "action": "apply",
      "skip_reason": null,
      "pre_revert": [],
      "depends_on": [],
      "risk_level": "低",
      "review_required": "低",
      "blame_hits": [],
      "duplicate_info": {"level": "无重复", "detail": ""},
      "conflicts_predicted": [],
      "special_notes": "上游依赖，Phase 1.5 步骤 6 拉取",
      "pr_mapping": {},
      "execution_log": []
    }
  ],
  "merge_order": [
    {
      "seq": 1,
      "task_id": "0001",
      "status": "pending",
      "patch_file": "/tmp/patches/0001-xxx.patch",
      "subject": "patch subject",
      "author": "patch author",
      "files_changed": ["file1.c", "file2.h"],
      "action": "apply",
      "skip_reason": null,
      "pre_revert": [],
      "depends_on": [],
      "risk_level": "低",
      "review_required": "低",
      "blame_hits": [],
      "duplicate_info": {"level": "无重复", "detail": ""},
      "conflicts_predicted": [],
      "special_notes": "",
      "pr_mapping": {
        "upstream_deps": [
          {
            "pr_id": "PR #456",
            "pr_url": "https://github.com/torvalds/linux/pull/456",
            "commits": ["dep-abc"],
            "cover_letter_msgid": "xxx@lore.kernel.org",
            "download_cmd": "b4 am xxx@lore.kernel.org",
            "reason": "缺失函数 stage2_try_set_pte"
          }
        ],
        "bugfix_deps": [
          {
            "pr_id": "独立 commit",
            "commits": ["fix-ghi789"],
            "reason": "修复空指针"
          }
        ],
        "revert_candidates": [
          {
            "pr_id": "PR #456",
            "commits": ["local-abc", "local-def"],
            "subject": "本地 HDBSS 实现",
            "revert_cmd": "git revert --ancestry-path local-abc^..local-def",
            "urgency": "必须"
          }
        ]
      },
      "execution_log": []
    }
  ]
}
```

### 字段说明

| 字段 | 必填 | 类型 | 说明 |
|------|:--:|------|------|
| `seq` | ✓ | int | 执行序号，merge agent 严格按此升序执行 |
| `task_id` | ✓ | string | 补零 4 位（如 `"0001"`）或 `dep-001`~`dep-00N`（依赖 patch） |
| `status` | ✓ | string | `pending` / `in_progress` / `done` / `blocked` / `skipped` / `failed` |
| `patch_file` | ✓ | string | .patch 文件的绝对路径 |
| `subject` | ✓ | string | patch 标题 |
| `author` | ✓ | string | patch 作者 |
| `files_changed` | ✓ | list | 涉改文件路径列表 |
| `action` | ✓ | string | `apply`（需要合入）或 `skip`（跳过） |
| `skip_reason` | - | string/null | 若 action=skip，必须填写具体原因；否则 null |
| `pre_revert` | ✓ | list | 需先 revert 的本地 commit hash |
| `depends_on` | ✓ | list | 前置 task_id 列表（可跨 deps_order / merge_order） |
| `risk_level` | ✓ | string | `高` / `中` / `低` |
| `review_required` | ✓ | string | `高` / `中` / `低` |
| `blame_hits` | ✓ | list | bugfix commit 列表 |
| `duplicate_info` | ✓ | dict | `{"level": "无重复|精确重复|高概率等效|可能冲突", "detail": "..."}` |
| `conflicts_predicted` | ✓ | list | 预判冲突点 |
| `special_notes` | ✓ | string | 合入注意事项 |
| `pr_mapping` | ✓ | dict | PR 映射聚合（见下方 pr_mapping 字段说明） |
| `execution_log` | ✓ | list | 初始 `[]`，Phase 2 动态追加 |
| `state_log` | - | list | gatekeeper 自动追加 `[{"step":"BUILD","time":"...","result":"pass","error_count":0}]` |

### pr_mapping 字段说明

| 字段 | 必填 | 说明 |
|------|:--:|------|
| `upstream_deps` | ✓ | 上游依赖 PR/commit 列表，Phase 1.5 步骤 6 用于拉取 |
| `bugfix_deps` | ✓ | bugfix 依赖 PR/commit 列表 |
| `revert_candidates` | ✓ | 本地需 revert 的 PR/commit 列表 |

每个条目包含：

| 字段 | 必填 | 说明 |
|------|:--:|------|
| `pr_id` | ✓ | PR 编号（如 `"PR #123"`）或 `"独立 commit"` |
| `pr_url` | - | PR 链接（若有） |
| `commits` | ✓ | 该 PR/分组包含的 commit hash 列表 |
| `cover_letter_msgid` | - | lore.kernel.org 的 cover letter message-id |
| `download_cmd` | - | 推荐的拉取命令（如 `b4 am xxx`） |
| `revert_cmd` | - | 推荐的 revert 命令（仅 revert_candidates） |
| `subject` | - | PR/subject 描述 |
| `reason` | ✓ | 依赖/revert 原因 |
| `urgency` | ✓ | `必须` / `建议` / `无须`（仅 revert_candidates） |

### 顶层字段说明

| 字段 | 必填 | 说明 |
|------|:--:|------|
| `patchset_info` | ✓ | 来源/目标/架构等基本信息 |
| `workflow_hints` | ✓ | 关键流程提示（压缩后恢复上下文用，初始由 gatekeeper 自动注入） |
| `current_state` | ✓ | 当前执行状态（null 或 `{"phase","task_id","step","status","last_update"}`；gatekeeper 自动管理） |
| `global_revert_order` | ✓ | PR 聚合的全局 revert 列表，Phase 2 PRE_REVERT 阶段消费 |
| `deps_order` | ✓ | 上游依赖 patch 列表（初始 `[]`），Phase 1.5 步骤 6 填充 |
| `merge_order` | ✓ | 主体合入任务列表，Phase 2 主要消费 |

### current_state 字段说明

| 字段 | 说明 |
|------|------|
| `phase` | 当前阶段（如 `PHASE_2_MERGE`） |
| `task_id` | 当前 task_id（如 `0003`） |
| `step` | 当前步骤（`BUILD`/`COMMIT`/`REVIEW`/`DONE`） |
| `status` | `in_progress`/`pass`/`fail` |
| `last_update` | 最后更新时间（ISO 8601） |

**恢复机制**：
```
# Phase 0 或任务启动时检查
python3 gatekeeper.py --merges-file merge_tasks.json --restore
# exit 10 → 有未完成工作，需要恢复
# exit 0  → 无未完成工作

# 恢复后清除标记
python3 gatekeeper.py --merges-file merge_tasks.json --restore --clear
```

**Phase 2 执行顺序**：先遍历 `deps_order`（若有），再遍历 `merge_order`，各自按 `seq` 升序。
| `execution_log` | ✓ | list | 初始 `[]`，Phase 2 动态追加 |

## analysis_cache.json 固定 Schema

Phase 1.5 主 Agent 汇总所有分析 Agent 的屏幕输出后生成。Phase 3 落盘时读取。

```json
{
  "0001": {
    "summary": "功能描述",
    "modules": "关联模块",
    "risk": "中",
    "risk_detail": "具体风险点",
    "revert_level": "建议",
    "revert_commits": ["abc123"],
    "revert_reason": "原因",
    "high_version_deps": ["缺失符号: commit"],
    "bugfix_deps": [
      {"symbol": "xx", "commit": "yy", "desc": "修复了什么"}
    ],
    "internal_deps": ["0002"],
    "duplicate_info": {"level": "无重复", "detail": ""},
    "review_required": "高",
    "review_reason": "为什么",
    "smoke_tests": ["验证点1", "验证点2"],
    "changed_files": ["file1.c", "file2.h"],
    "status_in_target": "在目标仓库中的现状描述",
    "pr_mapping": {
      "upstream_deps": [
        {
          "pr_id": "PR #123",
          "pr_url": "https://github.com/torvalds/linux/pull/123",
          "commits": ["abc123", "def456"],
          "cover_letter_msgid": "xxx@lore.kernel.org",
          "reason": "缺失函数 stage2_try_set_pte"
        }
      ],
      "bugfix_deps": [
        {
          "pr_id": "独立 commit",
          "commits": ["ghi789"],
          "reason": "修复空指针"
        }
      ],
      "revert_candidates": [
        {
          "pr_id": "PR #456",
          "commits": ["local-abc", "local-def"],
          "subject": "本地 HDBSS 实现",
          "urgency": "必须"
        }
      ]
    }
  }
}
```

### 字段说明

| 字段 | 必填 | 说明 |
|------|:--:|------|
| `summary` | ✓ | 功能描述 |
| `modules` | ✓ | 关联模块 |
| `risk` | ✓ | 风险程度：高/中/低 |
| `risk_detail` | ✓ | 风险具体说明 |
| `revert_level` | ✓ | 必须/建议/无须 |
| `revert_commits` | ✓ | 需 revert 的 commit 列表，无须则为 `[]` |
| `revert_reason` | ✓ | revert 理由 |
| `high_version_deps` | ✓ | 上游依赖列表 |
| `bugfix_deps` | ✓ | bugfix 依赖列表 |
| `internal_deps` | ✓ | patchset 内部依赖列表 |
| `duplicate_info` | ✓ | `{"level": "...", "detail": "..."}` |
| `review_required` | ✓ | 高/中/低 |
| `review_reason` | ✓ | review 理由 |
| `smoke_tests` | ✓ | 验证项列表 |
| `changed_files` | ✓ | 涉改文件列表 |
| `status_in_target` | ✓ | 目标仓库现状描述 |
| `pr_mapping` | ✓ | PR 映射聚合（Phase 0 步骤 6 产物，字段见 merge_tasks.json 的 pr_mapping 说明） |

## Phase 1 分析 Agent 屏幕输出格式

分析 Agent 不写文件，用以下结构化格式输出到屏幕（供主 Agent 解析）：

```
[PATCH-0001]
描述=功能描述
模块=关联模块（逗号分隔）
风险=高|中|低
风险详述=具体风险点
revert=必须|建议|无须 | commit_hash1,commit_hash2
revert理由=原因
依赖=缺失符号1:commit_hash1;缺失符号2:commit_hash2
blame记录=commit_hash1 (类型):描述;commit_hash2 (类型):描述
重复检测=无重复|精确重复:hash|高概率等效:hash:原因|可能冲突:原因
review需求=高|中|低
review理由=原因
验证项=验证点1;验证点2
```

### 字段说明

| 字段 | 格式 | 示例 |
|------|------|------|
| 描述 | 一句话中文描述 | KVM arm64 引入 5 级页表 stub |
| 模块 | 逗号分隔 | KVM,mmu,stage-2 |
| 风险 | 高/中/低 | 中 |
| 风险详述 | 1-2 句话 | 涉及页表遍历核心路径 |
| revert | 等级 \| hash列表 | 建议 \| abc123,def456 |
| revert理由 | 一句话 | 本地已实现该功能 |
| 依赖 | 符号:commit;符号:commit | kvm_stage2_get_level:abc123; |
| blame记录 | hash (类型):描述; | def789 (bugfix):修复空指针 |
| 重复检测 | 等级:详情 | 精确重复:abc123 |
| review需求 | 高/中/低 | 高 |
| review理由 | 一句话 | 页表级别变更需人工确认 |
| 验证项 | 分号分隔 | 启动 qemu 验证 KVM;检查 stage-2 页表 |

## Phase 1.5 全局预览模板（展示给用户确认）

Phase 1 分析和 Phase 1.5 汇总完成后，主 Agent 将以下 4 个部分结构化输出到屏幕，供用户确认后再进入 Phase 2。

---

### 第 1 部分：依赖 Patch 汇总

列出 patchset 所有依赖项（外部依赖 + 内部依赖 + bugfix 依赖），**优先按 PR 聚合展示**：

```
═══════════════════════════════════════════════
  依赖 Patch 汇总（PR 聚合）
═══════════════════════════════════════════════

[外部依赖] 需要从上游合入的前置 patch（按 PR 聚合）：

┌──────────────┬──────────────────────────────────────────────────────┐
│ PR #123      │ stage2 页表重构系列（含 3 个 commit）               │
│ github.com/..│ 原因: 缺失函数 stage2_try_set_pte 等                │
├──────────────┼──────────────────────────────────────────────────────┤
│ 包含 commit: │ - abc123: "arm64: mmu: refactor stage2 page table"   │
│              │ - def456: "arm64: add stage2_try_set_pte helper"    │
│              │ - ghi789: "arm64: use stage2_try_set_pte in KVM"    │
│ 推荐拉取:    │ b4 am 2024xxx@lore.kernel.org                       │
└──────────────┴──────────────────────────────────────────────────────┘

┌──────────────┬──────────────────────────────────────────────────────┐
│ [独立 commit]│ commit-jkl012                                        │
│              │ 原因: 缺失宏 VTCR_EL2_HDBSS                          │
│ 推荐拉取:    │ cherry-pick jkl012                                   │
└──────────────┴──────────────────────────────────────────────────────┘

[内部依赖] patchset 内部依赖链：

┌──────────┬──────────┬──────────────────────────────┐
│ Patch    │ 依赖     │ 原因                         │
├──────────┼──────────┼──────────────────────────────┤
│ 0003     │ 0001     │ 引用 0001 引入的 sysreg 宏   │
│ 0004     │ 0001,    │ 调用 0003 的函数 +          │
│          │ 0003     │ 依赖 0001 的寄存器定义       │
└──────────┴──────────┴──────────────────────────────┘

[Bugfix 依赖] 目标仓库已存在但需回溯的 bugfix（按 PR 聚合）：

┌──────────────┬──────────────────────────────────────────────────────┐
│ PR #456      │ KVM 内存泄漏修复系列（含 2 个 commit）               │
├──────────────┼──────────────────────────────────────────────────────┤
│ 包含 commit: │ - mno345: "KVM: fix memory leak in stage2"          │
│              │ - pqr678: "KVM: add cleanup helper"                 │
│ 推荐拉取:    │ cherry-pick mno345..pqr678                          │
└──────────────┴──────────────────────────────────────────────────────┘

📋 拉取策略推荐：
   [优先] 含 PR 的 → b4 am <cover-letter-msgid> 或 cherry-pick <range>
   [备选] 独立 commit → 逐个 cherry-pick

   确认"继续"后将自动执行拉取，结果写入 deps_order。
```

---

### 第 2 部分：Revert 清单（PR 聚合 + 逆序）

列出所有需回退的本地 commit，**优先按 PR 聚合，组内按 commit 时间逆序**：

```
═══════════════════════════════════════════════
  Revert 清单（PR 聚合）
═══════════════════════════════════════════════

  执行顺序（从上到下，PR 内部逆序）：

┌──────┬──────────────┬──────────────────────────────────┬──────────────┬──────────┐
│ 序号 │ PR / Commit  │ Subject                          │ 关联 Patch   │ 紧急度   │
├──────┼──────────────┼──────────────────────────────────┼──────────────┼──────────┤
│  1   │ PR #123      │ HDBSS 功能系列（3 commits）      │ 0001-0005    │ 必须     │
│      │   └ abc123   │   └ HDBSS 初始实现 v2           │              │          │
│      │   └ def456   │   └ 添加 HDBSS sysreg           │              │          │
│      │   └ ghi789   │   └ KVM 集成 HDBSS              │              │          │
│      │ revert_cmd:  │ git revert --ancestry-path       │              │          │
│      │              │   abc123^..ghi789                │              │          │
├──────┼──────────────┼──────────────────────────────────┼──────────────┼──────────┤
│  2   │ [独立]       │ 修复 HDBSS 内存泄漏              │ 0004         │ 建议     │
│      │   jkl012     │                                  │              │          │
│      │ revert_cmd:  │ git revert jkl012                │              │          │
└──────┴──────────────┴──────────────────────────────────┴──────────────┴──────────┘

  Revert 策略说明：
  - PR #123: 整个 PR 一次性 revert
    → git revert --ancestry-path abc123^..ghi789
  - [独立] jkl012: 单独 revert
    → git revert jkl012
```

---

### 第 3 部分：合入计划预览

展示完整的合入计划（merge_order 的可视化）：

```
═══════════════════════════════════════════════
  合入计划
═══════════════════════════════════════════════

┌─────┬────────┬──────────┬────────┬────────┬────────┬──────────────────────────────┐
│ Seq │ Patch  │ Subject  │ Action │ 风险   │ Review │ 备注                         │
├─────┼────────┼──────────┼────────┼────────┼────────┼──────────────────────────────┤
│  1  │ 0001   │ HDBSS    │ apply  │ 低     │ 低     │ 预判冲突: sysreg 新增条目     │
│     │        │ 寄存器   │        │        │        │                              │
├─────┼────────┼──────────┼────────┼────────┼────────┼──────────────────────────────┤
│  2  │ 0002   │ DBM 属性 │ skip   │ —      │ —      │ 原因: 目标仓库已完全实现      │
│     │        │ 支持     │        │        │        │                              │
├─────┼────────┼──────────┼────────┼────────┼────────┼──────────────────────────────┤
│  3  │ 0003   │ FEAT     │ apply  │ 中     │ 中     │ 依赖: 0001                   │
│     │        │ cpufeat  │        │        │        │ 预判冲突: cpufeature.c 注册   │
├─────┼────────┼──────────┼────────┼────────┼────────┼──────────────────────────────┤
│  4  │ 0004   │ HDBSS    │ skip   │ —      │ 高     │ 原因: 结构性冲突 10+ 维度     │
│     │        │ 核心实现 │        │        │        │                              │
├─────┼────────┼──────────┼────────┼────────┼────────┼──────────────────────────────┤
│  5  │ 0005   │ ioctl    │ apply  │ 低     │ 低     │ 依赖: 0003                   │
│     │        │ 文档     │        │        │        │                              │
└─────┴────────┴──────────┴────────┴────────┴────────┴──────────────────────────────┘

  统计: apply X | skip Y | 高/中/低风险 Z/W/V

⚠️  高关注项：
  - 0004 跳过但 review 紧急性=高，若后续发现缺失功能，需重新评估
  - 0003 cpufeature 变更需确认目标内核的 is_kernel_in_hyp_mode() 逻辑
```

---

### 第 4 部分：用户确认交互

```
═══════════════════════════════════════════════
  请确认
═══════════════════════════════════════════════

  请选择操作：

  [1] 继续执行 merge 流程
  [2] 调整合入顺序（提供新的 seq 排列）
  [3] 跳过特定 patch（提供要跳过的 task_id）
  [4] 中止，导出分析结果
  [5] 查看某个 patch 的详细分析（提供 task_id）
```

### 确认选项说明

| 选项 | 说明 |
|------|------|
| `[1] 继续` | 按上表顺序启动 Phase 2 串行 merge |
| `[2] 调整顺序` | 用户提供新的 task_id 顺序排列，重新生成 merge_order 的 seq 字段 |
| `[3] 跳过` | 将指定 patch 的 action 改为 skip，更新 skip_count 和 skip_reason |
| `[4] 中止` | 将已生成的 merge_tasks.json 和 analysis_cache.json 保存为草稿 |
| `[5] 查看详情` | 输出该 patch 的 Phase 1 分析报告摘要 |
