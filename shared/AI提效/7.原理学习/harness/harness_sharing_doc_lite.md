# Harness：让 AI Agent 可用、可控、可演化的工程骨架

---

## 第 0 章 开篇：一场失控的实验

你需要把 **50 个 kernel patch** 合入到一个 git 仓库。

| 维度 | 裸 LLM | + Harness |
|------|---------|-----------|
| 上下文管理 | 所有 patch 共享上下文 → 挤爆 | 每个 patch 独立上下文 → 不膨胀 |
| 冲突处理 | AI 自己乱解 | 独立 skill + 决策矩阵 |
| 状态追踪 | 无 → 不知道哪步出了问题 | execution_log.json → 每步可追溯 |
| 断点续跑 | 不可能 → 只能从头来 | 读 log 跳过已处理 patch |
| 编译验证 | 最后一起编 → 大海捞针 | checkpoint 小步编译 → 精准定位 |
| 50 patch 无人值守 | ❌ | ✅ |

> **模型能力是概率的，会漂移，偶尔会失控。真正让 Agent 可用、可控、可演化的，是模型外面那一层工程化的骨架——Harness。**

比喻：泉眼(LLM) → 水龙头(Prompt) → 水管(Context) → **阀门(Harness)** → 循环系统(Loop) → 自动检修(Self-Harness) → 整个供水网络(Environment)。**没有阀门的水管，水压一大就会爆管。没有 Harness 的 AI，任务一复杂就会失控。**

---

## 第 1 章 什么是 Harness

### 1.1 六个失控模式 → 六个解决方案

AI Agent 在无人值守场景下有**所有可能的失控模式**：

| 问题 | 解决方案 | Harness 要素 |
|------|---------|-------------|
| 死循环、无限重试 | 给循环加退出条件，限制最大重试次数 | **E**xecution Loop |
| AI 越界（合入器跑去解冲突） | 划定能力边界，每个 skill 只做自己的事 | **T**ool Registry |
| 上下文爆了（50 个 patch 日志全塞进去） | 隔离上下文，主 agent 编排，子 agent 执行 | **C**ontext Manager |
| 中断丢了（跑了 30 个 patch 后挂了） | 持久化状态，每步写 JSON，可断点续跑 | **S**tate Store |
| 关键操作拦不住（AI 执行了 git am —abort） | 关键时机拦截，红线 + 生命周期钩子 | **L**ifecycle Hooks |
| 质量看不见（AI 说完成了但做错了） | 独立评估，验证者 ≠ 生成者 | **E**valuation |

### 1.2 ETCSLE：三层防线

这六个要素不是并列的，而是**层层递进**的三层防线：

```
🛡️ 第一层：让任务跑完（可靠）
   E — Execution Loop：循环控制（最大重试、退出条件）
   C — Context Manager：上下文隔离（子 agent 独立上下文）
   S — State Store：状态持久化（断点续跑、可恢复）

🔒 第二层：让行为合规（可控）
   T — Tool Registry：能力边界（每个 skill 只能做自己的事）
   L — Lifecycle Hooks：关键拦截（红线、门禁、强制路径）

📈 第三层：让系统越用越好（可演化）
   E — Evaluation：独立评估（验证者 ≠ 生成者）
```

连"跑完"都保证不了，谈"合规"没意义；连"合规"都保证不了，谈"演化"是空话。

| 元素 | 一句话 | 对抗什么 | 真实代码 |
|------|--------|---------|---------|
| **E**xecution Loop | 循环不能无限跑 | 死循环 | conflict-handler: `MAX_RETRIES = 10` |
| **C**ontext Manager | 上下文不能共享 | 膨胀降智 | orchestrator 逐 patch 调 merge-executor，不传对话历史 |
| **S**tate Store | 状态不能丢 | 中断不可恢复 | `execution_log.json` + resume 读 log 跳过已处理 seq |
| **T**ool Registry | 能力不能越界 | 角色混乱 | merge-executor 的 `<HARD-GATE>`: 禁止 `git am —reject`、禁止自行修编译 |
| **L**ifecycle Hooks | 关键操作不能跳 | 不可控 | merge-executor 红线: "冲突后禁止 `git am —abort`，保留现场" |
| **E**valuation | 不能信任自汇报 | 质量退化 | Superpowers: spec-reviewer + code-quality-reviewer 双重独立审查 |

### 1.3 关键概念

**Artifact——阶段间的契约**

