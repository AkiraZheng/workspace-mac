# AGENTS.md — patchset-merge skill workspace

## 仓库角色

本仓库是 **merge-patchset skill 的开发和配置工作区**，并非 skill 的运行目录。实际的 skill 部署在 `/root/.claude/skills/merge-patchset/` 和 `/root/.agents/skills/merge-patchset/`（两者通过 symlink 关联）。修改 skill 文件后需同步到部署目录。

## 目标内核仓库

操作始终在**独立分支**上进行，不在主干分支直接操作。目标仓库和分支由用户在运行时通过环境变量配置：

```
KERNEL_REPO_PATH   # 内核仓库绝对路径
KERNEL_BRANCH      # 操作分支名
KERNEL_ARCH        # 目标架构（如 arm64）
BUILD_CMD          # 编译命令（如 make ARCH=arm64 Image）
```

skill 启动时会向用户确认这些值，不可硬编码。

## 关键工具链

| 工具 | 版本/路径 | 用途 |
|------|----------|------|
| `b4` | 0.15.2 (`/usr/local/bin/b4`) | 从 lore.kernel.org 下载 patchset |
| `python3` | `/usr/bin/python3` | skill 脚本编写 |
| `claude` | 2.1.123 (`/usr/local/bin/claude`) | Claude Code CLI |
| `opencode` | 1.15.7 (`/usr/local/bin/opencode`) | OpenCode CLI |

b4 下载 patchset 命令：
```bash
b4 am <message-id> -o /tmp/patches/
# 若需要代理，先检查本地代理配置
```

## 硬性约束（必须遵守）

以下规则来自 `通用技能.md` 和用户需求，是刚性约束，不可跳过：

1. **逐个合入 + 逐个 commit**：N 个 patch 就产生 N 个 commit，不允许批量合入
2. **仅在有问题时交互**：正常合入自动流转；冲突超限/循环依赖/重复 patch 时暂停等用户决策
3. **每 1 个 commit 完成后调用 code-review-expert skill 做 review**
4. **revert 也逐个 commit**：逆序 revert（最新→最旧），每 revert 一个就 commit 一个
5. **每合入一个 patch 必须编译验证**，编译失败需最小量修改直至通过；若涉及非合入 patch 相关的 config 问题，临时修改后编译，通过后 `git restore` 掉
6. **merge 必须串行执行**：merge 步骤不可并行
7. **前期分析阶段（patch 用途/依赖/revert 需求深度分析）是只读操作，可以并行**
8. **中文输出**：所有思考、解释、分析、输出报告使用中文
9. **只取改动行**：只应用 patch 中以 `+`/`-` 开头的实际修改行，上下文行不强制合入

## 输出模板

分析结果输出到 `./patch_analysis/`，格式：

```
patch_analysis/
  0001-<patch-name>-analys.md    # 每个 patch 一份分析报告
  0002-<patch-name>-analys.md
  ...
  summary.md                      # 汇总报告
```

每份分析报告需包含：
- patch 功能描述、关联模块
- 依赖分析（高版本依赖/bugfix 依赖/前置 patch）
- revert 需求评估（必要性等级）
- 风险程度（高/中/低）
- 人工 review 需求度
- 建议验证冒烟内容
- 与源 patch 的完整 diff

## 文件更新

- 动态更新README.md文件（比如目录更新，使用说明更新，skill结构更新等）

## 两大使用场景

### 场景1：高版本源端合入
从高版本 Linux 源端合入 patchset，需查找：
- **往前**：git blame 追溯 patch 代码行的历史，定位相关 bugfix
- **往后**：查找高版本依赖（可能也是 patchset 形式）
- 要求：速度快、定位精准，使用 git blame / git log -S 等

### 场景2：本地实现 + 新版本代码合并
本地已有实现代码，需合并新版本代码进来：
- 判断合入仓库是否有高依赖 patch
- 评判机制：是否需要全部回退本地实现
  - 若为独立特性实现 → 建议全部回退
  - 若为局部修改 → 需分析回退范围
- 需协助扩展回退判断标准

## 多 Agent 架构

skill 采用多 agent 并行+串行模式：

1. **并行阶段（只读）**：多个 agent 同时深度分析 patch 用途、依赖链、revert 需求
2. **串行阶段（写入）**：merge 逐个串行执行，每个 patch 合入→编译验证→review

依赖分析和 revert 判定属于**高危行为**，需进入专家模式干预和评判（提供必要性等级）。

## 编码规范

skill 代码需遵循 karpathy-guidelines（路径：`/root/.config/opencode/skills/karpathy-guidelines/.../SKILL.md`）：
- 先思考再编码，明确假设
- 最简代码解决问题，不过度抽象
- 手术式修改，不碰无关代码
- 以可验证目标驱动执行

关于这个skill的代码编写，必须同步到 `/mnt/shared/AI提效/1.\ 自动合入patch/patchset-merge/`

## Skill 部署流程

```bash
# 一键安装（运行测试 + 部署到 /root/.agents/skills/merge-patchset/）
bash install.sh

# 手动部署
cp SKILL.md /root/.claude/skills/merge-patchset/SKILL.md
cp SKILL.md /mnt/shared/AI提效/1.\ 自动合入patch/patchset-merge/SKILL.md
cp references/* /root/.claude/skills/merge-patchset/references/
```
