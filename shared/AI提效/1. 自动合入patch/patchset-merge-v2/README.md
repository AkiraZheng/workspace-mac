# Patchset-Merge Layered Architecture

Linux 内核 patchset 多 Agent 自动合入与冲突解决 Skill - 分层架构版本。

## 核心特性

- **清晰的四层架构** - Interaction、Search、Execution、Output
- **强制执行机制** - Skill 串联 + 门禁验证 + 状态文件
- **超时容错** - Skill 内控制流 + 最小脚本（<5s）
- **AI 遗忘规避** - 强制落盘 + 完整性验证
- **commit message 保护** - 强制 git am + 循环处理 .rej

## 架构模式

**方案 D（Skill 内控制流）** + **方案 C（Skill 串联）** + **路径 C（混合实现）**

## 目录结构

```
patchset-merge-v2/
├── patchset-merge-orchestrator/      # 主调度 Skill
├── layer1-interaction/               # 用户交互层
├── layer2-search/                    # 搜索层
├── layer3-execution/                 # 执行层（核心）
├── layer4-output/                    # 输出层
├── conflict-resolver/               # Git 冲突自动解决模块
├── linux-kernel-review/             # 内核 patch review 模块
├── shared-scripts/                   # 复用脚本（7个）
├── AGENTS.md                         # 开发工作区说明
└── install.sh                        # 一键安装脚本
```

## 使用方法

```bash
# 安装
bash install.sh

# 调用主调度 Skill
Skill tool: patchset-merge-orchestrator
输入: "合入 <message-id> 到 ~/code/openeuler/kernel 的 patch-xxx 分支"
```

## 四层职责

| Layer | 职责 | 关键特性 |
|-------|------|---------|
| Layer 1 | 用户交互 | 纯 Bash，不调脚本 |
| Layer 2 | 搜索 | Subagent 并行 + AI 汇总 |
| Layer 3 | 执行 | 强制 git am + BUILD_FIX |
| Layer 4 | 输出 | 强制验证完整性 |

## 核心约束

> ⚠️ **一个仓库目录下同一时间只能执行一个合入任务。**

❌ **禁止 git apply** - 会丢失 commit message  
❌ **禁止 git reset --hard** - 会删除 commit  
✅ **强制 git am** - 保护 commit message  
✅ **循环处理 .rej** - 最多 10 轮重试

## 输出目录结构

```
$KERNEL_REPO/
  patch_analysis/
    config.json                       ← 唯一固定入口（AI 访问点）
  patchmerge/
    <分支名>_output/                  ← 每次合入独立，分支隔离
      config.json                     ← 本次运行的配置（归档）
      state.json                      ← 执行状态（支持中断恢复）
      merge_tasks.json
      *-analyse.md                   ← 每个 patch 的分析记录
      summary.md                      ← 汇总报告
      output_report.json
      patches/                        ← git format-patch 导出
```

## 设计文档

- `docs/superpowers/specs/2026-06-10-patchset-merge-layered-architecture-design.md`
- `docs/superpowers/plans/2026-06-10-patchset-merge-layered-implementation.md`

## 测试

```bash
bash tests/test_integration.sh
```

## 版本

当前版本：v2（分层架构）  
旧版本：patchset-merge（Phase 0-4 架构）

## License

MIT