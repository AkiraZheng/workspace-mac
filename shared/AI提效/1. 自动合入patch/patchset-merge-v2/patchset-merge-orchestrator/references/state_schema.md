# state.json Schema

Orchestrator 持久化执行状态，支持中断恢复。存储路径：`$OUTPUT_DIR/state.json`（与本次合入输出同目录）

## 完整 Schema

```json
{
  "session_id": "patchset-merge-<timestamp>",
  "kernel_repo": "<内核仓库路径>",
  "current_layer": "layer2",
  "layer_status": {
    "layer1": {
      "status": "completed",
      "skill_invoked": "layer1-interaction",
      "output_files": ["config.json"],
      "gate_check_exit_code": 0,
      "completed_at": "2026-06-26T10:30:00Z"
    },
    "layer2": {
      "status": "completed",
      "skill_invoked": "layer2-search",
      "output_files": ["revert_candidates.json", "deps_candidates.json", "merge_tasks.json"],
      "subagents": ["agent_target_revert", "agent_upstream_deps"],
      "gate_check_exit_code": 0,
      "completed_at": "2026-06-26T10:35:00Z"
    },
    "layer3": {
      "status": "in_progress",
      "skill_invoked": "layer3-execution",
      "completed_at": null
    },
    "layer4": {
      "status": "pending",
      "skill_invoked": null,
      "completed_at": null
    }
  },
  "all_layers_completed": false
}
```

## 字段说明

| 字段 | 说明 |
|------|------|
| `session_id` | 会话标识，格式 `patchset-merge-<unix_timestamp>` |
| `kernel_repo` | 目标内核仓库路径 |
| `current_layer` | 当前所在层（`layer1` / `layer2` / `layer3` / `layer4`） |
| `layer_status.<layer>.status` | `pending` / `in_progress` / `completed` / `failed` / `cancelled` |
| `layer_status.<layer>.output_files` | 该层产出的文件列表 |
| `layer_status.<layer>.gate_check_exit_code` | 门禁验证退出码 |
| `all_layers_completed` | 所有层是否已全部完成 |

## 恢复机制

```bash
# 恢复流程
STATE_FILE="$OUTPUT_DIR/state.json"

if [ -f "$STATE_FILE" ]; then
  CURRENT_LAYER=$(python3 -c "
import json
with open('$STATE_FILE') as f:
    print(json.load(f)['current_layer'])
  ")
  
  case $CURRENT_LAYER in
    "layer1") # Layer 1 已完成 → 从 Layer 2 继续 ;;
    "layer2") # Layer 2 已完成 → 从 Layer 3 继续 ;;
    "layer3") # Layer 3 已完成 → 从 Layer 4 继续 ;;
    "layer4") # 全部完成，无需恢复 ;;
  esac
fi
```