```
scene-selector → request.json → workspace-manager → workspace.json → patch-analysis
→ merge_plan.json → merge-executor → execution_log.json → code-reviewer
→ review_report.json → report-generator → output_report.json
```

- 每个 skill **读**上阶段的 artifact，**写**自己的 artifact
- artifact 是 JSON 文件，写在磁盘上，不通过内存传递
- orchestrator **不信任** AI 的口头汇报，只读 artifact 做判断

**Skill + Harness——AI 做决策，代码做苦力**

| 放 Skill（AI 语义理解） | 放 Harness（代码确定性执行） |
|---|---|
| 读 git am 输出判断 passed/conflict/failed | `build_execution_item()` 构建 JSON |
| 读 .rej 文件理解冲突语义 | `read_json()`/`write_json()` 读写文件 |
| 决策：这个 patch 是不是 checkpoint | `append_execution_result()` 追加记录 |

> 原则：**需要理解输出才能做判断的放 Skill，机械可重复的不涉及语义的放 Harness。**

**红线 vs 门禁——两种约束机制**

| | 红线 | 门禁 |
|---|---|---|
| 位置 | SKILL.md 里的硬约束文字 | 阶段间的校验代码/规则 |
| 检查时机 | 执行过程中（行为约束） | 阶段切换时（准入约束） |
| 例子 | "冲突后禁止 git am —abort" | "无 workspace.json 禁止进入 patch-analysis" |
| 性质 | 文本约束（AI 自觉遵守） | 可代码化（校验 artifact 存在性） |

### 1.4 演进：不是"多了些规则"，而是换了范式

| 维度 | Prompt/Skill 阶段 | Harness 阶段 |
|------|-------------------|-------------|
| 约束性质 | **软约束**——AI 自觉遵守，违反了也没机制阻止 | **硬约束**——HARD-GATE 限制工具、门禁限制跳步、状态机限制跳转 |
| 状态管理 | **无状态**——每步靠人或 AI 自己记住 | **有状态**——JSON artifact 持久化，可断点续跑 |
| 编排者 | **人**——每步等人确认 | **系统**——orchestrator 自动调度，artifact 门禁保证衔接 |

> Superpowers（人在回路）用软调用就够了，patch-merge-workflow（无人值守）必须用硬调用——**问题域决定架构选择**，不是写法偏好。

---

## 第 2 章 为什么需要 Harness

### 2.1 LLM 的根本问题

LLM 是概率模型，不是确定性系统——不是"偶尔犯错"，而是"本质上就在概率分布上运行"。衍生出四个工程问题：

1. **输出不确定**：同一 prompt 不同结果 → 无法保证可复现
2. **上下文有容量上限**：水位 >50% 开始降智 → 长任务必然崩溃
3. **没有记忆**：每次 session 从零开始 → 经验无法积累
4. **没有工程能力**：无权限/无安全/无审计 → 无法独立运行在生产环境

这四个问题有因果链——上下文爆了会加剧输出不确定，没有记忆会导致重复犯同样的错，互相放大。

### 2.2 SKILL.md 能解决多少？

**能，但远远不够。** 三个原因：

**原因 1：文本规则无法穷尽隐式知识**

```
# 你能写出来的：
- 合入后检查 git 返回码
- 冲突后不要 abort

# 你写不出来的：
- git am --3way 返回非零时，要检查 .git/rebase-apply/ 是否存在来区分 conflict 和 hard fail
- conflict_resolved 后仍需检查 build_checkpoint，因为冲突消解可能引入编译错误
```

隐式规则不是"可以写但忘了写"，而是**只有踩过坑才知道要写**。

**原因 2：AI 在压力下会违反规则**

Superpowers 的 TDD skill 写了极强约束——`NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST`，还配了 Rationalization Table 预判 AI 的借口。**即便如此**，AI 仍然会跳过测试先写代码——当上下文膨胀、任务紧迫时，AI 会倾向于选择"更快"的路径。

**原因 3：SKILL.md 约束不了执行路径**

```
# SKILL.md 说：
"冲突后禁止 git am --abort"

# 但如果 AI 执行了 git am --abort，SKILL.md 没有任何机制阻止它
# 规则是"建议"，不是"护栏"
```

Harness 的解法不是靠一条更强的规则，而是**多层约束让 AI 做"错的事"变得不可能**：

1. HARD-GATE 列出禁止操作（比红线更醒目）
2. 状态机：conflict 只能 → blocked（AI 没机会执行 abort）
3. execution_log 记录每一步（AI 知道行为会被审查）
4. conflict-handler 是独立 skill（merge-executor 根本没有 git am --reject 的权限）

