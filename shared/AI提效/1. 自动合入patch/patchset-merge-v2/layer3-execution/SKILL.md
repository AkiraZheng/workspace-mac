---
name: layer3-execution
description: >
  Patchset-merge 执行层：串行 merge、编译验证、commit、review。
  
   强制前置条件：
   1. 必须在 layer2-search 完成后调用
   2. 必须存在 merge_tasks.json + patch_analysis.json
  
  输出文件：execution_log.json + build_*.log
  
  完成后状态：Write state.json: {"layer3": "completed"}
---

<HARD-GATE>
禁止操作：
❌ git apply（会丢失 commit message）
❌ git am --skip（会跳过 patch）
❌ git reset --hard（会删除 commit）
❌ 自主判断 patch "已存在"而跳过 APPLY 流程
❌ 不经过用户确认就跳过任何 patch（即使 patch 内容看似已存在）
❌ 将多个 patch 合并为一个 commit（N 个 patch = N 个 commit）
❌ 在 scene="unknown" 时继续执行（必须先确认 upgrade/backport）
❌ 未向用户展示任务清单并获得确认就进入执行步骤（必须先执行步骤 1.5）

必须遵循：
✅ 每个 patch 必须经过完整的 APPLY 流程（git am --3way → --reject → 处理 .rej）
✅ git am 会自然检测重复内容——让 git 工具判断，不由 AI 预判
✅ 若 patch 确实已存在，git am 会产出空 commit，这是可接受的
✅ 必须在 Layer 2 完成场景交互（scene 必须为 "upgrade" 或 "backport"）
✅ 任何跳过 patch 的决定必须经用户明确确认
</HARD-GATE>

# Layer 3 - 执行层

## 职责

串行执行 merge 流程：APPLY → VERIFY_INTENT → BUILD → COMMIT → REVIEW，每 patch 完成后落盘 analyse.md。

## 核心约束

1. **串行执行** - merge 步骤不可并行
2. **每 patch commit** - N 个 patch 产生 N 个 commit
3. **build_checkpoint 控制** - 仅在 checkpoint=true 编译验证
4. **强制落盘** - 每 commit 完成后立即 Write analyse.md
5. **门禁验证** - 每步骤调用 gatekeeper.py 标记状态

## 执行流程

### 步骤 1: 读取 config.json + merge_tasks.json

```bash
# 检查是否有未完成的恢复任务
python3 $SCRIPTS_DIR/gatekeeper.py \
  --merges-file "$OUTPUT_DIR/merge_tasks.json" \
  --restore || true

Read: $KERNEL_REPO/patch_analysis/config.json
```

从 config.json 提取全局变量 + 输出目录：
- `KERNEL_REPO_PATH` = config.kernel_repo_path
- `KERNEL_ARCH` = config.kernel_arch
- `BUILD_CMD` = config.build_cmd
- `OUTPUT_DIR` = config.output_dir

```bash
Read: $OUTPUT_DIR/merge_tasks.json
```

从 merge_tasks.json 提取每个 task 的：
- `task_id`, `patch_file`, `build_checkpoint`, `pre_revert`, `action`

### 步骤 1.5: 【HARD-GATE】向用户展示完整任务清单（三阶段）

**必须执行此步骤，不可跳过**。

使用 Question tool 向用户展示完整任务清单（包含Revert、Upstream、Patch三阶段）：

