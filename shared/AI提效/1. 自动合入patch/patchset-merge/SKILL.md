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
5. **BUILD_CHECKPOINT 的 patch 必须编译验证**：执行 `$BUILD_CMD`，0 error + 产物存在
6. **merge 串行，分析并行**：merge 步骤不可并行，前期分析只读可并行
7. **中文输出**：所有思考、解释、分析、输出报告使用中文
8. **只取改动行**：只应用 `+`/`-` 行，上下文行不强制合入
9. **修改严格归所属 patch**：不混入无关改动到其他 patch 的 commit
10. **编译通过 + 功能正常是第一指标**，两者同等优先级
11. **操作在独立分支**，不在主干分支（如master，OLK-6.6）
12. **对于原本就有序的patch，禁止打乱原始 patch 顺序**：严格按 0001→0002→...→000N 顺序合入，不可跳过、不可重排
13. **禁止局部编译**：不允许 `make file.h` 或 `make file.o`，必须完整 `make ARCH=$ARCH -j$(nproc)`
14. **禁止单项编译**：不允许 `make Image`（只编译镜像）或 `make modules`（只编译模块），必须全编
15. **必须验证产物**：编译后必须检查 `arch/$ARCH/boot/Image` 存在且非空

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
Phase 0: 下载 → .config 来源 (3选1) → 预开驱动 CONFIG=m
         → 提取特征 → 创建分支 patch_merge_<feature>
Phase 0.5: 场景问询（detect_duplicate.py --version-upgrade）
         → 检测旧版本 → 用户选择 upgrade/backport
Phase 1: L1 脚本（extract_patch_symbols.py）→ analysis_cache.json 骨架
         L2 Agent（并行，Write JSON）:
           agent_analysis — Write 补全 analysis_cache.json
           agent_revert  — Write revert_audit.json
Phase 1.5: generate_merge_tasks.py → 确定性组装 merge_tasks.json + 校验
Phase 2: 串行 Merge → 每 patch commit 后落盘 analyse.md
Phase 3: 汇总 → summary.md
```

## 文件清单

- `SKILL.md` — 本文件
- `$SCRIPTS_DIR/download_patches.py` — 统一下载入口（b4/wget/本地 .patch/.mbox）
- `$SCRIPTS_DIR/detect_duplicate.py` — 重复检测 + PR 聚合 + revert 决策 + 版本升级模式（--version-upgrade）
- `$SCRIPTS_DIR/extract_patch_symbols.py` — L1 确定性脚本：从 .patch 提取符号/功能分类 → analysis_cache.json 骨架
- `$SCRIPTS_DIR/generate_diff_report.py` — diff 对比生成
- `$SCRIPTS_DIR/generate_analyse_md.py` — 确定性生成 analyse.md
- `$SCRIPTS_DIR/generate_summary_md.py` — 确定性生成 summary.md
- `$SCRIPTS_DIR/verify_analyse_format.py` — 格式验证门禁
- `$SCRIPTS_DIR/merge_order_sort.py` — 全量排序（revert优先+deps插入+稳定顺序）
- `$SCRIPTS_DIR/detect_duplicate.py` — 重复检测 + PR 聚合 + revert 决策 + 版本升级模式（--version-upgrade）
- `$SCRIPTS_DIR/generate_revert_plan.py` — 从分析结果生成 revert_plan.json + revert_plan.sh
- `$SCRIPTS_DIR/execute_revert.py` — 执行 revert 计划（预执行 + 正式执行 + 失败处理 + 回滚）
- `$SCRIPTS_DIR/validate_phase1_artifacts.py` — Phase 1.5→2 / 2→3 硬性门禁（schema 校验）
- `references/diagnostic-guide.md` — 冲突诊断决策树（Ours/Theirs）
- `references/output-templates.md` — analyse.md / summary.md 模板 + 屏幕输出格式
- `references/code-review-expert/SKILL.md` — 捆绑的 review skill（安装时自动部署为独立 skill）

---

## Phase 0：下载

**执行者**：`$SCRIPTS_DIR/download_patches.py`（确定性脚本，不是 agent）

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

---

### Phase 0 步骤 2：.config 来源配置

编译验证开始前，需要确定 `.config` 文件的来源。**只执行一次**，后续所有 checkpoint 编译复用此文件。

#### 2a. 复用检查

读取 `$KERNEL_REPO_PATH/.patchmerge/config_preference.json`。若存在，展示上次配置并询问是否复用：

```
═══════════════════════════════════════════════
  .config 来源配置 — 检测到上次配置
