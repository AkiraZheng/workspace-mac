# Harness：让 AI Agent 可用、可控、可演化的工程骨架

## 演讲稿

---

### 第 0 章 开篇：一场失控的实验（3 分钟）

[翻页]

大家好，今天我想跟大家聊一个话题——怎么让 AI 在没有人盯着的情况下，也能把活干对。

先想象一个场景：你需要把 50 个 kernel patch 合入到一个 git 仓库。方案 A，裸 LLM，不加任何约束。[展示 图0-1] 一开始还行，patch 1、2 还过得去。到 patch 3，上下文开始膨胀，AI 忘了之前做了什么。到 patch 5，git 状态乱了，AI 没检查 rebase 残留。到 patch 8，冲突了，AI 自己乱解一通。到 patch 15，上下文挤爆，AI 开始胡言乱语。patch 30 以后全面失控——你不知道哪一步出了问题，想回滚都找不到断点。[互动] 在座各位有没有类似的经历？让 AI 跑一个多步任务，结果跑着跑着就歪了？

方案 B，加了 Harness。[展示 图0-2] 每个 patch 独立上下文，不膨胀。apply 之后有门禁，passed 就继续，conflict 就交给专门的 conflict-handler，failed 就 abort 并记录。如果是 checkpoint patch，还会小步编译验证。整个过程像一个精心设计的流水线——每个工位只做自己的事，做完交出质检单，下一工位拿到质检单才开工。

[翻页]

核心对比非常直观。上下文管理，裸 LLM 所有 patch 共享上下文必然挤爆，Harness 每个 patch 独立上下文不膨胀。冲突处理，裸 LLM 让 AI 自由发挥，Harness 用独立 skill 加决策矩阵。状态追踪，裸 LLM 无追踪，Harness 每步写 execution_log.json 可追溯。断点续跑，裸 LLM 只能从头来，Harness 读 log 跳过已处理 patch。**50 patch 无人值守，裸 LLM 不可能，Harness 可以。**

一句话结论：**模型能力是概率的，会漂移，偶尔会失控。真正让 Agent 可用、可控、可演化的，是模型外面那一层工程化的骨架——Harness。**

(停顿)

打个比方：LLM 是泉眼，Prompt 是水龙头，Context 是水管，**Harness 是阀门**。没有阀门的水管，水压一大就会爆管。没有 Harness 的 AI，任务一复杂就会失控。

[翻页]

---

### 第 1 章 什么是 Harness（5 分钟）

先从一个问题开始：如果让你设计一个系统，让 AI 在无人监督下完成一个 50 步的复杂任务，你会遇到什么问题？

不用猜，我们在 patch-merge-workflow 里全都踩过。[展示 图1-1] AI 跑飞了——死循环、无限重试、重复操作。AI 越界了——合入器跑去解冲突，解冲突的去修编译。上下文爆了——50 个 patch 的日志全塞进去，AI 开始胡言乱语。中断丢了——跑了 30 个 patch 后挂了，从头再来？关键操作拦不住——AI 在冲突后执行了 git am --abort，现场全没了。质量看不见——AI 说"完成了"但实际做错了。

这六个问题不是随机的——它们刚好覆盖了 AI Agent 在无人值守场景下**所有可能的失控模式**。对应的六个解决方案，构成了 Harness 的核心框架：**ETCSLE**。

[翻页]

ETCSLE 不是六个独立的模块，而是**三层防线**。[展示 图1-2] 第一层让任务跑完——Execution Loop 循环控制、Context Manager 上下文隔离、State Store 状态持久化。第二层让行为合规——Tool Registry 能力边界、Lifecycle Hooks 关键拦截。第三层让系统越用越好——Evaluation 独立评估。这三层层层递进：连"跑完"都保证不了，谈"合规"没意义；连"合规"都保证不了，谈"演化"是空话。

几个关键概念一笔带过：**Artifact 是阶段间的契约**，每个 skill 读上阶段的 artifact，写自己的 artifact，写在磁盘上不通过内存传递。**Skill 加 Harness 就是 AI 做决策、代码做苦力**——需要理解输出才能做判断的放 Skill，机械可重复的不涉及语义的放 Harness。**红线是行为约束，门禁是准入约束**——红线检查执行过程中，门禁检查阶段切换时。

[翻页]

最后，从 Prompt 到 Skill 再到 Harness，**不是"多了些规则"，而是换了范式**。[展示 图1-3] 约束性质从软约束变成了硬约束——HARD-GATE 限制工具、门禁限制跳步、状态机限制跳转。状态管理从无状态变成了有状态——JSON artifact 持久化可断点续跑。编排者从人变成了系统——自动调度加 artifact 门禁保证衔接。

**问题域决定架构选择，不是写法偏好。** Superpowers 人在回路用软调用就够了，patch-merge-workflow 无人值守必须用硬调用。

---

### 第 2 章 为什么需要 Harness（5 分钟）

[翻页]

我们常说"LLM 输出不稳定"，但这句话太笼统。真正的问题是：**LLM 是概率模型，不是确定性系统。** 它不是"偶尔犯错"，而是"本质上就在概率分布上运行"。

