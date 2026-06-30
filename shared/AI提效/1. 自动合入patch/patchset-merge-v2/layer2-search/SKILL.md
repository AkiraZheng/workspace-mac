---
name: layer2-search
description: >
  Patchset-merge 搜索层：下载 patch、检测旧版本、场景问询、目标仓库 revert patch 搜索 + upstream 依赖 patch 搜索。
  
  强制前置条件：
  1. 必须在 layer1-interaction 完成后调用
  2. 必须存在 config.json（由 layer1 输出）
  3. 若违反前置条件 → 立即中止
  
  输出文件：
  - /tmp/patches/（下载的 patch 文件）
  - samples_summary.json（抽样检测结果，快速）
  - duplicate_analysis.json（简化版匹配分析）
  - patch_analysis.json（agent_patch_analysis 产出，语义分析 + 风险 + 依赖）
  - revert_candidates.json
  - deps_candidates.json
  - merge_tasks.json
  
  完成后状态：Write state.json: {"layer2": "completed"}
---

# Layer 2 - 搜索层

<HARD-GATE>
禁止操作：
❌ 跳过步骤 3（场景问询）直接进入步骤 4
❌ scene 仍为 "unknown" 时继续后续流程
❌ AI 自主决定场景（upgrade/backport）而不询问用户

必须遵循：
✅ 必须执行步骤 3 的场景问询流程（抽样检测 → 展示结果 → 用户选择）
✅ scene 必须被设为 "upgrade" 或 "backport" 后才能进入步骤 4
✅ 步骤 3d 必须将 scene 写入 config.json
</HARD-GATE>

## 职责

下载 patch、检测旧版本、让用户选择合入场景（upgrade/backport）、并行启动两个 Subagent 搜索 revert 候选和 upstream 依赖，AI 汇总合并后生成 merge_tasks.json。

## 核心特性

- **下载 patch** - 支持三种方式（b4 message-id、wget URL、本地路径复制）
- **场景问询** - 检测旧版本实现，让用户选择 upgrade 或 backport
- **Subagent 并行** - 一条消息内同时启动两个 Task
- **不调 Python 脚本** - Subagent 内使用 Bash git 命令
- **AI 汇总** - 主 Agent 在 Skill 内合并逻辑（迁移 topo_sort.py 等）

## 执行步骤

### 步骤 1: 读取配置 + 反向验证

```bash
Read: $KERNEL_REPO/patch_analysis/config.json
```

**反向验证**：读取 config.json 后，必须校验其内容有效性：

```bash
cd $KERNEL_REPO

# 1. 必填字段检查
MISSING=$(python3 -c "
import json
with open('patch_analysis/config.json') as f:
    c = json.load(f)
required = ['patch_source', 'kernel_repo_path', 'kernel_branch', 'kernel_arch', 'build_cmd']
missing = [k for k in required if k not in c or not c[k]]
if missing:
    print(', '.join(missing))
" 2>/dev/null)

if [ -n "$MISSING" ]; then
    echo "❌ config.json 必填字段缺失或为空: $MISSING"
    echo "请回到 Layer 1 重新生成"
    exit 10
fi

# 2. 路径一致性校验
CONFIG_REPO=$(python3 -c "
import json
with open('patch_analysis/config.json') as f:
    print(json.load(f).get('kernel_repo_path', ''))
" 2>/dev/null)

if [ "$CONFIG_REPO" != "$KERNEL_REPO" ]; then
    echo "❌ config.json.kernel_repo_path 与实际不一致: config=$CONFIG_REPO actual=$KERNEL_REPO"
    exit 11
fi

# 3. schema_version 校验
SV=$(python3 -c "
import json
with open('patch_analysis/config.json') as f:
    print(json.load(f).get('schema_version', 'MISSING'))
" 2>/dev/null)

if [ "$SV" = "MISSING" ]; then
    echo "⚠️ config.json 缺少 schema_version 字段（可能是旧版 Layer 1 生成）"
elif [ "$SV" != "1.0" ]; then
    echo "❌ config.json schema_version=$SV，Layer 2 期望 1.0，接口可能不兼容"
    exit 12
fi

echo "✅ config.json 反向验证通过"

# 4. 提取输出目录（所有中间文件写入此处，避免多分支操作覆盖）
OUTPUT_DIR=$(python3 -c "
import json
with open('patch_analysis/config.json') as f:
    print(json.load(f)['output_dir'])
" 2>/dev/null)
mkdir -p "$OUTPUT_DIR"
echo "输出目录: $OUTPUT_DIR"
```

