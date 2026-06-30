# 输出模板与 Schema — 索引

> 本文件是索引，指向各层 `references/` 目录下的权威 schema 文档。
> 各层 SKILL.md 中已内联简化版 JSON 示例，完整 schema 请按以下路径查询。

## 层间 JSON Schema

| 文件 | Schema 定义位置 | 生产层 |
|------|----------------|--------|
| `config.json` | `layer1-interaction/references/config_schema.md` | Layer 1 |
| `samples_summary.json` | `layer2-search/references/samples_summary_schema.md` | Layer 2 |
| `duplicate_analysis.json` | `layer2-search/references/duplicate_analysis_schema.md` | Layer 2 |
| `revert_candidates.json` | `layer2-search/references/revert_candidates_schema.md` | Layer 2 |
| `deps_candidates.json` | `layer2-search/references/deps_candidates_schema.md` | Layer 2 |
| `patch_analysis.json` | `layer2-search/references/patch_analysis_schema.md` | Layer 2 |
| `patch_symbols.json` | `layer2-search/references/patch_symbols_schema.md` | Layer 2 |
| `merge_tasks.json` | `layer2-search/references/merge_tasks_schema.md` | Layer 2 |
| `output_report.json` | `layer4-output/references/output_checklist.md` | Layer 4 |

## 模板（Markdown）

| 模板 | 定义位置 | 使用层 |
|------|---------|--------|
| `analyse.md` 模板 | `layer4-output/references/analyse_template.md` | Layer 4 |
| `summary.md` 模板 | `layer4-output/references/summary_template.md` | Layer 4 |

## 跨层文档

| 文档 | 位置 | 说明 |
|------|------|------|
| 层间接口规范 | `orchestrator/references/layer_interface_schema.md` | schema_version 版本表 + 接口变更传播规则 |
| 执行状态机 | `layer3-execution/references/execution_state_machine.md` | PRECHECK → DONE 7 步流程 |
| 冲突决策树 | `layer3-execution/references/conflict_decision_tree.md` | Ours/Theirs 决策表 |
| 编译修复策略 | `layer3-execution/references/build_fix_strategy.md` | rebase amend + 根因定位 |
| 搜索策略 | `layer2-search/references/search_strategy.md` | Subagent 搜索工具链 |
| 用户交互指南 | `layer1-interaction/references/user_interaction_guide.md` | Layer 1 交互流程 |
| state.json Schema | `orchestrator/references/state_schema.md` | 执行状态持久化 |
| 降级机制 | `orchestrator/references/fallback_guide.md` | 脚本超时/失败的降级处理 |
| 输出完整性检查 | `layer4-output/references/output_checklist.md` | Layer 4 验证清单 |
| 冲突解决 | `conflict-resolver/SKILL.md` | git am 冲突自动解决 |
| Code Review | `linux-kernel-review/SKILL.md` | 内核 patch 合入后 review 操作指南 |

## 用户交互模板（屏幕输出）

以下模板用于 Layer 2 向用户展示确认信息，内联在 `layer2-search/SKILL.md` 步骤 9：

- 依赖 Patch 汇总（PR 聚合展示）
- Revert 清单（PR 聚合 + 逆序）
- 合入计划预览
- 反向依赖处理方案选择
- 用户确认交互

以上模板的完整参考格式见 `layer2-search/SKILL.md` 和 `layer3-execution/SKILL.md`。