这个根本差异衍生出四个具体的工程问题：[展示 图2-1] 输出不确定——同一 prompt 不同结果，无法保证可复现。上下文有容量上限——水位超 50% 开始降智，长任务必然崩溃。没有记忆——每次 session 从零开始，经验无法积累。没有工程能力——无权限、无安全、无审计，无法独立运行在生产环境。注意，这四个问题不是并列的，有因果链——上下文爆了会加剧输出不确定，没有记忆会导致重复犯同样的错。**它们互相放大，形成恶性循环。**

[翻页]

那能不能靠写好 SKILL.md 来约束？**能，但远远不够。**

原因一，文本规则无法穷尽隐式知识。你能写出"合入后检查 git 返回码"，但你写不出"git am --3way 返回非零时要检查 .git/rebase-apply/ 是否存在来区分 conflict 和 hard fail"。这些隐式规则**只有踩过坑才知道要写**。

原因二，AI 在压力下会违反规则。Superpowers 的 TDD skill 写了极强的约束——"NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST"，还配了 Rationalization Table 预判 AI 的借口。**即便如此**，AI 仍然会跳过测试先写代码。这不是 AI 的问题，是人类也会这样——deadline 前人会偷工减料，AI 会跳过约束。区别是，人偷工减料你知道，**AI 跳过约束你可能不知道**。

原因三，SKILL.md 约束不了执行路径——**规则是"建议"，不是"护栏"**。SKILL.md 写了"冲突后禁止 git am --abort"，但 AI 真的执行了 abort，SKILL.md 没有任何机制阻止它。

[翻页]

Harness 怎么解决？不是靠一条更强的规则，而是靠**多层约束让 AI 做"错的事"变得不可能**。HARD-GATE 列出禁止操作，比红线更醒目。状态机限制：conflict 只能转 resolving 或 handoff，AI 标记 conflict 后任务就停了，没机会执行 abort。execution_log 记录每一步，AI 知道行为会被审查。conflict-handler 是独立 skill，merge-executor 根本没有 git am --reject 的权限。**AI 的合法路径只剩：写 conflict_context.json → 标记 blocked → 停。**

(停顿)

那为什么 Superpowers 只用 SKILL.md 就够了？答案是：**Superpowers 把人的深度参与放在了最前端。** 在 spec 和 plan 阶段让人深度参与，把所有模糊性、歧义、边界情况都讨论清楚，产出高质量设计文档。后面的 AI 执行只是在照着清晰的 spec 做，出问题概率天然就低。但 patch-merge-workflow 的问题域不允许这样做——你不能让 50 个 patch 每个都先人来写 spec 再 AI 执行。所以策略完全不同：**把人前端做的那些"定义规则、消解歧义、判断边界"的工作，全部编码到 Harness 里。**

什么时候必须上 Harness？**任务步数多、无人值守、失败代价高，三个条件同时满足，必须上 Harness。**

---

### 第 3 章 Harness 的核心能力（15 分钟）

[翻页]

前两章讲了"是什么"和"为什么"，这章回答"怎么做"——每个能力具体怎么实现。

#### 3.1 上下文隔离：子 agent 做执行，主 agent 做编排

[翻页]

问题很直接：50 个 patch 合入，所有日志、diff、工具调用结果都塞进一个上下文窗口，水位超 50% 就降智。

解法：主 agent 只保留摘要和调度信息，子 agent 在独立上下文执行单个任务，通过 artifact 文件传递信息。[展示 图3-1] 主 agent 也就是 orchestrator，保留任务计划和 execution_log 的摘要。下发什么？下发 seq 编号、artifact 路径和约束条件。子 agent 做什么？执行 git am，判定结果，写 execution_log 和 conflict_context.json。信息怎么流转？子 agent 写入磁盘上的 artifact 文件，主 agent 从磁盘读取——不通过内存传递，不通过口头汇报。

**三条铁律**：子 agent 不继承父 agent 的对话历史，每个 patch 一个干净上下文。所有跨 agent 通信必须通过 artifact 文件，不通过内存，不通过口头汇报。父 agent 不信任子 agent 的口头汇报，只读 artifact 做判断。

看真实代码：orchestrator 不信任 AI 说"我完成了"，而是自己读 execution_log——`log = read_json(str(log_path))`，然后 `result = current["result"]`，passed 还是 conflict 还是 failed，从 JSON 里读，不是听 AI 说的。Superpowers 的 subagent-driven-development 也明确写了："They should never inherit your session's context or history — you construct exactly what they need." **英雄所见略同。**

[翻页]

#### 3.2 事前拦截：小步验证 + 决策矩阵

[翻页]

问题：无脑合入 50 个 patch 再编译是事后大海捞针；AI 解冲突自由发挥试错成本高。

**解法一：Checkpoint 编译——小步验证。** 不是"最后一起编"，而是根据 7 条规则自动标记哪些 patch 需要编译验证，合入后立即编译。[展示 图3-2] 给大家举个具体例子：patch-1 是普通的，apply 成功，不编译——这是 Rule 7 默认不检。patch-2 是 infra 类的，apply 成功，编译——这是 Rule 1 infra 类必检。patch-3 引用了 patch-5 定义的符号，apply 成功，不编译——注意，这是 Rule 1a 反向依赖，编译肯定不过因为 patch-5 还没合入。反过来，patch-5 作为反向依赖提供者必须编译——它的符号被前面的 patch 依赖了，得确保它自己没问题。patch-6 是最后一个 doc 类，apply 成功，编译——Rule 4 最后一个绝对覆盖，即使是 doc 也检。

