# AGENTS.md — patchset-merge-v2 workspace

## 仓库角色

本仓库是 **patchset-merge 分层架构版本**的开发和配置工作区。

## 目标内核仓库

操作始终在**独立分支**上进行，不在主干分支直接操作。目标仓库和分支由用户在运行时通过环境变量配置：

```
KERNEL_REPO_PATH   # 内核仓库绝对路径
KERNEL_BRANCH      # 操作分支名
KERNEL_ARCH        # 目标架构（如 arm64）
BUILD_CMD          # 编译命令（如 make ARCH=arm64 Image）
```

skill 启动时会向用户确认这些值，不可硬编码。

## 架构模式

- **基础模式**: 方案 D（Skill 内控制流 + 最小确定性脚本）
- **组织方式**: 方案 C（Skill 串联模式）
- **实现路径**: 路径 C（混合方案）

详见设计文档：`docs/superpowers/specs/2026-06-10-patchset-merge-layered-architecture-design.md`

## 硬性约束（必须遵守）

1. **逐个合入 + 逐个 commit**：N 个 patch 就产生 N 个 commit，不允许批量合入
2. **仅在有问题时交互**：正常合入自动流转；冲突超限/循环依赖/重复 patch 时暂停等用户决策
3. **每 1 个 commit 完成后调用 code-review-expert skill 做 review**
4. **revert 也逐个 commit**：逆序 revert（最新→最旧），每 revert 一个就 commit 一个
5. **build_checkpoint的 patch 必须编译验证**
6. **merge 必须串行执行**
7. **前期分析阶段是只读操作，可以并行**
8. **中文输出**：所有思考、解释、分析、输出报告使用中文
9. **只取改动行**：只应用 patch 中以 `+`/`-` 开头的实际修改行

## 核心修正（相对于 patchset-merge）

- ❌ **禁止 git apply**（会丢失 commit message）
- ✅ **强制 git am --3way --reject + 循环处理 .rej**
- ✅ **BUILD_FIX 详细流程**（rebase amend + 禁用 git reset）

## Skill 串联流程

```
patchset-merge-orchestrator (主调度)
  ↓
Layer 1: 用户交互（参数解析 + config.json）
  ↓ gate_check.sh 验证
Layer 2: 搜索层（Subagent 并行 + merge_tasks.json）
  ↓ gate_check.sh 验证
Layer 3: 执行层（串行 merge + analyse.md）
  ↓ gate_check.sh 验证
Layer 4: 输出层（summary.md + 完整性验证）
```

## 编码规范

skill 代码需遵循 karpathy-guidelines：
- 先思考再编码，明确假设
- 最简代码解决问题，不过度抽象
- 手术式修改，不碰无关代码
- 以可验证目标驱动执行

## 部署流程

**安装**：
```bash
bash install.sh
```

**卸载**：
```bash
bash uninstall.sh
```

卸载内容包括：
- Skill 目录（$HOME/.agents/skills/patchset-merge-v2）
- Python venv 环境（包含 b4）
- Claude Code symlink
- OpenCode symlink

**注意**：卸载不会删除 patch_analysis 目录（用户数据）