═══════════════════════════════════════════════

目标仓库: <KERNEL_REPO_PATH>
架构: <KERNEL_ARCH>

上次配置:
  选项:       [2] 提供完整 .config 文件
  来源路径:   /home/user/my-kernel.config
  时间:       2026-05-30 12:00

是否复用此配置？ [Y/n]
```

- **Y / 回车** → 直接按 `config_preference.json` 中的 option 和路径执行，跳过交互
- **n** → 清除偏好，进入 2b 完整交互

> 偏好文件路径：`$KERNEL_REPO_PATH/.patchmerge/config_preference.json`。仓库级别，跨 patchset 复用。

#### 2b. 完整交互

**用户问询**：

```
═══════════════════════════════════════════════
  .config 来源配置
═══════════════════════════════════════════════

目标仓库: <KERNEL_REPO_PATH>
架构: <KERNEL_ARCH>

请选择 .config 来源:

[1] 使用目标仓库已有 .config 文件
    (不做任何修改，直接进入下一步)

[2] 提供完整 .config 文件
    从指定路径 copy → make olddefconfig

[3] 提供增量 config 片段
    选基础 config + 增量片段 → merge → olddefconfig

  请选择: [1] / [2] / [3] (默认 [1])
```

**各选项实现 + 偏好保存**：

| 选项 | 执行 | 保存到 config_preference.json |
|------|------|-----|
| [1] | 检查 `$KERNEL_REPO_PATH/.config` 存在 → 继续 | `{"option": 1}` |
| [2] | 用户输入路径 → `cp <path> $KERNEL_REPO_PATH/.config` → `make ARCH=$KERNEL_ARCH olddefconfig` | `{"option": 2, "full_config_path": "<用户输入的路径>"}` |
| [3] | a. 扫描 `$KERNEL_REPO_PATH/arch/$KERNEL_ARCH/configs/*` 列出让用户选基础 config<br>b. 再次扫描同目录列出增量 config，末尾加 `[0] 手动输入外部文件路径` 供用户自由输入<br>c. `$KERNEL_REPO_PATH/scripts/kconfig/merge_config.sh -O "$KERNEL_REPO_PATH" <base> <incremental>`<br>d. `make ARCH=$KERNEL_ARCH olddefconfig` | `{"option": 3, "base_config": "<选中的基础config>", "incremental_path": "<选中的增量或用户输入的路径>"}` |

**偏好保存**（选项 2/3 执行成功后）：

```bash
mkdir -p "$KERNEL_REPO_PATH/.patchmerge"
python3 -c "
import json
with open('$KERNEL_REPO_PATH/.patchmerge/config_preference.json', 'w') as f:
    json.dump({
        'option': <opt>,
        'full_config_path': '<path>',
        'base_config': '<base>',
        'incremental_path': '<incr>',
        'last_used': '$(date -Iseconds)'
    }, f, indent=2)
"
```

**边界处理**：
- 路径不存在 → 报错，让用户重新输入
- `olddefconfig` 失败 → 报错退出，提示用户检查 config 文件
- 用户直接回车 → 默认 [1]
- 偏好文件不存在 → 直接进入 2b 完整交互

---

### Phase 0 步骤 3：一次性预开启驱动 CONFIG=m

`.config` 就绪后，扫描**所有 patch 的涉改文件**，一次性开启所有需要的驱动模块：

```bash
cd "$KERNEL_REPO_PATH"

DRIVER_FILES=$(python3 -c "
import re
from pathlib import Path
patches = sorted(Path('/tmp/patches').glob('0*.patch'))
all_files = set()
for p in patches:
    for line in p.read_text(errors='replace').split('\n'):
        m = re.match(r'diff --git a/(\S+) b/', line)
        if m:
            all_files.add(m.group(1))
for f in sorted(all_files):
    if f.startswith('drivers/') or f.startswith('sound/'):
        print(f)
" 2>/dev/null)

if [ -n "$DRIVER_FILES" ]; then
    echo "[CONFIG] 扫描到 $(echo "$DRIVER_FILES" | wc -l) 个驱动文件，预开启 CONFIG=m"

    all_configs=""
    for f in $DRIVER_FILES; do
        dir_path=$(dirname "$f")
        makefile="$KERNEL_REPO_PATH/$dir_path/Makefile"
        if [ ! -f "$makefile" ]; then
            continue
        fi
        configs=$(grep -oP 'obj-\$\((\w+)\)' "$makefile" 2>/dev/null \
            | sed 's/obj-\$(\(.*\))/\1/' | sort -u || true)
        all_configs="$all_configs $configs"
    done

    for cfg in $(echo "$all_configs" | tr ' ' '\n' | sort -u); do
        if grep -q "^${cfg}=[my]$" "$KERNEL_REPO_PATH/.config" 2>/dev/null; then
            continue
        fi
        echo "  + $cfg=m"
        $KERNEL_REPO_PATH/scripts/config --module "$cfg" 2>/dev/null || true
        CONFIG_CHANGED=1
    done

    if [ "${CONFIG_CHANGED:-0}" -eq 1 ]; then
        make ARCH=$KERNEL_ARCH olddefconfig 2>/dev/null || true
        echo "[CONFIG] olddefconfig 刷新完成"
    else
        echo "[CONFIG] 所有驱动模块已开启，无需修改"
    fi
else
    echo "[CONFIG] 无驱动文件，跳过"
fi
```

> `.config` 在 Phase 2 的每个 checkpoint 编译中复用，不再修改、不再恢复。

---

### Phase 0 步骤 4：创建独立操作分支（强制）

> ⚠️ 硬性约束：**操作必须在独立分支上进行**，禁止在 master / main / OLK-6.6 等主干分支操作。

```bash
# 1. 从第一个有效 patch 的 subject 提取特征名（大写缩写词）
FEATURE=$(python3 -c "
import re
from pathlib import Path
patches = sorted(Path('/tmp/patches').glob('0*.patch'))
if patches:
    for line in patches[0].read_text(errors='replace').split('\n')[:30]:
        m = re.match(r'Subject:\s*(.+)', line)
        if m:
            for w in m.group(1).split():
                clean = w.strip(':,;.()\"')
                if clean.isupper() and len(clean) >= 3:
                    print(clean)
                    exit(0)
print('patchset')
" 2>/dev/null)

BRANCH="patch_merge_${FEATURE}"

# 2. 若分支已存在，加 _v2 / _v3 后缀
SUFFIX=""
COUNT=1
while git -C "$KERNEL_REPO_PATH" rev-parse --verify "${BRANCH}${SUFFIX}" >/dev/null 2>&1; do
    COUNT=$((COUNT + 1))
    SUFFIX="_v${COUNT}"
done
BRANCH="${BRANCH}${SUFFIX}"

# 3. 创建并切换到新分支
git -C "$KERNEL_REPO_PATH" checkout -b "$BRANCH"
export KERNEL_BRANCH="$BRANCH"
echo "操作分支: $KERNEL_BRANCH（从 patch 特征自动创建）"
```

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

## Phase 0.5：场景问询（版本升级检测）

Phase 0 下载完成后、正式进入 Phase 1 前，检测目标仓库是否存在旧版本实现，让用户选择合入场景。

**步骤 1：初筛检测（用 version-upgrade 模式检测旧版本）**

```bash
python3 "$SCRIPTS_DIR/detect_duplicate.py" \
  --patch-dir /tmp/patches/ \
  --repo-path "$KERNEL_REPO_PATH" \
  --output "$KERNEL_REPO_PATH/patch_analysis/duplicate_analysis.json" \
  --version-upgrade
```

**步骤 2：检测结果表格展示**

脚本完成后，主 Agent 展示检测结果表格：

```
══════════════════════════════════════════════════════════════════════════════
  Phase 0.5 检测结果 — 重复/等效 Patch + PR 聚合 + Revert 建议
══════════════════════════════════════════════════════════════════════════════

[匹配统计] 高匹配阈值: >=30% (版本升级模式)
           中匹配阈值: >=15%

┌─────┬────────┬──────────────┬────────┬────────┬────────┬────────────┬──────────────┐
│ Seq │ Patch  │ 匹配 Commit  │ Diff   │ Symbol │ 综合   │ PR 归属    │ 匹配等级     │
├─────┼────────┼──────────────┼────────┼────────┼────────┼────────────┼──────────────┤
│  1  │ 0001   │ abc1234      │ 35.2%  │ 82.1%  │ 82.1%  │ PR!15754   │ 高匹配       │
│     │        │ def5678      │ 12.3%  │ 45.6%  │ 28.9%  │ PR!15754   │ 中匹配       │
├─────┼────────┼──────────────┼────────┼────────┼────────┼────────────┼──────────────┤
│  2  │ 0002   │ ghi9012      │ 91.2%  │ 95.3%  │ 95.3%  │ 独立 commit│ 高匹配       │
├─────┼────────┼──────────────┼────────┼────────┼────────┼────────────┼──────────────┤
│  3  │ 0003   │ 无匹配       │ —      │ —      │ —      │ —          │ —            │
└─────┴────────┴──────────────┴────────┴────────┴────────┴────────────┴──────────────┘

[PR 聚合] 按来源 PR 分组的匹配 commit：

┌─────────────┬─────────┬─────────────┬────────────┬──────────────────────────────┐
│ PR ID       │ Commits │ 高匹配数    │ 覆盖率     │ 关联 Patch                   │
├─────────────┼─────────┼─────────────┼────────────┼──────────────────────────────┤
│ PR!15754    │ 5       │ 3           │ 60%        │ 0001, 0004                   │
│ 独立 commit │ ghi9012 │ 1           │ 100%       │ 0002                         │
└─────────────┴─────────┴─────────────┴────────────┴──────────────────────────────┘

[Revert 建议] 按覆盖率判定 revert 策略：

┌─────────────┬─────────────┬──────────┬─────────────────────────────────────────┐
│ PR ID       │ 覆盖率      │ 紧急度   │ Revert 命令                              │
├─────────────┼─────────────┼──────────┼─────────────────────────────────────────┤
│ PR!15754    │ 60%         │ 建议     │ git revert abc1234 def5678 jkl3456      │
│             │             │          │ (逐个 revert，非整 PR)                   │
├─────────────┼─────────────┼──────────┼─────────────────────────────────────────┤
│ 独立 commit │ 100%        │ 必须     │ git revert -m 1 ghi9012                 │
│             │             │          │ (merge commit，用 -m 1)                  │
└─────────────┴─────────────┴──────────┴─────────────────────────────────────────┘

[旧版本批次] 版本升级模式扩展搜索结果：

┌─────┬─────────────┬─────────┬────────────┬──────────────────────────────────────┐
│ 批次│ 来源        │ Commits │ 时间范围   │ 关键词                               │
├─────┼─────────────┼─────────┼────────────┼──────────────────────────────────────┤
│  1  │ 关键词聚合  │ 8       │ 3天内     │ HDBSS, FEAT_HDBSS, DBM               │
│  2  │ revert追溯  │ 5       │ —         │ 来自 revert commit abc123            │
│  3  │ bugfix补充  │ 2       │ —         │ HDBSS 内存泄漏修复                   │
└─────┴─────────────┴─────────┴────────────┴──────────────────────────────────────┘

[风险分析] Revert 操作风险评估：

┌─────────────┬─────────────┬───────────────────────────────────────────────────────┐
│ PR ID       │ 风险等级    │ 风险详情                                               │
├─────────────┼─────────────┼───────────────────────────────────────────────────────┤
│ PR!15754    │ 中          │ 有 2 个后续 commit 可能依赖此 PR（dep_commits: mno789）│
│ 独立 commit │ 低          │ 无依赖 commit，涉改文件仅 3 个                          │
└─────────────┴─────────────┴───────────────────────────────────────────────────────┘

[关键词提取] 自动提取的特征关键词：
  HDBSS, FEAT_HDBSS, DBM, HDBSSF, HDBSSBR_EL2
```

**步骤 3：用户问询**

展示检测结果后，询问用户选择合入场景：

```
═══════════════════════════════════════════════
  场景问询 — 请选择合入场景
═══════════════════════════════════════════════

请选择合入场景：

[1] 版本升级（upgrade）
    要合入的 patchset 是旧版本的新版本。
    按上述表格执行 revert → 再合入新 patchset。
    PR 覆盖率 >=75% 的整体 revert，<75% 的逐个 revert。

[2] 纯新增（backport）
    目标仓库无相关实现，上述匹配为误报或极相似代码。
    不执行 revert，直接合入 patchset。
    仅当 diff ≥90% 时才暂停让用户确认。

[3] 查看详细匹配
    展示某个 patch 的完整匹配信息（diff 内容、符号列表）。

[4] 中止
    不执行任何操作，导出检测结果。

  请选择: [1] 版本升级 / [2] 纯新增 / [3] 查看详细 / [4] 中止
```

**步骤 4：用户选择后的行为**

| 选择 | 后续 |
|------|------|
| [1] 版本升级 | 记录场景为 `upgrade`，Phase 1 agent_revert 在 L2 做 AI 深度搜索旧版本 |
| [2] 纯新增 | 记录场景为 `backport`，Phase 1 agent_revert 只做严格审核（diff ≥90% → 暂停） |
| [3] 查看详细 | 展示指定 patch 的 `patch_duplicate_map[task_id]` 详细内容 |
| [4] 中止 | 退出，`duplicate_analysis.json` 已保存，用户可手动审查 |

**步骤 5：脚本结果传递给 subagent**

Phase 0.5 的 `duplicate_analysis.json` 输出包含以下字段，Phase 1 subagent 需读取：

| 字段 | 用途 |
|------|------|
| `patch_duplicate_map` | 每个 patch 对应的匹配 commit 列表（含 diff/symbol/pr_info） |
| `pr_aggregation` | PR 聚合结果（按 PR 分组，含 coverage_rate/revert_targets） |
| `global_revert_order` | 全局 revert 建议（按 urgency 排序，含 revert_cmd） |
| `version_upgrade.batches` | 旧版本批次（关键词聚合 + revert追溯 + bugfix补充） |
| `version_upgrade.keywords` | 提取的特征关键词（HDBSS, FEAT_HDBSS 等） |
| `thresholds` | 当前使用的阈值（sim_high/sim_medium） |
| `thresholds` | 当前使用的阈值（sim_high/sim_medium） |

---

## Phase 1：符号提取 + 语义分析

### L1 脚本层（确定性，并行执行）

在启动 L2 Agent 前，先运行 L1 确定性脚本。`detect_duplicate.py` 已在 Phase 0.5 完成，
此处运行 `extract_patch_symbols.py` 提取符号骨架：

```bash
# L1: 符号提取（生成 analysis_cache.json 骨架）
python3 "$SCRIPTS_DIR/extract_patch_symbols.py" \
  --patch-dir /tmp/patches/ \
  --output "$KERNEL_REPO_PATH/patch_analysis/analysis_cache.json"
```

产出 `analysis_cache.json`，含每个 patch 的：
- `introduced_symbols`：patch 新增/修改的函数名、宏名、结构体名
- `referenced_symbols`：patch 调用/引用的外部符号
- `功能分类`：按文件路径初步判定（infra/core/driver/fs/net/sound/doc/bugfix）
- `feature_signature.keywords` + `scope_dirs`：从 patch 路径推断
- `changed_files`：涉改文件列表

若 L1 脚本失败或产物缺失，Agent 降级为从 patch 文件直接提取。

### L2 语义层（AI Agent，只读不写，按职责分工）

主 Agent 在 L1 完成后，**必须在一条消息中同时启动 2 个 Agent**（使用多个 Task tool 调用），而不是逐个串行启动。

```
正确示例（并行）：一条消息中同时发送 2 个 Task tool
  Task(agent_analysis, 全部 patch + analysis_cache.json + $KERNEL_REPO_PATH, ...)
  Task(agent_revert, duplicate_analysis.json + 场景(upgrade/backport) + analysis_cache.json + $KERNEL_REPO_PATH, ...)

错误示例（串行 — 禁止）：
  Task(agent_analysis, ...) → 等 analysis 完成 → Task(agent_revert, ...)
```

**不再按 patch 数量平分 Agent**，改为 2 个专职 Agent 各司其职。

---

### agent_analysis 执行流程

**职责**：全量语义分析——功能理解、依赖标注、风险评估、build_checkpoint 预判。

**输入**：
- `/tmp/patches/000N-*.patch`（全部）
- `analysis_cache.json`（L1 已填充符号骨架）
- `$KERNEL_REPO_PATH`、`$UPSTREAM_REPO_PATH`（可选）

**步骤 1: 理解 commit message（优先）**
先深入理解每个 patch 的 commit message：功能是什么、关联哪个子模块、是否标注了前置依赖 commit。

**步骤 2: 补充语义字段并写回 analysis_cache.json**

读取 L1 的 `analysis_cache.json` 骨架，在 AI 理解后**用 Write tool 写回**补全的文件：

在 L1 骨架基础上，补充以下 AI 语义字段（字段 schema 见 `references/output-templates.md`）：

| 字段 | 说明 | 类型 |
|------|------|------|
| `功能分类` | 结合 commit message 修正 L1 初步分类 | string |
| `feature_signature.keywords` | AI 语义关键词（非机械截取） | list |
| `feature_signature.scope_dirs` | 限定搜索范围 | list |
| `depends_on` | patch 内依赖（P_j 依赖 P_i 的 task_id） | list |
| `risk_level` | 风险等级：高/中/低 | string |
| `review_required` | Review 紧急性：高/中/低 | string |
| `blame_hits` | git blame 找到的 bugfix commit 列表 | list |
| `conflicts_predicted` | 预判冲突点（文件:行号:原因） | list |
| `special_notes` | 合入注意事项 | string |
| `action` | apply/skip | string |
| `skip_reason` | 若 skip，必须填写原因 | string |

**输出方式**：用 Write tool 写入 `$KERNEL_REPO_PATH/patch_analysis/analysis_cache.json`，覆盖 L1 骨架。

> **注意**：不再只屏幕输出然后让主 Agent 手工解析。确保 JSON 结构完整，所有字段填入有效值。

**步骤 3: 向后搜索 Bugfix**（同原步骤 3，有 upstream 时执行）

**步骤 4: 向前搜索依赖**（同原步骤 4，有 upstream 时执行）

**步骤 5: 屏幕输出**

按 `references/output-templates.md` 中 "Phase 1 分析 Agent 屏幕输出格式" 输出。

---

### agent_revert 执行流程

**职责**：审核 L1（Phase 0.5）的 revert 候选，根据场景做深度搜索或严格审核。

**输入**：
- `duplicate_analysis.json`（L1 初筛结果 + PR 聚合 + revert 建议）
- 场景（upgrade / backport，由 Phase 0.5 用户选择决定）
- `analysis_cache.json` 的 `feature_signature.keywords` + `scope_dirs`
- `$KERNEL_REPO_PATH`

#### upgrade 模式（AI 深度搜索）

1. 读取 `duplicate_analysis.json` 中的 revert 候选（`global_revert_order` + `version_upgrade.batches`）
2. 读取 `analysis_cache.json` 中的 `feature_signature.keywords` 和 `scope_dirs`
3. **扩展搜索**：用 keywords 在 scope_dirs 下 `git log --grep=<kw>` 搜全部相关 commit（仅当前分支，不限阈值、不限时间范围）
4. **符号追溯**：用 `git log -S=<sym>` 在 scope_dirs 找所有引入 key symbol 的 commit
5. **文件追溯**：用 `git log -- <file>` 找出修改过涉改文件的所有 commit
6. **深入理解**：读取每个候选 commit 的 message + diff，AI 判断：
   - 是否是旧版本的功能实现？ → confirm
   - 是否是无关注释/格式/doc/无关 bugfix？ → reject
   - merge commit 包含检查：若候选中有 merge commit，用 `git log <merge>~1..<merge>` 展开子 commit 列表
7. **去重合并**：将 L1 结果和步骤 3-5 的搜索结果合并去重，确保最终 revert 列表无重复、无遗漏
8. **输出**：用 Write tool 写入 `$KERNEL_REPO_PATH/patch_analysis/revert_audit.json`，格式见 `references/output-templates.md`。核心字段：
   - `revert_rulings`: 每个 PR/commit 的 `ruling`（confirm/reject）+ `note`（理由）+ `revert_cmd`（AI 决定的 revert 命令）
   - `patch_pre_revert`: 每个 patch task_id → 需 revert 的 commit hash 列表
   - `ruling_summary`: 一句话总结（供主 Agent 展示）

> 核心原则：不靠阈值判定，AI 理解代码语义后做判断。L1 脚本只提供起点线索。

#### backport 模式（严格审核）

1. 读取 `duplicate_analysis.json`
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

**步骤 4: 生成 merge_tasks.json（确定性脚本）**

> ★ L2 Agent 已用 Write tool 写回 `analysis_cache.json`（补全语义字段）和 `revert_audit.json`。
> 主 Agent 不再手工解析屏幕文本，改用确定性脚本组装。

```bash
python3 "$SCRIPTS_DIR/generate_merge_tasks.py" \
  --analysis-cache "$KERNEL_REPO_PATH/patch_analysis/analysis_cache.json" \
  --duplicate-analysis "$KERNEL_REPO_PATH/patch_analysis/duplicate_analysis.json" \
  --revert-audit "$KERNEL_REPO_PATH/patch_analysis/revert_audit.json" \
  --patch-dir /tmp/patches/ \
  --output "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json"
```

**脚本行为**：
1. 读取 L1+L2 的 `analysis_cache.json`（已含 agent_analysis 补全的语义字段）
2. 读取 Phase 0.5 的 `duplicate_analysis.json`（PR 聚合 + revert 建议）
3. 读取 `revert_audit.json`（agent_revert 的 AI 审核结果）
4. 提取 `/tmp/patches/` 中的 patch 元数据（subject, author, patch_file）
5. 组装完整的 `merge_tasks.json`（所有 20+ 字段按 schema 填充）
6. **schema 校验**：必填字段为空 → exit 1，输出缺失字段列表
7. 通过 → 写入 `merge_tasks.json`，输出统计摘要

**merge_tasks.json 每个 task 必须包含**（脚本自动填充，不再手工维护）：
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
- `risk_detail` — 风险具体说明
- `review_required` — `高` | `中` | `低`
- `review_reason` — review 原因
- `smoke_tests` — 建议验证项列表
- `status_in_target` — 目标仓库中该功能当前状态描述
- `blame_hits` — bugfix commit 列表
- `duplicate_info` — 目标仓库重复检测结果（step 5 产物）
- `conflicts_predicted` — 预判冲突点列表（文件:行号:原因）
- `special_notes` — 合入注意事项
- `build_checkpoint` — `true` / `false`（是否在此 patch 点做编译验证）
- `pr_mapping` — PR 映射聚合结果（由 `generate_merge_tasks.py` 从 `duplicate_analysis.json` 组装，schema 见 `references/output-templates.md#_generate_merge_tasks-py`）
- `execution_log` — `[]`（初始空数组，Phase 2 动态追加）

**步骤 5: 校验 + 屏幕预览 → 用户确认 → 保存预览**

1. **保存预览文本**：将四部分预览的完整输出写入 `$KERNEL_REPO_PATH/patch_analysis/phase1_preview.md`（中断恢复/审计追溯用）
2. **展示预览**：按 `references/output-templates.md` 中"Phase 1.5 全局预览模板"的 4 部分格式展示：依赖汇总 → Revert 清单 → 合入计划 → 确认交互
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
| 1c | 含 `pre_revert`（需要 revert 旧 commit） | `true` | Revert 操作修改代码，必须编译验证 |
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

### 启动
读取 `$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json`。

**执行顺序**：遍历 `merge_order`，按 `seq` 升序处理。

### 状态机

```
PRECHECK → PRE_REVERT → APPLY → VERIFY_INTENT → BUILD (checkpoint only) → COMMIT → REVIEW → RECORD → DONE
```

> **⚠️ 每个 step 开始和结束时必须调用 gatekeeper**（标 ✅ 的行），确保 `state_log` + `execution_log` 被填充。

- `build_checkpoint=true` → 完整执行 BUILD→verify→gatekeeper
- `build_checkpoint=false` → 跳过 BUILD，直接进入 COMMIT

> **⚠️ `build_checkpoint=false` 不是 "skip patch"！patch 本身仍然走完整流程：**
> `PRECHECK → PRE_REVERT → APPLY → VERIFY_INTENT → [BUILD SKIP] → COMMIT → REVIEW → RECORD`
> 代码仍然会合入并 commit，只是不在此点编译。后续 checkpoint 编译时会一并验证前面所有已合入的 patch。

### 通用模式

每个 step 遵循固定模板：

```bash
# 开始：标记 in_progress
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" --step <STEP> --result in_progress

# ... 执行实际操作 ...

# 完成：记录结果
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" --step <STEP> --result pass [extra_args...]
```

### PRECHECK
```bash
# ✅ 标记开始
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" --step PRECHECK --result in_progress
```
- 校验 patch 文件存在
- 校验 `depends_on` 中所有 task_id 状态为 `done`
  - 若前置被 skip → 检查 `skip_dependency_impact`：强→阻塞，中/弱→允许继续
- 工作区干净：`git diff --quiet && git diff --cached --quiet`
```bash
# ✅ 记录结果
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" --step PRECHECK --result pass
```

### PRE_REVERT

读取 `$KERNEL_REPO_PATH/patch_analysis/revert_plan.json` 执行：

```bash
# ✅ 标记开始
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" --step PRE_REVERT --result in_progress

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

```bash
# ✅ 记录结果
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" --step PRE_REVERT --result pass
```

### APPLY
```bash
# ✅ 标记开始
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" --step APPLY --result in_progress
```
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

```bash
# ✅ 记录 APPLY 结果
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" --step APPLY --result pass
```

### VERIFY_INTENT（APPLY 后强制校验）

**每次 APPLY 完成后必须执行，确保 patch 核心意图未被冲突解决破坏：**

```bash
# ✅ 标记开始
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" --step VERIFY_INTENT --result in_progress

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

> `.config` 已在 Phase 0 步骤 2-3 中一次性生成 + 预开启所有驱动 CONFIG=m。
> 此处直接编译，不再修改 `.config`。

**BUILD 开始前先标记 in_progress**：

```bash
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" \
  --step BUILD --result in_progress
```

**编译禁止表（必须遵守）**

| 禁止操作 | 原因 | 正确做法 |
|---------|------|---------|
| `make file.h` / `make file.o` | 局部编译，无法验证 patch 改动的编译影响 | 完整 `make ARCH=$ARCH -j$(nproc)` |
| `make Image` | 只编译内核镜像，不编译驱动模块，驱动相关改动无法验证 | 完整编译（默认目标） |
| `make modules` | 只编译模块，不编译内核镜像 | 完整编译（默认目标） |
| 跳过产物验证 | 编译成功不等于产物存在，必须验证 `arch/$ARCH/boot/Image` | 检查 Image 存在且非空 |

**步骤 1：确定编译目标**（确定，不依赖外部脚本）

```bash
# 基础编译目标（默认目标 = Image + modules + dtbs）
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

**步骤 2：执行编译**

> `.config` 已在 Phase 0 步骤 2-3 中一次性生成 + 预开启所有驱动 CONFIG=m。此处直接编译，不再修改 `.config`。

```bash
# 编译日志存入 patch_analysis/build_logs/（持久化，不被 /tmp 清理）
mkdir -p "$KERNEL_REPO_PATH/patch_analysis/build_logs"
BUILD_LOG="$KERNEL_REPO_PATH/patch_analysis/build_logs/<task_id>_build.log"
echo "编译命令: $BUILD_CMD"
$BUILD_CMD 2>&1 | tee "$BUILD_LOG"
```

**步骤 3：提取模块信息 + 门禁验证**

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
  --build-log "$BUILD_LOG" \
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
| 非 patch 的环境 CONFIG 缺失 | 临时启用 CONFIG → make → 编译后 `git restore <config_file>` |

**CONFIG 操作**：
```bash
./scripts/config --enable CONFIG_NEW_FEATURE
make olddefconfig
# .config 已在 Phase 0 生成，不再 restore
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
```bash
# ✅ 标记开始
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" --step REVIEW --result in_progress
```
调用 **code-review-expert skill**（skill 框架按名称自动加载），对 `HEAD~1..HEAD` 做 review。
若 reference 不存在则跳过，标注"未做自动 review"。
- Must Fix 意见 → 标记需 rebase amend
- Suggest 意见 → 记录不阻塞
```bash
# ✅ 记录结果
python3 "$SCRIPTS_DIR/gatekeeper.py" \
  --merges-file "$KERNEL_REPO_PATH/patch_analysis/merge_tasks.json" \
  --task-id "<task_id>" --step REVIEW --result pass
```

### RECORD

**合入过程数据暂存，不写 analyse.md。Phase 3 统一落盘。gatekeeper 已自动记录到 execution_log，此处仅补充 AI 经验数据。**

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
