# Patchset Merge Skill — 技术分享报告

> 撰写日期：2026-05-22

---

## 1. 背景与动机

Linux 内核开发中，patchset 跨分支合入是高频操作。openEuler 等下游发行版需要持续从上游（linux-stable、Linaro、各 SIG 组）合入补丁，面临三个核心痛点：

| 痛点 | 传统方式 | 实际代价 |
|------|---------|---------|
| **路径差异** | 手动 find + sed 替换 patch 路径 | 每个 patchset 5-15 分钟 |
| **旧版本冲突** | 人工判断是否需要 revert，逐 commit 操作 | 容易漏掉依赖，导致编译失败 |
| **依赖缺失** | 编译失败 → 查日志 → git log 搜上游 → 手动挑 commit | 单次排查 20-60 分钟 |

merge-patchset skill 的目标是：**让 AI 自动完成检测、判定、执行的全流程，人只需要在关键决策点确认。**

---

## 2. 整体架构

### 2.1 四相工作流

```plantuml
@startuml
skinparam backgroundColor #FEFEFE
skinparam defaultFontSize 12

title Patchset Merge Skill — 四相工作流架构

|#LightBlue| 用户输入 |
start
:用户描述合入需求;
note right
  例: "把 HDBSS_v3 的 patch
  合入到 openEuler kernel"
end note

|#LightYellow| 路径智能推断 |
:提取/搜索 patch_dir;
:提取/搜索 source_dir;
:提取/搜索 upstream_dir (可选);

if (路径完整或搜索成功?) then (是)
  :直接使用，告知用户;
else (否)
  :询问用户缺失参数;
  note right: 唯一可能打断用户的地方
endif

|#LightGreen| LSP 环境准备 |
:检查 clangd 安装;
:生成 compile_commands.json;
:验证 LSP 可用性;
note right
  为后续 Agent 提供
  符号级代码导航
end note

|#LightCyan| 相位 0 — 并行 Agent 检测 |
fork
  :**Agent A: 冲突预检**
  扫描每个 patch 在目标仓库的冲突风险
  → none / low / high;
fork again
  :**Agent B: 依赖检测**
  在上游仓库查找缺失的依赖 commit
  → 强依赖 / 弱依赖;
fork again
  :**Agent C: 相似度检测**
  对 high 风险 patch 定位需要 revert 的 commit
  → ✅可revert / ⚠链式 / 🔴不可;
end fork
note right: 三个 Agent 并行运行，只读不写

|#LightSalmon| 相位 1 — 场景判定 |
:汇总 Agent 结果;
:判定场景 (A/B/C/E/组合);

if (场景 A 或 E唯一映射?) then (是)
  :🚀 自动继续;
  note right: 不打断用户
else (否)
  :⚠ 展示执行计划;
  :等待用户确认;
endif

|#Wheat| 相位 2 — 前置操作 |
switch (场景)
  case (B)
    :逆序 git revert 旧 commit;
  case (C)
    :从上游拉取强依赖 patch;
    :创建 stub 处理弱依赖;
  case (E)
    :find 搜索实际路径;
    :sed 替换 patch 路径;
endswitch

|#Thistle| 相位 3 — 核心 Merge |
:创建分支;
:逐个 patch 合入 (8步策略链);
:fix-compile loop;
:生成 per-patch 分析文档;
:生成 .patchset-summary.md;

stop
@enduml
```

<img src=2026-05-22-12-18-46.png>

<img src=2026-05-22-12-24-20.png>



### 2.2 8 步策略链条（Phase 3 核心）