```
=== Layer 3 执行任务清单 ===

Phase 1: Revert旧版本（N个commit）
  | # | commit_hash | subject | ruling_reason |
  |---|-------------|---------|---------------|
  | 1 | abc123 | HDBSS init | 旧版本sysreg部分 |
  | 2 | def456 | HDBSS buffer | 旧版本buffer管理 |
  | 3 | ghi789 | HDBSS ioctl | 旧版本ioctl接口 |
  | ... | ... | ... | ... |
  
  总计：N个commit需revert

Phase 2: 拉取上游依赖（如有）
  | # | task_id | source | subject | action |
  |---|---------|--------|---------|--------|
  | 1 | dep-001 | PR #456 | stage2页表重构 | apply |
  | ... | ... | ... | ... | ... |
  
  总计：M个依赖需拉取（若无则为空）

Phase 3: 应用新patch（N个patch）
  | # | task_id | patch_file | pre_revert | build_checkpoint | checkpoint_reason |
  |---|---------|------------|------------|------------------|-------------------|
  | 1 | 0001 | sysreg.patch | abc123 | true | Rule_1 infra |
  | 2 | 0002 | buffer.patch | def456 | false | Rule_7 其他 |
  | 3 | 0003 | ioctl.patch | ghi789 | true | Rule_6 分组最后 |
  | 4 | 0004 | events.patch | xyz789 | false | Rule_7 其他 |
  | 5 | 0005 | config.patch | pqr456 | true | Rule_6 分组最后 |
  | 6 | 0006 | Documentation.patch | 无 | false | Rule_5 doc |
  
  总计：N个patch，编译点K个（占比 X%）
    - infra：1个
    - 分组最后：Y个
    - 被依赖：Z个（如有）
    - 最后patch：1个（强制）
    - 其他：false

场景：upgrade（版本升级）/ backport（纯新增）

执行顺序：Phase 1 → Phase 2 → Phase 3（串行执行）

请确认是否执行以上任务：
[1] 确认执行（Recommended）
[2] 查看某个patch/commit的详细内容
[3] 中止执行
```

**数据来源**：
- Phase 1: 从 merge_tasks.json 的每个 task 的 `pre_revert` 字段提取所有 commit_hash
- Phase 2: 从 merge_tasks.json 的 `deps_order` 字段提取上游依赖列表
- Phase 3: 从 merge_tasks.json 的 `merge_order` 字段提取新 patch 列表

**统计计算**：
- Phase 1 commit数：统计所有 task 的 pre_revert 字段中的 commit hash 数（去重）
- Phase 2 dep数：deps_order 数组长度
- Phase 3 patch数：merge_order 数组长度
- 编译点数：统计 merge_order 中 build_checkpoint=true 的数量
- 编译点占比：编译点数 / patch数 × 100%

**强制规则**：
- 必须等待用户选择后才能继续
- 用户选择 [1] 才能进入步骤 2
- 用户选择 [3] 则中止流程，写入 state.json: {"layer3": "cancelled"}
- 不得自行跳过此步骤进入执行
- 必须展示完整三阶段任务（不能只展示 Phase 3）

### 步骤 2: Phase 1 - 执行所有 revert 任务

**Phase 1：批量执行所有 revert commit（从所有 task 的 pre_revert 字段提取）**

#### 2.1 提取所有 revert commit hash（去重）

```bash
cd $KERNEL_REPO_PATH

# 从 merge_tasks.json 提取所有 pre_revert commit hash
REVERT_COMMITS=$(python3 -c "
import json
with open('$OUTPUT_DIR/merge_tasks.json') as f:
    tasks = json.load(f)
    commits = set()
    for task in tasks['merge_order']:
        for c in task.get('pre_revert', []):
            commits.add(c)
    print(','.join(sorted(commits)))
")

if [ -z "$REVERT_COMMITS" ]; then
  echo "✅ 无需 revert（pre_revert 为空）"
else
  echo "Phase 1: 执行 revert（共 $(echo $REVERT_COMMITS | tr ',' '\n' | wc -l) 个 commit）"
fi
```

#### 2.2 执行 revert（逆序，单个commit粒度）

```bash
for commit in $(echo "$REVERT_COMMITS" | tr ',' '\n' | tac); do
  # 检测 commit 是否为 merge commit
  PARENT_COUNT=$(git rev-list --parents -n 1 "$commit" | wc -w)
  
  if [ $PARENT_COUNT -gt 2 ]; then
    # merge commit，立即中止
    Question: "检测到 merge commit $commit（有 $((PARENT_COUNT-1)) 个 parent）。

    Revert merge commit 会连带 revert 所有包含的 patch，包括不相关功能。
    pre_revert 字段必须是单个 commit hash，不是 merge commit hash。

    请返回 Layer 2 重新执行 agent_target_revert，展开 merge commit。

    [1] 中止当前任务（Recommended）
    [2] 强制继续（高风险）
    "
    
    if [ "$ANSWER" = "1" ]; then
      exit 22
    fi
  fi
  
  # 单个 commit，执行 revert
  git revert "$commit" || {
    git revert --abort
    Question: "Revert $commit 失败，如何处理？"
      [1] 跳过此 revert
      [2] 手工修复冲突后继续
      [3] 中止整个任务
  }
done

echo "✅ Phase 1 完成：所有 revert commit 已执行"
```

