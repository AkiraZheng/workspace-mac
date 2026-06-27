# analyse.md 固定模板

Layer 3 每个 patch 执行完成后落盘使用。复制以下模板，将 `{占位符}` 替换为实际值。

```markdown
# Patch {补丁编号}: {补丁标题}

## 1. 基本信息
| 项 | 值 |
|----|-----|
| 来源 commit | {上游提交} |
| 作者 | {作者} |
| 涉改文件数 | {文件数} |
| 合入状态 | {合入状态} |

## 2. 功能描述与关联模块

{功能描述}
关联模块：{关联模块}

## 3. 依赖分析

### 3.1 高版本依赖（上游版本差异）
{高版本依赖}
<!-- 如无，填写：未找到依赖 -->

### 3.2 Bugfix 依赖（git blame 追溯）
{bugfix 依赖}
<!-- 如无，填写：未找到 blame 记录 -->

### 3.3 前置 patch 依赖（本 patchset 内）
{内部依赖}
<!-- 如无，填写：无内部依赖 -->

### 3.4 目标仓库重复/等效 patch
{重复检测}
<!-- 如无，填写：未找到重复 patch -->
<!-- 若有：精确重复: <commit_hash> | 高概率等效: <commit_hash>:<原因> | 可能冲突: <原因> -->

## 4. Revert 需求评估

| 必要性等级 | {revert 等级} |
|-----------|-------------|
| 要 revert 的 commit | {revert 提交列表} |
| 理由 | {revert 理由} |

## 5. 风险程度

**{风险等级}**
{风险详述}

## 6. 人工 Review 需求度

**{review 需求}**
{review 理由}

## 7. 建议验证冒烟内容
{验证项}

## 8. 合入实际经验
（Layer 3 完成后填充，包含冲突解决过程、编译修复记录、重试次数）

- 冲突解决：{冲突详情}
- 编译修复：{编译修复详情}
- 重试次数：冲突 {冲突轮数} 次 / 编译 {编译轮数} 次

## 9. 与源 Patch/Commit 的差异对比

**对比对象**：
- **merge 场景**：原始 `.patch` 文件 vs 合入后的 commit（`git show <commit>`）
- **revert 场景**：被 revert 的原 commit vs revert commit

**输出焦点**：只展示偏离部分，不重复完整内容。由 `generate_diff_report.py` 生成。

**脚本调用**：
```bash
# merge 场景
python3 shared-scripts/generate_diff_report.py \
  --source "patch:/tmp/patches/0001-xxx.patch" \
  --target <commit_hash> --repo-path "$KERNEL_REPO_PATH" \
  --execution-log "$OUTPUT_DIR/merge_tasks.json" \
  --task-id "0001"

# revert 场景（镜像对比）
python3 shared-scripts/generate_diff_report.py \
  --source "commit:<被_revert_的_commit>" \
  --target <revert_commit_hash> --repo-path "$KERNEL_REPO_PATH" \
  --mode revert \
  --execution-log "$OUTPUT_DIR/merge_tasks.json" \
  --task-id "0001"
```

**偏离类型标注**：
- 源有目标无：patch/原 commit 有此行，实际 commit 无（因冲突跳过/被删除）
- 目标有源无：实际 commit 有此行，源 patch/原 commit 无（因适配新增/git am 自动调整）
- revert 模式：源添加→目标应删除，源删除→目标应恢复（镜像匹配）

**根因分析**：偏离标注后会从 execution_log 中提取根因。

```diff
{差异对比内容，由 generate_diff_report.py 生成}
```

## 10. 编译验证记录

```
编译命令结果：
  错误数: {错误数量}
  产物: {产物路径及状态}
  重试: {编译轮数} 次
```

## 11. Review 建议与改进方向
（Layer 4 汇总时由主 Agent 填入，基于对 patch 的深度理解）

### 功能改进建议
{功能改进}
<!-- 如无，填写：无 -->

### 潜在 Bug 提示
{潜在 bug}
<!-- 基于 blame 追溯和依赖分析标记的隐患 -->

### 代码质量建议
{代码质量}
<!-- 代码结构、命名、错误处理、锁使用等 -->

### 适配建议
{适配建议}
<!-- 针对目标仓库的适配注意事项 -->
```