```plantuml
@startuml
skinparam backgroundColor #FEFEFE
skinparam defaultFontSize 11

title 8 步策略链 — 逐级降级保证合入成功率

|From|
start
:patch 文件;

repeat
  :① git am;
  note right: 首选：保留完整 commit 元信息
  if (成功?) then (✓)
    :自动 commit;
    :编译验证;
    stop
  endif

  :② git am --3way;
  note right: 三路合并，处理上下文偏移
  if (成功?) then (✓)
    :自动 commit;
    :编译验证;
    stop
  endif

  :③ git am --ignore-whitespace;
  note right: 忽略空白差异
  if (成功?) then (✓)
    :自动 commit;
    :编译验证;
    stop
  endif

  :④ patch --fuzz=3;
  note right: 模糊匹配上下文
  if (成功?) then (✓)
    :手动 commit;
    :编译验证;
    stop
  endif

  :⑤ git apply --3way;
  note right: 三路合并不依赖 mail 格式
  if (成功?) then (✓)
    :手动 commit;
    :编译验证;
    stop
  endif

  :⑥ git apply --reject;
  note right: 部分应用，生成 .rej 文件
  if (成功?) then (✓)
    :检查 .rej 内容;
    :处理有效 hunk;
    :手动 commit;
    :编译验证;
    stop
  endif

  :⑦ 手动解冲突;
  note right: 分析冲突标记 → 诊断 → 解决
  if (成功?) then (✓)
    :手动 commit;
    :编译验证;
    stop
  endif

  :⑧ git apply (最后手段);
  note right: 放弃元信息，纯文件级合入
  if (成功?) then (✓)
    :手动 commit;
    :编译验证;
    stop
  else (✗)
    :记录失败;
    :报告用户决策;
    stop
  endif

repeat while (仍有策略可尝试?)

stop
@enduml
```

<img src=2026-05-22-12-19-11.png>

### 2.3 组件交互图

```plantuml
@startuml
skinparam backgroundColor #FEFEFE
skinparam componentStyle rectangle

title 系统组件交互图

package "SKILL.md (指令层)" #LightBlue {
  component "路径智能推断" as PathInfer
  component "四相工作流" as Workflow
  component "8步策略链" as Strategy
  component "fix-compile loop" as FixCompile
  component "交互模式规则" as Interaction
  component "反模式检查" as AntiPattern
}

package "References (知识层)" #LightYellow {
  component "output-templates.md\n输出模板" as Templates
  component "diagnostic-guide.md\n诊断指南" as DiagGuide
}

package "Agent 执行层" #LightGreen {
  component "Agent A\n冲突预检" as AgentA
  component "Agent B\n依赖检测" as AgentB
  component "Agent C\n相似度检测" as AgentC
  component "Grader Agent\n结果评估" as Grader
}

package "工具层" #Wheat {
  component "Bash\ngit/make/find" as Bash
  component "LSP\nclangd" as LSP
  component "Write\n文档生成" as Write
  component "Edit\n源码修改" as Edit
}

package "外部系统" #Thistle {
  database "源仓库\n(patch 来源)" as UpstreamRepo
  database "目标仓库\n(kernel 源码)" as TargetRepo
  database "上游仓库\n(linux-stable)" as Upstream
  folder "patch 文件夹" as PatchDir
}

Workflow --> Templates : Read
Workflow --> DiagGuide : Read
Workflow --> AgentA : spawn
Workflow --> AgentB : spawn
Workflow --> AgentC : spawn
AgentA --> Bash : use
AgentA --> LSP : use
AgentB --> Bash : use
AgentC --> Bash : use
AgentC --> LSP : use
Strategy --> Bash : use
Strategy --> Edit : use
FixCompile --> Bash : use
FixCompile --> Edit : use
Interaction --> Workflow : control
AntiPattern --> Workflow : guard

Bash --> TargetRepo : operate
Bash --> PatchDir : read
AgentB --> Upstream : search
@enduml
```

<img src=2026-05-22-12-19-45.png>

---

## 3. 内核多分支适配方案

### 3.1 当前适配能力矩阵

合入 patch 到不同内核分支时面临四类差异，skill 的应对如下：

| 差异类型 | 具体表现 | Skill 应对机制 | 对应场景 | 成熟度 |
|---------|---------|---------------|---------|--------|
| **路径差异** | 同一驱动在不同分支路径不同（如 `drivers/net/` vs `drivers/net/ethernet/vendor/`） | `find` 搜索文件名 → `sed` 替换 patch 路径 → 展示映射 | E — 路径适配 | ✅ 成熟 |
| **代码版本差异** | 目标分支已有旧版本实现（如 SIG 组提前回合的初版驱动） | Agent C 相似度检测 → git blame 追溯 → 安全评估 → 逆序 revert | B — 先 Revert | ✅ 成熟 |
| **依赖缺失** | 目标分支缺少 patch 依赖的前置 commit（新宏、新函数、新类型） | Agent B 在上游搜索 → 强/弱分级 → 拉取或 stub | C — 补依赖 | ⚠ 需上游路径 |
| **配置差异** | 不同分支的 Kconfig / defconfig 不同 | fix-compile loop 中临时修改 → commit 后还原 | Phase 3 内置 | ✅ 成熟 |
| **API 变更** | 目标分支的内核 API 版本不同（如 `kmalloc` 参数变化） | 8 步策略链中的 ②③ 自动适应；⑦ 手动解决 | Phase 3 内置 | ✅ 成熟 |
| **并发合入** | 多个 patchset 同时在相近代码区域合入 | 工作区不干净检测 → 警告用户 | Phase 3.1 | ⚠ 需人工协调 |