### 2.3 为什么 Superpowers 只用 SKILL.md 就够了？

**Superpowers 把人的深度参与放在了最前端**——在 spec 和 plan 阶段让人深度参与，把模糊性、歧义、边界情况都讨论清楚，产出一个高质量的设计文档。后面的 AI 执行只是在照着清晰的 spec 做，出问题概率低。

patch-merge-workflow 不允许这样做——不能让 50 个 patch 每个都先人来写 spec 再 AI 执行。所以策略是**把人在前端做的事全部编码到 Harness 里**：

| 人在 Superpowers 前端做的事 | Harness 在 PMW 中的对应 |
|---|---|
| 人讨论确定方案方向 | scene-selector 根据场景自动选择流程 |
| 人审查每个需求 | patch-analysis 自动提取元数据，标记 checkpoint |
| 人预判可能出问题的地方 | checkpoint 规则：7 条规则自动标记需编译验证的 patch |
| 人决定冲突怎么解 | decision_table.md：10 种冲突场景的 Ours/Theirs 决策矩阵 |
| 人确保不跳步 | 状态机 + artifact 门禁：只有合法状态才能转换 |
| 人检查做完对不对 | code-reviewer + report-generator：独立 skill 自动审查 |

**什么时候必须上 Harness？** 任务步数多、无人值守、失败代价高——三个条件同时满足。

---

## 第 3 章 Harness 的核心能力

### 3.1 上下文隔离：子 agent 做执行，主 agent 做编排

**三条铁律**：

1. **子 agent 不继承父 agent 的对话历史**——每个 patch 一个干净上下文
2. **所有跨 agent 通信必须通过 artifact 文件**——不通过内存，不通过口头汇报
3. **父 agent 不信任子 agent 的口头汇报，只读 artifact 做判断**

```python
# orchestrator 不信任 AI 说"我完成了"，而是自己读 execution_log
log = read_json(str(log_path))
current = next((i for i in log["items"] if i["seq"] == seq), None)
result = current["result"]  # passed / conflict / failed
```

### 3.2 事前拦截：小步验证 + 决策矩阵 + 能力边界

**Checkpoint 编译——小步验证**

不是"最后一起编"，而是根据 7 条规则自动标记哪些 patch 需要编译验证，合入后立即编译：

```
patch-1 (普通) → apply ✅ → 不编译                    ← Rule 7: 默认不检
patch-2 (infra) → apply ✅ → 编译 ✅                    ← Rule 1: infra 类必检
patch-3 (引用了patch-5定义的符号) → 不编译              ← Rule 1a: 反向依赖，编译肯定不过
patch-5 (符号被patch-3引用) → 编译 ✅                    ← Rule 1b: 反向依赖提供者，必须验证
patch-6 (最后一个，doc类) → 编译 ✅                      ← Rule 4: 最后一个绝对覆盖
```

反直觉但关键的 **Rule 1a**：反向依赖的 patch 不编译——patch-3 引用了 patch-5 的符号，但 patch-5 还没合入，编译注定失败。反过来，patch-5 作为反向依赖提供者必须编译。

**决策矩阵——减少 AI 试错**

conflict-handler 不让 AI 自由发挥，而是给一个 10 场景的决策矩阵：

| # | 场景 | 抉择 | 理由 |
|---|------|------|------|
| 1 | patch 的 `+` 行（新增代码） | **Theirs** | patch 核心意图，不可丢失 |
| 3 | 上下文行差异 | **Ours** | 目标仓库代码是真实代码 |
| 5 | 上游重构 vs 本地相同功能 | **Theirs** | 上游版本更权威 |
| 6 | 上游重构 vs 下游特有补丁 | **⚠️ 人工裁定** | 下游特有修改不可丢弃 |
| 7 | 同 bug 不同修复 | **Theirs** | 上游修复更权威 |
| 11 | 无法自动判定 | **⚠️ 暂停** | 交给人裁定 |

10 个场景中 8 个可以自动判定，2 个需人工介入——**不确定就不做，交给人**。

**HARD-GATE——强制能力边界**

```
<HARD-GATE>
禁止操作：
❌ git am --reject（这是 conflict-handler 的工具）
❌ 读取 .rej 文件（这是 conflict-handler 的职责）
❌ 编辑源码文件来修复编译错误（这是 build-validator 的活）
</HARD-GATE>
```

**三者的关系**：checkpoint 编译是**验证型拦截**（做完检查），决策矩阵是**引导型拦截**（做之前给路径），HARD-GATE 是**强制型拦截**（做不了不该做的事）。