这里有个反直觉但很关键的规则——**Rule 1a：反向依赖的 patch 不编译**。因为 patch-5 还没合入，编译注定失败，验了也白验。这比"全编"快得多，又比"不编"安全得多。本质上是**用领域知识精准投放验证资源**。

[翻页]

**解法二：决策矩阵——减少 AI 试错。** conflict-handler 不让 AI 自由发挥怎么解冲突，而是给一个 10 场景的决策矩阵。我挑几个典型的讲。场景 1，patch 新增行冲突，强制 Theirs——因为新增代码是 patch 的核心意图不可丢失。场景 3，上下文行差异，选 Ours——上下文是定位锚点，目标仓库代码才是真实代码。场景 6，上游重构 vs 下游特有补丁，**人工裁定**——下游特有修改不可丢弃，这个 AI 判不了，必须交给人。

核心思路：**给 AI 问题解决矩阵，而非让它自由发挥。** 10 个场景中 8 个可以自动判定，2 个需人工介入。这不是"还没写完"——而是**有意为之的安全边界：不确定就不做，交给人**。

**解法三：HARD-GATE——强制能力边界。** merge-executor 的 HARD-GATE 不只是"建议"，而是通过职责划分来强制执行——merge-executor 根本不应该拥有 git am --reject 的能力，那是 conflict-handler 的工具。禁止 git am --reject，禁止 git am --continue，禁止读取 .rej 文件，禁止编辑源码来修编译错误——连修编译错误都不行，那是 build-validator 的事，你 merge-executor 就管好 apply 就行了。

三者的关系：checkpoint 编译是**验证型拦截**（做完检查），决策矩阵是**引导型拦截**（做之前给路径），HARD-GATE 是**强制型拦截**（做不了不该做的事）。

补充一个工业级案例——**高德的三层快速失败评审**。代码提交后三层检查：第一层编译，失败立即退回；第二层静态质量，安全漏洞立即退回；第三层动态运行，P0 失败立即退回。某次因 .env.local 未配置，全流程跑完才发现耗时 4 分钟；引入快速失败后同样场景第一步就被拦截，耗时 1 秒。核心信念：**宁可让 Evaluator 花 10 次 1 秒钟快速退回，也不允许 1 次 4 分钟的无效评审。** 和我们的 checkpoint 编译是同一思路——快速失败等于低成本拦截。

[翻页]

#### 3.3 状态恢复：断点续跑

[翻页]

问题：跑了 30 个 patch 后挂了，从头再来？花了半小时的白费了？

解法：以 JSON artifact 为状态恢复依据，让长任务可以从断点继续。[展示 图3-3] 三层状态体系：工作流级 execution_log.status 管全局，单 patch 级 item.result 管每次合入，编译级 item.build.status 管编译验证。Resume 机制的核心代码——读 log 获取已处理完成的 seq 集合，主循环跳过已处理的。就这么简单，但**没有这一步，长任务根本跑不了**。跑了 30 个 patch 挂了，下次启动从第 31 个开始，前 30 个的结果全在 artifact 里，不用重跑。

还有几条踩坑后的关键调度规则，不是一开始就能想到的：conflict_resolved 后仍需检查 build_checkpoint——**冲突消解成功不代表编译安全**。checkpoint 编译失败不执行 git am --abort——**保留工作分支已有合入**。blocked 或 failed 状态仍需进入 code-reviewer 和 report-generator——**不能因为失败就不出报告**。

[翻页]

#### 3.4 约束执行：软调用 vs 硬调用

[翻页]

问题：AI 读到"invoke writing-plans skill"后，怎么确保它真的调了？调了之后怎么确保产出存在？

[展示 图3-4] 软调用是 Superpowers 的方式——brainstorming 写"invoke writing-plans skill"，AI 读到后自己调 Skill 工具，但无参数、无返回值约定、无校验，兜底靠**人保证衔接正确**。硬调用是 patch-merge-workflow 的方式——orchestrator 写 `Skill('scene-selector', args='PROJECT_ROOT=... artifacts_root=...')`，AI 按参数调用，调用后校验 request.json 和 config_selection.json 是否存在，兜底靠**代码保证衔接正确**。

硬调用比软调用多了三层：**参数约定、上下文传递、门禁校验**。选择标准很简单：前端有人的场景，软调用够了；需要无人值守，**必须硬调用**。这不是写法偏好，是问题域决定的。

[翻页]

#### 3.5 验证闭环：不信任自汇报

[翻页]

问题：AI 说"我完成了"，你怎么知道它真的做对了？**原则：验证者不等于生成者，零信任自汇报。**

Superpowers 的做法——spec-reviewer 的 prompt 原文："CRITICAL: Do Not Trust the Report. The implementer finished suspiciously quickly. Their report may be incomplete, inaccurate, or optimistic." patch-merge-workflow 的做法——不用另一个 AI 来验证，而是用**确定性代码**来验证。merge-executor 要求 AI 调 `build_execution_item()` 写入 execution_log.json，orchestrator 读 JSON 获取真实状态。