### 步骤 2: 下载 patch（调用脚本）

```bash
cd $KERNEL_REPO

# 从 config.json 提取 patch_source
PATCH_SOURCE=$(python3 -c "
import json
with open('patch_analysis/config.json') as f:
    print(json.load(f)['patch_source'])
")

# 下载 patch 到 /tmp/patches/
python3 $SCRIPTS_DIR/download_patches.py \
  --source "$PATCH_SOURCE" \
  --output /tmp/patches/ \
  --repo-path "$KERNEL_REPO"

# 验证下载结果
PATCH_COUNT=$(ls /tmp/patches/0*.patch 2>/dev/null | wc -l)
if [ $PATCH_COUNT -eq 0 ]; then
  echo "❌ 错误：未下载到任何 patch 文件"
  exit 21
fi

echo "✅ 已下载 $PATCH_COUNT 个 patch 文件到 /tmp/patches/"
```

执行时间：message-id (b4) <2min，URL (wget) <30s，local copy <5s。

### 步骤 3: 场景问询（抽样检测 + 用户选择）

编译验证开始前，需要确定是否存在旧版本实现，并让用户选择合入场景。

#### 3a. 抽样检测（快速，<2s）

**策略**：从 patch 中提取关键代码行，在目标仓库对应文件中查找是否已存在。

```bash
cd $KERNEL_REPO

# 步骤 1: 提取抽样（Python 快脚本，<1s）
python3 $SCRIPTS_DIR/detect_duplicate_sample.py \
  /tmp/patches/ \
  "$KERNEL_REPO" \
  $OUTPUT_DIR/samples_summary.json \
  > /tmp/grep_commands.txt

# 步骤 2: 并行执行 grep（Bash，<1s）
while IFS='|' read -r task_id file sample; do
    if [ -f "$KERNEL_REPO/$file" ]; then
        # grep 查找（超快，<0.1s per file）
        grep -F -n "$sample" "$KERNEL_REPO/$file" > /tmp/match_$task_id.txt &
    fi
done < /tmp/grep_commands.txt
wait

# 步骤 3: 统计匹配结果
for task_id in $(ls /tmp/match_*.txt 2>/dev/null | sed 's/match_//' | sed 's/.txt//'); do
    match_count=$(wc -l < /tmp/match_$task_id.txt)
    echo "[$task_id] 匹配行数: $match_count"
done

echo "✅ 抽样检测完成（执行时间 <2s）"
```

**Read samples_summary.json**：
- 每个 patch 的涉改文件列表
- 每个 patch 的符号样本（函数定义、宏定义、结构体定义）
- 每个 patch 的关键词样本（大写关键词）
- 每个 patch 的代表性代码（前5行新增代码）
- 每个 patch 的关键词列表（用于后续扩展搜索）

#### 3b. AI 分析匹配结果（Skill 内逻辑）

**AI 读取 /tmp/match_*.txt + samples_summary.json，判断匹配程度**：

| 匹配行数 | 判断 | 说明 |
|---------|------|------|
| **0 行** | 无匹配 | 目标仓库无相关实现 → **backport 场景** |
| **1-2 行** | 低匹配 | 可能误报（相似代码但非重复） → AI 需进一步分析 |
| **3-5 行** | 中匹配 | 可能存在旧版本 → **需用户确认** |
| **≥6 行** | 高匹配 | 高概率重复 → **upgrade 场景** |

**AI 输出简化版 duplicate_analysis.json**：

```json
{
  "schema_version": "1.0",
  "patch_duplicate_map": {
    "0001": [
      {
        "match_type": "sampling",
        "match_count": 7,
        "match_level": "高匹配",
        "matched_files": ["arch/arm64/kvm/hdbss.c"],
        "matched_samples": ["static int hdbss_init", "#define HDBSS_ENABLE"],
        "ruling": "疑似旧版本",
        "ruling_reason": "抽样检测发现7行匹配，建议 upgrade 模式"
      }
    ]
  },
  "keywords_summary": {
    "0001": ["HDBSS", "FEAT_HDBSS", "DBM"]
  },
  "total_patches": 5,
  "patches_with_matches": 3,
  "recommended_scene": "upgrade"
}
```

