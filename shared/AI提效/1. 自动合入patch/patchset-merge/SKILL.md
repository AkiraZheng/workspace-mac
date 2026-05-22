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
| | | "没有源仓库" / "无upstream" → 降级模式 | | 仅 metadata 推断 |
| | | 未提及 → 自动检测 `~/.cache/linux-upstream` | | 不存在则浅克隆，不可用则降级 |
| `KERNEL_ARCH` | grep `CONFIG_ARM64=y` `.config` → arm64 | 自动 | |
| `BUILD_CMD` | `make ARCH=$KERNEL_ARCH Image` | 自动 | |

## 硬性约束

以下约束来自项目规范，不可跳过：

1. **逐个合入 + 逐个 commit**：N 个 patch 产生 N 个 commit，不允许批量
2. **仅在出现问题时与用户交互**：正常合入→编译通过→commit→review 全过程自动流转；仅当冲突无法自动解决（10 轮上限）、循环依赖、或重复 patch 判定时暂停等用户决策
3. **每 commit 后调用 code-review-expert skill**（路径：`references/code-review-expert/SKILL.md`，缺则跳过并标注）
4. **revert 逐个 commit**：逆序（最新→最旧），每 revert 一个就 commit 一个
5. **每 patch 必须编译验证**：执行 `$BUILD_CMD`，0 error + 产物存在
6. **merge 串行，分析并行**：merge 步骤不可并行，前期分析只读可并行
7. **中文输出**：所有思考、解释、分析、输出报告使用中文
8. **只取改动行**：只应用 `+`/`-` 行，上下文行不强制合入
9. **修改严格归所属 patch**：不混入无关改动到其他 patch 的 commit
10. **编译通过 + 功能正常是第一指标**，两者同等优先级
11. **操作在独立分支**，不在主干分支

## 工作流总览

```
Phase 0: 下载（脚本）→ /tmp/patches/000N-*.patch + metadata.json
Phase 1: 并行分析（只读，不写文件）→ 屏幕输出分析结果
Phase 1.5: 主 Agent 汇总 → merge_tasks.json + analysis_cache.json
Phase 2: 串行 Merge（写入）→ 每 patch commit 后落盘 analyse.md
Phase 3: 汇总 → summary.md
```

## 文件清单

- `SKILL.md` — 本文件
- `scripts/download_patches.py` — 统一下载入口（b4/wget/本地）
- `scripts/generate_diff_report.py` — diff 对比生成
- `references/diagnostic-guide.md` — 冲突诊断决策树（Ours/Theirs）
- `references/output-templates.md` — analyse.md / summary.md 模板 + 屏幕输出格式
- `references/code-review-expert/SKILL.md` — 捆绑的 review skill

---

## Phase 0：下载

**执行者**：`scripts/download_patches.py`（确定性脚本，不是 agent）

```bash
python3 scripts/download_patches.py \
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

---

## Phase 1：并行分析（只读，不写文件）

### 分析 Agent 分配策略

| Patch 总数 | 每 Agent 负责 | Agent 数 |
|-----------|-------------|---------|
| ≤3 | 全部 | 1（主 Agent 兼任） |
| 4-8 | 2-3 个 | 2-3 |
| ≥9 | ≤4 个 | N/4 向上取整 |

### 分析 Agent 执行流程

**步骤 1: 理解 commit message（优先）**
先深入理解每个 patch 的 commit message：功能是什么、关联哪个子模块、是否标注了前置依赖 commit。

**步骤 2: 分析代码 diff**
解析每个 patch 的 diff，提取：
- `introduced_by_patch`：本 patch 新增/修改的函数名、宏名、类型名
- `referenced_symbols`：本 patch 调用/引用的符号
- `changed_files`：涉改文件的路径和行号范围

**步骤 3: 向后搜索 Bugfix（在 upstream 仓库上执行）**

```bash
# 对每个 changed_file，blame 追踪后续改动
git -C "$UPSTREAM_REPO_PATH" blame -L <start>,<end> <branch> -- <file>

# 查找 Fixes 标签（更精准）
git -C "$UPSTREAM_REPO_PATH" log --grep="Fixes:.*<upstream-commit-short>" \
    --all --format="%h %s"

# 递归追溯 bugfix 的 bugfix
```

**步骤 4: 向前搜索依赖**

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

**步骤 5: 检测目标仓库中的重复/等效 patch（在目标仓库上执行）**

在目标内核仓库中检查是否已有同等功能的 patch（已合入的 backport 或其他来源的等效实现）。

```bash
# 方法 1：搜索相同 commit subject
git -C "$KERNEL_REPO_PATH" log --all --oneline --grep="<patch subject 关键词>"