[翻页]

但这里有个更深的问题：**AI 调 harness 函数误导性地写入错误的状态怎么办？** AI 说"apply 成功了"然后调用 `append_execution_result(result="passed")`，但实际 git 里并没有这个 commit。harness 函数本身是纯函数，你让它写 passed 它就写 passed。

解法是在 harness 函数里加**状态校验**——写入前用确定性证据来验证 AI 声称的状态。AI 声称 result=passed，检查 git log 中是否存在该 patch 的最新 commit，不存在则拒绝写入。AI 声称 result=conflict，检查 .git/rebase-apply/ 是否存在，不存在则拒绝写入。**不只约束 AI 的行为，还要约束 AI 写入状态的真实性。** 这里有一个很漂亮的设计思想——**状态校验和状态转换校验是双保险**：状态校验验证"值对不对"，状态转换校验验证"路径对不对"，两者配合才是完整的安全网。

[翻页]

#### 3.6 执行计划：动态生成与跟踪

问题：50 个 patch 的执行顺序、checkpoint 标记、依赖关系不能写死，要根据输入动态生成。当前状态是 plan 硬编码在 SKILL.md 里，6 步不会动态调整。改进方案是把 pipeline 从 SKILL.md 硬编码迁移到 scene YAML，orchestrator 读取后动态生成 plan。三个好处：新增场景等于新增 YAML 文件不用改 orchestrator；requires/produces 天然就是 artifact 门禁；pipeline 是数据不是代码后续可做成可视化配置。

跟踪机制：TodoWrite 逐项打卡。背后是 Commitment 说服原则——**先公开声明任务列表，再逐项完成，违反一致性会产生心理压力**。

[翻页]

#### 3.7 Agent 自进化：从失败中学习

问题：每次失败都是孤立事件，同样的错反复犯，经验无法积累。解法：每次失败都是规则库的养分。当前实践：conflict-handler 记录冲突内容到 conflict_report.json；build-validator 记录编译错误到 build_result.json；checkpoint 规则本身就是经验沉淀——每条规则都对应一个曾经踩过的坑。演进方向：当冲突解决知识库足够丰富时，可以让 AI 自动提炼新规则、更新决策矩阵——**让系统越用越聪明**。

高德的量化证据：三轮评估迭代，均分从 64.5 提升到 83.4，CRITICAL 漏检降为 0——**可量化的评估才能驱动持续改进**。

---

### 第 4 章 怎么落地：Skill + Harness 两层架构与 SKILL.md 写作技巧（12 分钟）

[翻页]

前三章讲了"为什么"和"做什么"，这章回答"怎么做"。

#### 4.1 划界：什么放 Skill，什么放 Harness

[翻页]

第 1 章提过原则：需要理解输出才能做判断的放 Skill，机械可重复的不涉及语义的放 Harness。但实际落地时很多操作处于灰色地带，这里给一个更实用的判断方法：[展示 图4-1] 需要看 AI 输出才能决定下一步的放 Skill；不需要看但每次执行结果完全确定的放 Harness；不确定但出错时需要语义理解来修复的放 Skill；不需要语义理解的放 Harness。

用真实代码举例。读 git am 返回码和 stderr 判断 passed/conflict/failed，放 Skill，因为需要理解输出来区分冲突类型。.git/rebase-apply/ 是否存在来区分 conflict vs hard fail，放 Skill，因为需要理解 git 的状态机制。build_execution_item() 构建 JSON 对象，放 Harness，纯数据组装每次结果完全确定。read_json() / write_json() 读写文件，放 Harness，纯 I/O。按 decision_table 判断 Ours/Theirs，放 Skill，因为需要理解冲突场景并匹配规则。checkpoint 规则计算，放 Harness——虽然涉及"判断"，但判断逻辑是确定性的，7 条规则加优先级短路，输入确定输出确定。**判断依据不是"是否涉及判断"，而是"判断是否确定性可重复"。** 这是个很容易搞混的点，值得强调。

[翻页]

两层架构全景图：[展示 图4-2] **Skill 层是"大脑"**——做判断、做决策、理解语义。**Harness 层是"手脚"**——做确定性的数据组装、文件读写、格式校验。两层通过 artifact（JSON 文件）通信，**不共享内存**。Skill 层的 AI 调用 harness 函数读写 artifact，harness 层返回结构化数据和校验结果。这就是"大脑"指挥"手脚"干活的工程实现。

[翻页]

#### 4.2 SKILL.md 的约束技术：从 Superpowers 学到的五种武器

[翻页]

Superpowers 的 SKILL.md 不是普通的指令文档——它是一套精心设计的**行为约束系统**。五种武器：

**武器 1：Iron Law——绝对规则。** 大写加绝对否定加无例外。比如 "NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST"。违反等于重来。在我们的 patch-merge-workflow 中对应："冲突后禁止 git am --abort"、"禁止自行修复编译错误"。

