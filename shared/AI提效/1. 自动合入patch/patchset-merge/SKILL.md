---
name: merge-patchset
description: >
  Linux 内核 patchset 多 Agent 自动合入与冲突解决 Skill。
  场景1：从高版本 Linux 源端（lore.kernel.org）合入 patchset，自动查找依赖和 bugfix；
  场景2：本地实现代码合并新版本代码，评判回退策略。
  触发关键词："合入 patch"、"merge patchset"、"backport patch"、"合并内核补丁"、"apply kernel patch"、"git am"。
---

# Merge Patchset Skill

## 概述

将 Linux 内核 patchset 从高版本源端合入目标内核仓库的通用工作流 skill。采用多 Agent 并行分析 + 串行合入架构，每个 patch 走完整的 合入→编译→commit→review 链条。

## 使用方法

用户一句话描述需求，skill 自动提取配置。

```
# 场景 A：从 lore.kernel.org 下载
合入 <message-id> 到 ~/code/openeuler/kernel 的 patch-xxx 分支

# 场景 B：本地 patch 目录 + 指定 upstream 仓库
把 /mnt/shared/originPatch/dumpStage2 合入到 /root/code/openeuler/kernel，
upstream 是 ~/code/linux/linux

# 场景 C：本地 patch 目录，无 upstream
将 /mnt/shared/originPatch/HDBSS_v3 合入到 /root/code/openeuler/kernel，
没有源仓库
```

**解析规则**——按优先级从用户输入中提取：

| 配置项 | 提取方式 | 示例输入 | 提取值 |
|--------|---------|---------|--------|
| patch 来源 | "合入/merge/apply" 后的第一个路径/ID | `合入 <msg-id> 到…` | `<msg-id>` |
| | | `把 /path/ 合入到…` | `/path/` |
| `KERNEL_REPO_PATH` | "到/into/to" 后的路径 | `…到 ~/code/kernel` | `~/code/kernel` |
| `KERNEL_BRANCH` | "分支/branch" 后的词 | `…的 xxx 分支` | `xxx` |
| | | 未指定 → repo 当前分支 | | `git branch --show-current` |
| `UPSTREAM_REPO_PATH` | "upstream是/源仓库是/" 后的路径 | `…upstream 是 ~/linux/linux` | `~/linux/linux` |
| | | 未提及 / "没有源仓库" → **自动降级** | | 仅 metadata 推断，**不暂停、不询问用户** |
| `KERNEL_ARCH` | grep `CONFIG_ARM64=y` `.config` → arm64 | 自动 | |
| `BUILD_CMD` | `make ARCH=$KERNEL_ARCH -j$(nproc)`（有 perf 文件则追加 `make -C tools/perf`） | 自动 | |

## 硬性约束

以下约束来自项目规范，不可跳过：

1. **逐个合入 + 逐个 commit**：N 个 patch 产生 N 个 commit，不允许批量
2. **仅在出现问题时与用户交互**：正常合入→编译通过→commit→review 全过程自动流转；仅当冲突无法自动解决（10 轮上限）、循环依赖、或重复 patch 判定时暂停等用户决策
3. **每 commit 后调用 code-review-expert skill**（skill 框架按名称加载；若未安装则跳过并标注）
4. **revert 逐个 commit**：逆序（最新→最旧），每 revert 一个就 commit 一个
5. **每 patch 必须编译验证**：执行 `$BUILD_CMD`，0 error + 产物存在
6. **merge 串行，分析并行**：merge 步骤不可并行，前期分析只读可并行
7. **中文输出**：所有思考、解释、分析、输出报告使用中文
8. **只取改动行**：只应用 `+`/`-` 行，上下文行不强制合入
9. **修改严格归所属 patch**：不混入无关改动到其他 patch 的 commit
10. **编译通过 + 功能正常是第一指标**，两者同等优先级
11. **操作在独立分支**，不在主干分支
12. **门禁脚本不可绕过**：`gatekeeper.py --step COMMIT --check` 返回非 0 时禁止跳过 COMMIT
13. **禁止静默跳过**：BUILD/COMMIT/REVIEW 每步完成后必须显式输出 `[BUILD PASS]` / `[COMMIT PASS]` / `[REVIEW DONE]`
14. **原始 patch 顺序不可变**：apply 类型 patch 的合入顺序必须严格等于 patch 文件名编号顺序（0001→0002→...→000N），revert/dep 可插在前方但不可打乱 apply 组的相对顺序
15. **完整编译，禁止局部**：BUILD 必须执行 `$BUILD_CMD` 编译整个内核，禁止 `make path/to/file.o` 等局部编译，禁止 `make path/to/file.h`（不触发编译）

## Skill 初始化（任务启动时首先执行）

Agent 在执行任何任务前，必须动态发现 skill 安装目录和 scripts 路径：

```bash
# 方法 1：按 opencode 约定路径查找（推荐）
SKILL_DIR="$HOME/.agents/skills/merge-patchset"

# 方法 2：若约定路径不存在，全局搜索
if [ ! -d "$SKILL_DIR" ]; then
    SKILL_DIR=$(find "$HOME" -name "merge-patchset" -path "*skills*" -type d 2>/dev/null | head -1)
fi

# 方法 3：最后 fallback（GPT cli 约定路径）
if [ -z "$SKILL_DIR" ] || [ ! -d "$SKILL_DIR" ]; then
    SKILL_DIR="$HOME/.claude/skills/merge-patchset"
fi

export SKILL_DIR
export SCRIPTS_DIR="$SKILL_DIR/scripts"
export REFERENCES_DIR="$SKILL_DIR/references"

echo "SKILL_DIR=$SKILL_DIR"
echo "SCRIPTS_DIR=$SCRIPTS_DIR"
```

初始化完成后，所有 scripts 调用均使用 `$SCRIPTS_DIR/xxx.py` 绝对路径，保证 agent 在任何工作目录下都能正确找到脚本。

## 工作流总览

```
Phase 0: 下载（脚本）→ /tmp/patches/000N-*.patch + metadata.json
         → 创建 $KERNEL_REPO_PATH/patch_analysis/
Phase 1: 并行分析（只读，不写文件）→ 屏幕输出分析结果
    ⚠️ 所有 Agent 必须用 Task tool 一次性并行启动，禁止串行
Phase 1.5: 主 Agent 汇总 → patch_analysis/merge_tasks.json + analysis_cache.json
Phase 2: 串行 Merge（写入）→ 每 patch commit 后落盘 patch_analysis/analyse.md
Phase 3: 汇总 → patch_analysis/summary.md
```

## 文件清单

- `SKILL.md` — 本文件
- `$SCRIPTS_DIR/download_patches.py` — 统一下载入口（b4/wget/本地）
- `$SCRIPTS_DIR/extract_patch_symbols.py` — L1 确定性脚本：从 .patch 提取符号/功能分类/feature_signature → analysis_cache.json 骨架
- `$SCRIPTS_DIR/generate_diff_report.py` — diff 对比生成
- `$SCRIPTS_DIR/generate_analyse_md.py` — 确定性生成 analyse.md
- `$SCRIPTS_DIR/generate_summary_md.py` — 确定性生成 summary.md
- `$SCRIPTS_DIR/verify_analyse_format.py` — 格式验证门禁
- `$SCRIPTS_DIR/merge_order_sort.py` — 全量排序（revert优先+deps插入+稳定顺序）
- `$SCRIPTS_DIR/detect_duplicate.py` — 重复检测 + PR 聚合 + revert 决策
- `$SCRIPTS_DIR/generate_revert_plan.py` — 从分析结果生成 revert_plan.json + revert_plan.sh
- `$SCRIPTS_DIR/execute_revert.py` — 执行 revert 计划（预执行 + 正式执行 + 失败处理 + 回滚）
- `$SCRIPTS_DIR/validate_phase1_artifacts.py` — Phase 1.5→2 / 2→3 硬性门禁（schema 校验）
- `references/diagnostic-guide.md` — 冲突诊断决策树（Ours/Theirs）
- `references/output-templates.md` — analyse.md / summary.md 模板 + 屏幕输出格式
- `references/code-review-expert/SKILL.md` — 捆绑的 review skill（安装时自动部署为独立 skill）
- `references/agent-design.md` — Agent 职责定义参考文档

---

## Phase 0：下载

**步骤 0：环境初始化（必须，在下载前完成）**

