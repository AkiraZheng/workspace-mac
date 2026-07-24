# Harness 分享文档补充任务清单

## 已完成

### ✅ 第1项：Subagent 平台适配 → 已写入第7章
- 位置：harness_sharing_doc.md 第7章
- 内容：Claude Code vs OpenCode 对比、Superpowers 三阶段派发、Task vs Skill 传参差异、artifact 机制不变、改造方向

---

## 待完成

### 第2项：YAML 在 AI 工程中的角色
- **插入位置**：第7章之后，作为第8章
- **核心内容**：
  - 三种规则载体选择标准：SKILL.md（语义理解）vs YAML（机械判定）vs Python（必须代码执行），画对比图
  - 哪些规则应从 SKILL.md 迁移到 YAML：checkpoint规则→risk_rules.yaml，冲突决策→conflict_rules.yaml
  - 状态机流程定义：proposal-to-build.yaml, rollback.yaml，参考高德 condition+outputs+on_failure
  - 这与第3章3.6节"pipeline迁移到scene YAML"是自然延伸
- **需要验证的源码**：
  - /mnt/shared/patch-merge-workflow/ 下的 config/ 目录，看当前 YAML 用了什么
  - build_checkpoint.py 里的规则硬编码
  - decision_table.md 的规则
  - scenes/ 目录下的 YAML
- **关键问题**：哪些规则"需要AI语义理解"就留markdown，"机械可判定"就迁YAML

### 第3项：五种 Skill 设计模式（Google ADK）
- **插入位置**：第4章4.2节之后或作为新章节
- **核心内容**：
  - 五种模式：Tool Wrapper / Generator / Reviewer / Inversion / Pipeline
  - 每种模式的核心逻辑、适用场景、典型案例
  - 模式组合关系：Pipeline+Reviewer, Generator+Inversion, Inversion+Pipeline
  - patch-merge-workflow 用的是 Pipeline 模式
- **需要验证的源码**：
  - Google ADK 的五种模式定义（training_plan中引用了 x.com/GoogleCloudTech/status/2033953579824758855）
  - Superpowers 中各 skill 分别对应哪种模式
  - patch-merge-workflow 的7个 skill 分别对应哪种模式
- **关键描述**：这五种模式是 Google 总结的 Skill 设计方法论，帮读者设计自己的 skill 时知道有哪些模式可选

### 第4项：Skill 三层渐进式加载
- **插入位置**：第4章4.1节或4.4节附近
- **核心内容**：
  - L1 目录层（name+description, ~50-100 tokens）→ L2 指令层（完整SKILL.md, <5000 tokens）→ L3 资源层（scripts/references/templates, 按需）
  - 这是上下文管理（C要素）在 Skill 系统层面的具体实现
  - 与第3章3.1上下文隔离互补：3.1讲的是agent间隔离，这里讲的是单个skill内的token控制
- **需要验证的源码**：
  - OpenCode/Claude Code 实际怎么加载skill的（L1在会话启动时、L2在skill被激活时、L3按需）
  - superpowers.js 的 config hook 和 messages.transform hook
  - patch-merge-workflow deploy.sh 的部署方式
- **关键约束**：patch 必须串行合入，这是铁律——patch 间有依赖关系，不允许并发

---

## 文档审计修正记录（2025-07-24）

### 已修正的错误

1. **7.2 对比表**：
   - ❌ 旧：Claude Code 用 Task 工具 → ✅ 新：Claude Code 用 Agent 工具（v2.1.63+，Task 是别名）
   - ❌ 旧：OpenCode 不支持会话复用 → ✅ 新：OpenCode 支持 task_id 复用继续子 agent 自身会话（但不继承父 agent 上下文）
   - ❌ 旧：6维度 → ✅ 新：7维度，新增 isolation:worktree 和 context:fork 对比
   - 新增说明：Superpowers 源码用的是旧接口 Task，新项目应使用 Agent

2. **7.5 Git Worktree 隔离**：
   - ❌ 旧："YAML 声明式的 worktree 隔离是未来的改造方向，目前尚未实现"
   - ✅ 新：Claude Code 的 isolation:worktree 是 agent frontmatter 标准字段（v2.1.203+），已实现；OpenCode 无内置支持

