# Merge-Patchset Skill Architecture v2.1

> v2.0 → v2.1：Agent 按职责分工、revert checkpoint、Phase 0 场景问询。

## 1. 整体架构（不变）

```
                    用户输入
                       |
               +-------+--------+
               |  Phase 0: 下载   |  脚本: download_patches.py
               |  + 场景问询 ★新增 |  检测 revert 候选 → 用户选 upgrade/backport
               +-------+--------+
                       |
    +==============================================+
    |   Layer 1: 脚本层 (并行, 确定性, 不依赖 AI)     |
    |                                              |
    |  detect_duplicate.py  -- 三层下降做 revert     |
    |  topo_sort.py         -- 符号依赖图           |
    |  calculate_build_     -- 编译验证点            |
    |    checkpoints.py     -- ★含 revert checkpoint |
    +==============================================+
                       |
    +==============================================+
    |   Layer 2: 语义层 (并行, AI 只读不写文件)       |
    |                                              |
    |  ★ agent_analysis -- 全量 patch 语义分析       |
    |     (输入: /tmp/patches/* + analysis_cache.json) |
    |  ★ agent_revert   -- ★ upgrade: AI深度搜索清理  |
    |     (输入: duplicate_analysis.json + keywords)   |
    +==============================================+
                       |
    +==============================================+
    |   Layer 3: 主 Agent (串行, 唯一裁决入口)        |
    |  汇总 L1+L2 → 冲突判定 → 用户确认              |
    |  → merge_tasks.json + analysis_cache.json     |
    +==============================================+
                       |
    +==============================================+
    |   Phase 2: 串行 Merge                        |
    |  ★ revert 也走 checkpoint 编译                |
    +==============================================+
```

### 数据流依赖与实际执行顺序

架构图是逻辑分层，实际执行考虑数据依赖：

```
Phase 0: 下载 + 场景问询
    │
    ├── L1 并行组
    │   ├── detect_duplicate.py          → duplicate_analysis.json
    │   └── extract_patch_symbols.py ★新  → analysis_cache.json 骨架
    │                                        (feature_signature, introduced_symbols,
    │                                         referenced_symbols, 功能分类)
    │
    ├── L2 并行组 (依赖 L1 产物)
    │   ├── agent_analysis               → 追加 analyzed_notes, dep_hints
    │   └── agent_revert                 → 追加 revert_ruling
    │
    ├── Phase 1.5 L3 串行 (依赖 L1 + L2)
    │   ├── topo_sort.py                 → 符号依赖图 + 反向依赖
    │   ├── 主 Agent 汇总               → merge_tasks.json
    │   ├── merge_order_sort.py          → 全量排序
    │   └── calculate_build_checkpoints.py → 编译验证点
    │
    └── Phase 2: 串行 Merge
```

> ★ `extract_patch_symbols.py` 是 L1 纯确定性脚本：读 .patch 文件，用正则提取 `+` 行的函数名/宏名/结构体名/类型名，按 patch 写入 `analysis_cache.json` 骨架。不依赖 AI，不写 git。

## 2. Agent 职责定义（★核心变更）

### 2.1 对比：v2.0 vs v2.1

| 维度 | v2.0（当前） | v2.1（目标） |
|------|-------------|-------------|
| Agent 分工 | 按 patch 数量平分（N 个相同 Agent） | 按职责分工：2 个专职 Agent |
| agent_analysis 输入 | 各自分配的几个 patch | **全部** patch + analysis_cache.json |
| agent_revert | 不存在（夹在通用分析中） | **独立 Agent**，只审 L1 产物 |
| 数据来源 | Agent 自己跑 detect_duplicate | L1 脚本预跑，Agent 只读分析 |
| 并行性 | 多个 Agent 并行 | 2 个 Agent 并行（analysis + revert） |

### 2.2 agent_analysis

| 维度 | 定义 |
|------|------|
| 输入 | `/tmp/patches/000N-*.patch`（全部），`$KERNEL_REPO_PATH`，`analysis_cache.json`（L1 `extract_patch_symbols.py` 已填充 introduced_symbols / referenced_symbols / feature_signature / 功能分类） |
| 输出 | 屏幕输出结构化分析结果（`analyzed_notes` 含功能描述/模块关联/风险，`dep_hints` 含依赖线索），由主 Agent 在 Phase 1.5 汇总写入 `analysis_cache.json` |
| 规则 | 优先读 commit message 再读 diff；功能分类沿用现有规则；风险: 高(核心路径/锁/内存) / 中(驱动逻辑) / 低(doc/log) |
| 约束 | 只读，不调 git write，不写 merge_tasks |
| 启动时机 | L1 脚本全部完成后，与 agent_revert 并行 |
| 数量 | **固定 1 个**（处理全部 patch，不论数量） |

