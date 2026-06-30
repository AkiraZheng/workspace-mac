# Patchset-Merge v2 架构设计

## 1. 概述

Patchset-Merge v2 是一个将 Linux 内核 patchset 从上游自动合入目标仓库的 AI Agent 系统。采用**分层架构 + Skill 串联**模式，通过 4 个专职 Layer 和 3 个通用 Skill 协同完成从配置解析到输出报告的全流程。

### 1.1 设计目标

| 目标 | 说明 |
|------|------|
| 自动化 | 逐个合入、逐个编译、逐个 commit，N 个 patch 产生 N 个 commit |
| 可靠性 | 层间 JSON 接口 + schema_version 校验 + gate_check 门禁 |
| 可恢复 | state.json 持久化执行状态，支持中断后从断点继续 |
| 可审核 | 每个 patch 产出 analyse.md，汇总产出 summary.md |
| 可降级 | 脚本超时/失败时 AI 手工接管，不阻塞流程 |

### 1.2 核心技术栈

- **Skill 系统**: Claude Code / OpenCode Skill 定义格式（YAML frontmatter + Markdown body）
- **Subagent**: Task tool (subagent_type: general) 独立上下文并行搜索
- **脚本层**: Python 3 确定性脚本（符号提取、编译点计算、意图校验、状态机门禁）
- **门禁链**: gate_check.sh（层间）+ gatekeeper.py（层内 7 步状态机）双重保障

---

## 2. 整体架构

### 2.1 分层架构总览

```mermaid
graph TB
    subgraph 用户
        U[用户输入: 合入 patchset 描述]
    end

    subgraph Orchestrator["patchset-merge-orchestrator 主调度"]
        O_INIT[Phase 0: 状态恢复]
        O_L1[Phase 1: 调用 L1]
        O_L2[Phase 2: 调用 L2]
        O_L3[Phase 3: 调用 L3]
        O_L4[Phase 4: 调用 L4]
        O_DONE[Phase 5: 完成]
        O_INIT --> O_L1 --> O_L2 --> O_L3 --> O_L4 --> O_DONE
    end

    U --> O_INIT

    O_L1 --> L1
    O_L2 --> L2
    O_L3 --> L3
    O_L4 --> L4

    subgraph L1["Layer 1: 交互层"]
        L1_PARSE[解析用户输入]
        L1_VALIDATE[路径校验]
        L1_CONFIG[生成 config.json]
        L1_PARSE --> L1_VALIDATE --> L1_CONFIG
    end

    subgraph L2["Layer 2: 搜索层"]
        L2_DOWNLOAD[下载 patch]
        L2_SAMPLE[抽样检测]
        L2_SCENE[场景问询 upgrade/backport]
        L2_SUBAGENT[并行 Subagent]
        L2_MERGE[生成 merge_tasks.json]
        L2_DOWNLOAD --> L2_SAMPLE --> L2_SCENE --> L2_SUBAGENT --> L2_MERGE
    end

    subgraph L3["Layer 3: 执行层"]
        L3_REVERT[Phase 1: Revert 旧版本]
        L3_DEPS[Phase 2: 拉取依赖]
        L3_MERGE[Phase 3: 循环合入 7 步状态机]
        L3_REVERT --> L3_DEPS --> L3_MERGE
    end

    subgraph L4["Layer 4: 输出层"]
        L4_ANALYSE[生成 analyse.md]
        L4_SUMMARY[生成 summary.md]
        L4_REPORT[生成 output_report.json]
        L4_ANALYSE --> L4_SUMMARY --> L4_REPORT
    end

    style Orchestrator fill:#1a1a2e,stroke:#16213e,color:#e0e0e0
    style L1 fill:#1b3a2d,stroke:#0f5c3b,color:#e0e0e0
    style L2 fill:#2d1b3a,stroke:#5c0f8b,color:#e0e0e0
    style L3 fill:#3a2d1b,stroke:#8b5c0f,color:#e0e0e0
    style L4 fill:#1b2d3a,stroke:#0f5c8b,color:#e0e0e0
```

### 2.2 层间数据流