```bash
cd "$KERNEL_REPO_PATH"

# 1. 自动检测 KERNEL_ARCH
if grep -q "CONFIG_ARM64=y" .config; then
    KERNEL_ARCH=arm64
elif grep -q "CONFIG_X86_64=y" .config; then
    KERNEL_ARCH=x86
else
    KERNEL_ARCH=$(uname -m | sed 's/aarch64/arm64/;s/x86_64/x86/')
fi

# 2. 自动构造 BUILD_CMD
BUILD_CMD="make ARCH=$KERNEL_ARCH -j$(nproc)"

# 3. 切换目标分支（若指定，未指定则留在当前分支）
if [ -n "$KERNEL_BRANCH" ]; then
    git checkout "$KERNEL_BRANCH" 2>/dev/null || git checkout -b "$KERNEL_BRANCH"
fi

# 4. 确保工作区干净
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "错误: 工作区不干净，请先清理"
    exit 1
fi

echo "KERNEL_ARCH=$KERNEL_ARCH"
echo "BUILD_CMD=$BUILD_CMD"
echo "KERNEL_BRANCH=$(git branch --show-current)"
```

**步骤 1：下载**

**执行者**：`$SCRIPTS_DIR/download_patches.py`（确定性脚本）

```bash
python3 "$SCRIPTS_DIR/download_patches.py" \
  --source "<message-id | url | /path/to/patches>" \
  --output-dir /tmp/patches/ \
  --target-kernel "$KERNEL_REPO_PATH" \
  --target-branch "$KERNEL_BRANCH" \
  --build-target "$BUILD_CMD"
```

参数说明：
- `--source`：message-id（`<...@...>` 格式）、URL 或本地路径
- `--proxy`：可选，不传则自动检测环境变量
- 产出：`/tmp/patches/0001-*.patch` + `patchset.metadata.json`

**下载完成后立即执行**：
```bash
mkdir -p "$KERNEL_REPO_PATH/patch_analysis"
```

`$KERNEL_REPO_PATH/patch_analysis/` 目录用于存放所有分析阶段的结构化文件（JSON 中间产物 + 分析报告），确保不会因 AI 遗漏输出而丢失数据。

**Phase 0 完成后：恢复检查（关键步骤）**

若 `$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json` 已存在，检查是否有未完成的 work（session 压缩/中断后恢复）：

```bash
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --restore
```

| 退出码 | 含义 | 后续操作 |
|--------|------|---------|
| 0 | 无未完成工作 或 已完成 | 正常进入 Phase 1 |
| 10 | 有未完成工作 | 向用户展示 `phase/task_id/step/status`，询问是否恢复 |
| 1 | merge_tasks.json 不存在 | 正常流程，继续 Phase 1 |

**若用户确认恢复**：
1. 跳过 Phase 1 和 Phase 1.5（分析已完成）
2. 从 `current_state.phase` 和 `current_state.task_id` 指示的位置继续执行
3. 若 skill 内容丢失（上下文压缩），从 `workflow_hints` 读取关键规则
4. 恢复完成后清除标记：
   ```bash
   python3 "$SCRIPTS_DIR/gatekeeper.py" \
     --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
     --restore --clear
   ```**

---

### 场景问询（★v2.1 新增）

Phase 0 下载完成后、正式进入 Phase 1 前，检测目标仓库是否存在旧版本实现，让用户选择合入场景。

**步骤 1：初筛检测（用 version-upgrade 模式检测旧版本）**

```bash
python3 "$SCRIPTS_DIR/detect_duplicate.py" \
  --patch-dir /tmp/patches/ \
  --repo-path "$KERNEL_REPO_PATH" \
  --output "$KERNEL_REPO_PATH/patch_analysis/duplicate_analysis.json" \
  --version-upgrade
```

**步骤 2：根据结果分流**

- 若 `duplicate_analysis.json` 中 `global_revert_order` 为空且无 `old_version_batches` → 无旧版本，直接进入 Phase 1（默认 backport 模式）
- 若存在旧版本批次 → 展示摘要给用户，询问场景

```
═══════════════════════════════════════════════
  场景问询 — 检测到目标仓库中可能存在旧版本实现
═══════════════════════════════════════════════

检测到以下 commit 可能与要合入的 patch 相关：
  <commit_hash> <subject_line>

请选择合入场景：

[1] 版本升级（upgrade）
    要合入的 patchset 是旧版本的新版本。
    AI 将深度搜索目标仓库中所有相关旧版本 commit，
    确认后逐个回退，确保清理干净不留残留。

[2] 纯新增（backport）
    目标仓库无相关实现，上述匹配为误报或极相似代码。
    仅当 diff ≥90% 时才暂停让用户确认，其余全部跳过。
    不进行深度搜索，不会自动 revert。

  请选择: [1] 版本升级 / [2] 纯新增
```

**步骤 3：用户选择后的行为**

| 选择 | 后续 |
|------|------|
| [1] 版本升级 | 记录场景为 `upgrade`，进入 Phase 1。agent_revert 在 L2 做 AI 深度搜索 |
| [2] 纯新增 | 记录场景为 `backport`，进入 Phase 1。agent_revert 只做严格审核（diff ≥90% → 暂停让用户确认） |

---

## Phase 1：并行分析（只读，不写文件）

### L1 脚本初始化（★v2.1：先跑确定性脚本）

在启动 L2 Agent 前，先并行运行两个 L1 确定性脚本：

```bash
# L1a: 重复检测（初筛线索）
python3 "$SCRIPTS_DIR/detect_duplicate.py" \
  --patch-dir /tmp/patches/ \
  --repo-path "$KERNEL_REPO_PATH" \
  --output "$KERNEL_REPO_PATH/patch_analysis/duplicate_analysis.json"

# L1b: 符号提取（生成 analysis_cache.json 骨架）
python3 "$SCRIPTS_DIR/extract_patch_symbols.py" \
  --patch-dir /tmp/patches/ \
  --output "$KERNEL_REPO_PATH/patch_analysis/analysis_cache.json"
```

产出：
- `duplicate_analysis.json` — L2 agent_revert 消费
- `analysis_cache.json` — L2 agent_analysis 消费（含骨架：introduced_symbols / referenced_symbols / 功能分类 / feature_signature）

> 这两个脚本是完全确定性的，不依赖 AI。并行运行或串行均可。

### L2 Agent 分工（★v2.1：按职责分工）

不再按 patch 数量平分 Agent。改为 **2 个专职 Agent**，一条消息并行启动：

```
主 Agent 在 L1 脚本全部完成后，一条消息同时启动 2 个 Agent：
  Task(agent_analysis, 全部 patch + analysis_cache.json)
  Task(agent_revert, duplicate_analysis.json + 场景 + keywords)
```

**agent_analysis**：全量语义分析
- 输入：`/tmp/patches/000N-*.patch`（全部），`$KERNEL_REPO_PATH`，`analysis_cache.json`（L1 `extract_patch_symbols.py` 已填充骨架）
- 输出：屏幕输出结构化分析结果——功能描述、模块关联、风险等级、review 需求、依赖线索
- 详见 `references/agent-design.md`

**agent_revert**：revert 审核（★v2.1 新增独立 Agent）
- 输入：`duplicate_analysis.json`（L1 初筛），场景（upgrade/backport），`$KERNEL_REPO_PATH`，`feature_signature.keywords` + `scope_dirs`
- 输出：屏幕输出 `revert_ruling`（confirm/reject）+ 理由
- upgrade 模式：AI 自主深度搜索旧版本全貌（不限阈值），确保清理干净
- backport 模式：diff ≥90% → 暂停让用户确认；<90% → reject
- 详见 `references/agent-design.md`

> ★ 两个 Agent 必须在**同一条消息**中并行启动（使用多个 Task tool 调用），禁止串行。

### agent_analysis 执行流程

以下流程由 agent_analysis 执行，agent_revert 的流程见下一节。

**步骤 1: 理解 commit message（优先）**
先深入理解每个 patch 的 commit message：功能是什么、关联哪个子模块、是否标注了前置依赖 commit。

**步骤 2: 分析代码 diff**
解析每个 patch 的 diff，提取：
- `introduced_by_patch`：本 patch 新增/修改的函数名、宏名、类型名
- `referenced_symbols`：本 patch 调用/引用的符号
- `changed_files`：涉改文件的路径和行号范围
- `功能分类`：根据文件路径和 diff 内容判定功能分类

**功能分类判定规则**：