### 3.2 多分支场景示例

```
场景：将 HDBSS_v3 驱动 patchset 合入 3 个不同分支

分支 A (linux-stable 5.10):
  ├── 路径: drivers/net/ethernet/hisilicon/hdbss/  (新驱动，路径不存在)
  ├── 前置代码: 无
  ├── 判定: 场景 A + E (路径适配 + 干净合入)
  └── 结果: 🚀 自动完成

分支 B (openEuler 5.10):
  ├── 路径: drivers/net/ethernet/hisilicon/hdbss/  (已有旧版)
  ├── 前置代码: v1 版本驱动 (commit abc123)
  ├── 判定: 场景 B + E (revert 旧版 + 路径适配)
  └── 结果: ⚠ 确认 revert 后自动完成

分支 C (openEuler 6.6):
  ├── 路径: drivers/net/ethernet/hisilicon/hdbss/  (已有 v2)
  ├── 前置代码: v2 版本 + 依赖 commit def456 (来自上游)
  ├── 判定: 场景 B + C (revert + 补依赖)
  └── 结果: ⚠ 确认 revert + 依赖拉取后自动完成
```

---

## 4. 方案对比

### 4.1 四种合入方案对比

```plantuml
@startuml
skinparam backgroundColor #FEFEFE
skinparam defaultFontSize 11

title 四种 patchset 合入方案对比

rectangle "方案1\n手动合入" as M1 #LightPink {
  card "人逐个读 patch" as m1a
  card "手动 find + sed" as m1b
  card "手动 git am" as m1c
  card "编译失败 → 人修复" as m1d
  card "无文档记录" as m1e
}

rectangle "方案2\n脚本合入" as M2 #LightYellow {
  card "Shell 脚本" as m2a
  card "固定路径映射表" as m2b
  card "git am 批量" as m2c
  card "编译失败 → 人工介入" as m2d
  card "生成简单日志" as m2e
}

rectangle "方案3\nAI Skill 合入\n(当前方案)" as M3 #LightGreen {
  card "AI 理解自然语言意图" as m3a
  card "自动搜索路径/检测冲突" as m3b
  card "8步策略链逐级降级" as m3c
  card "fix-compile loop 自动修复" as m3d
  card "per-patch 分析 + 汇总报告" as m3e
}

rectangle "方案4\nCI/CD Pipeline" as M4 #LightBlue {
  card "Webhook 触发" as m4a
  card "容器化编译验证" as m4b
  card "规则引擎匹配" as m4c
  card "失败 → 人工提单" as m4d
  card "自动化报告" as m4e
}

@enduml
```

<img src=2026-05-22-12-20-23.png>

### 4.2 六维度量化对比

| 维度 | 方案1: 手动合入 | 方案2: Shell 脚本 | **方案3: AI Skill** | 方案4: CI/CD |
|------|:---:|:---:|:---:|:---:|
| **单 patchset 耗时** | 30-120 分钟 | 10-30 分钟 | **3-15 分钟** | 5-20 分钟(不含排队) |
| **冲突处理能力** | 依赖个人经验 | 规则固定，不灵活 | **LSP 增强 + 8 策略链** | 规则引擎，需预定义 |
| **依赖发现** | 编译失败后人工排查 | 不支持 | **Agent B 自动搜索+分级** | 不支持 |
| **路径适配** | 手动 find + sed | 硬编码映射表 | **自动 find + 智能映射** | 需预配置 |
| **可追溯性** | 依赖个人记录 | 简单日志 | **逐行 diff 分析文档** | 自动化报告 |
| **学习成本** | 高（需 git 深度知识） | 中（需脚本维护能力） | **低（自然语言交互）** | 高（需 CI/CD 平台能力） |
| **异常处理** | 人灵活决策 | 脚本中断，人工介入 | **AI 自主分析→修复→重试** | Pipeline 失败，人工处理 |
| **批量并行** | 不可并行 | 不可并行 | 3 Agent 并行检测 | 可并行 |
| **维护成本** | — | 映射表持续维护 | **修改指令即可** | Pipeline 配置维护 |

