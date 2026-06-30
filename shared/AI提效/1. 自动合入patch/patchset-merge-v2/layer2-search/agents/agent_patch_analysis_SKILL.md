# agent_patch_analysis — 语义分析 Subagent

## 职责

读取所有 .patch 原始文件，深度理解每个 patch 的功能、风险、依赖关系，产出 `patch_analysis.json` 固化落盘。Layer 3 在 git am 前必读此文件做行为指导。

若 config.json 含 `upstream_repo_path`，同时执行 upstream 依赖搜索并产出 `deps_candidates.json`。

## 输入

| 来源 | 内容 |
|------|------|
| `/tmp/patches/000N-*.patch` | 全部 patch 原始文件（commit message + 完整 diff） |
| `samples_summary.json` | Layer 2 步骤 3 采样结果（关键词、涉改文件、代表代码） |
| `patch_symbols.json` | Layer 2 步骤 7 符号提取结果（introduced/referenced symbols） |
| `config.json` | kernel_repo_path、upstream_repo_path（可选）、kernel_branch |

## 执行步骤

### 步骤 1: 读取所有 .patch → 理解功能

对每个 .patch 文件：
1. 读取 commit message（Subject + Body）→ 理解功能目的
2. 读取 diff 内容 → 理解改动范围、改了什么
3. 结合 `samples_summary.json` 中的 keywords 和 `patch_symbols.json` 中的符号

填写：
- `功能分类`: infra / driver / core / fs / net / sound / doc / bugfix
- `功能概述`: 一句话描述功能（中文）
- `review_required`: 高 / 中 / 低
- `review_reason`: 为什么需要 review

### 步骤 2: 对比目标仓库 → 预判冲突

```bash
cd $KERNEL_REPO_PATH

# 对每个 patch 的涉改文件，grep 目标仓库现有内容
# 重点：与 patch 改动行（+/− 行）关键字相近的已有代码
for f in ${files_changed[@]}; do
  if [ -f "$f" ]; then
    # 用 patch 中的新增符号名搜索目标仓库
    for sym in ${introduced_symbols[@]}; do
      git grep -n "$sym" "$f" >> /tmp/conflict_check_$task_id.txt
    done
  fi
done
```

填写：
- `conflicts_predicted`: 预判冲突点列表
  - `file`: 文件路径
  - `line_hint`: 预估冲突行号
  - `reason`: 冲突原因（如"目标已有旧版宏定义"）
  - `severity`: high / medium / low
- `risk_level`: 高 / 中 / 低
- `risk_detail`: 风险详述

### 步骤 3: 跨 patch 符号交叉 → 内部依赖

读取 `patch_symbols.json`，对每个 patch：
- 若 `referenced_symbols` 中包含其他 patch 的 `introduced_symbols` → 填 `depends_on`
- 例如：0002 引用 `hdbss_init`，而 0001 引入 `hdbss_init` → `depends_on: ["0001"]`

### 步骤 4: upstream 依赖搜索（若有 upstream_repo_path）

从 config.json 读取 `upstream_repo_path`，若存在则执行：

**4a. git blame 追溯 Bugfix（向后搜索）**

```bash
cd $UPSTREAM_REPO_PATH

# 对每次 patch 的涉改函数，在 upstream 做 blame
for file in ${files_changed[@]}; do
  basename_file=$(basename "$file")
  upstream_file=$(find . -name "$basename_file" -path "*" | head -1)
  if [ -n "$upstream_file" ]; then
    for sym in ${introduced_symbols[@]}; do
      git log --oneline -S "$sym" -n 10 "$upstream_file" >> /tmp/upstream_blame_$task_id.txt
    done
  fi
done

# 搜索 Fixes: tag
for kw in ${keywords[@]}; do
  git log --grep="Fixes:" --grep="$kw" --all-match --oneline -n 20 >> /tmp/upstream_fixes_$task_id.txt
done
```

**4b. git log -S 向前搜索依赖**