# 方法 2：搜索 patch 引入的关键函数是否已存在
git -C "$KERNEL_REPO_PATH" log --all --oneline -S "<key_function_name>"

# 方法 3：检查涉改文件行范围的修改历史
git -C "$KERNEL_REPO_PATH" log --oneline -L <start>,<end>:<file>
```

判定标准：

| 匹配程度 | 判定 | 处理 |
|---------|------|------|
| 包含相同 upstream commit hash | **精确重复** | 建议跳过，不重复合入 |
| subject 高度相似 + 改动相同函数 | **高概率等效** | 建议跳过 + 人工确认 |
| 同一文件区域有功能相似改动 | **可能冲突** | 合入时需特别注意 |
| 无匹配 | **无重复** | 正常流程 |

**步骤 6: 屏幕输出**
按 `references/output-templates.md` 中的结构化格式输出到屏幕。

---

## Phase 1.5：主 Agent 汇总

**步骤 1: 跨 patch 冲突检测**
- 文件修改集合重叠（直接重叠或相邻 <10 行）→ `CONFLICT_HIGH`
- `introduced` 符号的交叉引用 → 语义冲突
- `used ∩ introduced` → 强依赖（P_j 调用了 P_i 引入的符号）

**步骤 2: 依赖图 + 拓扑排序**
构建有向图 → 检测循环依赖 → 输出 merge_order。与原始 patchset 顺序对比，说明调整原因。

**步骤 3: 全局 Revert 清单去重**
所有 agent 报告的 revert commit 去重合并，按 commit 时间逆序排序。

**步骤 4: 生成 merge_tasks.json 和 analysis_cache.json**

写入 `/tmp/patches/merge_tasks.json` 和 `/tmp/patches/analysis_cache.json`。

**merge_tasks.json 必须严格按照以下 schema 生成，不可自行增减字段：**

每个 task 必须包含：
- `seq` — 执行序号（merge agent 严格按此升序执行）
- `task_id` — patch 编号（0001~000N）
- `status` — `pending`（初始值，Phase 2 动态更新）
- `patch_file` — .patch 文件的绝对路径
- `subject` — patch 标题
- `author` — patch 作者
- `files_changed` — 涉改文件路径列表
- `action` — `apply` | `skip`（判定是否需要合入）
- `skip_reason` — 若 skip，必须填写具体原因
- `pre_revert` — 需先 revert 的本地 commit hash 列表
- `depends_on` — 前置 task_id 列表
- `risk_level` — `高` | `中` | `低`
- `review_required` — `高` | `中` | `低`
- `blame_hits` — bugfix commit 列表（step 3 产物）
- `duplicate_info` — 目标仓库重复检测结果（step 5 产物）
- `conflicts_predicted` — 预判冲突点列表（文件:行号:原因）
- `special_notes` — 合入注意事项
- `execution_log` — `[]`（初始空数组，Phase 2 动态追加）

顶层必须包含 `global_revert_order`（去重+逆序的全局 revert 列表）。

**analysis_cache.json** 按 `references/output-templates.md` 中定义的字段生成。

**步骤 5: 校验 + 屏幕预览 → 用户确认**

写入后必须校验每个 task 的必填字段完整，然后按 `references/output-templates.md` 中"Phase 1.5 全局预览模板"的 4 部分格式展示给用户确认：依赖汇总 → Revert 清单 → 合入计划 → 确认交互。

---

## Phase 2：串行 Merge

### 启动
读取 `/tmp/patches/merge_tasks.json`，按 `merge_order[].seq` 升序处理每个 task。

### 状态机

```
PRECHECK → PRE_REVERT → APPLY → BUILD → COMMIT → REVIEW → RECORD → DONE
```

### PRECHECK
- 校验 patch 文件存在
- 校验 `depends_on` 中所有 task_id 状态为 `done`
  - 若前置被 skip → 检查 `skip_dependency_impact`：强→阻塞，中/弱→允许继续
- 工作区干净：`git diff --quiet && git diff --cached --quiet`

### PRE_REVERT
- 按逆序逐个 `git revert <commit> --no-edit`
- 冲突按 `references/diagnostic-guide.md` 决策树解决
- 失败回滚：`git revert --abort` + `git reset --hard HEAD~N`

### APPLY
降级链（详见 `references/diagnostic-guide.md`）：
```
git am --3way <patch>
  ├─ 成功 → BUILD
  └─ 失败 → git apply --3way --reject
       ├─ 成功 → 分析 .rej 文件手动填入
       └─ 失败 → 读取 .patch 逐 hunk 手工匹配