### 4.3 关键差异分析

```
方案选择决策树:

需要处理多种内核分支? 
├── 否 → 方案2 (脚本) 或 方案4 (CI/CD)
└── 是 → 分支间差异类型多吗?
    ├── 仅路径差异 → 方案2 (维护映射表)
    └── 路径 + 代码版本 + 依赖差异 → 方案3 (AI Skill)

合入频率?
├── 每天 ≥ 5 个 → 方案3 或 方案4
├── 每周 1-5 个 → 方案3 (推荐)
└── 偶尔 → 方案1 或 方案3

对可追溯性要求?
├── 需要审计 → 方案3 (per-patch 分析文档)
└── 不需要 → 方案2 或 方案4
```

### 4.4 AI Skill 方案的核心优势

1. **意图理解而非命令执行**：用户说"把 HDBSS_v3 合入 kernel"，AI 自动推理 patch_dir 和 source_dir
2. **检测前置而非事后修复**：Agent A/B/C 并行检测，提前知道冲突、依赖、revert 需求
3. **策略自适应降级**：`git am` → `git am --3way` → ... → `git apply`，8 级逐步降级
4. **自主修复循环**：编译失败 → 分析错误 → 修复源码 → 重编译，不中断流程
5. **完整的审计追踪**：每个 patch 的逐行 diff 对比、冲突解决思考过程、编译修复记录

---

## 5. 修改演进记录

### 5.1 版本演进时间线

```plantuml
@startuml
skinparam backgroundColor #FEFEFE

title merge-patchset Skill 演进时间线

concise "Skill 演进" as Skill

@2026-05-10
Skill is "v0: 初始版本"

@2026-05-11
Skill is "v1: 跨平台"
note right
  + compatibility 字段
  + 平台感知 preamble
  + install.sh 多平台部署
end note

@2026-05-22
Skill is "v2: 自主决策"
note right
  + 路径智能推断
  + Phase 1 分级确认
  + 交互反模式强化
end note
@enduml
```

### 5.2 关键修改记录

| 日期 | 版本 | 修改内容 | 解决的问题 |
|------|------|---------|-----------|
| 2026-05-10 | v0 | 初始 SKILL.md，含四相工作流、8步策略链、fix-compile loop | 建立基础框架 |
| 2026-05-11 | v1 | 添加 `compatibility: claude-code, opencode`；重写 preamble 为平台感知版本；install.sh 支持多平台部署 + Tier 2 降级版本生成 | Claude Code / OpenCode 双平台支持 |
| 2026-05-11 | v1 | 同步更新 revert-patchset SKILL.md；重写 README 多平台文档 | 保持一致 |
| 2026-05-22 | v2 | **新增「路径智能推断」章节**：4 级优先级（提取→搜索→推断→询问），含 `find` 搜索模板 | OpenCode 频繁询问路径问题 |
| 2026-05-22 | v2 | **Phase 1 分级确认**：场景 A → 自动继续；场景 E（唯一映射）→ 自动继续；B/C/组合 → 确认 | 干净合入无需等待 |
| 2026-05-22 | v2 | **交互模式重写**：核心原则 + 分级确认表 + 6 条反模式自检清单 | 减少不必要的用户打断 |
| 2026-05-22 | v2 | **反模式扩充**：禁止搜到结果还确认、禁止干净合入停下来、禁止重复询问 | 行为约束 |
| 2026-05-22 | v2 | 同步更新 `references/output-templates.md` 的 Phase 1 模板和输出规则 | 模板与规则一致 |

### 5.3 v2 修改的核心设计理念

