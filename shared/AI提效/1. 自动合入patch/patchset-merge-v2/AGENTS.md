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
3. **每 1 个 commit 完成后调用 linux-kernel-review skill 做 review**
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

## 层间接口规范（强制遵守）

层间通过 JSON 文件传递数据，每层强依赖上一层的输出。接口变更必须整体传播。

### schema_version 机制

所有层间 JSON 文件**必须包含 `schema_version` 字段**（当前版本 `"1.0"`）：

| 文件 | 生产层 | 消费层 | schema_version |
|------|--------|--------|----------------|
| `config.json` | Layer 1 | Layer 2, 3, 4 | `1.0` |
| `samples_summary.json` | Layer 2 | Layer 2（内部） | `1.0` |
| `duplicate_analysis.json` | Layer 2 | Layer 2（内部） | `1.0` |
| `revert_candidates.json` | Layer 2 | Layer 3 | `1.0` |
| `deps_candidates.json` | Layer 2 | Layer 3 | `1.0` |
| `merge_tasks.json` | Layer 2 | Layer 3, 4 | `1.0` |
| `output_report.json` | Layer 4 | 用户 | `1.0` |

`gate_check.sh` 在每层入口校验前置文件的 `schema_version`，不匹配则拒绝进入。

### 接口变更强制传播规则

修改任何层间 JSON 的字段时，**必须同步修改所有涉及的层和脚本**，步骤如下：

1. **更新 `schema_version`**：修改接口的层将版本号 +0.1（如 `1.0` → `1.1`），并更新自身 SKILL.md 中的输出示例
2. **更新消费层**：所有消费该 JSON 的层的 SKILL.md 中，读取该字段的代码/逻辑必须同步修改
3. **更新 `gate_check.sh`**：将对应 layer 的 `check_schema_version` 期望值更新为新版本
4. **更新 `references/` 下的 schema 文档**：如 `output-templates.md`、`config_schema.md` 等
5. **更新 Python 脚本**：所有 `shared-scripts/` 和 `scripts/` 下读写该 JSON 的脚本必须适配新字段
6. **更新 `docs/field_reference.md`**：同步修改对应字段的"生产者"/"消费者"列
7. **验证**：运行 `bash tests/test_integration.sh` 确认无破坏

**禁止行为**：
- ❌ 只改生产层不改消费层（消费层会静默失败或产出垃圾数据）
- ❌ 改了字段但不更新 schema_version（gate_check 无法检测不兼容）
- ❌ 改了 schema_version 但不更新 gate_check.sh 中的期望值（校验形同虚设）
- ❌ 改了字段但不更新 docs/field_reference.md（字段关系文档过时）

### 反向验证

Layer 2 步骤 1 对 Layer 1 的 `config.json` 执行反向验证：
- 必填字段完整性（`patch_source`, `kernel_repo_path`, `kernel_branch`, `kernel_arch`, `build_cmd`）
- 路径一致性（`kernel_repo_path` 与实际仓库路径匹配）
- `schema_version` 兼容性

`gate_check.sh` 对所有前置文件执行：
- JSON 可解析性（非空、格式正确）
- 关键字段存在性（如 `candidates` 数组、`merge_order` 数组）
- `schema_version` 匹配

## 参考文件分布

各层的 `references/` 目录下存放该层产出的 JSON schema 和执行参考文档，
按 **生产层归属** 组织（谁生产该文件，schema 就放在谁的 references/ 下）。

| 文件 | reference 路径 | 说明 |
|------|---------------|------|
| `config.json` | `layer1-interaction/references/config_schema.md` | Layer 1 产出，必填字段 + 结构定义 |
| `samples_summary.json` | `layer2-search/references/samples_summary_schema.md` | Layer 2 抽样检测产出 |
| `duplicate_analysis.json` | `layer2-search/references/duplicate_analysis_schema.md` | Layer 2 匹配分析产出 |
| `revert_candidates.json` | `layer2-search/references/revert_candidates_schema.md` | Layer 2 Subagent 产出 |
| `deps_candidates.json` | `layer2-search/references/deps_candidates_schema.md` | Layer 2 Subagent 产出 |
| `patch_symbols.json` | `layer2-search/references/patch_symbols_schema.md` | Layer 2 脚本产出 |
| `merge_tasks.json` | `layer2-search/references/merge_tasks_schema.md` | Layer 2 最终产出（核心 schema） |
| `analyse.md` 模板 | `layer4-output/references/analyse_template.md` | Layer 4 每 patch 落盘模板 |
| Build Fix 策略 | `layer3-execution/references/build_fix_strategy.md` | Layer 3 编译修复流程 |
| 状态机定义 | `layer3-execution/references/execution_state_machine.md` | Layer 3 7 步状态机 |
| 冲突决策树 | `layer3-execution/references/conflict_decision_tree.md` | Layer 3 Ours/Theirs 决策 |
| `summary.md` 模板 | `layer4-output/references/summary_template.md` | Layer 4 汇总报告模板 |
| 输出检查清单 | `layer4-output/references/output_checklist.md` | Layer 4 完整性验证 |
| `output_report.json` | `layer4-output/references/output_checklist.md` | Layer 4 产出（含 structure） |
| 层间接口规范 | `orchestrator/references/layer_interface_schema.md` | schema_version 版本表 + 传播规则 |
| `state.json` | `orchestrator/references/state_schema.md` | 执行状态（`$OUTPUT_DIR/state.json`） |
| 降级机制 | `orchestrator/references/fallback_guide.md` | 脚本超时/失败降级策略 |
| Schema 索引 | `orchestrator/references/output-templates.md` | 所有 schema 的索引导航 |
| 冲突解决 | `conflict-resolver/SKILL.md` | git am 冲突自动解决 + Ours/Theirs 决策 |
| Code Review | `linux-kernel-review/SKILL.md` | 内核 patch 合入后的专项 review 操作指南 |

查询规则：**改哪个 JSON 的字段 → 先查索引找到对应 reference → 改 reference 文件 → 按传播规则更新消费层**。

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

**注意**：卸载不会删除 `patch_analysis/config.json` 和 `patchmerge/` 目录（用户数据）