---
name: layer4-output
description: >
  Patchset-merge 输出层：汇总执行记录、生成最终报告、验证输出完整性。
  
  强制前置条件：
  1. 必须在 layer3-execution 完成后调用
  2. 必须存在所有 analyse.md 文件
  
  输出文件：summary.md + output_report.json
  
  完成后状态：Write state.json: {"layer4": "completed"}
---

<HARD-GATE>
输出文件必须落盘！不依赖 AI 记忆。

验证规则：
1. 所有 analyse.md 文件必须存在且非空
2. summary.md 必须存在且非空
3. output_report.json 必须包含完整性检查结果

若验证失败 → 中止并输出缺失文件列表
</HARD-GATE>

# Layer 4 - 输出层

## 职责

读取所有 analyse.md + execution_log.json，生成 summary.md 汇总报告，强制验证输出文件完整性。

## 执行流程

### 步骤 1: 门禁验证

```bash
bash $SCRIPTS_DIR/gate_check.sh layer4 $KERNEL_REPO_PATH
```

### 步骤 2-3: 读取执行记录

```bash
Read: $KERNEL_REPO/patch_analysis/execution_log.json
Read: $KERNEL_REPO/patch_analysis/merge_tasks.json
```

### 步骤 4: 读取所有 analyse.md

```bash
cd $KERNEL_REPO/patch_analysis

for analyse_file in *-analyse.md; do
  Read: "$analyse_file"
done
```

### 步骤 5: 生成 summary.md

```bash
python3 $SCRIPTS_DIR/generate_summary_md.py \
  --merge-tasks merge_tasks.json \
  --analysis-dir patch_analysis \
  --output summary.md

# AI 补充：
  - 整体合入经验总结
  - 典型冲突案例分析
  - 性能指标
  - 用户建议
```

### 步骤 6: 生成 diff 报告

```bash
python3 $SCRIPTS_DIR/generate_diff_report.py \
  --patch-dir /tmp/patches \
  --output-dir patch_analysis
```

### 步骤 7: 输出完整性验证（Skill 内 Bash）

```bash
cd $KERNEL_REPO/patch_analysis

REQUIRED_FILES=(config.json merge_tasks.json execution_log.json summary.md)
for file in $REQUIRED_FILES; do
  test -f "$file" || exit 10
  test -s "$file" || exit 11
done

ANALYSE_COUNT=$(ls *-analyse.md | wc -l)
PATCH_COUNT=$(python3 -c "
import json
with open('merge_tasks.json') as f:
    tasks = json.load(f).get('tasks', [])
    print(len([t for t in tasks if t.get('action') == 'apply']))
")

[ "$ANALYSE_COUNT" -eq "$PATCH_COUNT" ] || exit 12

echo "✅ 所有输出文件验证通过"
```

### 步骤 8: Write output_report.json

```json
{
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

### 步骤 9: 最终输出展示

```
═══════════════════════════════════════════════════════════════
  Patchset-Merge 执行完成
═══════════════════════════════════════════════════════════════

执行概览：
  成功合入:       14 patch
  跳过:           1 patch
  
输出文件完整性：
  ✅ summary.md
  ✅ 15 个 analyse.md
  
后续建议：
  1. 查看 summary.md 了解整体合入经验
  2. 检查 git log 确认所有 commit
  3. 若需合并到主干，请手工执行 git merge
```