| 分类 | 判定规则 | 示例路径 |
|------|---------|---------|
| `infra` | `include/linux/*.h`, `include/uapi/*.h`, `arch/*/include/`, diff 中 `#define`/`typedef`/`struct` 定义行占比 > 30% | `include/linux/kvm_host.h` |
| `core` | `kernel/`, `mm/`, `arch/*/kernel/`, `arch/*/mm/`, `init/` | `kernel/sched/core.c` |
| `driver` | `drivers/`, `arch/*/mach-*/` | `drivers/gpu/arm/` |
| `fs` | `fs/`, `include/linux/fs*.h` | `fs/ext4/` |
| `net` | `net/`, `include/linux/net*.h`, `include/net/` | `net/core/dev.c` |
| `sound` | `sound/`, `include/sound/` | `sound/soc/` |
| `doc` | `Documentation/`, commit message 含 "doc"/"comment"/"documentation" | `Documentation/kvm/` |
| `bugfix` | commit message 含 "fix"/"bug"/"error"/"patch"/"Fixes:" 且独立于特性系列 | 修复补丁 |

> 优先级：文件路径 > diff 内容（宏定义集中 > 文件路径）> commit message 关键词

**步骤 2.5: 提取特性签名（feature_signature）**

Agent 根据 commit message 和 diff 内容理解本系列特性，提取用于搜索旧版本的**语义关键词**，填入 `analysis_cache.json`：

```json
{
  "feature_signature": {
    "keywords": ["HDBSS", "Hardware Dirty Bit State Save", "DBM", "Dirty Bit Management", "HDBSSF"],
    "scope_dirs": ["arch/arm64/kvm/", "arch/arm64/tools/", "arch/arm64/include/"]
  }
}
```

字段说明：
- `keywords`：最能标识本特性的词（官方缩写 + 全称 + 关联功能名）。Agent 综合 commit message、diff 语境、模块关联推断，不是机械截取大写词
- `scope_dirs`：特性涉及的目录范围（限定搜索范围）

此字段供 `detect_duplicate.py --analysis-cache` 读取，替代脚本的自动关键词提取。未提供时脚本自动降级为内置提取逻辑。

**步骤 3: 向后搜索 Bugfix（在 upstream 仓库上执行）**

> **前提**：`$UPSTREAM_REPO_PATH` 可用时执行，不可用则跳过，仅从 patch metadata 推断。

```bash
# 对每个 changed_file，blame 追踪后续改动
git -C "$UPSTREAM_REPO_PATH" blame -L <start>,<end> <branch> -- <file>

# 查找 Fixes 标签（更精准）
git -C "$UPSTREAM_REPO_PATH" log --grep="Fixes:.*<upstream-commit-short>" \
    --all --format="%h %s"

# 递归追溯 bugfix 的 bugfix
```

**步骤 4: 向前搜索依赖**

> **前提**：`$UPSTREAM_REPO_PATH` 可用时执行，不可用时跳过 `git log -S`，仅用 `grep` 检查目标仓库。

```bash
# 在目标内核中检查符号是否存在
grep -rn "<symbol>" "$KERNEL_REPO_PATH/"

# 若不存在 → 在 upstream 中找引入该符号的 commit
git -C "$UPSTREAM_REPO_PATH" log --all --reverse -S "<symbol>" \
    --format="%H %s" | head -1

# 递归检查引入 commit 是否在目标内核中缺失
git -C "$KERNEL_REPO_PATH" branch --contains <commit>
# 空输出 → 目标内核缺少该 commit → 标记为依赖
```

若 `$UPSTREAM_REPO_PATH` 不可用：
- 跳过 git blame / git log -S
- 仅从 patch commit message 中提取 Fixes/Depends-on 标签
- 在 analyse.md 中标注 `未找到 blame 记录` / `未找到依赖`

**步骤 5: 检测目标仓库中的重复/等效 patch + PR 聚合 + revert 决策**

> **核心策略**：要合入的 patch **绝不跳过**。检测到重复/等效时，写入 `pre_revert` 列表，
> 先 revert 目标仓库的实现，再合入新 patch。禁止使用 `action: skip`。

调用 `detect_duplicate.py` 自动完成搜索、diff 对比、PR 聚合、revert 决策：

```bash
python3 "$SCRIPTS_DIR/detect_duplicate.py" \
  --patch-dir /tmp/patches/ \
  --repo-path "$KERNEL_REPO_PATH" \
  --output "$KERNEL_REPO_PATH/patch_analysis/duplicate_analysis.json"
```

**脚本内部流程**：

| 阶段 | 操作 |
|------|------|
| **候选搜索** | `git log --grep`（subject 匹配）+ `git log -S`（符号匹配）+ 涉改文件 commit |
| **diff 对比** | patch add lines vs commit add lines，计算交集比例 |
| **功能对比** | 函数名/宏名重叠度（符号提取），功能等效但代码不同的 patch 也能识别 |
| **综合判定** | 取 diff 和 symbol 中较高者（任一 >=80% 即高匹配）；都不高取均值 |
| **PR 聚合** | 解析 commit message Link 标签，按 PR 聚合候选 commits |

**判定标准**：

| 条件 | 判定 | 处理 |
|------|------|------|
| 综合相似度 >= 80%（diff 或 symbol 任一高） | **高匹配**（计入 PR 覆盖率） | → 写入 `pre_revert` |
| 综合相似度 50-79% | **中匹配**（不计入覆盖率） | → 标记 `可能冲突`，不 revert |
| 综合相似度 < 50% | **低匹配** | → 忽略 |
| 无候选 commit | **无重复** | → 正常流程 |
| symbol >= 80% 但 diff < 50% | **功能等效**（v1→v2 替换） | → 仍为高匹配，revert v1 保留 v2 |

**PR 聚合后 revert 决策**：

| PR 覆盖率 | revert 策略 | urgency |
|----------|------------|---------|
| >= 75% | revert 整个 PR | 必须 |
| 50-74% | revert 匹配的 commits（逐个，逆序） | 建议 |
| < 50% | 不自动 revert，合入时冲突解决 | 无须 |

**覆盖率计算**：`高匹配 commit 数 / PR 内总 commit 数 * 100`

**Agent 输出格式**：分析 Agent 读取 `duplicate_analysis.json` 结果，按以下格式输出：
```
重复检测=高匹配:abc123(PR#123,95%);中匹配:def456(PR#456,65%);无重复
```

> **步骤 6 已合并入步骤 5**。PR 映射聚合由 `detect_duplicate.py` 统一完成。

**步骤 7: 屏幕输出**

按 `references/output-templates.md` 中的结构化格式输出到屏幕。含 PR 映射结果。

输出中**必须包含 `验证点=待定|false`**：

Agent 根据以下规则做初步判定：

| 条件 | 验证点 值 | 说明 |
|------|:--:|------|
| 文件路径匹配 `include/linux/*.h`, `arch/*/include/` 等基础设施模式 | `待定` | 大概率 true，Phase 1.5 最终确认 |
| risk_level=高 或 conflicts_predicted 非空 | `待定` | 大概率 true，Phase 1.5 最终确认 |
| 独立 bugfix、文档、skip 的 patch | `false` | 确定不需要 |
| 上述条件均不满足的普通 patch | `false` | 默认不需要（功能模块最后、被依赖数等由 Phase 1.5 计算） |

> **注意**：即使 agent 判断为 `false`，Phase 1.5 汇总后仍可能被 `calculate_build_checkpoints.py` 覆盖为 `true`（如被 ≥3 个后续 patch 依赖）。Agent 只做初步排除。

---

### agent_revert 执行流程（★v2.1 新增）

agent_revert 根据场景（upgrade / backport）走不同流程。

#### upgrade 模式（AI 深度搜索）

1. 读取 `duplicate_analysis.json` 中的 L1 初筛 commit 列表（作为搜索起点）
2. 读取 `analysis_cache.json` 中的 `feature_signature.keywords` 和 `scope_dirs`
3. **扩展搜索**：用 keywords 在 scope_dirs 下 `git log --grep=<kw>` 搜全部相关 commit（仅当前分支，不限阈值、不限时间范围）
4. **符号追溯**：用 `git log -S=<sym>` 在 scope_dirs 找所有引入 key symbol 的 commit
5. **文件追溯**：用 `git log -- <file>` 找出修改过涉改文件的所有 commit
6. **深入理解**：读取每个候选 commit 的 message + diff，AI 判断：
   - 是否是旧版本的功能实现？ → confirm
   - 是否是无关注释/格式/doc/无关 bugfix？ → reject
   - **merge commit 包含检查**：如果候选中有 merge commit，用 `git log <merge>~1..<merge>` 展开其子 commit 列表，检查哪些子 commit 已被独立找到（覆盖判定）