```bash
# 对每个 referenced_symbol，在 upstream 找引入 commit
for sym in ${referenced_symbols[@]}; do
  git log -S "$sym" --oneline -n 15 >> /tmp/upstream_deps_$task_id.txt
done
```

对每个候选 commit：
1. `git show <hash>` 读取 diff
2. AI 判断：是否为本 patch 缺失的前置依赖？→ confirm / reject

填写：
- `blame_hits`: bugfix commit 列表
- 如发现 confirmed 的 upstream deps → 同时产出 `deps_candidates.json`

### 步骤 5: 提炼特殊注意事项

从 patch diff 和目标仓库现状对比中提取：
- API 变更提示（如"旧版宏 HDBSSBR_EL2 被重命名为 HDBSS_BR_EL2"）
- 锁/并发相关（如"新增 mmap_sem，确认目标仓库无同名锁"）
- 配置/编译项（如"依赖 CONFIG_KVM_HDBSS，检查目标 .config"）
- 编码规范（如"目标仓库使用 tab 缩进，patch 使用空格，需调整"）

### 步骤 6: 输出

**Write: `$OUTPUT_DIR/patch_analysis.json`**（必产）

```json
{
  "schema_version": "1.0",
  "0001": {
    "功能分类": "infra",
    "功能概述": "为 KVM 新增 HDBSS 系统寄存器定义，供后续 patch 使用",
    "risk_level": "高",
    "risk_detail": "修改了 sysreg.h 头文件，影响所有 arm64 编译单元",
    "review_required": "高",
    "review_reason": "寄存器地址需与 spec 逐位核对，误写一个 bit 会导致硬件异常",
    "conflicts_predicted": [
      {
        "file": "arch/arm64/include/asm/sysreg.h",
        "line_hint": 1234,
        "reason": "目标已有旧版 HDBSSBR_EL2 宏定义",
        "severity": "high"
      }
    ],
    "special_notes": [
      "目标仓库的 sysreg.h 使用了旧版命名宏 HDBSSBR_EL2，patch 使用 HDBSS_BR_EL2，合入后需检查所有引用旧宏的文件"
    ],
    "depends_on": [],
    "blame_hits": [],
    "execution_guide": {
      "am_mode": "reject",
      "conflict_strategy": "仔细核对寄存器地址"
    }
  },
  "0002": {
    "功能分类": "driver",
    "功能概述": "实现 HDBSS 缓冲管理函数，依赖 0001 引入的寄存器宏",
    "risk_level": "中",
    "risk_detail": "涉及复杂的状态机逻辑，逻辑错误会导致数据损坏",
    "review_required": "中",
    "review_reason": "状态转换是否正确需要熟悉 spec 的人 review",
    "conflicts_predicted": [],
    "special_notes": [
      "hdbss_buffer_init() 新增了 mmap_sem 读锁，确认目标仓库无同名锁竞争"
    ],
    "depends_on": ["0001"],
    "blame_hits": [],
    "execution_guide": {
      "am_mode": "3way",
      "conflict_strategy": null
    }
  }
}
```

**若步骤 4 发现 upstream 依赖，Write: `$OUTPUT_DIR/deps_candidates.json`**

```json
{
  "schema_version": "1.0",
  "dependencies": [
    {
      "commit_hash": "def456",
      "subject": "arm64: stage2 页表重构",
      "introduced_symbols": ["stage2_map"],
      "ruling": "confirm",
      "ruling_reason": "patch 0003 引用 stage2_map()，此函数由 def456 引入",
      "pull_cmd": "b4 am <msgid>",
      "reason": "0003 缺少前置函数 stage2_map()"
    }
  ]
}
```

## 执行纪律

- 每个 patch 都必须产出分析结果，不可跳过
- `execution_guide.am_mode`: 根据 risk_level 和 conflicts_predicted 决定
  - `risk_level=高` 或 `conflicts_predicted` 有 high severity → `reject`（手动 .rej 逐行处理）
  - 其他 → `3way`（git am --3way 自动合并）
- upstream_repo_path 不存在时，步骤 4 跳过，deps_candidates.json 不产生