**武器 2：HARD-GATE——能力边界。** 用 XML 标签包裹，明确列出禁止操作和必须遵循。和 Iron Law 的区别：Iron Law 是**价值观**——"测试先行"，HARD-GATE 是**能力边界**——"你只能做这些不能做那些"。Iron Law 告诉 AI "为什么"，HARD-GATE 告诉 AI "做什么和不做什么"。

[翻页]

**武器 3：Red Flags——自检信号。** 不是规则，而是信号灯——如果输出中出现"Code before test"、"I already manually tested it"等模式，说明可能违反了规则。

**武器 4：Rationalization Table——预判借口。** Superpowers 发现 AI 会"合理化"自己的违规行为，所以预判这些借口并提前反驳。"Too simple to test"? Simple code breaks."I'll test after"? Tests passing immediately prove nothing. verification-before-completion 更是从 24 次失败记忆中提炼出 Rationalization Table——**每条反驳都对应一个真实踩过的坑**。

**武器 5：Commitment——先声明后执行。** subagent-driven-development 要求 AI 在执行前先公开声明"我正在使用 writing-plans skill"，brainstorming 要求用 TodoWrite 创建任务列表再逐项完成。背后是心理学原理：**先公开承诺再执行，违反一致性会产生心理压力。对 AI 也有效。**

我在实际使用中感受很深——AI 用 TodoWrite 列了清单之后，确实会一个一个打勾，不会随便跳步。

[翻页]

五种武器从上到下约束强度递减但覆盖面递增：Iron Law 覆盖少数核心规则，Rationalization Table 覆盖大量边缘场景。

为什么管用？有实验证据。心理学家 Cialdini 的团队用 28000 次对话做了对照实验——同样的请求，加不加说服技巧，AI 的遵从率从 33% 涨到 72%。[互动] 猜猜看这五种武器分别对应什么说服技巧？Authority——"这是命令不是建议"对应 Iron Law 大写加绝对否定。Commitment——"先列清单再逐项打勾"对应 TodoWrite 加执行前声明。Scarcity——"现在不做就来不及了"对应必须先验证才能说完成。Social Proof——"别人都踩过这个坑"对应 From 24 failure memories。Unity——"我们是一伙的"对应把用户叫"伙伴"而非"主人"。**对人类管用的说服技巧，对 AI 同样管用。**

[翻页]

但这里要强调一个重要区别——**硬约束 vs 软说服**。上面五种技巧本质是同一件事换种说法让 AI 更愿意遵守，不改功能改语气。但在无人值守场景，**硬约束才是根本**。PMW 的选择是几乎只用硬约束——HARD-GATE 加禁止/必须清单，没用软说服。原因很现实：**AI 不会因为你说"伙伴"就真的更听话。** 后续优化方向：在硬约束兜底的基础上，用软说服提高合规上限。

[翻页]

#### 4.3 SKILL.md 的 description 陷阱

Superpowers 揭示了一个关键陷阱：**description 的作用是触发，不是描述工作流。** 好的 description 写"什么时候触发"，坏的 description 总结"怎么工作"。AI 可能读完 description 就觉得自己知道怎么做了，跳过完整 SKILL.md。原则：**description 只写触发条件，不写工作流。**

#### 4.4 Skill 三层渐进式加载

[翻页]

description 陷阱背后是一套完整的**三层渐进式加载**机制：[展示 图4-3] L1 Metadata 是会话启动时加载所有 skill 的 name 加 description，每个约 100 tokens。L2 Instructions 是 Skill 被激活时加载完整 SKILL.md body，每个不到 5000 tokens。L3 Resources 是执行时按需加载 references、scripts、assets。

实测数据：8 个 Skill 全量常驻约 24000 tokens；8 个 L1 常驻加 1 个激活 L2，3480 tokens。**省了 85%。**

与上下文隔离互补：上下文隔离是**横向**——Agent 间上下文不互相污染；三层加载是**纵向**——单个 Skill 内 token 逐层递进控制。两者协同实现**上下文精确投递**。

[翻页]

但三层加载有个天敌——**Compaction**。上下文接近上限时触发压缩，精心设计的分层会被打破。Claude Code 的 compaction 是 LLM 生成结构化摘要替换消息历史，已调用的 Skill 保留前 5000 tokens，总计 25000 tokens 硬限制，超出则最老的整 Skill 被 drop。OpenCode 的 compaction 是独立 Summarizer Agent 生成摘要截断到摘要点，Skill body 随对话消息一起被摘要化，无专门保留。防御原则四条：核心指令放 SKILL.md 开头 5000 tokens 以内；持久规则放 CLAUDE.md / OpenCode.md 注入 System Prompt 不参与 compaction；Skill 拆成 subagent 调用——subagent 有独立上下文不撑大主 agent；长任务前手动 `/compact focus on ...` 带焦点的摘要更可能保留关键上下文。

[翻页]

#### 4.5 一个完整的 SKILL.md 模板

综合以上技巧，面向无人值守场景的 SKILL.md 模板结构：frontmatter 写 name 和 description；Overview 核心原则一两句话；Iron Law 如有则大写无例外；Input 写从 args 接收什么和前置 artifact；Steps 写初始化、执行、写出结果三步；HARD-GATE 写禁止操作和必须遵循；Red Flags 写自检信号；Rationalization Table 如有写借口反驳；红线写行为约束；输出摘要写汇报格式。**关键设计：Steps 中的"判断"由 AI 做，"读写"由 harness 函数做——这就是两层架构在单个 skill 内部的体现。**