#### 2.3 Phase 1 结束后的强制编译验证

<HARD-GATE>
禁止跳过：
❌ Phase 1 完成后必须编译验证（确认仓库完整性）
</HARD-GATE>

**原因**：
- Revert 可能破坏代码完整性（revert infra commit → 后续 patch 无法编译）
- 为 Phase 3 提供干净的起点
- 避免 Phase 3 开始后才发现 revert 导致仓库不可编译

```bash
cd $KERNEL_REPO_PATH

echo "Phase 1 编译验证：确认 revert 后仓库可编译"

python3 $SCRIPTS_DIR/gatekeeper.py \
  --merges-file "$OUTPUT_DIR/merge_tasks.json" \
  --task-id "phase1_revert" \
  --step BUILD --result in_progress

BUILD_LOG="$OUTPUT_DIR/build_phase1_revert.log"

# 强制重建
rm -f arch/arm64/boot/Image

eval "$BUILD_CMD" 2>&1 | tee "$BUILD_LOG"
BUILD_EXIT=$?

ERROR_COUNT=$(grep -c "^make\[[0-9]*\]: \*\*\*" "$BUILD_LOG" 2>/dev/null || echo 0)

FAILED_REASON=""
PRODUCTS=""
if [ "$BUILD_EXIT" -eq 0 ]; then
  if test -f "arch/arm64/boot/Image" -a -s "arch/arm64/boot/Image"; then
    IMAGE_SIZE=$(du -h arch/arm64/boot/Image | cut -f1)
    PRODUCTS="Image:${IMAGE_SIZE}"
  else
    BUILD_EXIT=20
    FAILED_REASON="Image 产物缺失或为空"
  fi
  if echo "$BUILD_CMD" | grep -qE '(^| )modules($| )'; then
    KO_COUNT=$(find . -name "*.ko" -newer "$BUILD_LOG" 2>/dev/null | wc -l)
    if grep -q "MODPOST" "$BUILD_LOG" 2>/dev/null; then
      PRODUCTS="$PRODUCTS modules:${KO_COUNT}ko"
    else
      BUILD_EXIT=21
      FAILED_REASON="modules 编译无 MODPOST（模块安装未执行）"
    fi
  fi
fi

if [ "$BUILD_EXIT" -ne 0 ]; then
  Question: "Phase 1 编译失败（error=$ERROR_COUNT，原因=${FAILED_REASON:-编译错误}），如何处理？"
    [1] 查看编译错误详情
    [2] 手工修复编译问题
    [3] 回退所有 revert，重新规划
fi

python3 $SCRIPTS_DIR/gatekeeper.py \
  --merges-file "$OUTPUT_DIR/merge_tasks.json" \
  --task-id "phase1_revert" \
  --step BUILD --result pass \
  --error-count "$ERROR_COUNT" \
  --product "$PRODUCTS"

echo "✅ Phase 1 编译验证通过：仓库可编译（$PRODUCTS）"
```

**编译失败处理**：
- 选项 [1]：展示编译错误详情（最近100行）
- 选项 [2]：暂停，保留工作区状态供手工修复
- 选项 [3]：回退所有 revert commit（`git reset --hard ORIG_HEAD`），重新规划

### 步骤 3: Phase 2 - 拉取上游依赖（如有）

若 `merge_tasks.json` 的 `deps_order` 非空：