### 2.3 agent_revert（★从零新建）

| 维度 | 定义 |
|------|------|
| 输入 | `duplicate_analysis.json`（L1 脚本初筛候选），场景（upgrade/backport），`$KERNEL_REPO_PATH`，`feature_signature.keywords` + `scope_dirs`（由主 Agent 在 L1→L2 过渡时从 patch 提取后传入） |
| 输出 | 屏幕输出结构化 `revert_ruling`（confirm/reject）+ `revert_ruling_note`（理由），由主 Agent 在 Phase 1.5 汇总写入 `duplicate_analysis.json` |
| 核心职责 | **★ upgrade 模式：AI 自主深度搜索旧版本全貌，确保清理干净。backport 模式：审核 L1 候选** |
| 数量 | **固定 1 个**（与 agent_analysis 并行） |
| 启动时机 | L1 脚本全部完成后 |

**upgrade 模式——AI 深度搜索（核心流程）**：

不使用阈值匹配。agent_revert 以 L1 的候选 commit 为**起点**，自主做以下深度搜索：

| 步骤 | 操作 | 工具 |
|------|------|------|
| 1. 扩展搜索 | 用 `feature_signature.keywords` 在涉改目录 `scope_dirs` 下 `git log --grep=<kw>` 搜索**所有**相关 commit（不限阈值、不限时间范围） | `git log --grep` |
| 2. 符号追溯 | 对 patch 的 `introduced_symbols`，用 `git log -S=<sym>` 在涉改目录找所有引入该符号的 commit | `git log -S` |
| 3. 文件追溯 | 对 patch 的 `changed_files`，用 `git log -- <file>` 找出所有修改过这些文件的 commit | `git log -- <file>` |
| 4. 深入理解 | 读取每个候选 commit 的 message + diff，AI 判断：是否确实是旧版本的功能实现？还是无关修改（格式/doc/cleanup）？ | 读 commit |
| 5. 清理干净 | 将确认的旧版本 commit 按时间**逆序**排列，确保无遗漏、无多余 | AI 裁决 |

**核心原则**：
- 不靠 30%/50%/80% 阈值 —— AI 理解代码语义后做判断
- L1 脚本只提供**起点线索**（关键词 + 初筛 commit），不做最终决策
- 排除项：无关格式化、无关 bugfix（非本特性引入的）、doc 修改
- 输出结果：完整的 `revert_ruling` 列表，每个 entry 含 `confirm` + `理由`

**backport 模式——严格审核，用户定夺**：

| diff 相似度 | 判定 |
|------------|------|
| ≥90% | **暂停，展示给用户确认是否 revert**（极高相似才可能是旧版替换，但绝不自动 revert） |
| <90% | **reject**（非 upgrade 场景，不做 revert） |

> backport 模式**不启动 AI 深度搜索**。理由是：backport 就是纯新增，目标仓库没有旧版本需要"清理干净"。深度搜索只在 upgrade 模式下生效，不可跨模式混用。

## 3. Revert 检测（★职责重新划分）

### 3.1 L1 脚本：初筛线索

`detect_duplicate.py` 负责**收集线索**，不做最终裁决：

| 策略 | 说明 | 作者依赖 |
|------|------|:--:|
| 策略 1: 关键词聚合 | `git log --grep=<kw>` 搜索涉改目录，仅当前分支 | **无** |
| 策略 2: diff + 符号匹配 | `-S` pickaxe 搜索符号引入点 | **无** |
| 策略 3: revert commit 追溯 | `git log --grep="^Revert"` 解析 | **无** |

### 3.2 L2 agent_revert：AI 深度清理

| 场景 | L1 角色 | L2 agent_revert 角色 |
|------|---------|---------------------|
| upgrade | 提供关键词 + 初筛 commit（线索） | **AI 自主深度搜索**：用线索扩展 → 理解代码语义 → 裁决哪些 commit 确实需要 revert → 逆序排列，确保清理干净 |
| backport | 提供高阈值匹配结果 | **严格审核 + 用户定夺**：diff ≥90% → 暂停展示给用户确认；<90% → reject |

