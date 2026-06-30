# patch_analysis.json Schema

## 概述

Layer 2 Subagent `agent_patch_analysis` 产出。包含每个 patch 的语义分析、风险评估、冲突预判、依赖关系。Layer 3 在 git am 前必读。

## 顶层结构

```json
{
  "schema_version": "1.0",
  "<task_id>": { ... },
  ...
}
```

## 每个 task_id 的字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `功能分类` | string | 是 | infra / driver / core / fs / net / sound / doc / bugfix |
| `功能概述` | string | 是 | 一句话描述功能（中文） |
| `risk_level` | string | 是 | 高 / 中 / 低 |
| `risk_detail` | string | 是 | 风险详述 |
| `review_required` | string | 是 | 高 / 中 / 低 |
| `review_reason` | string | 是 | 为什么需要 review |
| `conflicts_predicted` | array | 是 | 预判冲突点（可为空数组） |
| `conflicts_predicted[].file` | string | 是 | 冲突文件路径 |
| `conflicts_predicted[].line_hint` | int | 否 | 预估冲突行号 |
| `conflicts_predicted[].reason` | string | 是 | 冲突原因 |
| `conflicts_predicted[].severity` | string | 是 | high / medium / low |
| `special_notes` | array | 是 | 特殊注意事项（可为空数组） |
| `depends_on` | array | 是 | 内部依赖 task_id 列表（可为空数组） |
| `blame_hits` | array | 是 | upstream git blame 追溯结果（可为空数组） |
| `execution_guide.am_mode` | string | 是 | reject / 3way |
| `execution_guide.conflict_strategy` | string | 否 | 冲突解决策略提示 |

## 消费方式

Layer 3 步骤 5 循环中，每个 task 的 git am 前读取当前 task_id 的字段：

- `risk_level=高` 或 `conflicts_predicted` 含 high severity → 使用 `--reject` 模式手动逐行处理
- `special_notes` 非空 → 在 .rej 解决时逐条参考
- `execution_guide.am_mode` → 决定 git am 模式
- `conflicts_predicted` 非空 → 提前 `git log` 或 `read` 目标文件做好准备
