# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Claude Code skill 集合，以纯指令驱动（SKILL.md）方式工作，不依赖 Python 代码。当前包含两个 skill：

- **merge-patchset** — 从 lore.kernel.org 下载 patchset 并逐个合入
- **revert-patchset** — 按逆序逐个 revert commit

## 部署

```bash
./install.sh
```

脚本将 SKILL.md 文件复制到 `~/.claude/skills/<skill-name>/`，检查/安装 b4 和 superpowers 插件，尝试从远程拉取最新的 karpathy-guidelines。

## Skill 架构

每个 skill 是单个 SKILL.md 文件，包含：

1. **YAML frontmatter** — `name`、`description`、`allowed-tools`
2. **前置技能加载** — 验证并加载 `superpowers:using-superpowers` + `karpathy-guidelines`
3. **核心约束** — 逐条操作、遇错即停、保留分支、中文输出
4. **工作流** — 分步骤的 bash 命令和策略表
5. **交互模式** — 需要向用户展示并等待决策的场景
6. **反模式** — 禁止的操作

AI 读到 SKILL.md 后直接用 bash 执行工作流，所有交互在对话中完成，不通过 Python CLI 或 `input()`。

## merge 与 revert 同步规则

两个 skill 流程高度相似，共享以下段落的模式：前置技能加载、核心约束、冲突解决策略、编译验证、交互模式、反模式、allowed-tools。

**修改任一个 skill 时，必须判断改动是否适用于另一个。** 合适的必须同步过去，避免两份文件逐渐分化出不一致的行为。判断标准：如果改动涉及上述共享段落，且不涉及各自特有的操作（`git am` vs `git revert`），就应该同步。

## 添加新 skill

1. 新建 `<skill-name>-SKILL.md`，参考现有 SKILL.md 的结构
2. 在 `install.sh` 中添加部署步骤
3. 新 skill 也必须有前置技能加载段

## 允许的工具权限

每个 SKILL.md 的 `allowed-tools` 字段应自包含 — 覆盖该 skill 需要的所有 bash 操作，不依赖用户全局 `settings.json`。当前覆盖：`b4`、`git`、`make`、`bash`、`grep`、`sed`、`cat`、`ls`、`find`、`rm`、`mkdir`、`echo`、`Write`。