```mermaid
flowchart LR
    subgraph 层间JSON["层间 JSON 接口（schema_version 校验）"]
        direction TB
        CFG[config.json<br/>Layer 1 → Layers 2,3,4]
        MT[merge_tasks.json<br/>Layer 2 → Layers 3,4]
        PA[patch_analysis.json<br/>Layer 2 → Layer 3]
        RC[revert_candidates.json<br/>Layer 2 → Layer 3]
        DC[deps_candidates.json<br/>Layer 2 → Layer 3]
        OR[output_report.json<br/>Layer 4 → 用户]
    end

    L1[Layer 1<br/>交互层] -->|产出| CFG
    CFG -->|消费| L2[Layer 2<br/>搜索层]
    L2 -->|产出| MT
    L2 -->|产出| PA
    L2 -->|产出| RC
    L2 -->|产出| DC
    MT -->|消费| L3[Layer 3<br/>执行层]
    PA -->|消费| L3
    RC -->|消费| L3
    DC -->|消费| L3
    MT -->|消费| L4[Layer 4<br/>输出层]
    L4 -->|产出| OR

    GATE{{gate_check.sh<br/>每层入口校验}}
    GATE -.->|schema_version 校验| CFG
    GATE -.->|schema_version 校验| MT
    GATE -.->|schema_version 校验| PA
    GATE -.->|schema_version 校验| RC
    GATE -.->|schema_version 校验| DC
```

---

## 3. Layer 详解

### 3.1 Layer 1 — 交互层

**职责**: 解析用户输入、校验路径、自动检测基线和架构、生成 config.json。

```mermaid
flowchart TD
    S1[1. 解析用户输入] --> S2[2. 路径校验<br/>内核仓库 / upstream 仓库]
    S2 --> S3[3. 基线分支检测<br/>OLK-6.6 → master → main]
    S3 --> S4[4. 创建工作分支<br/>从基线创建 patch_merge_xxx]
    S4 --> S5[5. .config 配置<br/>已有 / 指定路径 / 增量片段]
    S5 --> S6[6. 架构检测<br/>从 .config 提取 ARCH → BUILD_CMD]
    S6 --> S7[7. 用户确认<br/>展示完整配置]
    S7 --> S8[8. 生成 config.json]

    S8 -->|落盘| O1[(KERNEL_REPO/patch_analysis/config.json)]
```

**产出的 config.json 关键字段**:

| 字段 | 说明 | 示例 |
|------|------|------|
| `patch_source` | patch 来源 | `message-id: <xxx@lore.kernel.org>` |
| `kernel_repo_path` | 目标仓库路径 | `/root/code/openeuler/kernel` |
| `kernel_branch` | 操作分支 | `patch_merge_HDBSS_v3` |
| `baseline_branch` | 基线分支 | `OLK-6.6` |
| `kernel_arch` | 目标架构 | `arm64` |
| `build_cmd` | 编译命令 | `make ARCH=arm64 -j$(nproc)` |
| `output_dir` | 输出根目录 | `patchmerge/patch_merge_HDBSS_v3_output` |
| `scene` | 合入场景（Layer 2 回写） | `upgrade` / `backport` |

---

### 3.2 Layer 2 — 搜索层

**职责**: 下载 patch、检测旧版本、场景问询、并行 Subagent 搜索、AI 汇总生成 merge_tasks.json。

```mermaid
flowchart TD
    subgraph L2_流程["Layer 2 搜索层流程"]
        S1[1. 读取 config.json<br/>反向验证] --> S2[2. 下载 patch<br/>b4 / wget / local]
        S2 --> S3[3. 抽样检测<br/>detect_duplicate_sample.py]
        S3 --> S4[4. 场景问询<br/>用户选择 upgrade/backport]
        S4 -->|upgrade: 深度搜索| S5
        S4 -->|backport: 严格审核| S5
        S5[5. 符号提取<br/>extract_patch_symbols.py]
        S5 --> S6[6. 编译点计算<br/>calculate_build_checkpoints.py]
        S6 --> S7[7. AI 汇总 → merge_tasks.json]
    end

    subgraph Subagents["并行 Subagent（步骤 4）"]
        SA1[agent_target_revert<br/>目标仓库 revert 搜索<br/>→ revert_candidates.json]
        SA2[agent_patch_analysis<br/>语义分析/风险/依赖<br/>→ patch_analysis.json<br/>→ deps_candidates.json]
    end

    S4 -.->|Task tool 并行启动| Subagents

    SA1 -.-> S5
    SA2 -.-> S5
```

**Layer 2 Subagent 详解**:

```mermaid
flowchart LR
    subgraph agent_target_revert
        direction TB
        AR1[读取 keywords + files]
        AR2[4 层 git 搜索]
        AR3[关键词聚合<br/>git log --grep]
        AR4[Revert 追溯<br/>git log --grep='Revert']
        AR5[符号追溯<br/>git log -S]
        AR6[文件追溯<br/>git log --]
        AR7[AI 深入理解<br/>confirm/reject]
        AR8[去重合并]
        AR1 --> AR2
        AR2 --> AR3 & AR4 & AR5 & AR6
        AR3 & AR4 & AR5 & AR6 --> AR7 --> AR8
    end

    subgraph agent_patch_analysis
        direction TB
        AP1[读全部 .patch]
        AP2[理解功能<br/>分类/概述/review]
        AP3[对比目标仓库<br/>git grep → 冲突预判]
        AP4[符号交叉<br/>depends_on]
        AP5[upstream 搜索<br/>git blame + log -S]
        AP6[special_notes]
        AP1 --> AP2 --> AP3 --> AP4 --> AP5 --> AP6
    end
```

**产出的 merge_tasks.json 结构**:

```json
{
  "schema_version": "1.0",
  "merge_order": [
    {
      "seq": 1,
      "task_id": "0001",
      "action": "apply",
      "patch_file": "/tmp/patches/0001-xxx.patch",
      "pre_revert": ["abc123"],
      "depends_on": [],
      "build_checkpoint": true,
      "checkpoint_reason": {"rules_triggered": ["Rule_1"], "primary_reason": "infra patch"}
    }
  ],
  "deps_order": [],
  "current_state": null
}
```

---

### 3.3 Layer 3 — 执行层

**职责**: 串行 merge、编译验证、commit、review。最复杂的层，包含三阶段执行和 7 步状态机。

```mermaid
flowchart TD
    subgraph L3_Phase["Layer 3 三阶段执行"]
        PH1[Phase 1: Revert 旧版本<br/>逆序逐个 git revert<br/>编译验证]
        PH2[Phase 2: 拉取上游依赖<br/>逐个 fetch + am]
        PH3[Phase 3: 合入新 patch<br/>7 步状态机循环]
        PH1 --> PH2 --> PH3
    end

    subgraph StateMachine["7 步状态机（每个 task）"]
        SM1[5.1 PRECHECK<br/>文件存在 + 工作区干净]
        SM2[5.2 PRE_REVERT<br/>Phase 1 已完成，skip]
        SM3[5.3 APPLY<br/>git am --3way --reject<br/>→ .rej 循环处理]
        SM4[5.4 VERIFY_INTENT<br/>+ 行完整性 + symbol 存在性]
        SM5[5.5 BUILD<br/>完整仓库编译 + 产物校验]
        SM6[5.6 BUILD_FIX<br/>rebase amend 修复<br/>最多 10 轮]
        SM7[5.7 COMMIT<br/>git commit]
        SM8[5.8 REVIEW<br/>Task tool: linux-kernel-review]
        SM9[5.9 RECORD<br/>gatekeeper 完成标记]

        SM1 --> SM2 --> SM3 --> SM4
        SM4 -->|build_checkpoint=true| SM5
        SM4 -->|build_checkpoint=false| SM7
        SM5 -->|pass| SM7
        SM5 -->|fail| SM6
        SM6 -->|fix| SM5
        SM6 -->|10 轮失败| PAUSE1[/暂停等用户决策/]
        SM7 --> SM8 --> SM9
    end

    PH3 --> SM1
```

**7 步状态机前置依赖链**:

```mermaid
flowchart LR
    APPLY -->|强制| VERIFY_INTENT
    VERIFY_INTENT -->|build_checkpoint=true| BUILD
    BUILD -->|强制| COMMIT
    COMMIT -->|强制| REVIEW
    REVIEW -->|强制| RECORD

    gatekeeper{"gatekeeper.py --check"}
    gatekeeper -.->|COMMIT 前校验| VERIFY_INTENT
    gatekeeper -.->|COMMIT 前校验| BUILD
    gatekeeper -.->|RECORD 前校验| REVIEW
```

**步骤 5.3 APPLY 冲突解决流程**:

```mermaid
flowchart TD
    A1[git am --3way patch] -->|成功| V1[→ VERIFY_INTENT]
    A1 -->|冲突| A2[git am --abort]
    A2 --> A3[git am --reject patch<br/>生成 .rej 文件]
    A3 --> A4[循环处理 .rej 文件]
    A4 --> A5{Ours/Theirs 决策}
    A5 -->|patch 新增行 → Theirs| A6[采用 patch 内容]
    A5 -->|目标仓库上下文 → Ours| A7[保留目标仓库代码]
    A5 -->|无法判定| A8[/暂停等用户/]
    A6 & A7 --> A9[手动编辑冲突区域]
    A9 --> A10[git add → git am --continue]
    A10 --> V1
    A4 -->|10 轮未解决| A8
```

---

### 3.4 Layer 4 — 输出层

**职责**: 生成所有 analyse.md 和 summary.md，验证输出完整性，产出 output_report.json。

```mermaid
flowchart TD
    S1[1. 门禁验证<br/>gate_check.sh layer4] --> S2[2. 读取执行记录<br/>merge_tasks.json + execution_log.json]
    S2 --> S3[3a. 生成 .diff 参考文件<br/>generate_diff_report.py --output]
    S3 --> S4[3b. AI 逐 patch 手写 analyse.md<br/>11 节固定结构]
    S4 --> S5[4. 导出合入的 patch<br/>git format-patch baseline..HEAD]
    S5 --> S6[5. 生成 summary.md<br/>汇总报告]
    S6 --> S7[6. 完整性验证<br/>必需文件 + 数量校验]
    S7 --> S8[7. 生成 output_report.json]
```

**analyse.md 11 节结构**:

| 节 | 内容 | 生成方式 |
|----|------|----------|
| 1 | 基本信息（patch 编号/标题/作者/涉改文件） | AI 从 JSON 提取 |
| 2 | 功能描述与关联模块 | AI 语义分析 |
| 3 | 依赖分析（高版本/bugfix/内部/重复） | AI 从 Subagent 结果汇总 |
| 4 | Revert 需求评估 | AI 从 revert_candidates 提取 |
| 5 | 风险程度 | AI 从 patch_analysis 提取 |
| 6 | 人工 Review 需求度 | AI 判断 |
| 7 | 建议验证冒烟内容 | AI 建议 |
| 8 | 合入实际经验（冲突/编译修复/重试） | AI 从 execution_log 汇总 |
| 9 | 与源 Patch 的差异对比（逐行对比表） | AI 参考 .diff 文件生成 |
| 10 | 编译验证记录（错误数/产物/重试） | AI 从 gatekeeper 记录提取 |
| 11 | Review 建议与改进方向 | AI 深度分析 |

---

## 4. 通用 Skill 模块

### 4.1 conflict-resolver — Git 冲突自动解决

```mermaid
flowchart TD
    C1[接收: patch_file + repo_path] --> C2[git am --3way]
    C2 -->|成功| C7[完成]
    C2 -->|冲突| C3[git am --abort<br/>降级 → git am --reject]
    C3 --> C4{遍历 .rej 文件}
    C4 -->|每处冲突| C5{Ours/Theirs 决策表}
    C5 -->|patch 新增行| C6A[采用 Theirs<br/>patch 代码]
    C5 -->|目标仓库上下文| C6B[采用 Ours<br/>保留目标仓库]
    C5 -->|全部冲突| C6C[采用 Theirs<br/>整段替换]
    C5 -->|无法判定| C6D[/暂停用户决策/]
    C6A & C6B & C6C --> C8[手动编辑 → git add]
    C8 --> C9[git am --continue]
    C9 --> C4
    C4 -->|无更多 .rej| C7
```

**10 场景决策表（节选）**:

| 场景 | 冲突内容 | 决策 | 理由 |
|------|---------|------|------|
| 1 | patch 在文件末尾新增行 | Theirs | 无上下文冲突 |
| 2 | patch 修改函数内部，目标相同函数有不同代码 | Theirs | patch 引入新功能 |
| 3 | patch 删行，目标该行有本地修改 | Ours | 保护目标仓库适配 |
| 4 | patch + 目标均新增了不同函数在同位置 | Both | 保留两者，手工调整 |
| 5 | patch 改 Makefile/Kconfig | 暂停 | 编译控制文件需人工审核 |

### 4.2 linux-kernel-review — 内核 Patch 专项 Review