> ★ 深度搜索（"找到所有属于旧版本的 commit"）**仅限 upgrade 模式**。backport 模式绝不做扩展搜索——它是纯新增，不存在旧版本需要清理。

### 3.3 约束

- 搜索范围：**仅 target_branch（当前分支）**，不用 `--all`
- 作者名：**不用于过滤**，不用于分组
- upgrade 模式下**不使用阈值判定**（不用 30%/50%/80%），完全由 AI 语义理解裁决
- 目标：找到**所有**属于旧版本的 commit，一个不漏；排除**所有**无关的 commit，一个不多

## 4. Revert 的 Build Checkpoint（★新增）

### 4.1 规则

Revert 类型的 task（`action == "revert"`）也需要参与 `build_checkpoint` 判定。规则新增：

| 优先级 | 条件 | build_checkpoint | 说明 |
|--------|------|:---:|------|
| **1c** | **最后一个 revert task（revert 序列中 seq 最大）** | **`true`（强制）** | 所有 revert 完成后必定编译一次，确保回退后代码编译通过 |

### 4.2 判定顺序

```
revert 检查点判定：
  1. 统计 merge_order 中所有 action == "revert" 的 task
  2. 取其中 seq 最大者 → 强制 build_checkpoint = true
  3. 其余 revert task → 按普通规则（功能分类/风险/被依赖数）判定
  4. 注意：如果该 revert 恰好也是最后一个 patch（规则 5），优先级相同，checkpoint_reason 写 "最后一个 revert;末 patch 强制"
```

### 4.3 示例

```
Seq  Task       Action   功能分类  验证点  原因
1    dep-001    dep      core      —      依赖 patch
2    0002       revert   driver    —      普通 revert
3    0001       revert   infra     ✅     最后一个 revert（强制）
4    0003       apply    core      —      普通 patch
5    0005       apply    driver    ✅     末 patch 强制
```

### 4.4 实现位置

- `calculate_build_checkpoints.py`：增加规则优先级 1c
- `SKILL.md` Phase 1.5 步骤 8：更新计算规则表

## 5. Phase 0 场景问询（★新增）

### 5.1 流程

Phase 0 下载完成后、正式进入 Phase 1 前，增加以下步骤：

```
Phase 0 下载 → 恢复检查 → [★新增] 场景问询 → Phase 1
```

### 5.2 交互逻辑

1. 用 `detect_duplicate.py`（普通模式）先跑一遍做初筛
2. 若 **无 revert 候选** → 直接进入 Phase 1（默认 backport 模式）
3. 若 **有 revert 候选** → 展示摘要给用户，询问场景

```
═══════════════════════════════════════════════
  场景问询 — 检测到目标仓库中可能存在旧版本实现
═══════════════════════════════════════════════

检测到以下 commit 可能与要合入的 patch 相关：
  16ab2a2f arm64/sysreg: Add HDBSS related register information
  bd6106e3 KVM: arm64: Add support for FEAT_HDBSS
  74a13974 KVM: arm64: Add support to set the DBM attr...

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

### 5.3 用户选择后的行为

| 选择 | 后续 |
|------|------|
| [1] 版本升级 | 进入 Phase 1，agent_revert 在 L2 做 AI 深度搜索（不重跑 detect_duplicate） |
| [2] 纯新增 | 进入 Phase 1，agent_revert 只做严格审核（diff ≥90% → 暂停让用户确认） |

### 5.4 实现位置

- `SKILL.md` Phase 0：在"恢复检查"后插入此步骤
- 删除 `ask_scene.py`（交互逻辑在主 Agent 中实现，脚本只管数据产出）

## 6. Phase 1 Agent 并行方式变更（★核心）

### 6.1 v2.0（当前）

```bash
# 按 patch 数量平分，动态 Agent 数
Task(agent-1, patches 0001-0003)
Task(agent-2, patches 0004-0006)
```

### 6.2 v2.1（目标）

```bash
# 按职责分工，固定 2 Agent
Task(agent_analysis, all patches + analysis_cache.json)  ─┐
                                                           ├─ 并行