**工业级案例：高德的三层快速失败评审**

```
代码提交 → 第一层：代码质量（~几秒）❌ → 立即退回
            ✅ → 第二层：静态质量（30-60s）❌ → 立即退回
                 ✅ → 第三层：动态运行（2-5min）❌ → 立即退回
                      ✅ → 通过评审
```

实战：某次评审因配置问题全流程跑完后才发现，耗时 4 分钟；引入快速失败后同样场景第一步就被拦截，耗时 1 秒。**宁可 10 次 1 秒钟快速退回，也不允许 1 次 4 分钟的无效评审。**

### 3.3 状态恢复：断点续跑

**三层状态体系**：

| 层级 | 状态 | 作用 |
|------|------|------|
| 工作流级 | `execution_log.status` | running / completed / blocked / failed |
| 单 patch 级 | `item.result` | passed / conflict → conflict_resolved / failed |
| 编译级 | `item.build.status` | passed / failed / not_required |

```python
def get_processed_seqs():
    log = read_json(str(log_path))
    processed = set()
    for item in log.get("items", []):
        if item.get("result") == "passed":
            processed.add(item["seq"])
        resolution = item.get("resolution", {})
        if resolution.get("resolved"):
            processed.add(item["seq"])
    return processed

# 主循环跳过已处理的
for item in items:
    if seq in processed:
        continue
```

**关键调度规则**（踩坑后的经验）：

- `conflict_resolved` 后仍需检查 `build_checkpoint`——冲突消解成功不代表编译安全
- checkpoint 编译失败**不执行** `git am --abort`（保留工作分支已有合入）
- `blocked` 或 `failed` 状态**仍需**进入 code-reviewer 和 report-generator（失败也要出报告）

### 3.4 约束执行：软调用 vs 硬调用

| 层次 | 软调用（Superpowers） | 硬调用（patch-merge-workflow） |
|------|--------|--------|
| 参数约定 | `invoke writing-plans skill` 只说调，不传参 | `args="PROJECT_ROOT=... artifacts_root=..."` 显式参数 |
| 上下文传递 | 隐式——AI 自己找前置 skill 的产出文件 | 显式——通过 artifact 路径约定读哪个 JSON |
| 返回值约定 | 无 | 约定读哪个 JSON |
| 门禁校验 | 无 | artifact 存在性校验 |

软调用的"传参"靠隐式约定——brainstorming 写 spec 到某路径，writing-plans 的 AI 自己去找。没有参数约定意味着 AI 可能找错文件——但在人在回路的场景下，人会及时发现。

> **选择标准**：前端有人的场景 = 软调用够了；需要无人值守 = 必须硬调用。

### 3.5 验证闭环：不信任自汇报

**原则**：验证者 ≠ 生成者，零信任自汇报。

Superpowers 的 spec-reviewer 原文：*"The implementer finished suspiciously quickly. Their report may be incomplete, inaccurate, or optimistic."*

PMW 的做法更进一层——用**确定性代码**来验证 AI 声称的状态：

| AI 声称的状态 | 校验方式 | 不通过时 |
|--------------|---------|---------|
| `result=passed` | `git log` 中是否存在该 patch 的最新 commit | 拒绝写入 |
| `build.status=passed` | 编译日志文件是否存在且 returncode=0 | 拒绝写入 |
| `result=conflict` | `.git/rebase-apply/` 是否存在 | 拒绝写入 |

> 不只约束 AI 的行为，还要约束 AI **写入状态的真实性**。SKILL.md 写红线，harness 函数做校验，两者配合形成完整闭环。

### 3.6 执行计划：动态生成与跟踪

50 个 patch 的执行顺序、checkpoint 标记、依赖关系不能写死，要根据输入动态生成。

**PMW 改进方向**——pipeline 定义迁移到 scene YAML：

```yaml
# scenes/legacy-single-repo.yaml
scene_id: legacy-single-repo
features:
  build: true
  dependency: false

pipeline:
  - step: scene-selector
    produces: [request.json, config_selection.json]
  - step: workspace-manager
    requires: [request.json, config_selection.json]
    produces: [workspace.json, build/build.sh]
  - step: patch-analysis
    requires: [workspace.json]
    produces: [merge/merge_plan.json]
  - step: merge-executor
    requires: [merge/merge_plan.json]
    loop: true
    produces: [merge/execution_log.json]
  - step: code-reviewer
    requires: [merge/execution_log.json]
  - step: report-generator
    requires: [review/review_report.json]
```