```mermaid
flowchart TD
    R1[Subagent 启动<br/>Task tool: general] --> R2[读取 git show commit]
    R2 --> R3[4 类检查并行]

    R3 --> R3A[1. Commit message 完整性<br/>Subject/S-O-B/Fixes/tags]
    R3 --> R3B[2. 代码安全性<br/>内存配对/锁/RCU/错误处理]
    R3 --> R3C[3. API 兼容性<br/>函数存在/签名/CONFIG/结构体]
    R3 --> R3D[4. Patch 意图保留<br/>+ 行完整性/symbol 存在性]

    R3A & R3B & R3C & R3D --> R4[分级: P0/P1/P2/P3]

    R4 --> R5{P0 > 0?}
    R5 -->|是| R6[blocking: true<br/>暂停等用户决策]
    R5 -->|否| R7[blocking: false<br/>继续流程]

    R6 & R7 --> R8[Write review_xxxx.md]
```

**Review 严重度分级**:

| 级别 | 含义 | 示例 | 操作 |
|------|------|------|------|
| P0 | 内存泄漏/死锁/符号缺失/API 不兼容 | kmalloc 无 kfree | 必须修复 |
| P1 | 逻辑错误/锁问题/+ 行丢失 | 错误路径释放不完整 | 建议修复 |
| P2 | message 不完整/API 签名差异 | 缺少 Fixes tag | 信息记录 |
| P3 | 风格/格式/次要建议 | 缩进不一致 | 可选改进 |

### 4.3 agent_patch_analysis — 语义分析 Subagent

独立 Subagent（Task tool: general），在 Layer 2 步骤 4 并行启动。读取全部 .patch 文件，深度理解后产出 `patch_analysis.json`。

**6 步流程**:

| 步骤 | 操作 | 产出字段 |
|------|------|----------|
| 1 | 读 commit msg + diff → 理解功能 | `功能分类`, `功能概述`, `review_required` |
| 2 | git grep 目标仓库 → 预判冲突 | `conflicts_predicted`, `risk_level` |
| 3 | 符号交叉分析 → 内部依赖 | `depends_on` |
| 4 | upstream git blame/log -S → deps | `blame_hits`, `deps_candidates.json` |
| 5 | 提炼注意事项 | `special_notes` |
| 6 | 决定 AM 策略 | `execution_guide.am_mode`（reject/3way） |

Layer 3 在 git am 前读取 `patch_analysis.json`，根据 `risk_level` 和 `conflicts_predicted` 调整 AM 模式。

---

## 5. 脚本层

### 5.1 shared-scripts（7 个）

| 脚本 | 行数 | 职责 | 调用时机 |
|------|------|------|----------|
| `gatekeeper.py` | 357 | 7 步状态机门禁：记录/检查/恢复 | Layer 3 每步调用 |
| `verify_patch_intent.py` | 272 | APPLY 后意图校验（+ 行 + symbol） | Layer 3 步骤 5.4 |
| `extract_patch_symbols.py` | 214 | 从 .patch 提取符号和分类 | Layer 2 步骤 7 |
| `calculate_build_checkpoints.py` | 304 | 7 条规则计算编译检查点 | Layer 2 步骤 8 |
| `generate_analyse_md.py` | 423 | 确定性生成 analyse.md（保留，当前不调用） | — |
| `generate_diff_report.py` | 503 | 源 patch vs 实际 commit 偏离对比 | Layer 2 步骤 3, Layer 4 步骤 3a |
| `generate_summary_md.py` | 223 | 从 analyse.md 汇总 summary.md | Layer 4 步骤 5 |

### 5.2 orchestrator/scripts（5 个）

| 脚本 | 行数 | 职责 | 调用时机 |
|------|------|------|----------|
| `gate_check.sh` | 223 | 层间 JSON 存在性/有效性/schema_version 校验 | 每层入口 |
| `validate_json.py` | 45 | JSON 必填字段校验 | gate_check 内部 |
| `download_patches.py` | 389 | 统一下载（b4/wget/local）| Layer 2 步骤 2 |
| `detect_duplicate.py` | 1123 | 旧版本完整检测（PR 聚合+diff 相似度）| 保留不调用 |
| `detect_duplicate_sample.py` | 150 | 快速抽样检测（<1s）| Layer 2 步骤 3 |

---

## 6. 门禁体系

### 6.1 双层门禁

