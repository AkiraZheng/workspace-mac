# deps_candidates.json Schema

Layer 2 步骤 4 agent_upstream_deps Subagent 产出，Layer 3 消费。当前 schema_version: `1.0`。

## 完整 Schema

```json
{
  "schema_version": "1.0",
  "dependencies": [
    {
      "commit_hash": "def456",
      "subject": "stage2 页表重构",
      "introduced_symbols": ["stage2_map", "stage2_try_set_pte"],
      "ruling": "confirm",
      "pull_cmd": "b4 am <msgid>",
      "source_pr": "PR #456",
      "reason": "缺失函数 stage2_try_set_pte，patch 0003 调用此符号"
    }
  ]
}
```

## 字段说明

| 字段 | 必填 | 说明 |
|------|:--:|------|
| `dependencies[].commit_hash` | ✓ | 上游依赖 commit hash |
| `dependencies[].subject` | ✓ | commit 标题 |
| `dependencies[].introduced_symbols` | ✓ | 该依赖引入的符号列表 |
| `dependencies[].ruling` | ✓ | `confirm`（确认需要）/ `reject`（不需要） |
| `dependencies[].pull_cmd` | ✓ | 推荐的拉取命令 |
| `dependencies[].source_pr` | - | 上游 PR 编号 |
| `dependencies[].reason` | ✓ | 依赖原因说明 |