```
问题: OpenCode 每次都要停下来问路径

根因分析:
┌─────────────────────────────────────────────────────────┐
│ 1. 路径不完整时没有告诉 AI "可以自己去搜"                  │
│ 2. Phase 1 一刀切要求确认，不区分场景                      │
│ 3. 反模式只说"不要重复问"，没说"能搜就不要问"               │
│ 4. OpenCode 原生行为偏保守，缺少 karpathy-guidelines 指导   │
└─────────────────────────────────────────────────────────┘

解决策略:
┌─────────────────────────────────────────────────────────┐
│ 1. 路径智能推断: 给 AI 具体的 find 命令模板               │
│ 2. 分级确认: 可逆操作自动继续，不可逆才确认                 │
│ 3. 强化反模式: "搜到唯一结果直接用"变成硬规则               │
│ 4. 把决策权交给 AI: description 里写 "NEVER ask"          │
└─────────────────────────────────────────────────────────┘
```

---

## 6. 当前状态总结

### 6.1 能力地图

| 能力 | 状态 | 说明 |
|------|:----:|------|
| 路径自动推断 | ✅ | 支持关键词搜索、上下文推断、常见路径搜索 |
| 冲突预检 (Agent A) | ✅ | LSP 优先，grep 回退，三级风险评估 |
| 依赖检测 (Agent B) | ✅ | 强/弱分级，需指定 upstream |
| 相似度检测 (Agent C) | ✅ | 三级 revert 判定，含依赖链分析 |
| 路径适配 (场景 E) | ✅ | 自动 find + sed，唯一映射自动继续 |
| Revert 合入 (场景 B) | ✅ | 逆序 revert + 安全评估 |
| 依赖补全 (场景 C) | ✅ | 强依赖拉取 + 弱依赖 stub |
| 8步策略链 | ✅ | git am → ... → git apply 逐级降级 |
| fix-compile loop | ✅ | 分析→修复→重编译，环境问题自动还原 |
| per-patch 分析文档 | ✅ | 逐行 diff 对比 + 冲突解决思考过程 |
| 汇总报告 | ✅ | 风险评级 + 热力图 |
| Claude Code 支持 | ✅ | 原生支持 |
| OpenCode 支持 | ✅ | 原生支持 |
| 其他平台降级 | ✅ | Gemini CLI / Copilot / Cursor / 通用 |
| **干净合入自动继续** | ✅ | v2 新增 |
| **只问必要问题** | ✅ | v2 新增 |

### 6.2 已知局限与后续方向

| 局限 | 影响 | 后续方向 |
|------|------|---------|
| 编译验证仅支持 Makefile/CMakefile/build.sh | 特殊构建系统需手动编译 | 支持用户自定义编译命令 |
| 上游仓库需手动指定路径 | 依赖检测需额外输入 | 利用 git remote 自动推断 |
| LSP 仅支持 clangd | 非 C/C++ 项目无符号导航 | 扩展其他 LSP 支持 |
| 不支持 patch 冲突的自动合并 | 冲突时靠 8 策略链降级 | 探索 AI 辅助三路合并 |

### 6.3 待完成事项（TODO）

#### TODO-0：添加 Phase 4 Code Review 流程

**现状**：当前流程到 Phase 3 生成 `.patchset-summary.md` 即结束，缺少合入后的代码审查环节。

**目标**：在 Phase 3 之后新增 Phase 4，流程如下：

```
Phase 3 全部 patch 合入完成
  │
  └─ Phase 4: Code Review
       ├─ 4.1 调用 code-reviewer 子 agent
       │     ├─ 对每个合入 commit 做 diff 审查
       │     └─ 输出: Strengths / Issues (Critical / Important / Minor) / Assessment
       │
       ├─ 4.2 调用 security-reviewer 子 agent
       │     ├─ 检查: 权限检查、内存屏障、加密、输入校验
       │     └─ 输出: 安全问题清单 (P0/P1/P2/P3)
       │
       └─ 4.3 Fix Loop（如有修改意见）
            ┌──────────────────────────────────────────────┐
            │ 1. 定位目标 patch 的 commit id                │
            │ 2. git rebase -i 到该 commit 位置             │
            │ 3. 修改源码文件                               │
            │ 4. git add → git commit --amend              │
            │ 5. git rebase --continue                     │
            │ 6. 重新编译验证                               │
            │ 7. 重新调用 review agent 确认                 │
            └──────────────────────────────────────────────┘
```