```
┌─────────────────────────────────────────────────────┐
│                    门禁体系                          │
├─────────────────────┬───────────────────────────────┤
│   gate_check.sh     │       gatekeeper.py           │
│   层间门禁           │       层内状态机门禁           │
├─────────────────────┼───────────────────────────────┤
│ 校验内容:            │ 校验内容:                      │
│ - JSON 存在性/非空   │ - 前置步骤是否 pass            │
│ - JSON 可解析性      │ - build_checkpoint 编译要求    │
│ - schema_version     │ - VERIFY_INTENT 前置 COMMIT   │
│ - 必填字段完整性     │ - REVIEW 前置 RECORD           │
│ - 路径一致性         │ - 恢复模式（--restore）        │
├─────────────────────┼───────────────────────────────┤
│ 执行: 每层入口前     │ 执行: 每步状态转换时            │
│ 粒度: Layer 级       │ 粒度: Task 级（7 步状态机）     │
│ 退出码: 10-30       │ 退出码: 0-10                   │
└─────────────────────┴───────────────────────────────┘
```

### 6.2 schema_version 版本控制

所有层间 JSON 文件必须包含 `schema_version` 字段（当前 `"1.0"`）。gate_check.sh 在每层入口校验前置文件的版本是否匹配，不匹配则拒绝进入。

接口变更必须执行 **7 步传播规则**:
1. 更新 `schema_version` 版本号（+0.1）
2. 更新消费层 SKILL.md 中的读取逻辑
3. 更新 `gate_check.sh` 期望值
4. 更新 `references/` 下的 schema 文档
5. 更新 Python 脚本适应新字段
6. 更新 `docs/field_reference.md` 生产者/消费者关系
7. 运行集成测试验证

---

## 7. 文件与目录结构

```
patchset-merge-v2/
├── AGENTS.md                             # 开发规范与硬性约束
├── README.md                             # 项目说明
├── install.sh / uninstall.sh             # 安装/卸载脚本
│
├── patchset-merge-orchestrator/          # 主调度 Skill
│   ├── SKILL.md                          # 5 Phase 调度流程 + 恢复机制
│   ├── scripts/                          # 5 个脚本（门禁/下载/检测）
│   └── references/                       # 5 个参考文档
│
├── layer1-interaction/                   # Layer 1: 用户交互
│   ├── SKILL.md                          # 8 步交互流程
│   └── references/                       # 2 个参考文档
│
├── layer2-search/                        # Layer 2: 搜索
│   ├── SKILL.md                          # 10 步搜索流程 + 并行 Subagent
│   ├── agents/
│   │   └── agent_patch_analysis_SKILL.md # 语义分析 Subagent
│   └── references/                       # 8 个 schema 文档
│
├── layer3-execution/                     # Layer 3: 执行
│   ├── SKILL.md                          # 6 步执行流程 + 7 步状态机
│   └── references/                       # 3 个参考文档
│
├── layer4-output/                        # Layer 4: 输出
│   ├── SKILL.md                          # 7 步输出流程
│   └── references/                       # 3 个参考文档
│
├── conflict-resolver/                    # 独立模块: 冲突解决
│   ├── SKILL.md                          # git am 冲突自动解决
│   └── references/
│       └── decision_table.md             # 10 场景 Ours/Theirs 决策表
│
├── linux-kernel-review/                  # 独立模块: 内核 Review
│   └── SKILL.md                          # 4 类 19 项检查清单
│
├── shared-scripts/                       # 7 个复用 Python 脚本
│
├── docs/                                 # 设计文档
│   ├── architecture.md                   # 本文档
│   ├── field_reference.md                # 字段生产者/消费者关系
│   └── superpowers/                      # 规范与计划
│
└── tests/                                # 集成测试
    └── test_integration.sh
```

---

## 8. 关键设计决策

| 决策 | 说明 |
|------|------|
| **Subagent 用 Task tool: general** | Cannbot/opencode 只支持 `explore` 和 `general` 两种类型，搜索/分析 Agent 用 `general` |
| **review 用独立 Subagent** | 隔离上下文，避免主 AI 既做 merge 又 review 自己（无 fresh eyes） |
| **analyse.md 由 AI 手写** | 脚本生成的 markdown 太刻板，AI 从模板生成质量更高 |
| **编译前 rm -f Image** | 防止 make timestamp 优化跳过实际编译（虚假通过） |
| **多产物动态校验** | 解析 BUILD_CMD 目标 → Image 始终检查 + modules 按 MODPOST 判定 |
| **config.json 双写** | 保留 `patch_analysis/` 作为固定入口，同时归档到 `$OUTPUT_DIR/` |
| **输出目录隔离** | `patchmerge/<分支名>_output/`，不同分支互不干扰 |