三个好处：新增场景 = 新增 YAML 文件；`requires`/`produces` 天然是 artifact 门禁；pipeline 是数据不是代码，后续可做成可视化配置。

### 3.7 Agent 自进化：从失败中学习

每次失败都是规则库的养分：

- conflict-handler 记录冲突内容、解决方式 → `conflict_report.json`
- build-validator 记录编译错误类型、修复摘要 → `build_result.json` 的 `attempts[]`
- checkpoint 规则本身就是经验沉淀：每条规则都对应一个曾经踩过的坑

**当前状态**：有了每次任务执行后的沉淀资料，还没做到让 AI 自动提炼规则并更新决策矩阵。

**演进方向**：当冲突解决知识库足够丰富时，让 AI 在解冲突时自动提取新规则，存到规则库中，实现 skill 自动增强。

---

## 第 4 章 怎么落地：Skill + Harness 两层架构与 SKILL.md 写作技巧

### 4.1 划界：什么放 Skill，什么放 Harness

判断流程：

1. 需要看 AI 输出才能决定下一步？→ **Skill**
2. 每次执行结果完全确定？→ **Harness**
3. 出错时需要语义理解来修复？→ **Skill**，否则 → **Harness**

| 操作 | 放哪里 | 判断依据 |
|------|--------|---------|
| 读 git am 返回码判断 passed/conflict/failed | Skill | 需要理解输出 |
| `build_execution_item()` 构建 JSON | Harness | 纯数据组装，完全确定 |
| 读 .rej 文件理解冲突语义 | Skill | 需要理解代码含义 |
| 按 decision_table 判断 Ours/Theirs | Skill | 需要理解冲突场景并匹配规则 |
| checkpoint 规则计算 | Harness | 判断逻辑确定性可重复（7 条规则 + 优先级短路） |

> 判断依据不是"是否涉及判断"，而是"**判断是否确定性可重复**"。

### 4.2 SKILL.md 的约束技术：五种武器

| 武器 | 层次 | 一句话 | PMW 对应 |
|------|------|--------|---------|
| **Iron Law** | 价值观层 | 大写 + 绝对否定 + 无例外 | "冲突后禁止 git am --abort" |
| **HARD-GATE** | 行为层 | 能力边界：只能做这些，不能做那些 | merge-executor 的禁止/必须清单 |
| **Red Flags** | 自检层 | 异常信号灯：出现这些模式说明可能违规 | "执行了 git am --abort 但没检查 .git/rebase-apply" |
| **Rationalization Table** | 防御层 | 预判 AI 的借口并提前反驳 | （PMW 暂无，Superpowers 有） |
| **Commitment** | 心理层 | 先声明后执行，违反一致性产生压力 | TodoWrite 逐项打卡 |

从上到下约束强度递减，但覆盖面递增。Iron Law 只能覆盖少数核心规则，Rationalization Table 可以覆盖大量边缘场景。

**PMW 的选择**：几乎只用硬约束（`<HARD-GATE>` + 禁止/必须清单），没用软说服。原因——**无人值守场景，硬约束才是根本**，AI 不会因为你说"伙伴"就真的更听话。后续方向：在硬约束兜底的基础上，用软说服提高合规上限。

### 4.3 Skill 三层渐进式加载

一个 Agent 可能拥有数十个 Skill，按需加载控制 token 开销：

| 层级 | 触发时机 | 加载内容 | Token 开销 |
|------|---------|---------|-----------|
| **L1 Metadata** | 会话启动时 | frontmatter 的 name + description | ~100 tokens/skill |
| **L2 Instructions** | Skill 被激活时 | 完整 SKILL.md body | < 5,000 tokens/skill |
| **L3 Resources** | 执行时按需 | references/、scripts/、assets/ | 按需 |

实测：8 个 Skill 全量常驻 ~24,000 tokens；L1 常驻 + 1 个激活 L2 = **3,480 tokens**，节省 85%。

**description 陷阱**：description 属于 L1（常驻上下文），**只写触发条件，不写工作流**——AI 读完 description 可能觉得自己知道怎么做了，跳过完整 SKILL.md。

**与 3.1 上下文隔离的互补**：3.1 是横向隔离（Agent 间上下文不互相污染），三层加载是纵向控制（单个 Skill 内 token 逐层递进），两者协同实现**上下文精确投递**。