---

### 第 5 章 实战：patch-merge-workflow 架构全貌（10 分钟）

[翻页]

前四章讲完了理念、原则和落地方法。这章用一个完整的真实案例把所有概念串起来。

#### 5.1 全流程图

[展示 图5-1] 这是 patch-merge-workflow 的完整流程。我带着大家走一遍：

用户输入 patch 来源、目标仓库、分支。orchestrator 作为编排者不做具体逻辑，只收集输入、创建计划、逐个调子 skill、校验 artifact、分叉调度、汇报结果。

第一步 scene-selector——解析用户请求，生成 request.json 和 config_selection.json。

第二步 workspace-manager——读 request.json，校验 git repo，创建工作分支，写 workspace.json 和 build.sh。

第三步 patch-analysis——读 request 加 workspace，用 ingest_source() 收集 patch，提取元数据加 AI 语义补充，写 merge_plan.json 含 checkpoint 标记。

[翻页]

第四步 merge-executor 逐 patch 循环——这是核心中的核心，整个系统最复杂的部分。读 workspace 加 merge_plan，执行 git am --3way。returncode 等于 0 则 passed，检查是否 checkpoint；不等于 0 且 rebase-apply 存在则 conflict，写 conflict_context.json 标记 blocked 然后 break；不等于 0 且 rebase-apply 不存在则 failed，abort 标记 failed 然后 break。checkpoint 为 true 则调用 build-validator，编译通过继续，重试耗尽则 failed 保留现场。

这里有一个非常精妙的设计：**conflict 和 hard fail 的区分**。git am 返回非零不代表一定是冲突——可能是 hard fail。怎么区分？看 .git/rebase-apply/ 目录是否存在。存在说明 git 进入了 rebase-apply 状态，那就是冲突；不存在说明 git 已经自动清理了，那是 hard fail。这个判断需要 AI 语义理解——因为你要理解 git 的状态机制才能做这个区分，所以放在 Skill 层。

orchestrator 读 status：blocked 就调 conflict-handler；还有 patch 就继续 merge-executor；全部完成或 failed/blocked 就进入 code-reviewer 和 report-generator。

[翻页]

第五步 conflict-handler 仅 blocked 时——读 conflict_context 加 decision_table，执行 git am --abort 然后 git am --reject。为什么先 abort 再 reject？因为 git am --3way 失败后 git 处于 rebase-apply 中间状态，必须先 abort 清理，再用 --reject 模式重新 apply，这样才会生成 .rej 文件。找到 .rej 文件后，AI 逐 hunk 消解——Read .rej 加目标文件，按决策表选 Ours/Theirs，Edit 修改后 rm .rej，然后 git add -A 加 git am --continue。重试不超过 10 次；超过则写 handoff_ticket.json 交给人工。这里又体现了 Harness 的核心思想——**降级链**：git am --3way 是首选，失败了走 --reject 加人工消解，再失败就 handoff 交给人。

第六步 code-reviewer 加第七步 report-generator——code-reviewer 审查合入质量，report-generator 撰写报告，产出 output_report.json 和 summary.md。

[翻页]

#### 5.2 Artifact 数据流

[展示 图5-2] Artifact 的流转非常清晰：request.json → workspace.json → merge_plan.json → execution_log.json → 如果 blocked 则 conflict_context.json → resolution_result.json → 回到 execution_log.json → review_report.json → output_report.json 加 summary.md。**每个 artifact 写在磁盘上，不通过内存传递，不信任口头汇报。** Artifact 是磁盘契约，不依赖平台，不依赖调用方式——不管你怎么派子 agent，只要产出 artifact，衔接就不会断。

[翻页]

#### 5.3 两条典型路径

**Happy Path**（clean apply）：request → workspace → patch analysis → merge plan → git am success 乘 N → checkpoint build passed → execution_log: completed → code-review → report: completed。

**Blocked Path**（遇到冲突）：前 M 个 git am success → 第 M+1 个 conflict → execution_log: blocked → conflict-handler: 逐 .rej 消解 → resolved 继续合入剩余 patch → build；unresolved → handoff → report: blocked。

[翻页]

#### 5.4 七个 Skill 的职责分工

快速看一眼分工：scene-selector 解析请求写 request.json，workspace-manager 校验仓库写 workspace.json，patch-analysis 收集 patch 写 merge_plan.json，merge-executor 逐 patch 执行 git am 写 execution_log.json，conflict-handler 按决策矩阵消解冲突写 resolution_result.json，build-validator 编译修再编译循环写 build_result.json，code-reviewer 审查合入质量写 review_report.json，report-generator 撰写最终报告写 output_report.json 加 summary.md。

注意每个 Skill 的 Harness 函数使用模式——**读和写一定是 harness 的确定性操作，但判断写什么是 AI 的语义理解**。Skill 的核心价值在于"做什么"——这些都需要 AI 理解上下文后做决策。

---

### 第 6 章 踩坑与经验（5 分钟）

[翻页]