```bash
cd $KERNEL_REPO_PATH

DEPS_COUNT=$(python3 -c "
import json
with open('$OUTPUT_DIR/merge_tasks.json') as f:
    tasks = json.load(f)
    print(len(tasks.get('deps_order', [])))
")

if [ "$DEPS_COUNT" -gt 0 ]; then
  echo "Phase 2: 拉取上游依赖（共 $DEPS_COUNT 个）"
  
  for dep in $(python3 -c "
import json
with open('$OUTPUT_DIR/merge_tasks.json') as f:
    tasks = json.load(f)
    for d in tasks.get('deps_order', []):
        print(f\"{d['task_id']}|{d['patch_file']}|{d.get('source_pr', '')}\")
"); do
    task_id=$(echo "$dep" | cut -d'|' -f1)
    patch_file=$(echo "$dep" | cut -d'|' -f2)
    source_pr=$(echo "$dep" | cut -d'|' -f3)
    
    echo "拉取依赖：$task_id（来源：$source_pr）"
    
    git am "$patch_file" || {
      Question: "上游依赖 $task_id 应用失败，如何处理？"
        [1] 跳过此依赖
        [2] 手工修复
        [3] 中止任务
    }
  done
  
  echo "✅ Phase 2 完成：所有上游依赖已拉取"
else
  echo "✅ Phase 2：无需拉取上游依赖"
fi
```

<HARD-GATE>
禁止操作（编译产物生成与手工文件保护）：
❌ 自动执行编译产物生成命令（gen-sysreg.awk、生成头文件、生成配置、生成代码等）
❌ 覆盖手工维护的文件（如sysreg.h、某些头文件、配置文件、Makefile等）
❌ 执行未在 BUILD_CMD 中定义的编译命令
❌ 自主推断需要重新生成某个文件
❌ 使用 awk、python、脚本等工具生成或修改非patch涉及的文件

必须遵循：
✅ 编译验证只执行 BUILD_CMD 中定义的命令（如 make ARCH=arm64 Image）
✅ 若发现手工维护的文件被patch修改 → 提示用户确认："patch修改了手工维护的文件 xxx.h，是否继续？"
✅ 若编译失败需修复 → 仅修改patch涉及的文件，不生成新文件
✅ 任何额外的编译/生成命令必须经用户明确确认
✅ 仅在 BUILD 阶段执行编译命令，其他阶段不得执行编译相关命令

特殊情况：
- 若patch明确包含sysreg文件的修改 → sysreg.h不需要重新生成（patch已包含修改）
- 若patch明确需要生成某文件 → patch metadata中会说明，AI不得自行推断
- 手工维护的文件列表（常见）：arch/arm64/include/asm/sysreg.h, include/linux/kvm_host.h, Makefile, Kconfig

**案例警示**：
- 错误操作：AI自主执行 `awk -f gen-sysreg.awk arch/arm64/tools/sysreg > sysreg.h`
- 错误结果：手工维护的sysreg.h（1176行）被自动生成版本（7243行）覆盖，删除了大量寄存器定义
- 正确做法：patch已修改sysreg文件，sysreg.h内容已包含在patch中，不需要重新生成
</HARD-GATE>

### 步骤 4: 预开驱动 CONFIG=m

```bash
cd $KERNEL_REPO_PATH

# 扫描所有 patch 涉改的驱动文件
DRIVER_FILES=$(grep -h "^diff --git a/" /tmp/patches/0*.patch \
  | sed 's/diff --git a\///' | awk '{print $1}' \
  | grep -E "^(drivers|sound)/" | sort -u)

# 提取 CONFIG 符号并开启
for dir in $(dirname $DRIVER_FILES); do
  if [ "$dir" = "." ]; then
    continue
  fi
  makefile="$KERNEL_REPO_PATH/$dir/Makefile"
  if [ -f "$makefile" ]; then
    configs=$(grep -oP 'obj-\$\((\w+)\)' "$makefile" | sed 's/obj-\$(\(.*\))/\1/')
    for cfg in $configs; do
      if ! grep -q "^${cfg}=[my]" .config 2>/dev/null; then
        scripts/config --module "$cfg" 2>/dev/null || true
      fi
    done
  fi
done

make ARCH=$KERNEL_ARCH olddefconfig 2>/dev/null || true
```

### 步骤 5: Phase 3 - 遍历 merge_order（Skill 内循环）

**Phase 3：按 seq 升序应用所有新 patch（每个 patch 的 pre_revert 已在 Phase 1 执行）**