7. **去重 + 完整性验证**：将 L1 初筛结果和步骤 3-5 的搜索结果合并去重
   - **PR 聚合价值**：PR merge commit 无法直接 revert（需要 `-m`），所以不用于整体 revert。但它的子 commit 列表（`git log M~1..M`）作为**完整性基线**，验证是否遗漏
   - **覆盖验证**：commit x 属于 PR M ⟺ x 在 `git log M~1..M` 中。如果 L1 找到的 commit 全部被某个 PR 覆盖 → 说明搜索完整
   - **遗漏检查**：检查 PR M 的子 commit 中未被 L1 找到的 → AI 判断是否也需要纳入 revert
   - **独立 commit 保留**：不在任何 PR 子 commit 列表中的 commit → 必须保留
   - **revert 方式**：每个确认的 commit 单独 `git revert`（逆序），不是整体 revert PR
8. 输出：每个 commit 的 `revert_ruling`（confirm/reject）+ `revert_ruling_note` + 按时间逆序排列 + PR 覆盖验证报告
8. 输出：每个 commit 的 `revert_ruling`（confirm/reject）+ `revert_ruling_note` + 按时间逆序排列

> 核心原则：不靠阈值判定，AI 理解代码语义后做判断。L1 脚本只提供起点线索。排除无关格式化/doc/无关 bugfix。确保找到所有旧版本 commit，一个不多一个不少。

#### backport 模式（严格审核）

1. 读取 L1 的 `duplicate_analysis.json`
2. 对每个候选：
   - diff ≥90% → 暂停，展示 commit 给用户确认是否 revert
   - diff <90% → reject
3. **不启动扩展搜索**（纯新增场景，深度搜索仅限 upgrade 模式）

---

## Phase 1.5：主 Agent 汇总

**步骤 1: 跨 patch 冲突检测**
- 文件修改集合重叠（直接重叠或相邻 <10 行）→ `CONFLICT_HIGH`
- `introduced` 符号的交叉引用 → 语义冲突
- `used ∩ introduced` → 强依赖（P_j 调用了 P_i 引入的符号）

**步骤 2: 依赖图 + 反向依赖检测**

**核心原则：原始 patch 相对顺序不变。** 反向依赖通过编译验证点机制解决，不自动调整顺序。

```bash
# 输入: 从 analysis_cache.json 取每个 patch 的 introduced_symbols 和 referenced_symbols
# 加上 original_order（从 patch 文件名 0001~000N 提取）

python3 "$SCRIPTS_DIR/topo_sort.py" << 'JSON'
{
  "original_order": ["0001","0002","0003","0004","0005"],
  "0001": {"introduced_symbols": ["func_a"], "referenced_symbols": []},
  "0002": {"introduced_symbols": [], "referenced_symbols": ["func_a"]},
  "0003": {"introduced_symbols": ["func_b"], "referenced_symbols": ["func_a"]},
  ...
}
JSON
```

**topo_sort.py 输出**：
- `合入顺序`：== `原始顺序`（不调整）
- `反向依赖`：列表中每个条目含 `depender`（依赖者）、`provider`（被依赖者）、`symbols`（涉及符号）、位置信息
- `循环依赖`：若存在 → exit 1，暂停等用户决策

**用户交互**（Phase 1.5 步骤 5 预览时）：

```
═══════════════════════════════════════════════
  反向依赖处理方案选择
═══════════════════════════════════════════════

发现反向依赖：
  0001 → 0003: func_a（#1 引用 #3 的符号）

请选择处理方案：

[1] 保持原始顺序（推荐）
    执行顺序: 0001 → 0002 → 0003
    checkpoint:
      0001: —（反向依赖者，静默写入）
      0002: —
      0003: ✅（反向依赖被依赖者 + 末 patch）
    编译: 1 次
    说明: 0001 无验证点，代码写入不编译；
          0003 定义符号后编译验证整个系列。

[2] 调整顺序（依赖者移到被依赖者之后）
    执行顺序: 0003 → 0001 → 0002
    checkpoint: 按正常规则计算
    编译: 约 2 次
    说明: func_a 先定义后调用，依赖关系匹配原始代码顺序。

请选择: [1] / [2]
```

**选择 [2] 时的处理**：重新运行旧版 topo_sort 调整顺序后重算 build_checkpoint。

**步骤 3: 全局 Revert 清单 → 生成执行计划**

> Phase 1 步骤 5 已由 `detect_duplicate.py` 完成 PR 聚合和 revert 决策。
> 主 Agent 调用 `generate_revert_plan.py` 生成 users 确认的执行计划。

```bash
python3 "$SCRIPTS_DIR/generate_revert_plan.py" \
  --duplicate-analysis "$KERNEL_REPO_PATH/patch_analysis/duplicate_analysis.json" \
  --repo-path "$KERNEL_REPO_PATH" \
  --output-dir "$KERNEL_REPO_PATH/patch_analysis/"
```

**输出文件**：
- `revert_plan.json` — 用户确认后的执行计划（Phase 2 输入）
- `revert_plan.sh` — 手动执行备选脚本

**策略说明**：
- **要合入的 patch 绝不跳过**。重复/等效 → `pre_revert` 列表中追加目标 commit
- revert 顺序按 commit 时间逆序（最新→最早）
- `revert_plan.json` 包含完整 revert 方案：commit 详情、相似度、风险评估、依赖检测

**revert 策略优先级**：
| 场景 | revert_cmd |
|------|-----------|
| 整个 PR | `git revert --ancestry-path <first>^..<last>` |
| 单个 commit | `git revert <commit>` |
| PR 内部分 commit | 按逆序逐个 `git revert`

**步骤 4: 生成 merge_tasks.json 和 analysis_cache.json**

写入 `$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json` 和 `$KERNEL_REPO_PATH/patch_analysis/analysis_cache.json`。

**merge_tasks.json 必须严格按照以下 schema 生成，不可自行增减字段：**

**顶层结构**：
- `patchset_info` — 来源/目标/架构等基本信息
- `global_revert_order` — PR 聚合的全局 revert 列表（步骤 3 产物，见上方格式）
- `deps_order` — 待拉取的上游依赖 patch 列表（初始 `[]`，步骤 6 填充）
- `merge_order` — 主体合入任务列表

**每个 task 必须包含**（merge_order 和 deps_order 共用）：
- `seq` — 执行序号（merge agent 严格按此升序执行）
- `task_id` — patch 编号（0001~000N 或 dep-001~dep-00N）
- `status` — `pending`（初始值，Phase 2 动态更新）
- `patch_file` — .patch 文件的绝对路径
- `subject` — patch 标题
- `author` — patch 作者
- `files_changed` — 涉改文件路径列表
- `功能分类` — 功能分类（infra/core/driver/fs/net/sound/doc/bugfix，Phase 1 步骤 2 判定）
- `introduced_symbols` — 本 patch 新增/修改的函数名、宏名、类型名列表，用于跨 patch 依赖统计
- `referenced_symbols` — 本 patch 调用/引用的符号列表
- `action` — `apply` | `skip`（判定是否需要合入）
- `skip_reason` — 若 skip，必须填写具体原因
- `pre_revert` — 需先 revert 的本地 commit hash 列表
- `depends_on` — 前置 task_id 列表（可跨 deps_order / merge_order）
- `risk_level` — `高` | `中` | `低`
- `review_required` — `高` | `中` | `低`
- `blame_hits` — bugfix commit 列表（step 3 产物）
- `duplicate_info` — 目标仓库重复检测结果（step 5 产物）
- `conflicts_predicted` — 预判冲突点列表（文件:行号:原因）
- `special_notes` — 合入注意事项
- `build_checkpoint` — `true` / `false`（是否在此 patch 点做编译验证）
- `pr_mapping` — PR 映射聚合结果（step 6 产物，见下方格式）
- `execution_log` — `[]`（初始空数组，Phase 2 动态追加）