#### 6.1 端到端自动化的工程量被严重低估

我们最初以为写好 SKILL.md 就能跑起来。实际：状态管理远比想象复杂；超时和资源——5 个 skill 串联加门禁加重试完整任务可能十几分钟；环境一致性——本地编译正常云端构建失败；可追溯日志——失败时必须知道在哪里什么时间为什么，口头汇报不够必须有 artifact。教训：**端到端自动化等于软件工程**，不是写几个 SKILL.md 就完事了。

#### 6.2 SKILL.md 写了不等于 AI 会遵守

真实案例：merge-executor 红线写了"冲突后禁止 git am --abort"，AI 在上下文膨胀时仍然执行了 abort；build-validator 红线写了"禁止改 Makefile/Kconfig"，AI 修编译错误时改了 Kconfig；orchestrator 红线写了"禁止一次性调用 merge-executor 处理所有 patch"，AI 偷懒传了所有 seq。**解法不是写更强的红线，而是加代码级兜底。**

[翻页]

#### 6.3 小步快跑

不要追求一步到位的全自动化。我们的迭代节奏：v0.1 单个 patch 的 happy path 能跑通 → v0.2 多个 patch 的循环能跑通 → v0.3 冲突路径能跑通 → v0.4 checkpoint 编译能跑通 → v0.5 端到端全流程。**核心原则：每个版本保证最起码的通路，然后在当前版本上迭代。上一轮验证过的部分是可信的，新问题一定出在新加的部分。**

#### 6.4 完全无人干预不是 0/1 的状态

真正有价值的是把人工干预的频率降到足够低：v0.1 每步都确认 → v0.3 每 5-10 步确认一次 → v0.5 每次任务确认一次 → 目标仅冲突场景 6/10 时介入。**不需要追求 100% 无人值守。从"每步确认"到"仅异常时介入"，每降低一个量级的干预频率，就释放一个量级的人力。**

[翻页]

#### 6.5 模型很强但仍会出问题

长链路稳定性脆弱：假设 8 个关键节点每个 90% 成功率，端到端一次通过率等于 0.9 的 8 次方约等于 43%。当前靠 build-validator 的修复循环、conflict-handler 的 10 次重试、orchestrator 的 resume 断点续跑、execution_log 的完整记录来兜底。Harness 的设计本身就是增量式的：**先让它跑起来，再让它跑得稳，最后让它跑得聪明。**

#### 6.6 约束不只是规则——环境工具化

高德的实践揭示了一个重要洞见：**开发环境本身就是约束。** AI 约 10 次尝试只能成功 1-2 次；封装好 API 调用方式为 Skill 后基本都能成功。关键不是写了更强的红线，而是**把调用方式封装成 Skill，限制 AI 只能在特定场景下使用特定组件**。6.2 说红线写了不等于 AI 会遵守——解法不只是更强的红线或代码兜底，还可以是**从环境层面消除犯错的可能**。HARD-GATE 是"你不该做"，环境工具化是"你做不了"。

---

### 第 7 章 Subagent 架构（4 分钟）

[翻页]

前面讲了 Harness 的原理和落地方法，但有一个关键问题没回答：**子 agent 怎么派出去？怎么收回来？**

核心原则——Superpowers 的 subagent-driven-development SKILL.md 开篇就写了：**"They should never inherit your session's context or history — you construct exactly what they need."** 翻译过来就是：子 agent 永远不继承父 agent 的对话历史，你构造它需要的东西就行了。和第 3 章的三条铁律完全一致。

两个平台都用各自的子 agent 调度工具派发——Claude Code 是 Agent 工具，OpenCode 是 Task 工具。但"怎么构造子 agent 的内容"不同：Claude Code 是父 agent 提前做好所有准备，把完整指令文本直接粘贴到 Agent(prompt=...) 中，子 agent 只看 prompt 不读文件不调 Skill——**父 agent 准备好一切**。OpenCode 是子 agent 通过 Task 被派发后，自己用 Skill 工具加载 SKILL.md 按指令执行自己读 artifact——**子 agent 自己按需加载**。两种方式都能实现上下文隔离，只是信息传递的主动权不同。

[翻页]

七个关键维度的对比中，最核心的差异：**Claude Code 提供了更完整的子 agent 工程化能力**——从 agent 定义到会话管理到 Skill 声明式子 agent 化。**OpenCode 更轻量**——Task 工具即开即用，但缺少工作区隔离和会话复用机制。

当前 patch-merge-workflow 的一个重要问题：orchestrator 调用的是 Skill 工具而非 Task 工具，效果是 SKILL.md 内容被加载到主 agent 上下文中内联执行，**并没有创建真正的子 agent**。这意味着所有 patch 共享主 agent 上下文，违背了上下文隔离的设计初衷。改造方向：从 Skill 内联执行改为 Task 子 agent 调用，参数从 args 字符串改为 prompt 文本，**artifact 机制完全不变**——这正是 Artifact 作为磁盘契约的工程价值。

---

### 第 8 章 YAML 在 AI 工程中的角色（3 分钟）

[翻页]

第 4 章讲了 Skill 加 Harness 两层架构，但有些规则既不需要 AI 语义理解也不需要 Python 计算，只是机械可判定的配置——放哪里？

