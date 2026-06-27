# 输出完整性检查清单

Layer 4 步骤 7 执行，验证所有输出文件存在且非空。

## 必须文件

| 文件 | 来源 | 检查项 |
|------|------|--------|
| `config.json` | Layer 1 | 存在、非空、JSON 可解析 |
| `merge_tasks.json` | Layer 2 | 存在、非空、JSON 可解析、merge_order 非空 |
| `execution_log.json` | Layer 3 | 存在、非空、JSON 可解析 |
| `summary.md` | Layer 4 | 存在且非空 |
| `*-analyse.md` | Layer 3 | 数量 = merge_tasks.json 中 action=apply 的 patch 数，每个文件非空 |

## 验证 Bash

```bash
cd $OUTPUT_DIR

# 1. 必需文件存在且非空
REQUIRED_FILES=(config.json merge_tasks.json execution_log.json summary.md)
for file in $REQUIRED_FILES; do
  test -f "$file" || exit 10
  test -s "$file" || exit 11
done

# 2. analyse.md 数量校验
ANALYSE_COUNT=$(ls *-analyse.md 2>/dev/null | wc -l)
PATCH_COUNT=$(python3 -c "
import json
with open('merge_tasks.json') as f:
    tasks = json.load(f).get('merge_order', [])
    print(len([t for t in tasks if t.get('action') == 'apply']))
")

if [ "$ANALYSE_COUNT" -ne "$PATCH_COUNT" ]; then
  echo "❌ analyse.md 数量不匹配: 期望=$PATCH_COUNT 实际=$ANALYSE_COUNT"
  exit 12
fi

# 3. analyse.md 非空检查
for f in *-analyse.md; do
  [ -s "$f" ] || { echo "❌ $f 为空"; exit 13; }
done

echo "✅ 所有输出文件验证通过"
```

## output_report.json 结构

```json
{
  "schema_version": "1.0",
  "session_id": "...",
  "total_patches": 15,
  "patches_applied": 14,
  "build_checkpoints": 5,
  "conflicts_resolved": 8,
  "output_files": {
    "config.json": {"exists": true},
    "analyse_files": {"count": 15}
  },
  "verification_status": "all_passed"
}
```

## 验证失败处理

- 输出缺失文件清单
- 标记 output_report.json.verification_status = "failed"
- 提示用户补全缺失文件后重新执行 Layer 4