**Compaction 威胁**：上下文接近上限时触发压缩，L1/L2 精心设计的分层会被打破。防御：核心指令放 SKILL.md 开头（5,000 tokens 以内）；持久规则放 CLAUDE.md/OpenCode.md；Skill 拆成 subagent 调用。

### 4.4 SKILL.md 模板

```markdown
---
name: skill-name
description: 触发条件，不要总结工作流
---

# Skill 标题

## Overview
核心原则，1-2 句话

## Iron Law（如有）
绝对规则，大写，无例外

## Input
- 从 args 接收什么
- 前置 artifact 有哪些

## Steps
1. 初始化（调 harness 函数）
2. 执行（AI 做语义判断）
3. 写出结果（调 harness 函数写 artifact）

## <HARD-GATE>
禁止操作：
❌ ...
必须遵循：
✅ ...
</HARD-GATE>

## Red Flags
- ...

## 红线
- ...
```

> Steps 中的"判断"由 AI 做，"读写"由 harness 函数做——两层架构在单个 skill 内部的体现。

---

## 第 5 章 实战：patch-merge-workflow 架构全貌

### 5.1 全流程

```
用户输入 → ① scene-selector(解析请求)
          → ② workspace-manager(校验仓库，创建工作分支)
          → ③ patch-analysis(收集patch，提取元数据，标记checkpoint)
          → ④ merge-executor(逐patch: git am → passed/conflict/failed)
              ├─ passed + checkpoint → build-validator(编译→修→再编译)
              ├─ conflict → ⑤ conflict-handler(决策矩阵消解，最多10次)
              └─ failed → 终止
          → ⑥ code-reviewer(审查合入质量)
          → ⑦ report-generator(撰写最终报告)
```

### 5.2 两条典型路径

**Happy Path**：request → workspace → patch analysis → git am success (×N) → checkpoint build passed → completed ✅

**Blocked Path**：request → workspace → patch analysis → git am success (前M个) → git am conflict (第M+1个) → conflict-handler: 逐 .rej 消解 → resolved 继续合入 / unresolved handoff ⚠️

### 5.3 七个 Skill 的职责分工

| Skill | 读什么 | 做什么 | 写什么 | Harness 函数 |
|-------|--------|--------|--------|-------------|
| **scene-selector** | 用户输入 | 解析请求，生成配置 | request.json, config_selection.json | `write_json()` |
| **workspace-manager** | request.json | 校验 git repo，创建工作分支 | workspace.json, build.sh | `validate_local_git_repo()`, `setup_work_branch()` |
| **patch-analysis** | request + workspace | 收集 patch，提取元数据，标记 checkpoint | merge_plan.json | `ingest_source()`, `build_merge_plan()`, `calculate_checkpoints()` |
| **merge-executor** | workspace + merge_plan | 逐 patch 执行 git am，判断结果 | execution_log.json, conflict_context.json | `build_execution_item()`, `append_execution_result()` |
| **conflict-handler** | conflict_context + decision_table | 按决策矩阵消解冲突 | resolution_result.json, conflict_report.json | `read_json()`, `write_json()` |
| **build-validator** | build.sh | 编译→修→再编译循环 | build_result.json | `read_json()`, `write_json()` |
| **code-reviewer** | workspace + execution_log | 审查合入质量 | review_report.json | `read_json()`, `write_json()` |
| **report-generator** | 所有 artifact | 撰写最终报告 | output_report.json, summary.md | `read_json()`, `write_json()` |

---

## 第 6 章 踩坑与经验

### 6.1 端到端自动化的工程量被严重低估

| 低估的维度 | 以为 | 实际 |
|-----------|------|------|
| 状态管理 | AI 自己记住就行 | 每步必须写 JSON，三层状态 |
| 超时和资源 | AI 跑完就好 | 5 个 skill 串联 + 门禁 + 重试，可能十几分钟 |
| 环境一致性 | 本地能跑就能跑 | 本地编译正常、云端构建失败 |
| 可追溯日志 | AI 告诉我就行 | 必须有 artifact：在哪里、什么时间、为什么 |

> **端到端自动化 = 软件工程**，不是写几个 SKILL.md 就完事了。

### 6.2 SKILL.md 写了不等于 AI 会遵守

踩过的真实案例：
- 红线写了"冲突后禁止 git am --abort"，AI 在上下文膨胀时仍执行了 abort
- 红线写了"禁止改 Makefile/Kconfig"，AI 修编译错误时改了 Kconfig
- 红线写了"禁止一次性调用 merge-executor 处理所有 patch"，AI 偷懒传了所有 seq