#### 3c. 展示检测结果 + 用户问询

**AI 将抽样检测结果以简洁形式展示**：

```
═══════════════════════════════════════════════
  抽样检测结果（快速检测，<2s）
═══════════════════════════════════════════════

┌─────┬────────┬────────────┬──────────┬──────────────────────────────┐
│ Seq │ Patch  │ 匹配行数   │ 判断     │ 关键词                       │
├─────┼────────┼────────────┼──────────┼──────────────────────────────┤
│  1  │ 0001   │ 7 行       │ 高匹配   │ HDBSS, FEAT_HDBSS, DBM       │
│  2  │ 0002   │ 3 行       │ 中匹配   │ HDBSS, stage2_map            │
│  3  │ 0003   │ 0 行       │ 无匹配   │ PERF, tracepoint             │
│  4  │ 0004   │ 0 行       │ 无匹配   │ Documentation                │
│  5  │ 0005   │ 1 行       │ 低匹配   │ vmalloc（可能误报）          │
└─────┴────────┴────────────┴──────────┴──────────────────────────────┘

[场景建议] 基于抽样检测结果：
  - 3 个 patch 检测到匹配 → 建议版本升级（upgrade）
  - 2 个 patch 无匹配 → 可能纯新增（backport）

[关键词提取] 自动提取的特征关键词（供 agent_target_revert 扩展搜索）：
  HDBSS, FEAT_HDBSS, DBM, HDBSSF, HDBSSBR_EL2
```

**用户问询（选择合入场景）**：

```
═══════════════════════════════════════════════
  场景问询 — 请选择合入场景
═══════════════════════════════════════════════

请选择合入场景：

[1] 版本升级（upgrade）
    检测到高/中匹配，目标仓库可能已有旧版本实现。
    agent_target_revert 会做 AI 深度搜索旧版本（关键词聚合 + revert追溯 + bugfix补充）。

[2] 纯新增（backport）
    目标仓库无相关实现，抽样匹配为误报或极相似代码。
    agent_target_revert 只做严格审核（diff ≥90% → 暂停）。

[3] 查看详细匹配
    展示某个 patch 的完整匹配信息（匹配行内容、文件路径）。

[4] 中止
    不执行任何操作，导出检测结果。

  请选择: [1] 版本升级 / [2] 纯新增 / [3] 查看详细 / [4] 中止
```

**用户选择后的行为**：

| 选择 | 后续 |
|------|------|
| [1] 版本升级 | 记录场景为 `upgrade`，agent_target_revert 在步骤 4 做 AI 深度搜索旧版本 |
| [2] 纯新增 | 记录场景为 `backport`，agent_target_revert 只做严格审核（diff ≥90% → 暂停） |
| [3] 查看详细 | 展示指定 patch 的 /tmp/match_$task_id.txt 详细内容 |
| [4] 中止 | 退出，samples_summary.json 已保存，用户可手动审查 |

#### 3d. 更新 config.json 的 scene 字段

```bash
cd $KERNEL_REPO

# 从 config.json 提取当前内容
python3 -c "
import json
with open('patch_analysis/config.json') as f:
    config = json.load(f)
config['scene'] = '$SCENE'  # upgrade 或 backport
with open('patch_analysis/config.json', 'w') as f:
    json.dump(config, f, indent=2)
"

echo "✅ config.json 已更新：scene=$SCENE"
```

### 步骤 4: 并行启动搜索 Subagent

**一条消息内同时启动两个 Task**：