**执行纪律：每个 task 必须完整走完 5.1→5.9，一步都不能跳。gatekeeper --check 在 COMMIT 时强制校验 VERIFY_INTENT 已完成，在 RECORD 时强制校验 REVIEW 已完成，跳过会硬性阻塞。**

AI 按 seq 升序处理每个 task。

**在处理每个 task 前，先读取预分析信息**：

```bash
# 读取 agent_patch_analysis 产出的预制信息
python3 -c "
import json, sys
with open('$OUTPUT_DIR/patch_analysis.json') as f:
    pa = json.load(f).get('$task_id', {})
if not pa:
    print('WARNING: no pre-analysis for $task_id', file=sys.stderr)
    sys.exit(0)
print(f'功能分类: {pa.get(\"功能分类\", \"?\")}')
print(f'功能概述: {pa.get(\"功能概述\", \"?\")}')
print(f'风险等级: {pa.get(\"risk_level\", \"?\")} — {pa.get(\"risk_detail\", \"\")}')
print(f'Review: {pa.get(\"review_required\", \"?\")} — {pa.get(\"review_reason\", \"\")}')
print(f'内部依赖: {pa.get(\"depends_on\", [])}')
print(f'冲突预判: {json.dumps(pa.get(\"conflicts_predicted\", []), ensure_ascii=False)}')
print(f'注意事项: {json.dumps(pa.get(\"special_notes\", []), ensure_ascii=False)}')
print(f'AM 模式: {pa.get(\"execution_guide\", {}).get(\"am_mode\", \"3way\")}')
"
```

**AI 根据预分析调整行为**：
| 条件 | 行为调整 |
|------|----------|
| `risk_level=高` 或 conflicts_predicted 有 high severity | 步骤 5.3 APPLY 使用 `--reject` 模式（手动 .rej 逐行处理） |
| conflicts_predicted 非空 | 在 git am 前 `read` 目标文件确认现状 |
| special_notes 非空 | .rej 解决时逐条参考 |
| execution_guide.am_mode | 覆盖默认 AM 模式（reject 优于 3way） |

**注意**：
- Phase 1 已批量执行所有 revert commit
- Phase 3 的步骤 5.2（PRE_REVERT）不再执行（pre_revert 已在 Phase 1 完成）
- 若 task.pre_revert 非空，说明这些 commit 已在 Phase 1 revert

**在处理每个 task 前提取局部变量**：
- `$task_id` ← task.task_id
- `$seq` ← task.seq
- `$patch_file` ← task.patch_file
- `$pre_revert` ← task.pre_revert（仅用于记录，Phase 1 已执行）
- `$build_checkpoint` ← task.build_checkpoint
- `$checkpoint_reason` ← task.checkpoint_reason

#### 5.1 PRECHECK

```bash
python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step PRECHECK --result in_progress

test -f "$patch_file" || exit 10
git diff --quiet && git diff --cached --quiet || exit 12

python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step PRECHECK --result pass
```

#### 5.2 PRE_REVERT（已跳过，Phase 1 已执行）

**说明**：
- Phase 1 已批量执行所有 revert commit（步骤 2）
- Phase 3 不再执行 pre_revert（避免重复 revert）
- task.pre_revert 字段仅用于记录，不触发 revert 操作

```bash
# 标记 PRE_REVERT 为 skip（Phase 1 已执行）
python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step PRE_REVERT --result skip --note "Phase 1 completed"
```

#### 5.3 APPLY

<HARD-GATE>
禁止操作：
❌ git apply（会丢失 commit message）
❌ git am --skip（会跳过 patch）
❌ 自主判断 patch "已存在"而跳过 APPLY 流程

必须遵循：
✅ 调用 conflict-resolver skill 执行 git am --3way → --reject → .rej 处理
✅ 仅在 conflict-resolver 返回失败（重试 10 次仍失败）时才阻塞，向用户问询
</HARD-GATE>