**pr_mapping 字段格式**：
```json
{
  "upstream_deps": [
    {
      "pr_id": "PR #123",
      "pr_url": "https://github.com/torvalds/linux/pull/123",
      "commits": ["abc123", "def456"],
      "cover_letter_msgid": "xxx@lore.kernel.org",
      "download_cmd": "b4 am xxx@lore.kernel.org",
      "reason": "缺失函数 stage2_try_set_pte"
    }
  ],
  "bugfix_deps": [
    {
      "pr_id": "独立 commit",
      "commits": ["ghi789"],
      "reason": "修复空指针"
    }
  ],
  "revert_candidates": [
    {
      "pr_id": "PR #456",
      "commits": ["local-abc", "local-def"],
      "subject": "本地 HDBSS 实现",
      "revert_cmd": "git revert --ancestry-path local-abc^..local-def",
      "urgency": "必须"
    }
  ]
}
```

**analysis_cache.json** 按 `references/output-templates.md` 中定义的字段生成（含 `pr_mapping`）。

**步骤 5: 校验 + 屏幕预览 → 用户确认 → 保存预览**

1. **保存预览文本**：将完整预览输出写入 `$KERNEL_REPO_PATH/patch_analysis/phase1_preview.md`（中断恢复/审计追溯用）
2. **展示预览**：按 `references/output-templates.md` 中"Phase 1.5 全局预览模板"的格式展示——**先输出统一执行计划表（含 revert/dep/apply 全部任务 + checkpoint/风险/分析备注）**，再补充对外依赖详情和反向依赖方案
3. **用户确认**：等待用户选择

**步骤 6: 拉取上游依赖（用户确认"继续"后自动执行）**

用户选择 `[1] 继续执行 merge 流程` 后，遍历所有 task 的 `pr_mapping.upstream_deps`，拉取缺失的依赖 patch。

**拉取策略**：
| 依赖类型 | 拉取命令 |
|---------|---------|
| lore.kernel.org PR（有 cover_letter_msgid） | `b4 am <cover_letter_msgid> -o /tmp/patches/deps/` |
| GitHub PR（有 pr_url） | `git fetch origin && git cherry-pick <commit_range>` |
| 独立 commit（有 commit hash） | `b4 am <msgid>` 或直接 cherry-pick |

**拉取后处理**：
1. 检查新 patch 是否与现有 patchset 有文件冲突
2. 检查符号依赖是否满足（recursive）
3. 将拉取的 patch 写入 `deps_order`（格式与 merge_order 的 task 相同，task_id 为 dep-001~dep-00N）
4. 更新 `merge_order` 中相关 task 的 `depends_on`，引用 deps_order 的 task_id
5. 屏幕输出：
```
已拉取 3 个依赖 patch，已插入 deps_order：
  dep-001: stage2 页表重构 (PR #456)
  dep-002: KVM helper 重构
  dep-003: 宏定义修正
```

**无上游依赖时**：跳过此步骤，直接进入步骤 7。

**步骤 7: 全量排序（merge_order_sort）**

deps 拉取完成后，将 deps_order 和 merge_order 按优先级合并为最终执行序列：

```bash
python3 "$SCRIPTS_DIR/merge_order_sort.py" \
  --merge-tasks "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --output "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json"
```

**排序规则（方案 A）**：

| 优先级 | 规则 | 说明 |
|--------|------|------|
| 1（最高）| 所有含 `pre_revert` 的任务排在前面 | revert 先执行 |
| 2 | `deps_order` 按依赖插入到需要的 patch 之前 | dep 插入到最早需要它的 merge 任务之前 |
| 3 | 原始 patch 保持稳定相对顺序 | topo_sort 已保证 |

脚本行为：
- revert 组的依赖 dep → 一并放入 revert 组（最前面）
- apply 组的依赖 dep → 插入到 apply 组内部对应位置
- deps_order 清空（全部已移入 merge_order）
- 重新分配 seq 序号

**输出示例**：
```
合并排序完成：
  ✓ 2 个 deps 已插入 merge_order, deps_order 已清空
  ✓ 2 个 revert 组排在最前面: dep-002, 0002
    含 1 个 revert 依赖: dep-002
  总计: 7 个任务

Seq   Task       Action   Subject
1     dep-002    dep      stage2 refactor
2     0002       revert   DBM attr
3     dep-001    dep      helper function
4     0001       apply    HDBSS sysreg
5     0003       apply    FEAT cpufeat
6     0004       apply    HDBSS core
7     0005       apply    ioctl doc
```

---

**步骤 8: 计算编译验证点（calculate_build_checkpoints）**

merge_order_sort 完成后，运行脚本综合所有条件计算最终的 `build_checkpoint` 和 `checkpoint_reason`：

```bash
python3 "$SCRIPTS_DIR/calculate_build_checkpoints.py" \
  --merge-tasks "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --output "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json"
```

**写入字段**（嵌入每个 task）：
- `build_checkpoint` — `true` / `false`
- `checkpoint_reason` — 判定依据 `{rules_triggered, primary_reason, excluded, forced_by, reverse_dep_detail}`

**计算规则**（按优先级依次判定）：

| 优先级 | 条件 | build_checkpoint | 说明 |
|--------|------|:---:|------|
| 1a | 反向依赖者（前面的 patch 引用后面 patch 的符号） | `false` | **完全排除**，即使满足 infra/高风险等规则也不验证；代码静默写入，等被依赖者定义符号后在 checkpoint 统一验证 |
| 1b | 反向依赖的被依赖者（定义符号被前面 patch 引用） | `true` | 强制验证确保符号定义正确，验证时依赖者的代码已写入仓库 |
| 1c | 最后一个 revert task（revert 序列中 seq 最大） | `true`（强制） | 所有 revert 完成后必定编译一次，确保回退后代码编译通过 |
| 2 | `功能分类` == `infra` | `true` | 基础设施/公共头文件/宏定义，影响面最广 |
| 3 | `introduced_symbols` 被 ≥3 个后续 patch 的 `referenced_symbols` 引用 | `true` | 高依赖点，出错影响多个 patch |
| 4 | `risk_level` == `"高"` 或 `conflicts_predicted` 非空 | `true` | 高风险 patch |
| 5 | 最后一个 patch（seq 最大） | `true`（强制） | 覆盖所有规则（含反向依赖者），skip/doc 也强制验证 |
| 6 | `action` == `"skip"` 或 `功能分类` == `"doc"`（仅对非末 patch） | `false` | 无需编译验证 |
| 7 | 当前 patch 的 `功能分类` + 路径前缀分组中，组规模 > 1 且它是该组最后一个 patch | `true` | 功能模块完结，做一次验证 |
| 8 | 以上均不满足 | `false` | 普通 patch，不设验证点 |

**后续 patch 范围**：
- 包含 `merge_order` 和 `deps_order` 中所有的 patch
- 按 `seq` 排序后，统计当前 patch 的 `introduced_symbols` 被多少后面的 patch 引用

**分组依据**：
- 按 `功能分类` + 路径前缀（前 3 级目录，如 `drivers/gpu/arm`）分组
- 每组最后一个 patch 设验证点（组间切换前验证）

**输出示例**（保持原始顺序 + 反向依赖处理）：
```
📊 编译验证点计算结果：

Seq  Task      功能分类  验证点  原因
1    0001      core      —      反向依赖者（引用后面 patch 的符号: func_a→0003）
2    0002      infra     ✅      基础设施（公共头文件/宏定义）
3    0003      driver    ✅      反向依赖：定义符号 func_a（被前面 patch 引用）; 最后一个 patch（强制）

统计: ✅=2 处验证点，预计编译 2 次（共 3 个 patch）
```

---

### 步骤 9：硬性门禁（禁止绕过，必须通过脚本验证）

> **⚠️ 此门禁为强制步骤，exit 非 0 则禁止进入 Phase 2。**

```bash
python3 "$SCRIPTS_DIR/validate_phase1_artifacts.py" \
  --merge-tasks "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --analysis-cache "$KERNEL_REPO_PATH/patch_analysis/analysis_cache.json"
```

**校验内容**：
- `merge_tasks.json` 存在、Schema 合法（顶层字段 + 每个 task 22 个必填字段）
- `analysis_cache.json` 存在、每个 task_id 有对应条目、Schema 合法
- 不通过则退出，不允许进入 Phase 2

---

## Phase 2：串行 Merge

### ★ 执行顺序（硬性约束，不可违反）

1. 读取 `merge_tasks.json` 的 `merge_order` 数组
2. **严格按 `seq` 升序逐个处理**，不可跳过、不可重排、不可并行
3. 每个 task 完成全部 PRECHECK→...→DONE 后，才能开始下一个 task
4. 原始 patch 的相对顺序（0001→0002→0003→...→000N）**在执行顺序中必须保持不变**（revert 和 dep 可插在前方，但 apply 组内部顺序不变）