3. **7.6 改造方向**：
   - 删除了"第三步并发合入"（patch 必须串行，是铁律）
   - 改造从三步变两步

### 关键事实来源

- Claude Code 官方文档：https://docs.anthropic.com/en/docs/claude-code/sub-agents 和 skills 页面
- OpenCode：GitHub README + 当前实际 Task 工具能力
- Superpowers 源码：本地文件 /root/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/

### 用户提供表格的验证结论

| 表格中的说法 | 验证结果 |
|---|---|
| Claude Code isolation: worktree | ✅ 真实，v2.1.203+ |
| Claude Code context: fork | ✅ 真实，SKILL.md frontmatter 字段 |
| OpenCode task_id 复用 | ✅ 支持（Task 工具的 task_id 参数），但只继续子 agent 自身会话，不继承父 agent 上下文 |
| btw-opencode 插件 | ❌ 查无此物 |
| opencode-mission-control / parallel-code | ❌ 查无此物 |

### 第5项：高德自主增长系统的更多实践细节
- **插入位置**：分散插入各章节，作为补充案例
- **核心内容**（三块）：
  - 三层快速失败评审流程：代码质量→静态质量→动态运行，实战数据：评审耗时从4分钟降到1秒
  - Benchmark 评估闭环：三轮迭代 64.5→67.5→83.4
  - 环境工具化本身就是约束：接入skill前成功率10-20%，接入后基本都能成功
- **需要验证的源码**：
  - 高德文章：developer.aliyun.com/article/1739352
  - 这些数据来自 training_plan 的引用，需要确认原始出处
- **关键描述**：
  - 三层评审 → 插入第3章3.2事前拦截，作为"小步验证"的工业级案例
  - Benchmark闭环 → 插入第3章3.7 Agent自进化，作为"可量化评估"的实践
  - 环境工具化 → 插入第6章踩坑经验，作为"约束不只是规则"的证据

### 第6项：说服原则的完整版
- **插入位置**：第4章4.2节"五种武器"之后，作为补充
- **核心内容**：
  - Authority：YOU MUST / Never，最有效，合规率翻倍
  - Commitment：先声明任务列表再逐项完成，制造一致性压力（sharing_doc已提）
  - Scarcity：IMMEDIATELY after X，制造紧迫感
  - Social Proof：Every time / X without Y = failure，建立规范
  - Unity：your human partner / we，共同身份
  - 来源：N=28,000对话实验
- **需要验证的源码**：
  - Superpowers 的 SKILL.md 中这五种原则的实际使用
  - TDD skill 中的 Authority（NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST）
  - subagent-driven-development 中的 Commitment（I'm using the writing-plans skill）
  - verification-before-completion 中的 Social Proof
- **关键描述**：sharing_doc第4.2节只提了Commitment，其他四种没展开。这五种原则是让SKILL.md的文本约束更有效的心理学依据

### 第7项：Skill-Creator 的 A/B 测试方法
- **插入位置**：第3章3.7 Agent自进化之后，作为"验证skill是否有效"的实操方法
- **核心内容**：
  - 并行启动 with_skill / without_skill 两组子 Agent
  - Grader 评分（自批评机制：对薄弱断言给通过比失败更糟）
  - Comparator 盲比较（不知道哪个输出来自哪个 Skill）
  - Analyzer 事后分析（揭盲后分析 WHY）
- **需要验证的源码**：
  - Google ADK 或 Superpowers 中 Skill-Creator 的实现
  - training_plan 引用了 skillsbench.ai 作为评测基准
- **关键描述**：这是第3.7节"Agent自进化"的实操方法——不只记录+沉淀，还要验证skill是否真的有效

---

## 全局注意事项
1. 每写完一项，停下来等用户确认后才能继续下一项
2. 用户可能要求删除已写入的内容，所以每项尽量独立成章节，方便整块删除
3. 参考文档只是草稿，必须从源码验证后才能落笔
4. 语言精简、多图、面向presentation