```bash
python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step APPLY --result in_progress

# 调用 conflict-resolver skill 执行 git am 循环
# 输入：patch_file, repo_path
# 成功时自动完成 git am + .rej 处理
# 失败时（exit 1）暂停，等待用户决策
Skill tool: conflict-resolver
  输入: patch_file=$patch_file, repo_path=$KERNEL_REPO_PATH

# 检查 conflict-resolver 是否成功
if git diff --quiet && git diff --cached --quiet; then
  # 无变更，可能未成功
  Question: "conflict-resolver 未能应用 patch $task_id，如何处理？"
    [1] 跳过此 patch
    [2] 暂停，保留工作区供人工修复
    [3] 中止任务
fi

python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step APPLY --result pass
```

#### 5.4 VERIFY_INTENT

```bash
python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step VERIFY_INTENT --result in_progress

python3 $SCRIPTS_DIR/verify_patch_intent.py \
  --patch-file "$patch_file" \
  --merges-file "$OUTPUT_DIR/merge_tasks.json" \
  --task-id $task_id \
  --repo-path "$KERNEL_REPO_PATH"

python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step VERIFY_INTENT --result pass
```

#### 5.5 BUILD（若 build_checkpoint=true）

**若 build_checkpoint=false**: 跳过 BUILD，直接进入 COMMIT。

<HARD-GATE>
强制约束：必须编译整个仓库，不可跳过、不可只编译部分文件！

| 禁止操作 | 原因 | 正确做法 |
|---------|------|---------|
| `make <目标>` 单文件编译 | 无法验证 patch 改动的全局影响 | `$BUILD_CMD` 完整编译 |
| 跳过产物验证 | 编译成功 ≠ 产物存在 | 动态校验：Image（始终）+ modules/ dtbs（按 BUILD_CMD 目标） |
| 复用旧产物 | make 可能因 timestamp 跳过实际编译 | 编译前 `rm -f arch/arm64/boot/Image` |
</HARD-GATE>

```bash
python3 $SCRIPTS_DIR/gatekeeper.py \
  --merges-file "$OUTPUT_DIR/merge_tasks.json" \
  --task-id $task_id \
  --step BUILD --result in_progress

# 编译日志持久化
BUILD_LOG="$OUTPUT_DIR/build_${task_id}.log"
echo "编译命令: $BUILD_CMD"

# 强制重建：编译前删除产物，防止 make timestamp 优化跳过实际编译
rm -f arch/arm64/boot/Image

eval "$BUILD_CMD" 2>&1 | tee "$BUILD_LOG"
BUILD_EXIT=$?

# 统计 error 数
ERROR_COUNT=$(grep -c "^make\[[0-9]*\]: \*\*\*" "$BUILD_LOG" 2>/dev/null || echo 0)

# 动态产物校验（根据 BUILD_CMD 目标决定检查项）
PRODUCTS=""
FAILED_REASON=""
if [ "$BUILD_EXIT" -eq 0 ]; then
  # Image：所有 arm64 编译都检查
  if test -f "arch/arm64/boot/Image" -a -s "arch/arm64/boot/Image"; then
    IMAGE_SIZE=$(du -h arch/arm64/boot/Image | cut -f1)
    PRODUCTS="Image:${IMAGE_SIZE}"
  else
    BUILD_EXIT=20
    FAILED_REASON="Image 产物缺失或为空"
  fi

  # Modules：BUILD_CMD 含 modules 目标时检查
  if echo "$BUILD_CMD" | grep -qE '(^| )modules($| )'; then
    KO_COUNT=$(find . -name "*.ko" -newer "$BUILD_LOG" 2>/dev/null | wc -l)
    if grep -q "MODPOST" "$BUILD_LOG" 2>/dev/null; then
      PRODUCTS="$PRODUCTS modules:${KO_COUNT}ko"
    else
      BUILD_EXIT=21
      FAILED_REASON="modules 编译无 MODPOST（模块安装未执行）"
    fi
  fi
fi

if [ "$BUILD_EXIT" -ne 0 ]; then
  echo "❌ 编译失败，error 数=$ERROR_COUNT，原因=${FAILED_REASON:-编译错误}，见 $BUILD_LOG"
  exit $BUILD_EXIT
fi

python3 $SCRIPTS_DIR/gatekeeper.py \
  --merges-file "$OUTPUT_DIR/merge_tasks.json" \
  --task-id $task_id \
  --step BUILD --result pass \
  --error-count "$ERROR_COUNT" \
  --product "$PRODUCTS" \
  --build-target "$BUILD_CMD" \
  --build-log "$BUILD_LOG"

echo "[BUILD CHECKPOINT] $task_id: ✅ 编译通过（$PRODUCTS）"
```