```markdown
Task 1: agent_target_revert
  输入: 
    - config.json（含 KERNEL_REPO_PATH, keywords, scene）
    - duplicate_analysis.json（旧版本检测结果）
  工具权限: Bash, Read, Write
  执行模式: 不调 Python 脚本，直接用 Bash git 命令
  
  **根据 scene 执行不同策略**：
  
  ### upgrade 模式（AI 深度搜索）
  
  1. 读取 `duplicate_analysis.json` 中的 `keywords_summary`（抽样检测提取的关键词）
  2. 读取 `samples_summary.json` 中的 `files`（涉改文件，用于限定搜索范围）
  
  **扩展搜索流程**（使用 Bash git 命令，不调 Python 脚本）：
  
  ```bash
  # 步骤 1: 关键词聚合（限定涉改目录）
  for kw in ${keywords[@]}; do
    git log --grep="$kw" --oneline -n 50 "${files[@]}" > /tmp/kw_search_$kw.txt
  done
  
  # 步骤 2: Revert 追溯（从 revert commit 找原始 commit）
  git log --grep="Revert" --grep="$kw" -i --all-match --oneline -n 30 > /tmp/revert_search.txt
  
  # 步骤 3: 符号追溯（git log -S）
  for sym in ${symbols[@]}; do
    git log -S "$sym" --oneline -n 20 "${files[@]}" > /tmp/sym_search_$sym.txt
  done
  
  # 步骤 4: 文件追溯（git log --）
  git log --oneline -n 20 "${files[@]}" > /tmp/file_search.txt
  ```
  
  3. **深入理解**：读取每个候选 commit 的 message + diff，AI 判断：
     - 是否是旧版本的功能实现？ → confirm
     - 是否是无关注释/格式/doc/无关 bugfix？ → reject
     - **merge commit 必须展开**（强制执行）：
       
       **检测方法**：
       ```bash
       PARENT_COUNT=$(git rev-list --parents -n 1 "$commit" | wc -w)
       # PARENT_COUNT > 2 表示 merge commit（有多个 parent）
       ```
       
       **展开处理**：
       ```bash
       # 用 git log 展开 merge commit 的子 commit 列表
       git log --oneline "$commit~1..$commit"
       
       # 输出示例：
       # abc123 patch 1: HDBSS init
       # def456 patch 2: HDBSS buffer
       # ghi789 patch 3: HDBSS ioctl
       ```
       
       **写入 revert_candidates.json 的规则**：
       - ❌ **禁止**写入 merge commit hash（如 `b1d8169dd540`, `fe4fa7481191`）
       - ✅ **必须**写入展开后的子 commit hash（如 `abc123`, `def456`, `ghi789`）
       - ✅ 每个子 commit 单独一个 candidate entry
       
       **示例输出**：
       ```json
       {
         "commit_hash": "abc123",
         "subject": "patch 1: HDBSS init",
         "ruling": "confirm",
         "ruling_reason": "旧版本 HDBSS 实现的 patch 1",
         "revert_cmd": "git revert abc123"
       }
       ```
       
       **原因**：
       - Revert merge commit 会连带 revert 所有包含的 patch（包括不相关功能）
       - 导致后续 patch 应用冲突或代码丢失
       - 单个 commit 粒度 revert 才能精准控制范围
  
  4. **去重合并**：将关键词聚合、revert追溯、符号追溯、文件追溯的结果合并去重
  
  5. **输出**：Write revert_candidates.json（包含 commit_hash + ruling + ruling_reason）
  
  ### backport 模式（严格审核）
  
  1. 读取 `duplicate_analysis.json` 中的抽样检测结果
  
  2. **不启动扩展搜索**（纯新增场景，深度搜索仅限 upgrade 模式）
  
  3. **严格审核**：
     - 对于 match_count >= 6 的 patch → 暂停，提示用户确认："抽样检测发现高匹配（≥6行），是否真的要忽略？"
     - 对于 match_count < 6 的 patch → 直接标记为 reject（误报或极相似代码）
  
  4. **输出**：Write revert_candidates.json（通常为空列表或少量需用户确认的候选）
  
  输出要求: Write revert_candidates.json
  
Task 2: agent_patch_analysis
  输入: 
    - /tmp/patches/000N-*.patch（全部 patch 原始文件）
    - samples_summary.json（抽样检测结果）
    - patch_symbols.json（符号提取结果）
    - config.json（含 KERNEL_REPO_PATH, UPSTREAM_REPO_PATH）
  工具权限: Bash, Read, Write
  执行模式: 不调 Python 脚本，直接用 Bash git 命令
  输出要求:
    - 必产: Write patch_analysis.json
    - 若有 upstream_repo_path: Write deps_candidates.json

  详细执行流程见 agents/agent_patch_analysis_SKILL.md：
  
  1. 读取所有 .patch → 理解功能 → 填 功能分类/功能概述/review_required
  2. 对比目标仓库（git grep 现有代码 vs patch 改动行）→ 填 conflicts_predicted/risk_level
  3. 跨 patch 符号交叉（patch_symbols.json）→ 填 depends_on
  4. 若 config 含 upstream_repo_path → git blame + git log -S 搜索 → 填 blame_hits + 产出 deps_candidates.json
  5. 提炼 special_notes（API变更/锁冲突/配置项/编码规范）
  6. 根据 risk_level 和 conflicts_predicted 决定 execution_guide.am_mode（reject / 3way）
  7. Write: patch_analysis.json

  输出 schema 见 references/patch_analysis_schema.md
```