**设计要点**：

| 项目 | 决策 |
|------|------|
| Review 时机 | 全部 patch 合入完成后统一审查（非 per-patch） |
| Reviewer agent | 独立子 agent，使用 `agents/code-reviewer.md` prompt 模板 |
| Security reviewer | 独立子 agent，使用 `agents/security-reviewer.md` prompt 模板 |
| Fix 方式 | `git rebase` + `commit --amend`，保持历史整洁 |
| Fix 后验证 | 重新编译 + 重新 review，直到通过 |
| 用户交互 | review 结果展示给用户，Critical/Important 问题必须修复，Minor 由用户决定 |

#### TODO-1：index.js 分析结论

**问题**：其他 skill 的 `index.js` 是做什么的？我们需要吗？

**分析结论**：

搜索了 `~/.claude/skills/`、`~/.agents/skills/` 全部目录，**没有任何 skill 使用 `index.js`**。`/root/.config/opencode/node_modules/` 下的 `index.js` 是 OpenCode 自身的 npm 依赖（zod、msgpackr、cross-spawn 等），与 skill 无关。

merge-patchset 是**纯指令驱动 skill**（SKILL.md + references/ + agents/），AI 读取 Markdown 指令后直接用 Bash/Agent/Edit/LSP 执行，不依赖任何编程语言运行时。**不需要也不应该加 `index.js`**。

> 部分 AI 编码平台的 skill/plugin 系统使用 `index.js` 作为代码入口（如 Copilot 的 agent 模式），但我们的目标是跨平台指令驱动方案，加入 JS 代码会破坏这个原则。

#### TODO-2：Subagent 设计优化

**现状**：当前 3 个 agent（A/B/C）的定义全部内联在 SKILL.md 中，SKILL.md 已 844 行。

**问题**：
1. SKILL.md 过长影响 AI 对核心流程的把握
2. Agent prompt 内联导致无法被其他 skill 复用
3. 新增 review 流程需要再加 agent，继续膨胀

**建议方案**：将 agent 定义拆到 `agents/` 目录，SKILL.md 只保留调度逻辑。

```
merge-patchset/
├── SKILL.md                         # 工作流调度逻辑（瘦身到 ~500 行）
├── agents/
│   ├── conflict-checker.md          # Agent A: 冲突预检 (Phase 0)
│   ├── dependency-detector.md       # Agent B: 依赖检测 (Phase 0)
│   ├── similarity-analyzer.md       # Agent C: 相似度检测 + Revert 定位 (Phase 0)
│   ├── code-reviewer.md             # 代码审查 (Phase 4)
│   └── security-reviewer.md         # 安全审查 (Phase 4)
├── references/
│   ├── output-templates.md
│   └── diagnostic-guide.md
└── ...
```

**设计原则**：

| 原则 | 说明 |
|------|------|
| **语义命名** | agent 文件名描述其职责，不是 "agent-a.md" |
| **自包含** | 每个 agent prompt 包含完整的任务描述，不依赖 SKILL.md 上下文 |
| **可复用** | agent prompt 使用 `{PLACEHOLDER}` 模板变量，可被不同场景调用 |
| **分层调度** | SKILL.md 写 "Dispatch Agent A using `agents/conflict-checker.md`"，agent 内部处理细节 |

**SKILL.md 中的调度写法示例**：

```markdown
### Agent A — 冲突预检

调度子 agent，使用 prompt 模板 `agents/conflict-checker.md`：

参数替换：
- `{PATCH_DIR}` → 相位 0 中确定的 patch_dir
- `{SOURCE_DIR}` → 相位 0 中确定的 source_dir
- `{LSP_AVAILABLE}` → LSP 准备阶段的结果 (true/false)

Agent 返回后，提取冲突风险评级填入 Phase 1 汇总表。
```

#### TODO-3：Patch 拓扑排序算法（大批量合入）

**背景**：当前 skill 假设 patch 已按正确顺序排列（文件名排序）。当 patch 数量较大（如 50+）且来自多个上游时，patch 之间可能存在隐式依赖关系。

**思路**（参考性能组方案）：