#### 5.6 BUILD_FIX（编译失败修复）

<HARD-GATE>
编译失败时，绝对禁用：
❌ git reset --hard
❌ git reset --soft
❌ 批量 git commit --amend

允许：
✅ git rebase -i HEAD~N
✅ git commit --amend --no-edit
</HARD-GATE>

**根因定位**：三重匹配（文件匹配 → 符号匹配 → 功能匹配）

**错误分类修复**：

| 错误类型 | 处理方式 |
|---------|---------|
| 当前 checkpoint 组内某 patch 语法/逻辑错误 | rebase amend 该 patch |
| 调用不存在的符号 | 标记为缺失依赖，检查是否需要插入新 dep |
| patch 引入的新功能需要新 CONFIG | 启用 CONFIG，amend 到对应 patch |
| 非 patch 的环境 CONFIG 缺失 | 临时启用 CONFIG → make → 编译后记录在 analyse.md |

**rebase amend 修复流程**：
```bash
# 假设出错 patch 是 0003，当前在 0005（checkpoint）
N=3  # 覆盖 0003/0004/0005
git rebase -i HEAD~$N
# 将 0003 标记为 "edit"

# 在 0003 上修复
vim <错误文件>
make ARCH=$KERNEL_ARCH -j$(nproc)    # 验证修复

git add <只改过的文件>            # 禁止 -A，禁止 -a
git commit --amend --no-edit     # 不改 message
git rebase --continue
```

**10 轮失败处理**：
累计 10 次冲突解决或编译修复未通过 → 暂停等待用户决策，输出：

1. **冲突定位**：精确到 文件:行号:函数名 + 错误原文
2. **根因分析**：Ours vs Theirs 代码对比 / 编译器错误原文 / 语义矛盾点
3. **可选方案（2-4 个）**：
   - 方案 A: 具体步骤 → 影响范围 → 风险 → 所需额外工作
   - 方案 B: ...
   - 方案 C: skip 此 patch（标注后续依赖程度）
4. **推荐**（标注理由）

#### 5.7 COMMIT

```bash
python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step COMMIT --result in_progress

# 门禁检查：build_checkpoint=true 时 BUILD 必须已通过，否则阻塞
python3 $SCRIPTS_DIR/gatekeeper.py \
  --merges-file "$OUTPUT_DIR/merge_tasks.json" \
  --task-id $task_id \
  --step COMMIT --check

SUBJECT=$(grep "^Subject:" "$patch_file" | sed 's/Subject: //')
AUTHOR=$(grep "^From:" "$patch_file" | sed 's/From: //')

git commit --author="$AUTHOR" -F- <<COMMIT_MSG
$SUBJECT
COMMIT_MSG

COMMIT_HASH=$(git rev-parse HEAD)

python3 $SCRIPTS_DIR/gatekeeper.py \
  --merges-file "$OUTPUT_DIR/merge_tasks.json" \
  --task-id $task_id \
  --step COMMIT --result pass \
  --commit "$COMMIT_HASH"
```

#### 5.8 REVIEW

```bash
python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step REVIEW --result in_progress
```

**启动独立 Subagent 做 review（Task tool，隔离上下文）**：