**解法不是写更强的红线，而是加代码级兜底**——这正是 Harness 存在的意义。

### 6.3 小步快跑

```
v0.1：单个 patch 的 happy path 能跑通
  ↓ 验证：手动跑一个 clean patch
v0.2：多个 patch 的循环能跑通
  ↓ 验证：跑 3 个 clean patch，确认 resume 逻辑对
v0.3：冲突路径能跑通
  ↓ 验证：跑 1 个 conflict patch
v0.4：checkpoint 编译能跑通
  ↓ 验证：跑 1 个 checkpoint patch
v0.5：端到端全流程
```

**核心原则**：每个版本保证最起码的通路。上一轮验证过的部分是可信的，新问题一定出在新加的部分。

### 6.4 完全无人干预不是 0/1 的状态

| 阶段 | 人工干预频率 |
|------|------------|
| v0.1 | 每步都确认 |
| v0.3 | 每 5-10 步确认一次 |
| v0.5 | 每次任务确认一次 |
| 目标 | 仅冲突场景 6/10 时介入 |

不需要追求"100% 无人值守"。从"每步确认"到"仅异常时介入"，每降低一个量级的干预频率，就释放一个量级的人力。

### 6.5 模型很强但仍会出问题

长链路稳定性脆弱：8 个关键节点 × 90% 成功率 = 端到端一次通过率 ~43%。靠 build-validator 编译修复循环、conflict-handler 重试、orchestrator resume、execution_log 追溯来兜底。

### 6.6 约束不只是规则——环境工具化

高德的实践：AI 约 10 次尝试只能成功 1-2 次；把 API 调用方式封装成 Skill 后基本都能成功。**解法不只是更强的红线或代码兜底，还可以是从环境层面消除犯错的可能。** HARD-GATE 是"你不该做"，环境工具化是"你做不了"。

---

## 第 7 章 Subagent 架构

### 7.1 核心原则：上下文隔离

> "They should never inherit your session's context or history — you construct exactly what they need."

两种实现方式：

| | Claude Code（Superpowers） | OpenCode（PMW） |
|---|---|---|
| 传参 | `Agent(prompt=完整指令文本)`，子 agent 只看 prompt | `Task(prompt='加载 Skill 并执行')`，子 agent 自己加载 SKILL.md |
| 信息来源 | 父 agent 准备好一切 | 子 agent 按需加载 |

两种方式都能实现上下文隔离，只是信息传递的主动权不同。

> ⚠️ **当前 PMW 的问题**：orchestrator 调用 `Skill("merge-executor", args="seq=7")`——这不是 Task 工具，而是 Skill 工具，效果是 SKILL.md 内容被加载到主 agent 上下文中内联执行，**并没有创建真正的子 agent**。

### 7.2 Superpowers 的三阶段派发

每个 task 都走三阶段，每个阶段都是独立子 agent：

```
implementer(实现+测试+提交)
  → spec-reviewer(验证是否按 spec 做，零信任原则)
  → code-quality-reviewer(验证代码质量)
```

spec-reviewer 的零信任原则：*"DO NOT: Take their word / Trust their claims. DO: Read the actual code / Compare to requirements line by line"*

implementer 的安全阀：*"It is always OK to stop and say 'this is too hard for me.' Bad work is worse than no work."* 四种返回状态：DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT。

### 7.3 Git Worktree 隔离：物理级上下文隔离

逻辑隔离是"对话历史不共享"，物理隔离是"连文件系统都不共享"——每个 worktree 是 git 仓库的独立检出目录，子 agent 在自己的目录里操作，即使执行了 `git checkout` 或 `git reset`，主仓库纹丝不动。

在 Claude Code 上 `isolation: worktree` 是标准字段；OpenCode 目前无内置支持。

### 7.4 对 PMW 的改造方向

**核心**：从 Skill 内联执行 → Task 子 agent 调用。

**参数传入**：从 `args="key=value key=value"` 字符串 → prompt 文本中直接写参数。

**结果传出：artifact 机制完全不变**——不管怎么派子 agent，子 agent 都是把结果写入磁盘上的 JSON 文件，父 agent 都是用 `read_json()` 读取。**artifact 是磁盘契约，不依赖平台，不依赖调用方式。**

| 维度 | 当前（Skill 内联） | 改造后（Task 子 agent） |
|------|-------------------|----------------------|
| 上下文占用 | 所有 patch 共享主上下文 → 膨胀 | 每个 patch 独立上下文 → 不膨胀 |
| 执行隔离 | merge-executor 出错可能影响 orchestrator | 子 agent 挂了不影响主 agent |