```
冲突解决按 Ours/Theirs 决策表（`references/diagnostic-guide.md`）。

### BUILD
```bash
$BUILD_CMD -j$(nproc)
# 通过条件: 0 error + 编译产物存在
# 超时: 120 秒
```

### BUILD_FIX
编译失败时的错误分类修复（详见 `references/diagnostic-guide.md`）：
- patch 代码本身的语法/逻辑错误 → 编辑源文件最小修复
- 调用不存在的符号 → 标记为缺失依赖，尝试最小适配或 stub
- 非 patch 的 config 问题 → 临时改 `.config` → make → `git restore .config`，记录在 analyse.md

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
git commit -m "<patch subject>" --author="<patch author>"
```
二次确认 `git diff --staged` 只含本 patch 文件。

### REVIEW
加载 `references/code-review-expert/SKILL.md`，对 `HEAD~1..HEAD` 做 review。
若 reference 不存在则跳过，标注"未做自动 review"。
- Must Fix 意见 → 标记需 rebase amend
- Suggest 意见 → 记录不阻塞

### RECORD

**合入过程数据暂存，不写 analyse.md。Phase 3 统一落盘。**

将当前 task 的合入经验追加记录到 `/tmp/patches/merge_tasks.json` 的 `execution_log` 中，供 Phase 3 使用：

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

所有 task 状态为 `done`/`skipped`/`failed` 后，**必须写入以下全部文件，不可只写 summary**：

```bash
mkdir -p "$KERNEL_REPO_PATH/patch_analysis"
```

**对每个 task（含 done / skipped / failed）**：

```bash
# 1. 从 analysis_cache.json 读取 Phase 1 分析数据
# 2. 从 merge_tasks.json 的 execution_log 读取 Phase 2 合入经验
# 3. 生成 diff 对比（仅 done 的 task，skipped/failed 标注"未合入"）
python3 scripts/generate_diff_report.py \
  --patch-file "/tmp/patches/<task_id>-<name>.patch" \
  --repo-path "$KERNEL_REPO_PATH" \
  --commit <commit_hash> \
  > "/tmp/patches/<task_id>-diff.txt"

# 4. 按模板写入
```

**写入路径**：`$KERNEL_REPO_PATH/patch_analysis/<task_id>-<name>-analys.md`

**必需内容**（每份 analyse.md）：
- Phase 1 分析数据（analysis_cache.json 中对应条目）
- Phase 2 合入经验（merge_tasks.json 中 execution_log）
- 完整 diff（generate_diff_report.py 输出）
- 编译验证记录

**然后写入汇总**：
- 读取 `$KERNEL_REPO_PATH/patch_analysis/` 下所有 `*-analys.md`
- 读取 `/tmp/patches/merge_tasks.json` 获取执行历史
- 按 `references/output-templates.md` 中的 summary.md 模板写入 `$KERNEL_REPO_PATH/patch_analysis/summary.md`

**最终验证**：
```bash
ls -la "$KERNEL_REPO_PATH/patch_analysis/"
# 应包含：0001-*-analys.md, 0002-*-analys.md, ..., summary.md
```

## Phase 4：清理中间产物

汇总落盘完成后，列出所有中间产物供用户选择是否删除。**只列不删**，由用户决定。

### 永久保留（不列出）

```
$KERNEL_REPO_PATH/patch_analysis/000N-*-analys.md  # 每 patch 的分析报告
$KERNEL_REPO_PATH/patch_analysis/summary.md        # 汇总报告
git commits（已合入内核仓库）
```

### 中间产物清单（可安全删除）

| 路径 | 说明 |
|------|------|
| `/tmp/patches/0001-*.patch` ~ `000N-*.patch` | 下载的原始 patch 文件 |
| `/tmp/patches/<task_id>-diff.txt` | 每 patch 的 diff 报告临时文件 |
| `/tmp/patches/patchset.metadata.json` | patchset 元数据 |
| `/tmp/patches/merge_tasks.json` | 合并任务调度文件 |
| `/tmp/patches/analysis_cache.json` | Phase 1 分析缓存 |
| `*.rej`（内核仓库下） | git apply --reject 产生 |
| 编译产物 | `.o`、`Image` 等 |

### 输出格式

```
## 清理建议

以下中间产物已不再需要，是否需要删除？

1. /tmp/patches/ (N 个 .patch + 3 个 .json) — 下载和分析缓存
2. *.rej 文件 — git apply 冲突残留
3. 编译产物（make clean 清理）

请选择要清理的项目（输入编号，逗号分隔，直接回车跳过）：
```

---

## 任务恢复

重启时读 `merge_tasks.json`，找 `status ≠ "done"` 的 task：
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