Task(agent_revert, duplicate_analysis.json)               ─┘
```

### 6.3 agent_analysis 执行流程

1. 接收全部 patch 文件 + `analysis_cache.json`（含 L1 预填充的 `introduced_symbols` / `referenced_symbols` / `feature_signature`）
2. 逐 patch 读 commit message → 理解功能 → 功能分类
3. 补充 `analyzed_notes`（功能描述/模块关联/风险等级/review需求）
4. 提取 `dep_hints`（commit message 中的 Depends-on/Fixes 标签）
5. 输出：追加到 analysis_cache.json

### 6.4 agent_revert 执行流程

**upgrade 模式（AI 深度搜索）**：

1. 读取 `duplicate_analysis.json` 中的 L1 初筛 commit 列表（作为搜索起点）
2. 读取 `analysis_cache.json` 中的 `feature_signature.keywords` 和 `scope_dirs`
3. **扩展搜索**：用 keywords 在 scope_dirs 下 `git log --grep=<kw>` 搜全部相关 commit
4. **符号追溯**：用 `git log -S=<sym>` 在 scope_dirs 找所有引入 key symbol 的 commit
5. **文件追溯**：用 `git log -- <file>` 找出修改过涉改文件的所有 commit
6. **深入理解**：读取每个候选 commit 的 message + diff，AI 判断：
   - 是否是旧版本的功能实现？ → confirm
   - 是否是无关注释/格式/doc/无关 bugfix？ → reject
7. **去重合并**：将 L1 初筛结果和步骤 3-5 的搜索结果合并去重
8. 输出：每个 commit 的 `revert_ruling`（confirm/reject）+ `revert_ruling_note` + 按时间逆序排列

**backport 模式（严格审核 + 用户定夺）**：

1. 读取 L1 的 `duplicate_analysis.json`
2. 对每个候选：
   - diff ≥90% → 暂停，展示 commit 给用户确认是否 revert
   - diff <90% → reject
3. **不启动扩展搜索**（纯新增场景，深度搜索仅限 upgrade 模式）

## 7. 文件变更清单

| 文件 | 动作 | 变更说明 |
|------|------|---------|
| `SKILL.md` | **修改** | Phase 0 增加场景问询；Phase 1 Agent 改为职责分工；Phase 1.5 步骤 8 增加 revert checkpoint 规则 |
| `references/agent-design.md` | **新建** | Agent 职责定义（§2 内容迁移到此文件） |
| `scripts/calculate_build_checkpoints.py` | **修改** | 增加规则 1c：最后一个 revert task 强制 checkpoint |
| `scripts/extract_patch_symbols.py` | **新建** | L1 确定性脚本：从 .patch 文件提取 introduced_symbols / referenced_symbols / feature_signature / 功能分类，输出 analysis_cache.json 骨架 |
| `scripts/detect_duplicate.py` | 不修改 | 仅用普通模式做初筛（不用 --version-upgrade），深度搜索由 agent_revert 完成 |
| `AGENTS.md` | 不修改 | §2 架构图已含三层架构 |
| `references/output-templates.md` | 不修改 | 当前格式已满足 |

## 8. 关键原则（从已有 git 历史提炼，不再单独列约束文件）

1. **仅搜目标仓库当前分支**（ea9cdb4）：`detect_duplicate.py` 不用 `--all`，`-S` 搜符号也不扩展分支
2. **不依赖作者名做过滤**：关键词聚合是唯一搜索维度，作者信息仅用于时间戳排序
3. **非 upgrade 从严**：backport 模式 revert 判定阈值 90%，拒绝自动 revert；≥90% 也需用户确认
4. **深度搜索仅限 upgrade**：找到所有旧版本 commit 的行为只在 upgrade 模式生效，backport 绝不做扩展搜索
5. **Revert 也有 checkpoint**：最后一个 revert 强制编译，防止回退后代码不编译
6. **编译 + 落盘门禁不可绕过**（8c5ac05）：validate_phase1_artifacts.py + gatekeeper.py
7. **agent 并行不可串行**（913b0a2）：L2 两个 Agent 必须一条消息同时启动
8. **原始 patch 顺序不变**（f7090e3）：topo_sort 不调整顺序，反向依赖通过 checkpoint 解决
9. **upstream 未指定自动降级**（2479d93）：不猜测路径、不询问用户
