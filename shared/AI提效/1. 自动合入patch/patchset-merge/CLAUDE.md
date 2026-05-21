# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Claude Code skill 集合，以纯指令驱动（SKILL.md）方式工作，不依赖 Python 代码。当前包含一个 skill：

- **merge-patchset** — 智能 patchset 合入（源文件 `SKILL.md`），内置多场景检测：干净合入、先 revert 再合入、上游依赖自动发现、路径适配、部分跳过

辅助文件 `karpathy-guidelines-SKILL.md` 是行为准则的本地副本，install.sh 会优先从 GitHub 远程拉取最新版，拉取失败时回退到本地文件。

## 核心架构：三相工作流

SKILL.md 定义了三个相位：

1. **相位 0 — 前置检测（并行 agent）**：同时启动 3 个只读检测 agent
   - Agent A：冲突预检（扫描目标仓库，判断每个 patch 的冲突风险）
   - Agent B：依赖检测（在 `--upstream` 源仓库中查找缺失的依赖 commit）
   - Agent C：已合入检测（检查哪些 patch 的等效修改已存在于目标仓库）
2. **相位 1 — 场景判定**：汇总 agent 结果，判定场景（A~E），向用户展示并确认
3. **相位 2 — 前置操作 + Merge**：按场景执行 revert / 拉依赖 / 路径适配，然后逐个合入

场景表：
| 场景 | 触发条件 | 前置操作 |
|------|---------|---------|
| A — 干净合入 | 冲突风险 none/low | 无 |
| B — 先 Revert 再合入 | 高冲突风险，有对应旧 commit | 逆序 revert 旧 commit |
| C — 补依赖再合入 | 上游有依赖 commit 未在目标仓库 | 从上游 format-patch 拉取 |
| D — 部分跳过 | 部分 patch 已合入 | 跳过已合入的 |
| E — 路径适配 | patch 文件路径在目标仓库不存在 | 搜索实际路径并映射 |

场景可以组合（如 B+D：先 revert 旧代码，跳过已合入的，再 merge 剩余的）。

## `@preamble-start` / `@preamble-end` 标记

这两个 HTML 注释标记包裹前置技能加载段，install.sh 用 `sed` 删除此段来生成降级版本。修改时 preamble 内只放平台检测和 skill 加载相关指令，preamble 外是 skill 核心逻辑。

## 部署

```bash
./install.sh
```

脚本将 SKILL.md 复制到 `~/.claude/skills/merge-patchset/`，检查/安装 superpowers 插件，尝试从远程拉取最新的 karpathy-guidelines。

## Skill 文件结构

1. **YAML frontmatter** — `name`、`description`、`allowed-tools`、`compatibility`
2. **`<!-- @preamble-start -->` 到 `<!-- @preamble-end -->`** — 前置技能加载段，Tier 2 生成时被剥离
3. **核心约束** — 逐条操作、遇错即停、保留分支、中文输出、逆序 revert
4. **工作流** — 三相结构：前置检测（并行 Agent A/B/C）→ 场景判定 → 按场景执行 + merge
5. **交互模式** — 需要向用户展示并等待决策的场景
6. **反模式** — 禁止的操作

AI 读到 SKILL.md 后直接用 bash 执行工作流，Phase 0 使用 Agent 工具并行启动检测 agent，所有交互在对话中完成。

## 添加新 skill

1. 新建 `<skill-name>-SKILL.md`，参考现有 SKILL.md 的结构
2. 在 `install.sh` 的 claude 和 opencode 分支中添加 `deploy_skill` 调用
3. 新 skill 也必须有前置技能加载段（`@preamble-start` / `@preamble-end` 包裹）

## 允许的工具权限

SKILL.md 的 `allowed-tools` 字段应自包含 — 覆盖该 skill 需要的所有操作。当前覆盖：`git`、`make`、`bash`、`grep`、`sed`、`cat`、`ls`、`find`、`rm`、`mkdir`、`echo`、`Write`、`Agent`。