等待两个 Task 返回结果。

### 步骤 5: 读取搜索结果 + patch_analysis.json

```bash
Read: $OUTPUT_DIR/revert_candidates.json
Read: $OUTPUT_DIR/deps_candidates.json
Read: $OUTPUT_DIR/patch_analysis.json
```

### 步骤 6: JSON 格式验证（Skill 内检查）

**不调外部 schema 文件**，AI 按本文件的输出 Schema 定义手工检查必填字段：

- **revert_candidates.json**: 必须包含 `candidates` 数组
- **deps_candidates.json**: 必须包含 `dependencies` 数组

**若验证失败**：降级方案 → AI 手工修复 JSON 或标记该文件为异常

### 步骤 7: 符号提取（调用快速脚本）

```bash
python3 $SCRIPTS_DIR/extract_patch_symbols.py \
  --patch-dir /tmp/patches/ \
  --output $OUTPUT_DIR/patch_symbols.json
```

执行时间 <3s，不会超时。

输出示例：
```json
{
  "0001": {
    "subject": "arm64: sysreg: Add HDBSS registers",
    "introduced_symbols": ["hdbss_init", "HDBSS_ENABLE"],
    "referenced_symbols": ["kvm_stage2_map", "kvm_pte_to_phys"],
    "changed_files": ["arch/arm64/kvm/hdbss.c"],
    "功能分类": "infra"
  },
  "0002": {
    "subject": "KVM: arm64: Add HDBSS support",
    "introduced_symbols": ["hdbss_buffer_init", "hdbss_enable"],
    "referenced_symbols": ["hdbss_init", "HDBSS_ENABLE"],
    "changed_files": ["arch/arm64/kvm/hdbss.c", "virt/kvm/arm.c"],
    "功能分类": "driver"
  }
}
```

### 步骤 8: 调用深度分析脚本 + AI 汇总合并

#### 8.1 调用 calculate_build_checkpoints.py（计算编译点）

```bash
python3 $SCRIPTS_DIR/calculate_build_checkpoints.py \
  --merge-tasks $OUTPUT_DIR/merge_tasks.json \
  --output $OUTPUT_DIR/merge_tasks_checkpointed.json
```

执行时间 <2s，不会超时。

**脚本自动执行**：
- 检测反向依赖（patch_i引用patch_j（j>i）的符号）
- 计算 build_checkpoint（7条规则）
- 输出 checkpoint_reason（每条规则的触发原因）

**规则优先级**（已优化，删除"含 pre_revert → true"）：
```
Rule 1a: 反向依赖者 → false（完全排除）
Rule 1b: 反向依赖的被依赖者 → true（强制验证）
Rule 1: infra patch → true（基础设施必须编译）
Rule 2: introduced_symbols被≥3个later patches引用 → true
Rule 3: risk_level='高' 或 conflicts_predicted非空 → true
Rule 4: 最后一个patch → true（强制）
Rule 5: skip/doc → false（不编译）
Rule 6: 功能模块分组最后一个 → true
Rule 7: 其他 → false
```

