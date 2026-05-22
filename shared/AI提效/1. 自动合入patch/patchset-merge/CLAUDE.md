# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Claude Code skill 集合，以纯指令驱动（SKILL.md + references/）方式工作，不依赖 Python 代码。当前包含一个 skill：

- **merge-patchset** — 智能 patchset 合入（源文件 `SKILL.md`），内置多场景检测：干净合入、先 revert 再合入、上游依赖自动发现、路径适配。使用 LSP（clangd）增强代码导航能力。

辅助文件 `karpathy-guidelines-SKILL.md` 是行为准则的本地副本，install.sh 会优先从 GitHub 远程拉取最新版，拉取失败时回退到本地文件。

## 核心架构：四相工作流 + LSP 前置

SKILL.md 定义了四个相位（含 LSP 环境准备）：

1. **LSP 环境准备** — 检查/安装 clangd，生成 compile_commands.json，为后续分析提供符号级导航
2. **相位 0 — 前置检测（3 个并行 agent）**：
   - Agent A：冲突预检（扫描目标仓库，判断每个 patch 的冲突风险，LSP 优先）
   - Agent B：依赖检测（在 `--upstream` 源仓库中查找缺失的依赖 commit，强/弱分级）
   - Agent C：代码相似度检测与 Revert 定位（深度代码相似度分析 + revert 依赖链安全评估）
3. **相位 1 — 场景判定**：汇总 agent 结果，判定场景（A/B/C/E），向用户展示并确认
4. **相位 2 — 前置操作 + Merge**：按场景执行 revert / 拉依赖 / 路径适配，然后逐个合入
5. **相位 3 — 核心 Merge**：8 步策略链 + fix-compile loop + per-patch 分析文档 + 汇总报告

场景表：
| 场景 | 触发条件 | 前置操作 |
|------|---------|---------|
| A — 干净合入 | 所有 patch 冲突风险 none/low | 无 |
| B — 先 Revert 再合入 | Agent A 标记 high + Agent C 确认可 revert（含安全评估） | 逆序 revert 旧 commit |
| C — 补依赖再合入 | Agent B 找到强功能依赖 commit | 从上游拉取强依赖；弱依赖创建 stub |
| E — 路径适配 | patch 文件路径在目标仓库不存在 | 搜索实际路径并映射 |

场景可以组合（如 B + C：先 revert 旧代码，拉取强依赖，再 merge）。

**Agent C 的 Revert 判定分级**：
- ✅ 可 revert：相似度 ≥ 70% + 后续无 commit 依赖，独立 revert 安全
- ⚠ 链式 revert：相似度 ≥ 70% + 后续有依赖但链 ≤3 层，需一并 revert
- 🔴 不可 revert：依赖链 >3 层，退回走冲突解决
- — 走冲突解决：相似度 < 70%，不列入 revert 清单

## Skill 文件结构（渐进式披露）

1. **SKILL.md** (~740 行) — 核心工作流、agent 定义、策略链条、约束、反模式
2. **references/output-templates.md** — 各相位输出模板、per-patch 分析文档模板、汇总报告模板
3. **references/diagnostic-guide.md** — 冲突类型分类、编译错误分类与修复策略

## `@preamble-start` / `@preamble-end` 标记

这两个 HTML 注释标记包裹前置技能加载段，install.sh 用 `sed` 删除此段来生成降级版本。修改时 preamble 内只放平台检测和 skill 加载相关指令，preamble 外是 skill 核心逻辑。

## 部署

```bash
./install.sh
```

脚本将 SKILL.md 和 references/ 复制到 `~/.claude/skills/merge-patchset/`（Claude Code）和 `~/.config/opencode/skills/merge-patchset/`（OpenCode）。检查/安装 superpowers 插件，尝试从远程拉取最新的 karpathy-guidelines。

## 添加新 skill

1. 新建 `<skill-name>-SKILL.md`，参考现有 SKILL.md 的结构
2. 在 `install.sh` 的 claude 和 opencode 分支中添加 `deploy_skill` 调用
3. 新 skill 也必须有前置技能加载段（`@preamble-start` / `@preamble-end` 包裹）

## 允许的工具权限

SKILL.md 的 `allowed-tools` 字段应自包含 — 覆盖该 skill 需要的所有操作。当前覆盖：`git`、`make`、`bash`、`grep`、`sed`、`cat`、`ls`、`find`、`rm`、`mkdir`、`echo`、`Write`、`Agent`、`LSP`。
