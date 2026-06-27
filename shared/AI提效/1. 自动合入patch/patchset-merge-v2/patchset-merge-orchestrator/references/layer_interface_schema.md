# 层间接口规范

层间通过 JSON 文件传递数据，每层强依赖上一层的输出。接口变更必须整体传播。

## 接口链

```
Layer 1: config.json
  ↓ gate_check.sh 验证
Layer 2: samples_summary.json, duplicate_analysis.json,
         revert_candidates.json, deps_candidates.json, merge_tasks.json
  ↓ gate_check.sh 验证
Layer 3: *-analyse.md, execution_log.json
  ↓ gate_check.sh 验证
Layer 4: summary.md, output_report.json
```

## schema_version 版本表

所有层间 JSON 文件必须包含 `schema_version` 字段（当前版本 `"1.0"`）：

| 文件 | 生产层 | 消费层 | schema_version |
|------|--------|--------|----------------|
| `config.json` | Layer 1 | Layer 2, 3, 4 | `1.0` |
| `samples_summary.json` | Layer 2 | Layer 2（内部） | `1.0` |
| `duplicate_analysis.json` | Layer 2 | Layer 2（内部） | `1.0` |
| `revert_candidates.json` | Layer 2 | Layer 3 | `1.0` |
| `deps_candidates.json` | Layer 2 | Layer 3 | `1.0` |
| `merge_tasks.json` | Layer 2 | Layer 3, 4 | `1.0` |
| `output_report.json` | Layer 4 | 用户 | `1.0` |

## 接口变更强制传播

修改任何层间 JSON 的字段时，必须同步修改所有涉及的层和脚本：

1. **更新 `schema_version`**：修改接口的层将版本号 +0.1（如 `1.0` → `1.1`），并更新自身 SKILL.md + references/ 中的输出示例
2. **更新消费层**：所有消费该 JSON 的层的 SKILL.md 中，读取该字段的代码/逻辑必须同步修改
3. **更新 `gate_check.sh`**：将对应 layer 的 `check_schema_version` 期望值更新为新版本
4. **更新 `references/` 下的 schema 文档**：该 JSON 对应的 schema 文件
5. **更新 Python 脚本**：所有 `shared-scripts/` 和 `scripts/` 下读写该 JSON 的脚本必须适配新字段
6. **验证**：运行 `bash tests/test_integration.sh` 确认无破坏

### 禁止行为

- ❌ 只改生产层不改消费层（消费层会静默失败或产出垃圾数据）
- ❌ 改了字段但不更新 schema_version（gate_check 无法检测不兼容）
- ❌ 改了 schema_version 但不更新 gate_check.sh 中的期望值（校验形同虚设）

## gate_check.sh 验证内容

对每层的前置文件执行：
- 文件存在性
- JSON 可解析性（非空、格式正确）
- 关键字段存在性（如 `candidates` 数组、`merge_order` 数组）
- `schema_version` 匹配

## 反向验证

Layer 2 步骤 1 对 Layer 1 的 `config.json` 执行反向验证：
- 必填字段完整性
- 路径一致性
- `schema_version` 兼容性
