---
name: layer4-output
description: >
  Patchset-merge 输出层：生成 analyse.md、汇总执行记录、生成最终报告、验证输出完整性。
  
  强制前置条件：
  1. 必须在 layer3-execution 完成后调用
  2. 必须存在 merge_tasks.json + execution_log.json
  
  输出文件：analyse.md 系列 + summary.md + output_report.json
  
  完成后状态：Write state.json: {"layer4": "completed"}
---

<HARD-GATE>
输出文件必须落盘！不依赖 AI 记忆。

验证规则：
1. merge_tasks.json + execution_log.json 必须存在且非空（入口门禁）
2. 所有 analyse.md 文件必须生成且非空（步骤 3 生成后自检）
3. summary.md 必须存在且非空
4. output_report.json 必须包含完整性检查结果

若验证失败 → 中止并输出缺失文件列表
</HARD-GATE>

# Layer 4 - 输出层

## 职责

生成所有 analyse.md、读取执行记录，生成 summary.md 汇总报告，强制验证输出文件完整性。

## 执行流程

### 步骤 1: 门禁验证 + 提取输出目录

```bash
bash $SCRIPTS_DIR/gate_check.sh layer4 $KERNEL_REPO_PATH

# 提取输出目录
OUTPUT_DIR=$(python3 -c "
import json
with open('$KERNEL_REPO_PATH/patch_analysis/config.json') as f:
    print(json.load(f)['output_dir'])
")
echo "输出目录: $OUTPUT_DIR"
```

### 步骤 2: 读取执行记录

```bash
Read: $OUTPUT_DIR/execution_log.json
Read: $OUTPUT_DIR/merge_tasks.json
```

### 步骤 3: 生成所有 analyse.md

```bash
cd $OUTPUT_DIR

# 遍历 merge_tasks.json 中所有 action=apply 的 task，生成 analyse.md
python3 -c "
import json, subprocess, sys
with open('merge_tasks.json') as f:
    tasks = json.load(f)
for t in tasks.get('merge_order', []):
    if t.get('action') == 'apply':
        result = subprocess.run(
            ['python3', '$SCRIPTS_DIR/generate_analyse_md.py', '--task-id', t['task_id']],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f'❌ {t[\"task_id\"]} analyse.md 生成失败: {result.stderr}', file=sys.stderr)
"

echo "✅ analyse.md 生成完成"
```

AI 按 `references/analyse_template.md` 模板补充语义内容：
  - 功能描述与关联模块
  - 依赖分析（3.1 - 3.4）
  - Revert 需求评估
  - 风险/Review 评估
  - 合入实际经验
  - Review 建议与改进方向

### 步骤 4: 导出合入的 patch（git format-patch）

```bash
cd $KERNEL_REPO_PATH

BASELINE=$(python3 -c "
import json
with open('$KERNEL_REPO_PATH/patch_analysis/config.json') as f:
    print(json.load(f)['baseline_branch'])
")

mkdir -p "$OUTPUT_DIR/patches"
git format-patch ${BASELINE}..HEAD -o "$OUTPUT_DIR/patches/"

echo "✅ patch 已导出到 $OUTPUT_DIR/patches/"
```

### 步骤 5: 生成 summary.md

```bash
python3 $SCRIPTS_DIR/generate_summary_md.py \
  --merge-tasks merge_tasks.json \
  --analysis-dir $OUTPUT_DIR \
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
  --output-dir $OUTPUT_DIR
```

### 步骤 7: 输出完整性验证（Skill 内 Bash）

```bash
cd $OUTPUT_DIR

REQUIRED_FILES=(config.json merge_tasks.json execution_log.json summary.md)
for file in $REQUIRED_FILES; do
  test -f "$file" || exit 10
  test -s "$file" || exit 11
done

ANALYSE_COUNT=$(ls *-analyse.md | wc -l)
PATCH_COUNT=$(python3 -c "
import json
with open('merge_tasks.json') as f:
    tasks = json.load(f).get('merge_order', [])
    print(len([t for t in tasks if t.get('action') == 'apply']))
")

[ "$ANALYSE_COUNT" -eq "$PATCH_COUNT" ] || exit 12

echo "✅ 所有输出文件验证通过"
```

### 步骤 8: Write output_report.json

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