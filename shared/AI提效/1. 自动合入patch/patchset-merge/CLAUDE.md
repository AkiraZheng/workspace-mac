# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Claude Code skill 集合，以纯指令驱动（SKILL.md）方式工作，不依赖 Python 代码。当前包含两个 skill：

- **merge-patchset** — 从用户指定的 patch 文件夹逐个合入（源文件 `SKILL.md`）
- **revert-patchset** — 按逆序逐个 revert commit（源文件 `revert-patchset-SKILL.md`）

辅助文件 `karpathy-guidelines-SKILL.md` 是行为准则的本地副本，install.sh 会优先从 GitHub 远程拉取最新版，拉取失败时回退到本地文件。

## 多平台架构（Tier 1 / Tier 2）

install.sh 生成两种版本：

| 层级 | 平台 | 方式 | 特点 |
|------|------|------|------|
| Tier 1（原生） | Claude Code, OpenCode | 直接复制 SKILL.md | 保留 superpowers + karpathy-guidelines 完整引用，skill 间可互相调用 |
| Tier 2（降级） | Gemini CLI, Copilot, Cursor, 通用 | 内联 karpathy-guidelines + 剥离 preamble | 自包含单文件，无外部 skill 依赖 |

**降级版本的生成逻辑在 install.sh 的 `generate_degraded()` 函数中**：用 `awk` 提取 karpathy-guidelines 正文（跳过 YAML frontmatter），用 `sed` 删除 `<!-- @preamble-start -->` 到 `<!-- @preamble-end -->` 之间的前置技能加载段，其余内容原样拼接。

这意味着：
- **`@preamble-start` / `@preamble-end` 之间的内容**仅适用于原生平台，修改时只放平台检测和 skill 加载相关指令
- **preamble 之外的内容**在所有平台版本中都会出现，是 skill 的核心逻辑

## 部署

```bash
./install.sh
```

脚本将 SKILL.md 文件复制到 `~/.claude/skills/<skill-name>/`，检查/安装 superpowers 插件，尝试从远程拉取最新的 karpathy-guidelines。

## Skill 文件结构

每个 skill 是单个 .md 文件，包含：

1. **YAML frontmatter** — `name`、`description`、`allowed-tools`、`compatibility`（值为 `claude-code, opencode` 表示原生平台）
2. **`<!-- @preamble-start -->` 到 `<!-- @preamble-end -->`** — 前置技能加载段，Tier 2 生成时被剥离
3. **核心约束** — 逐条操作、遇错即停、保留分支、中文输出
4. **工作流** — 分步骤的 bash 命令和策略表
5. **交互模式** — 需要向用户展示并等待决策的场景
6. **反模式** — 禁止的操作

**文件命名约定**：merge-patchset 的源文件直接命名为 `SKILL.md`（cli 端 user-invocable skills 列表中排在靠前位置），其他 skill 命名为 `<skill-name>-SKILL.md`。部署到目标目录时统一重命名为 `SKILL.md`。

AI 读到 SKILL.md 后直接用 bash 执行工作流，所有交互在对话中完成，不通过 Python CLI 或 `input()`。

## merge 与 revert 同步规则

两个 skill 流程高度相似，共享以下段落的模式：前置技能加载、核心约束、冲突解决策略、编译验证、交互模式、反模式、allowed-tools。

**修改任一个 skill 时，必须判断改动是否适用于另一个。** 合适的必须同步过去，避免两份文件逐渐分化出不一致的行为。判断标准：如果改动涉及上述共享段落，且不涉及各自特有的操作（`git am` vs `git revert`），就应该同步。

## 添加新 skill

1. 新建 `<skill-name>-SKILL.md`，参考现有 SKILL.md 的结构（YAML frontmatter 含 `compatibility` 字段、preamble 标记、核心约束/工作流/交互模式/反模式段落）
2. 在 `install.sh` 中添加：
   - 平台部署（`deploy_skill` 用于 Claude Code / OpenCode）
   - Tier 2 降级生成（`generate_degraded` 调用，已自动覆盖所有平台）
3. 新 skill 也必须有前置技能加载段（`@preamble-start` / `@preamble-end` 包裹）
4. 根据需要同步更新 CLAUDE.md 中的同步规则列表

## 允许的工具权限

每个 SKILL.md 的 `allowed-tools` 字段应自包含 — 覆盖该 skill 需要的所有 bash 操作，不依赖用户全局 `settings.json`。当前覆盖：`git`、`make`、`bash`、`grep`、`sed`、`cat`、`ls`、`find`、`rm`、`mkdir`、`echo`、`Write`。