一条规则出来，先问一个问题：**谁消费这条规则？** [展示 图8-1] AI 读了才能做决策的放 SKILL.md，比如冲突场景 6"上游重构 vs 下游特有补丁 → 人工裁定"，AI 需要理解什么叫"上游""下游""特有"。运行时解析器机械判定的放 YAML，比如 checkpoint Rule 2"被 3+ 后续 patch 引用 → 必检"，运行时数引用数就行。需要计算加 IO 加算法的放 Python harness，比如反向依赖检测 detect_reverse_dependencies()。一句话判断标准：**规则是否需要 AI 语义理解？需要就留 Markdown，机械可判定就迁 YAML，需要计算就留 Python。**

Claude Code 的 SKILL.md 结构完美体现了这个原则——frontmatter 给运行时解析器消费，body 给 AI 模型消费。**YAML frontmatter 不是"给 AI 看的规则"，而是"给运行时看的配置"。**

[翻页]

几个迁移机会：checkpoint 规则可以迁 risk_rules.yaml——7 条规则全是纯机械判定，硬编码在 Python 里改一次改代码，YAML 里改一次改配置。decision_table.md 可以一分为二——机械判定规则迁 YAML，语义判断留 Markdown。状态转换定义可以迁 state_machines YAML——当前 AI 可以从任何状态跳到任何状态，YAML 声明合法转换加 Python 代码读取校验。

几个常见的坑：把 AI 指令放 YAML，AI 理解效果远差于 Markdown。用 YAML 替代 Python 计算，图算法不能写进 YAML。定义了 YAML 状态机就以为有了状态机引擎——YAML 是声明 Python 是执行两者缺一不可。枚举三处重复定义——functional_category 在 SKILL.md、schema JSON、Python 中各写一遍，改一处忘其他。

---

### 第 9 章 模式语言（3 分钟）

[翻页]

最后快速过两个层面的模式语言。

Google ADK 定义了 7 种多 Agent 工作流模式，由 3 个工作流原语加 3 个交互机制组合而成。3 个原语：SequentialAgent 顺序执行、ParallelAgent 并发执行、LoopAgent 循环执行。3 个机制：Session State 通过 output_key 传递状态、transfer_to_agent 由 LLM 自动路由、AgentTool 显式调用。加 1 个扩展点——Human-in-the-Loop。组合出 7 种模式：Coordinator & Dispatcher 中心路由、Sequential Pipeline 顺序串联、Parallel Fan-out 并行聚合、Hierarchical Decomposition 多层分解、Generate and Review 生成加审查、Iterative Refinement 循环迭代、Human-in-the-Loop 人工决策。核心洞察：7 种模式由 3 个原语加 3 个机制加 1 个扩展点组合构成，可嵌套。

[翻页]

这是多 Agent 间的编排，落到单个 Skill 的内部设计，有五种设计模式：Pipeline 固定顺序多步流程，Reviewer 独立评估质量不改代码，Generator 读模板加上下文生成产出，Inversion 先收集需求约束决策再行动，Tool Wrapper 封装领域知识为硬约束。ADK 管"谁来做、按什么顺序"，Skill 管"单个怎么做"。两者不在同一抽象层但有对应关系：Sequential Pipeline 对应 Pipeline，Generate and Review 对应 Generator 加 Reviewer，Human-in-the-Loop 对应 Inversion。

四种常见组合：Pipeline 加 Reviewer 是管道末端加质量门禁——PMW 的 merge-executor 乘 N 后接 code-reviewer。Generator 加 Inversion 是先收集需求再填充模板——Superpowers 的 brainstorming 后接 writing-plans。Inversion 加 Pipeline 是先需求澄清再执行流水线——PMW 的 scene-selector 收集用户输入后接 5 步 Pipeline。Tool Wrapper 加 Pipeline 是管道中每步封装领域知识——PMW 的 workspace-manager、merge-executor、conflict-handler、build-validator 都是 Tool Wrapper 被 Pipeline 编排。

注意——**纯 Skill 层无法独立落地**，需要 Harness 层提供执行环境、共享状态和确定性工具。模式是设计语言，Harness 是运行时。

---

### 总结（2 分钟）

[翻页]

今天的内容可以用几句话收束：

**Harness 的本质是什么？** 是模型外面那一层工程化的骨架。模型能力是概率的，Harness 让概率系统变得可用、可控、可演化。

**核心框架 ETCSLE 三层防线**：第一层让任务跑完——Execution Loop、Context Manager、State Store；第二层让行为合规——Tool Registry、Lifecycle Hooks；第三层让系统越用越好——Evaluation。

**落地关键**：Skill 加 Harness 两层架构——AI 做决策，代码做苦力；SKILL.md 五种武器——Iron Law、HARD-GATE、Red Flags、Rationalization Table、Commitment；三层渐进式加载——L1 Metadata、L2 Instructions、L3 Resources。

**选择标准**：问题域决定架构选择。人在回路用软调用就够了，无人值守必须硬调用。这不是写法偏好，是工程现实。

最后一句话：**先让它跑起来，再让它跑得稳，最后让它跑得聪明。** 这就是 Harness 的迭代哲学。