输出示例：
```json
{
  "merge_order": [
    {
      "task_id": "0001",
      "build_checkpoint": true,
      "checkpoint_reason": {
        "rules_triggered": ["Rule_1"],
        "primary_reason": "infra patch（基础设施必须编译）",
        "reverse_dep_detail": null
      }
    },
    {
      "task_id": "0002",
      "build_checkpoint": false,
      "checkpoint_reason": {
        "rules_triggered": ["Rule_7"],
        "primary_reason": "其他（非关键节点）",
        "reverse_dep_detail": null
      }
    },
    {
      "task_id": "0003",
      "build_checkpoint": true,
      "checkpoint_reason": {
        "rules_triggered": ["Rule_6"],
        "primary_reason": "功能模块分组最后一个（driver/hdbss组最后）",
        "reverse_dep_detail": null
      }
    }
  ]
}
```

#### 8.2 AI 审核编译点结果

读取 `merge_tasks_checkpointed.json`，检查：

**合理性检查**：
- 编译点总数：应 ≤ patch总数的40%（避免过度编译）
- infra patch：应为 true
- 最后一个patch：应为 true
- doc patch：应为 false

**异常检测**：
- 若所有patch的build_checkpoint=true → 警告，提示用户："所有patch都是编译点，可能是规则配置异常，请确认是否继续？"
- 若发现反向依赖 → 提示用户："检测到反向依赖（patch_i → patch_j），建议调整顺序或保留原始顺序"

**用户确认**：
```
编译点分布：
  - 总patch数：N个
  - 编译点数：M个（占比 X%）
  - infra：1个
  - 分组最后：Y个
  - 被依赖：Z个
  - 其他：false

请确认编译点分布是否合理：
[1] 确认（Recommended）
[2] 手动调整某些patch的编译点
[3] 查看详细checkpoint_reason
```

#### 8.3 生成最终 merge_tasks.json

```bash
cp $OUTPUT_DIR/merge_tasks_checkpointed.json $OUTPUT_DIR/merge_tasks.json
```

### 步骤 9: Write merge_tasks.json（必须包含seq字段）

AI 将汇总结果写入 merge_tasks.json，**必须包含以下必填字段**：

**merge_order字段**：
- `seq`: **执行序号（整数，从1开始，按patch原始顺序递增）**
  - 0001.patch → seq=1
  - 0002.patch → seq=2
  - 0003.patch → seq=3
  - ...
- `task_id`: patch编号（从patch文件名提取，如"0001"）
- `subject`: patch标题（从patch文件的Subject行提取）
- `patch_file`: patch文件完整路径（如"/tmp/patches/0001-xxx.patch"）
- `files_changed`: 涉改文件列表（从patch_symbols.json提取）
- `功能分类`: 从patch_symbols.json提取（infra/driver/core/doc等）
- `introduced_symbols`: 从patch_symbols.json提取
- `referenced_symbols`: 从patch_symbols.json提取
- `pre_revert`: 需revert的commit hash列表（从revert_candidates.json提取）
- `build_checkpoint`: false（初始值，步骤8.1会计算并更新）
- `checkpoint_reason`: null（初始值，步骤8.1会计算并更新）

**deps_order字段**（如有上游依赖）：
- `seq`: **执行序号（整数，从merge_order最后一个seq+1开始）**
  - 例如：merge_order有5个patch（seq=1-5），则deps_order的seq从6开始
- `task_id`: dep编号（如"dep-001"）
- `subject`: dep标题
- `source_pr`: 上游PR编号
- `patch_file`: dep patch路径
- `files_changed`: 涉改文件列表
- `功能分类`: 从patch分析提取
- `introduced_symbols`: 从patch分析提取
- `referenced_symbols`: 从patch分析提取
- `pre_revert`: []（deps通常无需revert）
- `build_checkpoint`: false（初始值）
- `checkpoint_reason`: null（初始值）
- `action`: "apply"
- `depends_on`: 前置task_id列表