```
执行模板:
  for t in sorted(merge_order, key=lambda x: x['seq']):
      process_task(t)  # 串行，逐个完成
  
  禁止:
    - 按 task_id 排序（deps 的 task_id 格式不同会打乱顺序）
    - 按 patch 文件大小排序
    - "先处理简单的"（什么算简单是主观判断）
    - 并行处理多个 task
```

### 启动
读取 `$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json`。

**Phase 2 首次进入时更新 current_state**（标记 merge 阶段开始）：
```bash
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<第一个 task_id>" \
  --step BUILD --result in_progress
```

```
```

### 状态机

```
PRECHECK → PRE_REVERT → APPLY → VERIFY_INTENT → BUILD (checkpoint only) → COMMIT → REVIEW → RECORD → DONE
```

- `build_checkpoint=true` → 完整执行 BUILD→verify→gatekeeper
- `build_checkpoint=false` → 跳过 BUILD，直接进入 COMMIT

### PRECHECK
- 校验 patch 文件存在
- 校验 `depends_on` 中所有 task_id 状态为 `done`
  - 若前置被 skip → 检查 `skip_dependency_impact`：强→阻塞，中/弱→允许继续
- 工作区干净：`git diff --quiet && git diff --cached --quiet`

### PRE_REVERT

读取 `$KERNEL_REPO_PATH/patch_analysis/revert_plan.json` 执行：

```bash
python3 "$SCRIPTS_DIR/execute_revert.py" \
  --plan "$KERNEL_REPO_PATH/patch_analysis/revert_plan.json" \
  --repo-path "$KERNEL_REPO_PATH"
```

**执行流程**：
1. 创建回滚 checkpoint（`git branch -f BACKUP_PRE_REVERT HEAD`）
2. 逐 item 执行：
   - 预执行：`git revert --no-commit <commit>`（dry-run 检查冲突）
   - 成功 → 正式执行：`git commit`
   - 失败 → 自动降级（整体 PR → 逐个 commit）→ 暂停等用户决策
3. 全部完成 → 清理 checkpoint

**失败处理选项**：
| 选项 | 操作 | 适用场景 |
|------|------|---------|
| [1] 跳过此项 | `git checkout -- .` 清理 → 继续下一个 | 非关键独立 commit |
| [2] 回退全部 | `git reset --hard BACKUP_PRE_REVERT` | 方案需重新设计 |
| [3] 中止导出 | 保存状态退出 | 离线分析冲突 |
| [4] 手动修复 | 用户解决冲突 → 继续 | 冲突小可解决 |

也可手动执行 `bash $KERNEL_REPO_PATH/patch_analysis/revert_plan.sh <repo_path>`。

### APPLY
降级链（详见 `references/diagnostic-guide.md`）：
```
git am --3way <patch>
  ├─ 成功 → VERIFY_INTENT
  └─ 失败 → git apply --3way --reject
       ├─ 成功 → 分析 .rej 文件手动填入 → VERIFY_INTENT
       └─ 失败 → 读取 .patch 逐 hunk 手工匹配 → VERIFY_INTENT
```
冲突解决按 Ours/Theirs 决策表（`references/diagnostic-guide.md`）。

**硬性规则**：
- **patch 的 `+` 行（新增代码）→ 必须保留**，不可选 Ours 删除
- **introduced_symbols 所在行 → 必须保留**，不可丢失

### VERIFY_INTENT（APPLY 后强制校验）

**每次 APPLY 完成后必须执行，确保 patch 核心意图未被冲突解决破坏：**

```bash
python3 "$SCRIPTS_DIR/verify_patch_intent.py" \
  --patch-file "<patch_file>" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" \
  --repo-path "$KERNEL_REPO_PATH"
```

**退出码含义**：

| 退出码 | 含义 | 处理 |
|--------|------|------|
| 0 | ✅ patch 意图完整保留 | 进入 BUILD |
| 1 | ⚠️ 部分 + 行缺失 | 检查缺失行 → 补充 → 重新校验 |
| **3** | **❌ introduced_symbols 缺失** | **严重：核心功能代码丢失 → 暂停等用户决策** |

**每个 APPLY 完成后必须显式输出**：
```
[VERIFY_INTENT] task_id=0001
introduced_symbols: func_a ✅ / MACRO_B ✅
patch + 行:  150/150 ✅
结论: ✅ patch 意图完整保留 → BUILD
```

### BUILD

**强制约束：必须编译并验证整个仓库，不可跳过、不可只编译部分文件！**

**★ 禁止的编译方式（绝对不允许，违者不能进入 COMMIT）**：

| 禁止 | 原因 |
|------|------|
| `make path/to/file.h` | 头文件不触发任何编译动作，zero-error 假通过 |
| `make path/to/file.o` | 只编译单个文件，无法发现链接错误和跨文件依赖 |
| `make drivers/xxx/` | 只编译单个子目录，无法发现全局影响 |
| `make`（不带 arch）| 可能编译错误架构 |
| 编译后不验证 Image 产物 | 可能只编译了部分中间文件 |

**★ 唯一允许的编译方式**：
```bash
$BUILD_CMD 2>&1 | tee "$BUILD_LOG"
# 其中 BUILD_CMD="make ARCH=$KERNEL_ARCH -j$(nproc)"
# 必须验证产物: arch/$KERNEL_ARCH/boot/Image 存在
```

**编译策略**：不是每个 patch 都编译，只在 `build_checkpoint=true` 的 patch 时编译验证。

**BUILD 开始时检查 checkpoint**：

```bash
if [ "$build_checkpoint" = "true" ]; then
    # 执行编译验证（完整流程），完成后调用 gatekeeper --step BUILD
else
    echo "[BUILD SKIP] task_id=$task_id 非验证点，跳过编译"
    # 不调用 gatekeeper --step BUILD，state_log 不会有 BUILD 记录
    # 直接进入 COMMIT
fi
```

> **约束**：`build_checkpoint=false` 的 task **不调用 gatekeeper --step BUILD**。
> Phase 3 查询时：`state_log` 有 BUILD pass 记录 → 必定是验证点，且真的编译过。

**编译流程**（仅 build_checkpoint=true 时执行）：

**BUILD 开始前先标记 in_progress**：

```bash
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" \
  --step BUILD --result in_progress
```

**步骤 1：确定编译目标**（确定，不依赖外部脚本）

```bash
# 基础编译目标
BUILD_CMD="make ARCH=$KERNEL_ARCH -j$(nproc)"

# 有 tools/perf 文件 → 追加 perf 编译
PERF_FILES=$(python3 -c "
import json
d = json.load(open('$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json'))
for s in ['deps_order', 'merge_order']:
    for t in d.get(s, []):
        for f in t.get('files_changed', []):
            if f.startswith('tools/perf/'):
                print('1')
                exit(0)
" 2>/dev/null) || true
if [ -n "$PERF_FILES" ]; then
    BUILD_CMD="$BUILD_CMD && make -C tools/perf"
fi
```

**步骤 2：驱动模块临时开启 CONFIG=m（强制执行，不可跳过）**

