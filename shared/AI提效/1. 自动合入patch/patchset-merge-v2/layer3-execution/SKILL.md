---
name: layer3-execution
description: >
  Patchset-merge 执行层：串行 merge、编译验证、commit、review。
  
  强制前置条件：
  1. 必须在 layer2-search 完成后调用
  2. 必须存在 merge_tasks.json
  
  输出文件：analyse.md 系列 + execution_log.json
  
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

### 步骤 1: 读取 merge_tasks.json + config.json

```bash
Read: $KERNEL_REPO/patch_analysis/merge_tasks.json
Read: $KERNEL_REPO/patch_analysis/config.json
```

从 config.json 提取全局变量：
- `KERNEL_REPO_PATH` = config.kernel_repo_path
- `KERNEL_ARCH` = config.kernel_arch
- `BUILD_CMD` = config.build_cmd

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
with open('patch_analysis/merge_tasks.json') as f:
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

# 执行编译
eval "$BUILD_CMD"

if [ $? -eq 0 ]; then
  # 根据架构选择对应的编译产物路径
  case $KERNEL_ARCH in
    arm64) test -f "arch/arm64/boot/Image" || BUILD_FAIL=1 ;;
    x86_64) test -f "arch/x86/boot/bzImage" || BUILD_FAIL=1 ;;
    *) echo "⚠️ 未知架构 $KERNEL_ARCH，跳过产物检查" ;;
  esac
  
  if [ -z "$BUILD_FAIL" ]; then
    echo "✅ Phase 1 编译验证通过：仓库可编译"
    git status
  else
    Question: "Phase 1 编译失败：revert 后仓库不可编译。

    可能原因：
    - Revert 破坏了依赖关系（如 revert infra commit）
    - Revert 顺序不正确
    - 存在未发现的 revert 冲突

    [1] 查看编译错误详情
    [2] 手工修复编译问题
    [3] 回退所有 revert，重新规划
    "
  fi
else
  Question: "Phase 1 编译失败，如何处理？"
    [1] 查看编译错误
    [2] 手工修复
    [3] 中止任务
fi
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
with open('patch_analysis/merge_tasks.json') as f:
    tasks = json.load(f)
    print(len(tasks.get('deps_order', [])))
")

if [ "$DEPS_COUNT" -gt 0 ]; then
  echo "Phase 2: 拉取上游依赖（共 $DEPS_COUNT 个）"
  
  for dep in $(python3 -c "
import json
with open('patch_analysis/merge_tasks.json') as f:
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

AI 按 seq 升序处理每个 task。

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

#### 5.3 APPLY（强制 git am 循环重试）

**上下文缺失的处理原则**：

patch 中以空格开头的上下文行（如 ` #define KVM_PTE_LEAF_ATTR_HI_S2_XN`）是 git 的定位依据，
不是必须存在的代码。git am --reject 会将不能应用的部分写入 .rej 文件，AI 处理 .rej 即可。

<HARD-GATE>
禁止操作：
❌ git apply（会丢失 commit message）
❌ git am --skip（会跳过 patch）
❌ 在 git am 执行前分析 patch 上下文是否在目标文件中存在
❌ 因为上下文行缺失而提前阻塞流程（如提示"缺少基础设施定义"）
❌ 在 git am --reject 执行前暂停向用户问询

必须遵循：
✅ 先执行 git am --3way，让 git 工具判断
✅ 失败后执行 git am --3way --reject
✅ AI 处理 .rej 文件时智能判断插入位置（参考 references/diagnostic-guide.md）
✅ 仅在 10 次重试全部失败后才阻塞，向用户问询
</HARD-GATE>

**说明**：
- 参考 `references/diagnostic-guide.md` 中的 Ours/Theirs 决策树
- 参考 `references/diagnostic-guide.md` 中的最小修改原则

```bash
python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step APPLY --result in_progress

RETRY_COUNT=0

while true; do
  ### 尝试 1: git am --3way
  git am --3way "$patch_file"
  
  if [ $? -eq 0 ]; then
    echo "✅ git am 成功"
    break
  else
    ### 尝试 2: git am --3way --reject
    git am --abort
    git am --3way --ignore-space-change --keep-cr --reject "$patch_file"
    
    ### 循环处理 .rej 文件
    while [ -n "$(find . -name '*.rej')" ]; do
      for rej_file in $(find . -name "*.rej"); do
        Read: "$rej_file"
        Read: 目标文件
        AI 判断如何填入
        Edit: 目标文件
        rm "$rej_file"
      done
    done
    
    ### 尝试 3: git add + git am --continue
    git add -A
    git am --continue
    
    if [ $? -eq 0 ]; then
      echo "✅ 成功"
      break
    else
      RETRY_COUNT=$((RETRY_COUNT + 1))
      if [ $RETRY_COUNT -ge 10 ]; then
        Question: "git am 已重试 10 次仍失败，如何处理？"
          [1] 放弃当前 patch，跳过（git am --abort）
          [2] 暂停，保留工作区状态供人工修复
          [3] 中止整个任务
      fi
    fi
  fi
done

python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step APPLY --result pass
```

#### 5.4 VERIFY_INTENT

```bash
python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step VERIFY_INTENT --result in_progress

python3 $SCRIPTS_DIR/verify_patch_intent.py \
  --patch-file "$patch_file" \
  --task-id $task_id

python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step VERIFY_INTENT --result pass
```

#### 5.5 BUILD（若 build_checkpoint=true）

```bash
python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step BUILD --result in_progress

eval "$BUILD_CMD"

if [ $? -eq 0 ]; then
  # 根据架构选择对应的编译产物路径
  case $KERNEL_ARCH in
    arm64) test -f "arch/arm64/boot/Image" || exit 20 ;;
    x86_64) test -f "arch/x86/boot/bzImage" || exit 20 ;;
    *) echo "⚠️ 未知架构 $KERNEL_ARCH，跳过产物检查" ;;
  esac
fi

python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step BUILD --result pass
```

**若 build_checkpoint=false**: 跳过 BUILD

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

**rebase amend 修复流程**：
```bash
N=<出错 patch 到当前 checkpoint 的 patch 数>
git rebase -i HEAD~$N

vim <错误文件>
make ARCH=$KERNEL_ARCH -j$(nproc)
git add <只修改的文件>
git commit --amend --no-edit
git rebase --continue
```

#### 5.7 COMMIT

```bash
python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step COMMIT --result in_progress

SUBJECT=$(grep "^Subject:" "$patch_file" | sed 's/Subject: //')
AUTHOR=$(grep "^From:" "$patch_file" | sed 's/From: //')

git commit --author="$AUTHOR" -F- <<COMMIT_MSG
$SUBJECT
COMMIT_MSG

python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --step COMMIT --result pass
```

#### 5.8 REVIEW

```bash
Skill tool: code-review-expert（若已安装）
```

#### 5.9 RECORD

```bash
python3 $SCRIPTS_DIR/generate_analyse_md.py --task-id $task_id

python3 $SCRIPTS_DIR/gatekeeper.py --task-id $task_id --result done
```