**示例输出**：
```json
{
  "schema_version": "1.0",
  "merge_order": [
    {
      "seq": 1,
      "task_id": "0001",
      "subject": "sysreg: Add HDBSS registers",
      "patch_file": "/tmp/patches/0001-sysreg.patch",
      "files_changed": ["arch/arm64/include/asm/sysreg.h"],
      "功能分类": "infra",
      "introduced_symbols": ["HDBSS_ENABLE", "HDBSS_BR_EL2"],
      "referenced_symbols": [],
      "pre_revert": ["abc123"],
      "build_checkpoint": false,
      "checkpoint_reason": null,
      "action": "apply",
      "depends_on": [],
      "risk_level": "低",
      "conflicts_predicted": []
    },
    {
      "seq": 2,
      "task_id": "0002",
      "subject": "kvm: Add HDBSS buffer",
      "patch_file": "/tmp/patches/0002-kvm.patch",
      "files_changed": ["arch/arm64/kvm/hdbss.c"],
      "功能分类": "driver",
      "introduced_symbols": ["hdbss_buffer_init"],
      "referenced_symbols": ["HDBSS_ENABLE"],
      "pre_revert": ["def456"],
      "build_checkpoint": false,
      "checkpoint_reason": null,
      ...
    },
    {
      "seq": 3,
      "task_id": "0003",
      ...
    }
  ],
  "deps_order": [],
  "pr_analysis": [...],
  "patch_pre_revert": {...}
}
```

**seq字段的重要性**：
- calculate_build_checkpoints.py依赖seq字段识别patch顺序
- Rule 4（最后一个patch强制编译）需要seq字段判断
- 如果seq字段缺失，所有patch的seq默认为9999，导致Rule 4无法触发

AI 按 `references/merge_tasks_schema.md` 中的 schema 手工检查必填字段。

## 输出文件 Schema

### samples_summary.json（抽样检测）

```json
{
  "schema_version": "1.0",
  "patches": [
    {
      "task_id": "0001",
      "files": ["arch/arm64/kvm/hdbss.c", "include/linux/kvm_host.h"],
      "symbol_samples": ["static int hdbss_init", "#define HDBSS_ENABLE"],
      "keyword_samples": ["HDBSS_BR_EL2 enable", "hdbss->flags"],
      "representative_samples": ["static int hdbss_init...", "#include <linux/..."],
      "total_add_lines": 150,
      "keywords": ["HDBSS", "FEAT_HDBSS", "DBM"]
    }
  ],
  "total_patches": 5,
  "scan_mode": "sampling"
}
```

### duplicate_analysis.json（简化版匹配分析）

```json
{
  "patch_duplicate_map": {
    "0001": [
      {
        "match_type": "sampling",
        "match_count": 7,
        "match_level": "高匹配",
        "matched_files": ["arch/arm64/kvm/hdbss.c"],
        "matched_samples": ["static int hdbss_init", "#define HDBSS_ENABLE"],
        "ruling": "疑似旧版本",
        "ruling_reason": "抽样检测发现7行匹配，建议 upgrade 模式"
      }
    ],
    "0002": [],
    "0003": []
  },
  "keywords_summary": {
    "0001": ["HDBSS", "FEAT_HDBSS", "DBM"],
    "0002": ["HDBSS", "stage2_map"],
    "0003": ["PERF", "tracepoint"]
  },
  "total_patches": 5,
  "patches_with_matches": 3,
  "recommended_scene": "upgrade"
}
```

**说明**：
- `patch_duplicate_map`：AI 判断的匹配结果（简化版，基于抽样）
- `keywords_summary`：每个 patch 的关键词（供 agent_target_revert 扩展搜索使用）
- `recommended_scene`：AI 推荐的场景（upgrade/backport）
- 完整的 commit 定位和 PR 聚合由 **agent_target_revert** 后续完成

### revert_candidates.json

```json
{
  "schema_version": "1.0",
  "candidates": [
    {
      "commit_hash": "abc123",
      "subject": "...",
      "similarity_score": 0.82,
      "ruling": "confirm",
      "ruling_reason": "旧版本 HDBSS 实现",
      "revert_cmd": "git revert abc123"
    }
  ],
  "keywords_used": ["HDBSS"],
  "files_searched": ["arch/arm64/kvm/hdbss.c"]
}
```

### deps_candidates.json

```json
{
  "schema_version": "1.0",
  "dependencies": [
    {
      "commit_hash": "def456",
      "subject": "stage2 页表重构",
      "introduced_symbols": ["stage2_map"],
      "ruling": "confirm",
      "pull_cmd": "b4 am <msgid>"
    }
  ]
}
```