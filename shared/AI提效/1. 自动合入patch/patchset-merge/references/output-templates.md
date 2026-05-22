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

## 9. 与源 Patch 的完整 Diff

（由 scripts/generate_diff_report.py 生成，合并原始 patch + 实际应用 diff + 差异对比）

```diff
{diff 内容}
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
  "global_revert_order": ["commit_hash_1", "commit_hash_2"],
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
      "execution_log": []
    }
  ]
}
```

### 字段说明

| 字段 | 必填 | 类型 | 说明 |
|------|:--:|------|------|
| `seq` | ✓ | int | 执行序号，merge agent 严格按此升序执行 |
| `task_id` | ✓ | string | 补零 4 位，如 `"0001"` |
| `status` | ✓ | string | `pending` / `in_progress` / `done` / `blocked` / `skipped` / `failed` |
| `patch_file` | ✓ | string | .patch 文件的绝对路径 |
| `subject` | ✓ | string | patch 标题 |
| `author` | ✓ | string | patch 作者 |
| `files_changed` | ✓ | list | 涉改文件路径列表 |
| `action` | ✓ | string | `apply`（需要合入）或 `skip`（跳过） |
| `skip_reason` | - | string/null | 若 action=skip，必须填写具体原因；否则 null |
| `pre_revert` | ✓ | list | 需先 revert 的本地 commit hash |
| `depends_on` | ✓ | list | 前置 task_id 列表 |
| `risk_level` | ✓ | string | `高` / `中` / `低` |
| `review_required` | ✓ | string | `高` / `中` / `低` |
| `blame_hits` | ✓ | list | bugfix commit 列表 |
| `duplicate_info` | ✓ | dict | `{"level": "无重复|精确重复|高概率等效|可能冲突", "detail": "..."}` |
| `conflicts_predicted` | ✓ | list | 预判冲突点 |
| `special_notes` | ✓ | string | 合入注意事项 |
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
    "status_in_target": "在目标仓库中的现状描述"
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

列出 patchset 所有依赖项（外部依赖 + 内部依赖 + bugfix 依赖）：

```
═══════════════════════════════════════════════
  依赖 Patch 汇总
═══════════════════════════════════════════════

[外部依赖] 需要从上游合入的前置 patch：

┌──────────┬──────────────────────┬──────────────────────────────┐
│ 类型     │ Commit / Message-ID  │ 原因                         │
├──────────┼──────────────────────┼──────────────────────────────┤
│ 上游依赖 │ commit-abc123        │ 缺失函数 stage2_try_set_pte  │
│ 上游依赖 │ msgid-2024xxxx       │ 依赖锁重构系列(patchset)     │
└──────────┴──────────────────────┴──────────────────────────────┘

[内部依赖] patchset 内部依赖链：

┌──────────┬──────────┬──────────────────────────────┐
│ Patch    │ 依赖     │ 原因                         │
├──────────┼──────────┼──────────────────────────────┤
│ 0003     │ 0001     │ 引用 0001 引入的 sysreg 宏   │
│ 0004     │ 0001,    │ 调用 0003 的函数 +          │
│          │ 0003     │ 依赖 0001 的寄存器定义       │
└──────────┴──────────┴──────────────────────────────┘

[Bugfix 依赖] 目标仓库已存在但需回溯的 bugfix：

┌──────────────┬──────────────────────────────┐
│ Commit       │ 修复内容                     │
├──────────────┼──────────────────────────────┤
│ def456       │ 修复 KVM stage-2 页表泄漏    │
└──────────────┴──────────────────────────────┘

📋 需额外下载的 patch：共 X 个
   b4 am <message-id-1>
   b4 am <message-id-2>
```

---

### 第 2 部分：Revert 清单（全局逆序）

列出所有需回退的本地 commit，按 commit 时间逆序排列（最新→最旧）：

```
═══════════════════════════════════════════════
  Revert 清单
═══════════════════════════════════════════════

  执行顺序（从上到下）：

┌──────┬──────────────┬──────────────────────────────────┬────────────┬──────────┐
│ 序号 │ Commit Hash  │ Subject                          │ 关联 Patch │ 紧急度   │
├──────┼──────────────┼──────────────────────────────────┼────────────┼──────────┤
│  1   │ abc123       │ HDBSS 初始实现 v2               │ 0001-0005  │ 必须     │
│  2   │ def456       │ 修复 HDBSS 内存泄漏             │ 0004       │ 建议     │
│  3   │ ghi789       │ 调整 HDBSS 寄存器偏移           │ 0001       │ 建议     │
└──────┴──────────────┴──────────────────────────────────┴────────────┴──────────┘

  Revert 原因说明：
  - abc123: 本地实现了 HDBSS 完整功能，patchset 提供标准化版本
  - def456: 本地 fix 仅作用于旧实现，新 patchset 已涵盖
  - ghi789: 寄存器偏移值与 patchset 定义冲突
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