---

## 第 8 章 YAML 在 AI 工程中的角色：规则该放哪一层？

### 8.1 三种规则载体：谁消费，就放谁

| 载体 | 消费者 | AI 可读 | 机器可校验 | 适合放什么 |
|------|--------|---------|-----------|-----------|
| **SKILL.md** | AI 模型 | ✅ 最佳 | ❌ | 需要语义理解的决策指南、流程步骤、红线 |
| **YAML** | 运行时解析器 | ⚠️ 能读但非最优 | ✅ 最佳 | 场景配置、参数阈值、枚举分类、状态转换 |
| **Python** | 程序执行 | ❌ | ✅ 可测试 | 确定性计算、JSON 构建、文件 I/O、算法 |

**判断标准**：规则是否需要 AI 语义理解？→ 需要就留 Markdown，机械可判定就迁 YAML，需要计算就留 Python。

**Claude Code 的实践验证**：SKILL.md 的 YAML frontmatter 给运行时（name/tools/model/context:fork），Markdown body 给 AI。两者消费者不同，载体自然不同。

### 8.2 迁移机会

**机会 1（最高优先级）：checkpoint 规则 → risk_rules.yaml**

当前 7 条规则硬编码在 `build_checkpoint.py:55-121`，全是 if condition → boolean，零语义理解。`reference_count >= 3` 的 "3" 是经验值，不同项目可能不同——YAML 里改一次只要改配置。

**机会 2：decision_table.md → 一分为二**

- #1 patch `+` 行 → Theirs、#3 上下文行差异 → Ours：**纯语法判定，迁 YAML**
- #4-#6、#7-#11：**需语义理解，留 Markdown**

**机会 3：状态转换定义 → state_machines/*.yaml**

当前状态转换逻辑散落在 SKILL.md 中以自然语言描述。YAML 声明合法状态转换，Python 代码读取并校验——当 AI 试图从 `conflict` 直接跳到 `passed`，校验器拦截。

> 这和 3.5 的"harness 函数写入前校验状态真实性"是一体两面——3.5 校验**状态值是否真实**，这里校验**状态转换是否合法**。

### 8.3 常见的坑

| 坑 | 正确做法 |
|----|---------|
| 把 AI 指令放 YAML | AI 要读的规则放 SKILL.md，YAML 只放机械配置 |
| 用 YAML 替代 Python 计算 | YAML 定义规则参数，Python 实现算法逻辑 |
| 定义了 YAML 状态机就以为有了状态机引擎 | YAML 是声明，Python 是执行，两者缺一不可 |
| 枚举三处重复定义（SKILL.md + schema JSON + Python） | YAML 单一数据源 + schema 从中自动生成 |

---

## 第 9 章 Skill 设计模式

### 9.1 五种 Skill 设计模式

| 模式 | 一句话 | 识别标志 | 案例 |
|------|--------|---------|------|
| **Pipeline** | 固定顺序多步流程，每步读前步产物 | "由 X 调用" + 前置 artifact | PMW（整体）、subagent-driven-development |
| **Reviewer** | 独立评估质量，不改代码 | "仅做审查" + findings + severity | code-reviewer、spec-reviewer |
| **Generator** | 读模板+上下文，用自然语言生成产出 | "读取模板" + "用自然语言撰写" | report-generator、writing-plans |
| **Inversion** | 先收集需求/约束/决策，再行动 | "Ask clarifying questions" + HARD-GATE | scene-selector、brainstorming |
| **Tool Wrapper** | 封装领域知识为硬约束，Agent 按指令执行 | "红线" + "禁止/必须"列表 | merge-executor、conflict-handler、build-validator |

### 9.2 四种组合模式

| 组合 | 逻辑 | 案例 |
|------|------|------|
| **Pipeline + Reviewer** | 管道末端加质量门禁 | PMW: merge-executor(×N) → code-reviewer |
| **Generator + Inversion** | 先收集需求再填充模板 | Superpowers: brainstorming → writing-plans |
| **Inversion + Pipeline** | 先需求澄清再执行流水线 | PMW: scene-selector → 后续 5 步 Pipeline |
| **Tool Wrapper + Pipeline** | 管道中每步都是封装好的领域操作 | PMW: workspace-manager / merge-executor / conflict-handler / build-validator |

> 纯 Skill 层无法独立落地——需要 Harness 层提供执行环境、共享状态（artifact）和确定性工具。模式是设计语言，Harness 是运行时。