> **⚠️ 只要涉改文件包含 drivers/* 或 sound/*，就必须执行此步骤。**

```bash
cd "$KERNEL_REPO_PATH"

# 提取所有涉改的驱动文件
DRIVER_FILES=$(python3 -c "
import json
d = json.load(open('$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json'))
for s in ['deps_order', 'merge_order']:
    for t in d.get(s, []):
        for f in t.get('files_changed', []):
            if f.startswith('drivers/') or f.startswith('sound/'):
                print(f)
" 2>/dev/null)

if [ -n "$DRIVER_FILES" ]; then
    echo "[DRIVER] 检测到驱动文件，开启对应 CONFIG=m"
    
    for f in $DRIVER_FILES; do
        dir_path=$(dirname "$f")
        makefile="$KERNEL_REPO_PATH/$dir_path/Makefile"
        
        if [ ! -f "$makefile" ]; then
            continue
        fi
        
        # 解析 Makefile 中的 obj-$(CONFIG_XXX) → 提取 CONFIG 名
        configs=$(grep -oP 'obj-\$\((\w+)\)' "$makefile" 2>/dev/null \
            | sed 's/obj-\$(\(.*\))/\1/' | sort -u || true)
        
        for cfg in $configs; do
            # 已是 m 或 y → 跳过
            if grep -q "^${cfg}=[my]$" "$KERNEL_REPO_PATH/.config" 2>/dev/null; then
                continue
            fi
            # 不是 m → 临时开启
            echo "  临时开启: $cfg=m"
            $KERNEL_REPO_PATH/scripts/config --module "$cfg" 2>/dev/null || true
            CONFIG_CHANGED=1
        done
    done
    
    if [ "${CONFIG_CHANGED:-0}" -eq 1 ]; then
        # 刷新 .config（旧 defconfig 可能冲突）
        make ARCH=$KERNEL_ARCH olddefconfig 2>/dev/null || true
    fi
fi
```

**步骤 3：执行编译**

```bash
BUILD_LOG="/tmp/patch_build_<task_id>.log"
echo "编译命令: $BUILD_CMD"
$BUILD_CMD 2>&1 | tee "$BUILD_LOG"
```

**步骤 4：恢复 .config（不污染仓库）**

```bash
if [ "${CONFIG_CHANGED:-0}" -eq 1 ]; then
    git checkout .config
    echo "[RESTORE] .config 已恢复"
fi
```

**步骤 5：提取模块信息 + 门禁验证**

```bash
MODULE_DIRS=$(python3 -c "
import json
d = json.load(open('$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json'))
for section in ['deps_order', 'merge_order']:
    for t in d.get(section, []):
        if t.get('task_id') == '<task_id>':
            dirs = set()
            for f in t.get('files_changed', []):
                if f.startswith('drivers/') or f.startswith('sound/'):
                    dirs.add(f.rsplit('/', 1)[0])
            print(','.join(sorted(dirs)) if dirs else '')
            sys.exit(0)
") || true

MODULE_COUNT=0
if [ -n "$MODULE_DIRS" ]; then
    for d in $(echo "$MODULE_DIRS" | tr ',' ' '); do
        cnt=$(find "$d" -name "*.ko" -type f 2>/dev/null | wc -l)
        MODULE_COUNT=$((MODULE_COUNT + cnt))
    done
fi

bash "$SCRIPTS_DIR/verify_build.sh" \
  --log "$BUILD_LOG" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" \
  --repo-path "$KERNEL_REPO_PATH" \
  --product "arch/$KERNEL_ARCH/boot/Image"

python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" \
  --step BUILD --result pass \
  --error-count <error_count> \
  --product "arch/$KERNEL_ARCH/boot/Image" \
  --build-target "$BUILD_CMD" \
  --module-dirs "$MODULE_DIRS" \
  --module-count "$MODULE_COUNT"
```

> 非验证点的 patch 直接跳过 BUILD 步骤，进入 COMMIT。

**每个 checkpoint 完成后必须显式输出**：
```
[BUILD CHECKPOINT] task_id=<task_id>
编译命令:  $BUILD_CMD
模块目录:  ${MODULE_DIRS:-无}
模块产物:  ${MODULE_COUNT:-0} 个 .ko
日志路径:  /tmp/patch_build_<task_id>.log
error 数:  <error_count>
产物验证:  Image ✅ / 模块 ✅
结论:      ✅ 编译通过

[SKIP] task_id=0002 非验证点，跳过编译
[SKIP] task_id=0003 非验证点，跳过编译
```

### BUILD_FIX

编译失败时的修复策略。**绝对禁用 `git reset`**，使用 rebase amend 工作流。

**根因定位（按文件/符号/功能反查）**：

编译失败时，错误不一定在当前 checkpoint patch 中，可能来自此 checkpoint 组内的更早 patch。

```bash
# 步骤 0：确定 checkpoint 组范围
# 上一个 checkpoint 的 task_id → 当前 checkpoint 的 task_id
# 例如：上一个 ✅ 是 0001，当前 ✅ 是 0005 → 组内 patch = [0002, 0003, 0004, 0005]
```

**步骤 1：提取编译错误信息**

从 BUILD_LOG 提取每条 error 的三要素：

```
错误文件: drivers/gpu/arm/mali_kbase_core.c:150
错误符号: kbase_reg_write
错误功能: GPU 寄存器写入
```

**步骤 2：反查 patch（文件匹配 → 符号匹配 → 功能匹配）**

| 匹配方式 | 查询来源 | 匹配条件 |
|---------|---------|---------|
| 文件匹配 | task `files_changed` | 错误文件 ∈ files_changed |
| 符号匹配 | task `introduced_symbols` + `referenced_symbols` | 错误符号 ∈ introduced_symbols ∪ referenced_symbols |
| 功能匹配 | task `功能分类` | 错误功能模块 == 功能分类（如 driver ↔ driver 匹配） |

**步骤 3：定位结果输出**

```
[BUILD_FAIL] 定位错误源：

错误文件: drivers/gpu/arm/mali_kbase_core.c
错误符号: kbase_reg_write
错误行号: 150

检查点范围: 0002 (上一个 ✅) → 0005 (当前 ✅)
组内 patch:
  0002: drivers/gpu/arm/mali_kbase_ctx.c     (功能: driver)
  0003: drivers/gpu/arm/mali_kbase_common.h  (功能: driver)  ← 符号匹配
  0004: drivers/gpu/arm/mali_kbase_core.c    (功能: driver)  ← 文件匹配 ✅
  0005: drivers/gpu/arm/mali_kbase_debug.c   (功能: driver)

定位结果: 0004 匹配错误文件 + 0003 匹配错误符号
建议: 先检查 0004 的实现代码，若符号 kbase_reg_write 定义在 0003 则先 amend 0003
```

**步骤 4：rebase amend 修复**

```bash
# 假设出错 patch 是 0003，当前在 0005（checkpoint）
N=3  # 覆盖 0003/0004/0005
git rebase -i HEAD~3
# 将 0003 标记为 "edit"

# 在 0003 上修复
vim <错误文件>
make $BUILD_TARGET -j$(nproc)    # 验证修复

# 提交修复
git add <只改过的文件>            # 禁止 -A，禁止 -a
git commit --amend --no-edit     # 小修不改 message
git rebase --continue

# 在 checkpoint 重新编译验证
git log -1 --oneline             # 确认当前在 0005
make $BUILD_TARGET -j$(nproc)    # 再次验证
```

**关键原则**：
- ❌ **绝对禁用 `git reset --hard`** 和 `git reset HEAD~N`
- ✅ 使用 `git rebase -i` + `edit` + `commit --amend` + `rebase --continue`
- ✅ 只改属于目标 patch 的代码
- ✅ `git add` 只加实际改过的文件，禁止 `git add -A`

**错误分类修复**：

| 错误类型 | 处理方式 |
|---------|---------|
| 当前 checkpoint 组内某 patch 语法/逻辑错误 | rebase amend 该 patch |
| 调用不存在的符号 | 标记为缺失依赖，检查是否需要插入新 dep |
| patch 引入的新功能需要新 CONFIG | 启用 CONFIG + 保留修改，识别为 checkpoint 内正确 patch 后 amend |
| 非 patch 的环境 CONFIG 缺失 | 临时启用 → make → `git restore .config` |

**CONFIG 操作**：
```bash
./scripts/config --enable CONFIG_NEW_FEATURE
make olddefconfig
# 编译后若为环境 CONFIG → git restore .config
# 若为 patch 需要的 CONFIG → amend 到对应 patch
```

### 10 轮失败处理
累计 10 次冲突解决或编译修复未通过 → 深度分析根因 → 输出具体方案：

1. **冲突定位**：精确到 文件:行号:函数名 + 错误原文
2. **根因分析**：Ours vs Theirs 代码对比 / 编译器错误原文 / 语义矛盾点
3. **具体推荐方案（2-4 个，每个可直接操作）**：
   - 方案 A: 具体操作步骤 → 影响范围 → 风险 → 所需额外工作
   - 方案 B: ...
   - ...
   - 方案 C: skip 此 patch（放倒数第二，标注后续依赖程度：强/中/弱）
4. **推荐**（标注理由）

### COMMIT
```bash
# 0. COMMIT 开始前标记 in_progress（恢复点）
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" \
  --step COMMIT --result in_progress

# 1. 门禁检查：BUILD 必须已通过（不可跳过）
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" \
  --step COMMIT --check
# 若 exit code ≠ 0 → 禁止 commit，回到 BUILD 步骤

# 1. 提交
git commit -m "<patch subject>" --author="<patch author>"

# 2. 验证只含本 patch 文件
git diff --staged

# 3. 更新状态机
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" \
  --step COMMIT --result pass \
  --commit <commit_hash>
```

### REVIEW
调用 **code-review-expert skill**（skill 框架按名称自动加载），对 `HEAD~1..HEAD` 做 review。
若 reference 不存在则跳过，标注"未做自动 review"。
- Must Fix 意见 → 标记需 rebase amend
- Suggest 意见 → 记录不阻塞

### RECORD

**合入过程数据暂存，不写 analyse.md。Phase 3 统一落盘。**

将当前 task 的合入经验追加记录到 `$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json` 的 `execution_log` 中，供 Phase 3 使用：

- 冲突解决过程：描述 + 解决方式（Ours/Theirs 决策）
- 编译修复记录：修改了哪些文件、修改原因
- loop 次数：冲突 N 次 / 编译 M 次
- review 意见：Must Fix / Suggest 项
- 编译验证结果：`$BUILD_CMD` 的错误数 + 产物状态

**注意**：如果后续 rebase 修改了此 patch，RECORD 数据需同步更新到 execution_log。

---

## 跨 Patch 修复（rebase + amend）

当 merge 后续 patch 时发现根因在前面已 commit 的 patch：

```bash
git rebase -i HEAD~N            # 标记目标 commit 为 edit
# 编辑文件 → 只改属于此 patch 的代码
$BUILD_CMD
git add <只改过的文件>            # 禁止 -A
git commit --amend               # 小修不改 message，大修末尾追加 Fixup 说明
git rebase --continue
$BUILD_CMD                       # 终验
```
然后更新目标 patch 的 analyse.md（追加修复记录）。

---

## Phase 3：汇总落盘

所有 task 状态为 `done`/`skipped`/`failed` 后，**批量确定性生成**，确保所有 patch 的分析文件不遗漏：

> **⚠️ 硬性门禁**：Phase 3 依赖 `analysis_cache.json` 和 `merge_tasks.json` 存在。
> 进入 Phase 3 前先验证：
> ```bash
> python3 "$SCRIPTS_DIR/validate_phase1_artifacts.py" \
>   --merge-tasks "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
>   --analysis-cache "$KERNEL_REPO_PATH/patch_analysis/analysis_cache.json"
> ```
> **必须通过脚本落盘，禁止 agent 手动绕过脚本直接写文件。**

**步骤 1：批量生成所有 analyse.md**

```bash
# 一条命令生成所有 patch 的 analyse.md（遍历 merge_order + deps_order）
python3 "$SCRIPTS_DIR/generate_all_analyses.py" \
  --analysis-cache "$KERNEL_REPO_PATH/patch_analysis/analysis_cache.json" \
  --merge-tasks "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --diff-script "$SCRIPTS_DIR/generate_diff_report.py" \
  --repo-path "$KERNEL_REPO_PATH" \
  --output-dir "$KERNEL_REPO_PATH/patch_analysis/"
```

**退出码含义**：
| 退出码 | 含义 | 处理 |
|--------|------|------|
| 0 | 全部成功 | 进入步骤 2 |
| 1 | 部分失败 | 检查失败列表，修复后重新运行 |
| 2 | 参数错误 | 检查文件路径 |

**步骤 2：AI 补充文字性内容**

脚本生成的 analyse.md 中 `{REQUIRES_AI}` 标记的字段需要 AI 补充：
- 第 2 节功能描述（若 analysis_cache 无完整文本）
- 第 3 节依赖分析文字说明
- 第 8 节合入经验（若无 execution_log）
- 第 11 节 Review 建议

**步骤 3：门禁验证（确定性脚本，确保所有文件存在且格式正确）**

```bash
# 一体验证：应有文件存在 + 格式完整 + 无占位符残留
python3 "$SCRIPTS_DIR/verify_analyse_format.py" \
  --dir "$KERNEL_REPO_PATH/patch_analysis/" \
  --expected-from "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json"
```

**退出码含义**：
| 退出码 | 含义 | 处理 |
|--------|------|------|
| 0 | 全部通过 | 进入步骤 4 |
| 1 | 章节缺失 | 补充缺失章节 |
| 2 | 占位符未替换 | 将 `{xxx}` 替换为实际内容 |
| 4 | 文件不存在 | 重新运行 generate_all_analyses.py |
| **5** | **应有文件缺失** | 对比 merge_tasks.json 与实际文件，运行步骤 1 补充生成 |

**步骤 4：生成 summary.md**

```bash
python3 "$SCRIPTS_DIR/generate_summary_md.py" \
  --analyse-dir "$KERNEL_REPO_PATH/patch_analysis/" \
  --merge-tasks "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --output "$KERNEL_REPO_PATH/patch_analysis/summary.md"

# 验证 summary 格式
python3 "$SCRIPTS_DIR/verify_analyse_format.py" \
  --type summary \
  --file "$KERNEL_REPO_PATH/patch_analysis/summary.md"
```

**步骤 5：最终验证**

```bash
ls -la "$KERNEL_REPO_PATH/patch_analysis/"
# 应包含：0001-*-analys.md, 0002-*-analys.md, ..., summary.md

# 格式一体验证（确保所有文件无占位符残留）
python3 "$SCRIPTS_DIR/verify_analyse_format.py" \
  --dir "$KERNEL_REPO_PATH/patch_analysis/"
```

**Phase 3 完成后必须输出提醒**（不依赖 AI 记忆，硬编码到流程中）：

```
═══════════════════════════════════════════════
  ⚠️ 任务完成 — 请检查分析文件
═══════════════════════════════════════════════

  执行以下命令检查：
    ls "$KERNEL_REPO_PATH/patch_analysis/"

  必须包含：
    ✓ 0001-*-analys.md ~ 000N-*-analys.md  (每个 patch)
    ✓ summary.md                            (汇总报告)
    ✓ merge_tasks.json                      (调度文件)
    ✓ analysis_cache.json                   (分析缓存)
    ✓ 0001-diff.txt ~ 000N-diff.txt         (diff 报告)

  若缺少任何文件 → 重新加载 merge-patchset skill，
  告知 AI 补充生成缺少的分析文件。
═══════════════════════════════════════════════
```

## Phase 4：清理中间产物

汇总落盘完成后，列出所有中间产物供用户选择是否删除。**只列不删**，由用户决定。

### 永久保留（不列出）

```
$KERNEL_REPO_PATH/patch_analysis/000N-*-analys.md  # 每 patch 的分析报告
$KERNEL_REPO_PATH/patch_analysis/summary.md        # 汇总报告
$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json  # 合并任务调度文件
$KERNEL_REPO_PATH/patch_analysis/analysis_cache.json # Phase 1 分析缓存
$KERNEL_REPO_PATH/patch_analysis/<task_id>-diff.txt  # diff 报告
git commits（已合入内核仓库）
```

### 中间产物清单（可安全删除）

| 路径 | 说明 |
|------|------|
| `/tmp/patches/0001-*.patch` ~ `000N-*.patch` | 下载的原始 patch 文件 |
| `/tmp/patches/deps/*.patch` | 上游依赖 patch 文件 |
| `/tmp/patches/patchset.metadata.json` | patchset 元数据 |
| `*.rej`（内核仓库下） | git apply --reject 产生 |
| 编译产物 | `.o`、`Image` 等 |

⚠️ **不建议清理** `$KERNEL_REPO_PATH/patch_analysis/` — 其中包含分析报告、调度文件和 diff 报告，是本次合入的完整记录，有持久化价值。

### 输出格式

```
## 清理建议

以下中间产物已不再需要，是否需要删除？

1. /tmp/patches/ (N 个 .patch + 元数据) — 下载的原始 patch
2. /tmp/patches/deps/ — 上游依赖 patch
3. *.rej 文件 — git apply 冲突残留
4. 编译产物（make clean 清理）

⚠️ $KERNEL_REPO_PATH/patch_analysis/ 不建议清理 — 含完整分析记录

请选择要清理的项目（输入编号，逗号分隔，直接回车跳过）：
```

---

## 任务恢复

重启时读 `$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json`，找 `status ≠ "done"` 的 task：
- 工作区干净 → 从 PRECHECK 开始
- 有未提交改动 → 提示用户清理
- am 中间态 → `git am --abort`，重新开始

---

## 两大场景处理

### 场景 A：高版本源端合入
从高版本 Linux 源端合入 patchset，使用 b4 + git blame + git log -S 向前向后搜索依赖和 bugfix。要求速度快、定位精准。

### 场景 B：本地实现 + 新版本代码合并
本地已有实现代码，需合并新版本：
- 判断目标仓库是否有高依赖 patch
- 评判机制：是否需要回退本地实现
  - 独立特性实现 → 建议全部回退
  - 局部修改 → 分析回退范围