```
Task tool: subagent_type: general
输入:
  task_id=$task_id
  patch_file=$patch_file
  commit_hash=$COMMIT_HASH（来自步骤 5.7）
  KERNEL_REPO_PATH

Subagent prompt（内联全部 review 检查清单）:

---

你是 Linux 内核代码 review 专家。对以下已合入的 commit 做专项 review。

**输入数据（自行 Read）**：
1. `git -C <KERNEL_REPO_PATH> show <commit_hash>` → 实际 diff + commit message
2. Read: `<patch_file>` → 原始 .patch 文件（对比意图）
3. verify_patch_intent 退出码（从 gatekeeper state_log 获取）:
   - 0=+ 行完整
   - 1=部分 + 行缺失（可能适配）
   - 3=introduced_symbols 缺失（P0）

**检查项**：

### 1. Commit message 完整性
| 检查点 | 规则 | 严重度 |
|--------|------|--------|
| Subject | 不能空，应有子系统前缀（arm64:/KVM:/mm:），≤75 字符 | P1 |
| Signed-off-by | 至少一个 DCO 签名 | P1 |
| Fixes tag | 原 patch 有则不应丢失 | P2 |
| 其他 tag | Reviewed-by/Acked-by/Tested-by/Cc | P3 |
| 空行分隔 | Subject 和 body 之间有空行 | P3 |

### 2. 代码安全性
| 检查点 | 规则 | 严重度 |
|--------|------|--------|
| 内存配对 | kmalloc/kfree, alloc_pages/free_pages 等成对 | P0 |
| goto cleanup | 错误路径是否正确释放，有无遗漏 | P0 |
| 锁使用 | spin_lock/spin_unlock 配对，持锁期间不应睡眠 | P0 |
| RCU | rcu_read_lock/rcu_read_unlock 配对，rcu_dereference 正确 | P1 |
| 错误返回值 | IS_ERR/PTR_ERR 检查，-ENOMEM 风格一致 | P1 |
| 数组/缓冲区 | 越界风险，sizeof 正确，snprintf 长度 | P1 |
| refcount | refcount_t/atomic_t inc/dec 配对 | P1 |

### 3. API 兼容性（backport 专属）
| 检查点 | 规则 | 严重度 |
|--------|------|--------|
| 函数存在性 | 目标内核是否有被调用函数原型 | P0 |
| 签名匹配 | 参数数量/类型是否一致 | P0 |
| 宏/CONFIG | 依赖的 CONFIG_xxx 在目标 .config 是否存在 | P0 |
| 结构体字段 | 访问的结构体成员在目标版本中是否存在 | P1 |
| 头文件 | include 路径在目标内核中是否存在 | P2 |

### 4. Patch 意图保留
| 检查点 | 规则 | 严重度 |
|--------|------|--------|
| introduced_symbols 缺失 | verify exit 3 → P0 | P0 |
| + 行缺失 | verify exit 1 → 分析是适配还是丢失 | P1/P2 |
| + 行完整 | verify exit 0 → 通过 | — |

**输出（Write + 返回）**：

Write `$OUTPUT_DIR/review_<task_id>.md`，格式：

```markdown
## Code Review — Patch {task_id}: {subject}

### Commit message
[逐项检查结果]

### 安全性
[逐项检查结果]

### API 兼容
[逐项检查结果]

### Patch 意图
[逐项检查结果]

### 总结
P0: N, P1: N, P2: N, P3: N
blocking: true/false
```

返回给主 Agent 的消息：
```
REVIEW_RESULT: task_id=<task_id> P0=<N> P1=<N> P2=<N> blocking=<true|false>
```
```

**Subagent 返回后，主 AI 处理**：

```bash
# 读取 review 结果
Read: $OUTPUT_DIR/review_$task_id.md
```

**阻塞判断**：
- `blocking=true` 或 P0 > 0 → 暂停等用户决策：
  ```
  Patch {task_id} review 发现 P0 问题：
  [列出 P0 项]
  
  请选择：
  [1] 修复 P0 后继续（git commit --amend）
  [2] 接受风险继续（不推荐）
  [3] 中止
  ```
- `blocking=false` → 继续流程

```bash
python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step REVIEW --result pass
```

#### 5.9 RECORD

```bash
python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step RECORD --result in_progress

# 门禁检查：REVIEW 必须已完成
python3 $SCRIPTS_DIR/gatekeeper.py \
  --merges-file "$OUTPUT_DIR/merge_tasks.json" \
  --task-id $task_id \
  --step RECORD --check

python3 $SCRIPTS_DIR/gatekeeper.py \
  --merges-file "$OUTPUT_DIR/merge_tasks.json" \
  --task-id $task_id \
  --step DONE --result pass
```