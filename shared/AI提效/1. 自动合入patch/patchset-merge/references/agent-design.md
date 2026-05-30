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
| 4. 深入理解 | 读取每个候选 commit 的 message + diff，AI 判断：是否确实是旧版本的功能实现？还是无关修改（格式/doc/cleanup/无关 bugfix）？如果候选中有 merge commit，展开其子 commit 列表，检查哪些子 commit 已被独立找到（覆盖判定） | 读 commit |
| 5. 清理干净 | 将确认的旧版本 commit 按时间逆序排列。**每个 commit 单独 revert**（逆序），不整体 revert merge commit（merge 无法直接 revert）。PR merge commit 的作用：提供子 commit 完整列表作为验证基线，确保无遗漏选择。 | AI 裁决 |

核心原则：
- 不靠阈值判定 —— AI 理解代码语义后做判断
- L1 脚本只提供起点线索，不做最终决策
- 排除项：无关格式化、无关 bugfix（非本特性引入的）、doc 修改
- 输出：完整的 revert_ruling 列表，每个 entry 含 confirm + 理由

**去重合并 + 完整性验证（Step 5 详细）**：

```
对每个 L1 候选 commit x：

  1. 检查 x 是否在某个 merge commit M 的子 commit 列表中
     (git log M~1..M 的输出中包含 x 的 hash)
     → 是：x 属于 PR M，记录为"已验证覆盖"
     → 否：继续下一步

  2. x 不在任何 merge 的子 commit 列表中
     → 标记为独立 commit，必须保留

  3. 对于每个 PR merge commit M：
     a. 列出 M 的所有子 commit（git log M~1..M）
     b. 对比 L1 找到的候选列表：
        → 已找到的子 commit：记录为"已验证"（PR 聚合价值：证明没漏）
        → M 中未被找到的子 commit：AI 逐条判断是否也属于旧版本实现
           → 是：纳入 revert 列表
           → 否：跳过
     c. 最终 revert 方式：对确认的子 commit 逐个 git revert（逆序），不是 revert M 本身

覆盖判定标准：
  - "commit x 被 PR M 覆盖" ⟺ x 是 M 的直接子 commit（M~1..M 中包含它）
  - PR 聚合的价值 = 验证完整性 + 发现遗漏，不是"一并 revert"
  - 每个 commit 独立 revert，按时间逆序（最新→最旧）
```

最终输出示例：
  revert 目标（全部独立 revert，按逆序排列）:
    a5e3c939fbb1 (msg: "do not support hdbss in nvhe")     ← PR!17748 子 commit
    00c93102b328 (msg: "fix memory leak in HDBSS")          ← PR!17748 子 commit
    1d334a25caf9 (msg: "use KABI_EXTEND to skip check")     ← PR!15754 子 commit
    8d2e1e3b26a9 (msg: "add config for HDBSS")              ← PR!15754 子 commit
    6d60015590c3 (msg: "handle the HDBSSF event")           ← PR!15754 子 commit
    bd6106e348d7 (msg: "ioctl to enable/disable HDBSS")     ← PR!15754 子 commit
    74a1397438e0 (msg: "set DBM attr during abort")         ← PR!15754 子 commit
    16ab2a2fee8b (msg: "add HDBSS register information")    ← PR!15754 子 commit

  验证: PR!15754 子 commit 8 个 → 全部找到 ✅  覆盖率 100%
        PR!17748 子 commit 3 个 → 全部找到 ✅  覆盖率 100%

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