```
构建 patch 依赖图:
  输入: N 个 .patch 文件
  步骤:
    1. 解析每个 patch 的符号变更（引入/修改/删除的函数、结构体、宏）
    2. 构建依赖矩阵 M[N][N]:
       - M[i][j] = 1 表示 patch i 依赖 patch j 引入的符号
       - 判断方式: patch i 的 diff 中使用了 patch j 新增的符号
    3. 拓扑排序:
       - 对依赖图做 Kahn 算法或 DFS 拓扑排序
       - 检测循环依赖（如有则报错）
    4. 分层合入:
       - 同一层（无相互依赖）的 patch 可并行合入
       - 不同层按拓扑序依次合入
  输出: 排序后的 patch 列表 + 依赖关系图
```

**适用场景**：
- 大批量安全补丁回合（CVE backport，单次 50-200 个 patch）
- 跨子系统 patchset 合并（网络 + 驱动 + 架构 交叉依赖）
- 多版本 LTS 分支维护

**前提条件**：当前单 patchset 场景稳定后开始设计，先积累 20+ 个真实案例的依赖模式数据。

#### TODO-4：按 Tag 切基线场景的遗留问题

**场景描述**：有时 patchset 需要合入的不是当前 HEAD，而是某个历史 tag（如 `v5.10.0-rc1`），然后在此基础上合入新 patch。

**遗留问题清单**：

| # | 问题 | 影响 | 状态 |
|---|------|------|:----:|
| 1 | Tag 基线自动识别 — 用户说"合入到 5.10 分支"，AI 应自动 `git tag -l "*5.10*"` 找到最近 tag | 用户需手动指定完整 tag 名 | 🔴 待解决 |
| 2 | 基线切出后的分支命名冲突 — 从 tag 切出新分支时，分支名可能与已有分支冲突 | 需手动指定分支名或追加时间戳 | 🟡 有规避 |
| 3 | Tag 基线编译环境差异 — 切到历史 tag 后，可能需要特定工具链版本才能编译 | 编译失败后需手动配置工具链 | 🔴 待解决 |
| 4 | Tag 前后的安全补丁 — 切到历史 tag 可能缺少安全补丁，合入新 patch 后又需补回合 | 需人工判断 | 🔴 待解决 |
| 5 | 跨 tag 合入的 revert 安全 — 历史 tag 上的旧代码如果被 revert，依赖链分析需要切换到 tag 的时间视角 | Agent C 的依赖链分析可能不准 | 🟡 待验证 |
| 6 | Tag 基线 + 路径适配的组合 — 历史 tag 的文件路径可能与当前 HEAD 不同 | 路径搜索需要指定 `git checkout <tag>` 后的状态 | 🟡 有规避 |

> 🟡 = 有规避方案但不优雅，🔴 = 尚无方案

---

## 7. 附录

### 7.1 项目文件结构

```
patchset-merge/
├── SKILL.md                         # merge-patchset 源文件 (~844 行)
├── karpathy-guidelines-SKILL.md     # AI 行为准则
├── install.sh                       # 多平台安装脚本
├── CLAUDE.md                        # Claude Code 项目指令
├── README.md                        # 项目文档
├── agents/                          # 子 agent prompt 模板（规划中）
│   ├── conflict-checker.md          #   Agent A: 冲突预检
│   ├── dependency-detector.md       #   Agent B: 依赖检测
│   ├── similarity-analyzer.md       #   Agent C: 相似度检测
│   ├── code-reviewer.md             #   Phase 4: 代码审查
│   └── security-reviewer.md         #   Phase 4: 安全审查
├── references/
│   ├── output-templates.md          # 输出模板 (Phase 0-4 对话/文档/报告)
│   └── diagnostic-guide.md          # 冲突/编译错误诊断指南
└── docs/
    └── merge-patchset-skill-report.md  # 本报告
```

### 7.2 技术栈

| 层 | 技术 | 用途 |
|----|------|------|
| 指令定义 | Markdown + YAML frontmatter | SKILL.md 本体 |
| AI 平台 | Claude Code / OpenCode | Skill 加载和执行 |
| 代码分析 | clangd (LSP) | 符号导航、调用链分析 |
| 版本控制 | git (am/apply/revert/format-patch/blame/log) | 所有合入操作 |
| 编译 | make / cmake / build.sh | 编译验证 |
| 部署 | Bash (install.sh) | 多平台安装 + 降级版本生成 |
