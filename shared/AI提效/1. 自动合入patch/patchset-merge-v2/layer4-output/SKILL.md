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

### 步骤 3: 生成 analyse.md（AI 手写）

#### 3a: 生成每个 patch 的 .diff 参考文件

```bash
BASELINE=$(python3 -c "
import json
with open('$KERNEL_REPO_PATH/patch_analysis/config.json') as f:
    print(json.load(f)['baseline_branch'])
")

cd $KERNEL_REPO_PATH
git log --reverse --format="%H" ${BASELINE}..HEAD > /tmp/merge_commits.txt

mkdir -p "$OUTPUT_DIR/diffs"

while IFS=, read -r task_id patch_file action; do
    if [ "$action" != "apply" ]; then continue; fi
    commit=$(sed -n "${task_id}p" /tmp/merge_commits.txt)
    python3 $SCRIPTS_DIR/generate_diff_report.py \
      --source "patch:/tmp/patches/${patch_file}" \
      --target "$commit" \
      --repo-path "$KERNEL_REPO_PATH" \
      --execution-log "$OUTPUT_DIR/merge_tasks.json" \
      --task-id "$task_id" \
      --output "$OUTPUT_DIR/diffs/${task_id}.diff"
done < <(python3 -c "
import json
with open('$OUTPUT_DIR/merge_tasks.json') as f:
    d = json.load(f)
for t in d.get('merge_order', []):
    print(f'{t[\"task_id\"]},{t.get(\"patch_file\",\"\")},{t.get(\"action\",\"\")}')
")
```

#### 3b: AI 逐 patch 手写 analyse.md

AI 必须使用 **Write 工具** 逐个生成每个 patch 的 analyse.md。

**数据源**（AI 需 Read）：
| 文件 | 用途 |
|------|------|
| `layer4-output/references/analyse_template.md` | 结构模板 |
| `$OUTPUT_DIR/merge_tasks.json` | 任务元数据 + dependency/devert 信息 |
| `$OUTPUT_DIR/execution_log.json` | Layer 3 执行记录 |
| `$OUTPUT_DIR/diffs/<task_id>.diff` | 逐行偏离参考数据（第 9 节） |
| `/tmp/patches/<patch_file>` | 原始 .patch 文件（理解源意图） |
| `git show <commit_hash>` | 实际合入提交 |

**生成顺序**：按 merge_order seq 升序，一个 patch 一个 `<task_id>-<subject_slug>-analyse.md`。

**第 9 节格式要求**（关键）：
- **不要**把 `.diff` 文件内容原样粘贴
- 读取 `.diff` 中的偏离数据 + 原始 `.patch` → AI 理解后生成**人工 review 友好的逐行对比表**
- 格式：

```markdown
### <文件路径>
源 patch 意图：+X 行, -Y 行 → 实际 commit：+X' 行, -Y' 行

| 源 patch 行 | 实际 commit 行 | 偏离说明 |
|------------|--------------|----------|
| `+ original_code` | `+ adapted_code` | API 适配，ga 冲突修正 |
| （无） | `+ extra_code` | 目标仓库额外适配 |
| `- removed_line` | （无） | 目标仓库保留此行（无冲突） |

**结论**：X 处偏离。X 处冲突修正（低风险），X 处目标仓库适配（需 review）。
```

**全自动生成规则**：AI 不交互、不停顿、不等待用户确认。连续写完全部 analyse.md 后再进入步骤 4。

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

### 步骤 6: 输出完整性验证（Skill 内 Bash）

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

### 步骤 7: Write output_report.json

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

### 步骤 8: 最终输出展示


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