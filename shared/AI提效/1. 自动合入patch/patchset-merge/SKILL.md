---
name: merge-patchset
description: Use when the user provides a patch folder path, runs /merge-patchset, or asks to merge/apply/合入/打补丁/回退 a patchset into a source tree. Handles multi-scenario intelligent merge: clean apply, revert-then-merge for conflicting old code, dependency auto-discovery from upstream repos, and partial-apply detection. Uses parallel sub-agents for pre-check analysis. Trigger on: 合入patch、合入补丁、打patch、apply patch、merge patch、回退旧代码再合入、/merge-patchset, and any mention of applying patches to a repo.
compatibility: claude-code, opencode
allowed-tools: Bash(git:*), Bash(make:*), Bash(bash:*), Bash(mkdir:*), Bash(grep:*), Bash(sed:*), Bash(cat:*), Bash(ls:*), Bash(find:*), Bash(rm:*), Bash(echo:*), Write(*), Agent
---

# Patchset Merge

从用户指定的 patch 文件夹逐个合入到源码仓库。内置多场景智能检测：自动判断是否需要先 revert 旧代码、是否需要从上游拉取依赖 patch、是否部分已合入。遇问题在对话中交互决策。

<!-- @preamble-start -->
## 前置技能加载（必须）

**开始任何合入工作前，验证并加载前置技能。不通过则不继续。**

按当前运行的平台执行对应步骤：

### Claude Code

验证 superpowers 插件和 karpathy-guidelines skill 已安装：

```bash
test -d ~/.claude/plugins/cache/claude-plugins-official/superpowers && echo "✓ superpowers OK" || echo "✗ superpowers MISSING"
test -f ~/.claude/skills/karpathy-guidelines/SKILL.md && echo "✓ karpathy-guidelines OK" || echo "✗ karpathy-guidelines MISSING"
```

有 "MISSING" 时：
- 缺少 superpowers: 运行 `claude plugins install superpowers@claude-plugins-official`，安装后重启
- 缺少 karpathy-guidelines: 运行 `./install.sh` 重新部署

验证通过后，用 Skill 工具加载：
1. `superpowers:using-superpowers` — 确保正确使用 skill 系统，遵循指令优先级
2. `karpathy-guidelines` — 减少过度设计、避免猜测、面向数据做决策

### OpenCode

karpathy-guidelines 由 OpenCode 自动发现并加载，无需手动验证。确保未被 opencode.json 的 `permission.skill` deny 即可：

```bash
grep -q '"skill.*karpathy.*deny"' opencode.json 2>/dev/null && echo "✗ karpathy-guidelines is denied, check opencode.json" || echo "✓ OK"
```

确认后直接继续，OpenCode 原生 skill 发现机制会自动加载 karpathy-guidelines。

**缺少前置技能或验证不通过则不能继续。**

<!-- @preamble-end -->

## 核心约束

1. **逐个合入**: 有多少个 patch 就处理多少个，不跳过（除非确认已合入）
2. **逐个 commit**: 每个 patch 单独 git commit；revert 操作也单独 commit
3. **遇错即停**: 当前操作失败时停止，报告用户，不跳到下一个
4. **保留分支**: 操作分支保留不删除，不在主干分支上操作
5. **只取改动行**: 只应用以 `+`/`-` 开头的实际修改行，上下文行仅用于定位
6. **逆序 revert**: 如需 revert 旧代码，从最新到最旧逆序执行
7. **中文输出**: 所有思考、解释、输出使用中文

## 参数

| 参数 | 必需 | 说明 | 默认值 |
|------|------|------|--------|
| `patch_dir` | 是 | 包含 .patch 文件的文件夹路径 | — |
| `--source` | 否 | 目标源码 git 仓库路径 | 当前目录 `.` |
| `--upstream` | 否 | 上游源码仓库路径，用于查找依赖 patch | — |
| `--branch` | 否 | 操作分支名 | 自动生成 |

## 工作流

整个流程分三个相位：前置检测 → 场景确认 → 执行 merge。

---

### 相位 0：前置检测（并行 agent）

同时启动 3 个检测 agent，各自独立工作，输出结构化结果。这是只读阶段，不做任何修改。

所有 agent 返回后，按「输出规范 → 相位 0 输出」模板汇总展示。

#### Agent A — 冲突预检

**任务**：扫描目标仓库，判断每个 patch 的冲突风险。

```bash
# 每个 patch 执行以下检查：
# 1. 提取 patch 涉及的函数名 / 结构体名 / 宏名
grep -oP '^(?:@@|diff|---|\+\+\+).*|^\+\s*(?:static\s+)?(?:void|int|struct|enum|unsigned|char|bool|long|size_t|ssize_t)\s+\w+\s*\(' <patch_file> | head -20

# 2. 在目标仓库搜索这些标识符是否已存在
grep -r -l "<提取的关键函数名>" <source_dir> --include="*.c" --include="*.h" 2>/dev/null

# 3. 检查 patch 中修改的文件在目标仓库是否存在
# 对每个 +++ b/<filepath> 提取路径，检查目标仓库中是否存在
test -f <source_dir>/<filepath> && echo "EXISTS" || echo "NOT_FOUND"
```

**输出**：每个 patch 的冲突风险评级（none / low / high）及依据：
- **high** — patch 修改的文件/函数在目标仓库已存在且内容不同
- **low** — 文件存在但函数/结构不重叠
- **none** — 文件不存在或函数名完全找不到

#### Agent B — 依赖检测（仅在指定 `--upstream` 时启动）

**任务**：在上游仓库中查找 patchset 可能依赖但未包含在文件夹中的 commit。

```bash
# 1. 提取 patch 中引用的 commit hash（Fixes: / Depends-on: / 正文中的 hash）
grep -oP '(?:Fixes|Depends-on|commit|cherry.picked.from|upstream.commit)[:\s]+\K[0-9a-f]{7,40}' <patch_files> | sort -u

# 2. 提取 patch Subject 中的关键词，在上游仓库搜索相关 commit
# 3. 对于高频关键词，在上游 git log 中搜索最近 5000 条 commit
git -C <upstream_dir> log --oneline -n 5000 --grep="<keyword>" -i
```

**输出**：推荐拉取的依赖 commit 列表（hash + subject），以及匹配理由。

#### Agent C — 已合入检测

**任务**：检测哪些 patch 的等效修改已经存在于目标仓库。

```bash
# 对每个 patch：
# 1. 用 Subject 关键词搜索目标仓库 commit log
git -C <source_dir> log --oneline -n 200 -i --grep="<subject_keywords>"

# 2. 用 git apply --check 试应用（干跑）
git -C <source_dir> apply --check <patch_file> 2>&1
# "already applied" 或 "patch does not apply"（所有 hunk 都已存在）= 已合入
```

**输出**：每个 patch 的状态（not_applied / already_applied / partially_applied）。

---

### 相位 1：场景判定

汇总三个 agent 的结果，判定场景并向用户展示：

| 场景 | 触发条件 | 前置操作 |
|------|---------|---------|
| **A — 干净合入** | 所有 patch 冲突风险 none/low，无依赖缺失，无已合入 | 无，直接 merge |
| **B — 先 Revert 再合入** | 存在 high 风险 patch，且目标仓库有对应旧版本的 commit（Agent C 找到相关 commit） | 逆序 revert 旧 commit → merge |
| **C — 补依赖再合入** | Agent B 找到依赖 commit，且 Agent C 确认目标仓库缺少这些依赖 | 从上游拉取依赖 patch → merge |
| **D — 部分跳过** | Agent C 检测到部分 patch 已合入 | 跳过已合入的，只 merge 剩余的 |
| **E — 路径适配** | Agent A 发现 patch 文件路径在目标仓库不存在（NOT_FOUND） | 找到实际路径映射 → 调整 patch → merge |

场景可以组合（如 B + D：先 revert 旧代码，跳过已合入的，再 merge 剩余的）。

按「输出规范 → 相位 1 输出」模板展示场景判定和执行计划。**必须等用户确认后才进入 Phase 2。**

---

### 相位 2：前置操作（按场景执行）

每个前置操作按「输出规范 → 相位 2 输出」模板展示进度。

#### 场景 B — Revert 旧代码

对 Agent A 标记为 high 风险的 patch，在目标仓库中找到对应的旧 commit：

```bash
# 用 patch 的关键函数名/文件名搜索相关 commit
git -C <source_dir> log --oneline -n 500 -i --grep="<关键词>" -- <相关文件路径>
```

将找到的 commit 列表展示给用户确认，确认后**逆序**逐个 revert：

| 序号 | 策略 | 命令 |
|------|------|------|
| ① | `git revert` | `git revert --no-edit <hash>` |
| ② | 解冲突 | 读取冲突文件 → 优先保留 revert 方向 → `git add` + `git commit` |
| ③ | 手动 | `git revert --abort` → `git diff <hash>^..<hash> \| git apply -R` → `git add .` + `git commit` |

每个 revert 后必须编译验证。

#### 场景 C — 拉取依赖 patch

根据 Agent B 的推荐列表，对每个依赖 commit：

```bash
# 从上库生成 patch 文件
git -C <upstream_dir> format-patch -1 <dependency_hash> -o /tmp/deps-patches/
```

将生成的 .patch 文件追加到合入列表的最前面，确保依赖先合入。

#### 场景 E — 路径适配

对路径不匹配的 patch 文件，在目标仓库中搜索实际路径：

```bash
# 用文件名在目标仓库中搜索
find <source_dir> -name "$(basename <original_path>)" -type f 2>/dev/null
```

找到后修改 patch 中的路径，用 `sed` 替换 `--- a/<old_path>` 和 `+++ b/<old_path>` 为实际路径。向用户展示映射关系，确认后应用。

---

### 相位 3：核心 Merge 流程

对所有待合入的 patch（经过前置处理后），按文件名排序逐个合入。

#### 3.1 准备

```bash
# 确认是 git 仓库
git -C <source_dir> rev-parse --git-dir

# 确认工作区干净
git -C <source_dir> status --porcelain
```
工作区不干净时警告用户，展示未提交文件列表，询问是否继续。

#### 3.2 验证 patch 文件夹

```bash
test -d <patch_dir> && echo "✓ 文件夹存在" || echo "✗ 文件夹不存在"
ls <patch_dir>/*.patch 2>/dev/null | wc -l
```
没有找到 .patch 文件 → 报告用户并停止。

#### 3.3 解析 patch 文件

```bash
ls <patch_dir>/*.patch | sort
```

读取每个 .patch 文件内容，用 `^Subject:\s*(.+)$` 提取标题，用 `^\+\+\+ b/(.+)$` 提取涉及文件。检查是否有空文件或格式无效的 patch。

解析完成后按「输出规范 → 相位 3 输出 → 3.3 解析完成后输出 patch 清单」展示。

#### 3.4 创建分支

```bash
# 从首个 patch 的 Subject 生成分支名
# 1. 去掉 [PATCH] [RFC] [vN] 等前缀
# 2. 空格/特殊字符换连字符
# 3. 移除所有非字母数字连字符下划线的字符
# 4. 取前 50 字符
# 5. 确保不以数字开头，以数字开头则加 "patch-" 前缀
# 格式: patch-<关键词>
# 分支已存在则追加 -$(date +%m%d%H%M)

git checkout -b <branch_name>
```

#### 3.5 逐个合入

对每个 patch：

**前置检查**：用 `git apply --check <file.patch>` 检测是否已合入。

通过检查后，按以下策略链条逐个尝试。策略按"保住 git 历史 → 降级到纯文件修改"的顺序排列：

| 序号 | 策略 | 命令 | 适用场景 | 成功时 | 失败时 |
|------|------|------|---------|--------|--------|
| ① | `git am` | `git am <file.patch>` | 默认首选，完整保留 commit 元信息 | 自动 commit，继续 | 进入② |
| ② | `git am --3way` | `git am --3way <file.patch>` | 上下文轻微偏移；**非冲突文件的修改会被保留**，只标记冲突文件 | 自动 commit，继续 | 有冲突 → 进入③；完全失败 → 进入④ |
| ③ | `git am --ignore-whitespace` | `git am --ignore-whitespace <file.patch>` | Tab/Space 不一致、行尾空格等空白字符差异导致的假冲突 | 自动 commit，继续 | 进入④ |
| ④ | `patch --fuzz` | `patch -p1 --fuzz=3 < <file.patch>` | 上下文行号因无关变更偏移，但实际修改内容仍适用 | `git add .` + `git commit` | 进入⑤ |
| ⑤ | `git apply --3way` | `git apply --3way <file.patch>` | 需要三路合并的更复杂场景 | `git add .` + `git commit` | 进入⑥ |
| ⑥ | `git apply --reject` | `git apply --reject <file.patch>` | 部分 hunk 已合入、部分需合入 | 检查 `.rej` 文件内容 → 手动处理有效 .rej → `git add .` + `git commit` | 进入⑦ |
| ⑦ | 手解冲突 | 见下方「手解冲突分类指南」 | 上述自动化策略全部失败 | 按冲突类型选择子策略 | 进入⑧ |
| ⑧ | `git apply` | `git apply <file.patch>` | 最后手段，放弃 commit 元信息 | `git add .` + `git commit` | **报告用户** |

**冲突解决规则**: 优先保留 patchset 的修改内容。目标仓库中与 patchset 无关的已有代码不能擅自删除。

**手解冲突分类指南**（策略⑦的具体化）：

| 冲突类型 | 诊断方法 | 解决方式 |
|---------|---------|---------|
| 上下文偏移 | patch hunk 行号与目标文件对不上，但上下文内容能部分匹配 | 手动调整 `@@` 行号，或回到策略④用 `patch --fuzz` |
| 空白差异 | 内容相同但缩进/空白风格不同 | 回到策略③ `git am --ignore-whitespace` |
| 函数签名变更 | 目标仓库中函数多了参数、返回值类型变了 | 提取目标仓库签名 → 适配 patch 中的调用 → `git add` + `git commit` |
| 部分已合入 | 部分 hunk 的目标代码已存在 | 回到策略⑥ `git apply --reject`，忽略已合入的 .rej |
| 文件被移动 | 文件在目标仓库的路径不同 | `find <source> -name "basename"` 找到实际路径 → `sed` 替换 patch 中路径 |
| 头文件缺失 | patch 引用的 `#include` 在目标仓库不存在 | `find <source> -name "*.h" \| xargs grep -l "<符号>"` 找等价头文件，或从 `--upstream` 引入 |
| 结构性冲突 | 目标仓库对该文件做了大规模重构 | 分析 patch 语义意图 → 展示分析结果给用户 → 用户决定方向 |

每个 patch 合入后：
1. 按「输出规范 → 相位 3 输出 → 每个 patch 合入后输出进度」模板展示结果（含所使用的策略序号）
2. 对成功合入的 patch，立即生成 per-patch 分析文档到 `<source_dir>/.patchset-analysis/`（模板见「输出规范 → per-patch 分析文档」），避免事后遗忘细节

**检测冲突文件**:
```bash
git diff --name-only --diff-filter=U
```

**策略② `git am --3way` 说明**：此策略的关键优势是**保留非冲突文件的修改**。即使部分文件有冲突，其他文件的变更已经被 stage，只需处理冲突文件即可。冲突解决后用 `git am --continue` 而非重新 commit。

**策略⑥ `git apply --reject` 说明**：生成 `.rej` 文件包含无法自动合入的 hunk。对每个 `.rej`：
- 如果内容是 patch 新增但目标仓库已有 → 删除 .rej
- 如果内容是真正需要合入的 → 手动将该 hunk 写入源文件
- 处理完后 `git add .` + `git commit`

#### 3.6 每个 patch 合入后编译验证

```bash
if test -f build.sh; then
    bash build.sh
elif test -f Makefile; then
    make -j$(nproc)
elif test -f CMakeLists.txt; then
    mkdir -p build && cd build && cmake .. && make -j$(nproc)
else
    echo "未找到 build.sh / Makefile / CMakeLists.txt，跳过编译验证"
fi
```
编译失败 → 向用户展示错误（前 20 行），询问继续或停止。

#### 3.7 生成报告、分析和总结

合入完成后：
1. 对**每个成功合入的 patch**，按「输出规范 → per-patch 分析文档」模板生成分析文档，写入 `<source_dir>/.patchset-analysis/<序号>-<slug>-analysis.md`
2. 按「输出规范 → 文件输出」模板写入 `<source_dir>/.patchset-diff.md`
3. 按「输出规范 → 风险评级总结」模板生成并写入 `<source_dir>/.patchset-analysis/summary.md`
4. 按「输出规范 → 相位 3 输出 → 全部完成后对话输出总结」模板在对话中展示总结

## 交互模式

以下场景必须在对话中向用户展示信息并等待决策，**不自行决定**:

| 场景 | 展示内容 | 用户选项 |
|------|---------|---------|
| 工作区不干净 | 未提交的文件列表 | 继续 / 取消 |
| 场景判定结果 | 三个 agent 的检测摘要、推荐场景、将执行的操作 | 确认执行 / 调整参数 / 取消 |
| Revert 确认 | 要 revert 的 commit 列表（hash + 标题） | 确认 / 逐条选择 / 取消 |
| 依赖拉取确认 | 推荐的依赖 commit 列表 | 全部拉取 / 逐条选择 / 取消 |
| 路径映射 | 原始路径 → 目标路径的映射表 | 确认 / 手动修正 / 取消 |
| 全部策略失败 | patch 编号和标题、已尝试策略、错误信息、冲突文件 | 手动处理后继续 / 停止 |
| 结构性冲突 | 目标仓库大规模重构导致无法自动合入，AI 语义分析结果 | 指定适配方向 / 跳过 / 停止 |
| 编译失败 | patch 编号、编译错误（前 20 行） | 跳过继续 / 停止 |
| patch 已合入或无效 | patch 文件名、检测依据 | 跳过 / 停止 |

## 反模式

- 跳过失败的 patch 直接合入下一个
- 在 master/main 等主干分支上操作
- 删除操作分支
- 多个 patch 合并为一个 commit
- revert 时不按逆序执行
- 写 Python 脚本来替代直接的 bash 调用
- 遇到问题不询问用户自行决定
- 把 patch diff 中的上下文行（不带 `+`/`-` 前缀的行）写入源码文件
- 跳过前置检测直接开始 merge
- 不向用户展示场景判定结果就执行修改操作

## 输出规范

所有用户可见的输出必须遵循以下模板。分三种输出类型：

- **对话输出**（Markdown 块）→ 直接展示给用户，简洁可扫读
- **分析文档**（写入 `.patchset-analysis/` 目录）→ 每个 patch 的逐行 diff 对比和冲突解决过程
- **汇总报告**（写入 `.patchset-diff.md` 和 `.patchset-analysis/summary.md`）→ 全局视图和风险评级

---

### 相位 0 输出：前置检测结果

Agent 全部返回后，用此模板汇总。在 Phase 0 结束时输出。

```markdown
## 🔍 前置检测结果

### 冲突预检
| # | Patch 标题 | 风险 | 依据 |
|---|-----------|------|------|
| 1 | <title>   | HIGH | <具体原因，如：函数 foo_init 在目标仓库已存在> |
| 2 | <title>   | LOW  | <原因> |
| 3 | <title>   | NONE | <原因> |

### 依赖检测
> 仅在指定 --upstream 时展示

| # | Upstream Commit | 标题 | 匹配理由 |
|---|-----------------|------|---------|
| 1 | abc123          | <title> | patch #N 引用此 commit |
| 2 | def456          | <title> | 关键函数 bar_setup 的引入 commit |

未找到依赖时显示: `未发现缺失的依赖 commit`

### 已合入检测
| # | Patch 标题 | 状态 | 依据 |
|---|-----------|------|------|
| 1 | <title>   | NOT_APPLIED | — |
| 2 | <title>   | ALREADY_APPLIED | commit xyz789 标题匹配 |
| 3 | <title>   | PARTIALLY_APPLIED | 2/4 hunk 已存在 |

全部 NOT_APPLIED 时显示: `所有 patch 均未合入`
```

---

### 相位 1 输出：场景判定 + 执行计划

在 Phase 1 结束时输出，**必须等用户确认后才进入 Phase 2**。

```markdown
## 📋 场景判定

- **场景**: <A / B / C / D / E，可组合如 B + D>
- **判定依据**:
  - <场景 X>: <触发条件，如 patch #1 冲突风险 HIGH>
  - <场景 Y>: <触发条件，如 patch #2 ALREADY_APPLIED>

### 执行计划
| 步骤 | 操作 | 详情 |
|------|------|------|
| 1 | 创建分支 | patch-<keyword> |
| 2 | Revert 旧 commit | 逆序 revert N 个 commit（场景 B） |
| 3 | 跳过已合入 | 跳过 patch #M（场景 D） |
| 4 | Merge | 合入剩余 N 个 patch |
| 5 | 编译验证 | 每个 patch 后编译 |
| 6 | 生成报告 | .patchset-diff.md |

确认以上计划后开始执行。
```

---

### 相位 2 输出：前置操作进度

每个前置操作输出一行进度 + 结果。

**场景 B — Revert**：
```
## ⏪ Revert 旧代码 (1/3)
- Commit: abc123 "fix: hdbss init"
- 策略: git revert --no-edit ✓
- Revert Commit: def456
```

**场景 C — 拉取依赖**：
```
## 📥 拉取依赖 patch (1/2)
- Upstream Commit: abc123 "add: bar_setup helper"
- 已生成: /tmp/deps-patches/0001-add-bar_setup-helper.patch
```

**场景 E — 路径适配**：
```
## 🔀 路径适配
| 原始路径 | 目标路径 |
|---------|---------|
| drivers/net/hdbss.c | drivers/net/ethernet/vendor/hdbss.c |
| include/linux/hdbss.h | include/linux/hdbss.h (不变) |
```

---

### 相位 3 输出：Merge 进度

#### 3.3 解析完成后输出 patch 清单

```markdown
## 📝 待合入 patch 清单
| # | 文件 | 标题 | 涉及文件数 |
|---|------|------|-----------|
| 1 | 0001-xxx.patch | <title> | 3 |
| 2 | 0002-yyy.patch | <title> | 1 |
| 3 | 0003-zzz.patch | <title> | 2 |

共 N 个 patch，开始逐个合入。
```

#### 3.5 每个 patch 合入后输出进度

```markdown
## 📝 Patch (N/M)
- **标题**: <subject>
- **策略**: git am ✓（或：解冲突 ✓ / git apply --3way ✓ / git apply ✓）
- **Commit**: <hash>
- **编译**: ✓ 通过（或：✗ 失败，见下方错误）
```

失败时追加错误详情：
```
- **错误**: 
  ```
  <编译错误前 5 行>
  ```
- **状态**: ⚠ 等待用户决策
```

#### 3.7 全部完成后对话输出总结

```markdown
## ✅ 合入完成

| 项目 | 值 |
|------|-----|
| 分支 | <branch> (已保留) |
| 场景 | <A~E 组合> |
| 合入 | N 成功 / M 跳过 / K 失败 |
| Revert | N 个旧 commit（如有） |
| 依赖 | N 个拉取的依赖（如有） |
| 报告 | <source_dir>/.patchset-diff.md |

### 失败详情（如有）
| # | Patch | 失败原因 |
|---|-------|---------|
| 3 | xxx   | 全部策略失败，冲突文件: a.c, b.h |
```

---

### 文件输出：`patchset-diff.md`

写入源码目录，保留完整记录。用 Write 工具生成。

```markdown
# Patchset 合入报告

## 概要
- **日期**: <YYYY-MM-DD HH:MM>
- **场景**: <A~E 组合>
- **分支**: <branch> (已保留)
- **目标仓库**: <source_dir>
- **上游仓库**: <upstream_dir>（如有）
- **总数**: N / **成功**: N / **跳过**: N / **失败**: N
- **Revert 的旧 commit**: N 个
- **拉取的依赖 patch**: N 个

## 前置检测摘要
### 冲突预检
| # | Patch | 风险 | 依据 |
|---|-------|------|------|
...

### 依赖检测
...

### 已合入检测
...

## 前置操作
### Revert（如有）
| # | 原始 Commit | 标题 | Revert Commit |
|---|-------------|------|---------------|
| 1 | abc123      | xxx  | def456        |

### 拉取的依赖（如有）
| # | Upstream Commit | 标题 | 本地 Patch 文件 |
|---|-----------------|------|-----------------|
| 1 | abc123          | xxx  | /tmp/deps-patches/0001-xxx.patch |

## 各 patch 合入状态
| # | Patch 文件 | 标题 | 状态 | 策略 | Commit |
|---|-----------|------|------|------|--------|
| 1 | 0001-xxx.patch | <title> | ✓ 成功 | git am | abc123 |
| 2 | 0002-yyy.patch | <title> | ⊘ 跳过 | — | — |
| 3 | 0003-zzz.patch | <title> | ✗ 失败 | — | — |

## 失败详情
### patch #3: <title>
- **失败原因**: <原因>
- **尝试的策略**: git am → git apply --3way → git apply → git commit
- **冲突文件**:
  - drivers/net/example.c
- **错误信息**:
  ```
  <具体错误>
  ```
```

---

### Per-patch 分析文档

每个 patch 合入成功后立即生成，写入 `<source_dir>/.patchset-analysis/<序号>-<slug>-analysis.md`。

首先生成 `mkdir -p <source_dir>/.patchset-analysis`。

**核心要求**：必须包含源 patch 与实际合入 commit 之间的 diff 对比。用 `git diff` 生成：

```bash
# 获取原始 patch 和实际 commit 之间的差异
diff <(git -C <source_dir> show <commit_hash> --format=raw) <(cat <original_patch_file>) || true
```

模板：

```markdown
# Patch 分析: <patch subject>

## 基本信息
| 项 | 值 |
|----|-----|
| 原始 patch 文件 | <filename> |
| 合入 commit | <hash> |
| 合入策略 | ① git am / ② git am --3way / ③ git am --ignore-whitespace / ④ patch --fuzz / ⑤ git apply --3way / ⑥ git apply --reject / ⑦ 手解冲突 / ⑧ git apply |
| 涉及文件 | N 个 |
| 编译结果 | ✓ 通过 / ✗ 失败 |
| 分析时间 | <YYYY-MM-DD HH:MM> |

## 源 patch vs 实际合入 diff

> 以下 diff 展示原始 patch（a/）与最终合入到仓库的代码（b/）之间的差异。
> 标记 `!` 的行代表合入时被修改的内容。

### 文件: <filepath>

```diff
--- a/<filepath> (原始 patch 意图)
+++ b/<filepath> (实际合入结果)
@@ -<line>,<n> +<line>,<n> @@
  <unchanged context>
- <原始 patch 中要删除的行>
+ <原始 patch 中要添加的行>
! <合入时被修改的行 — 与原始 patch 不同>
```

> 对每个涉及文件重复 ### 块。

## 逐行差异明细

对每一处合入时产生的差异，列出原因：

| 行号 | 原始 patch 内容 | 实际合入内容 | 差异原因 |
|------|----------------|-------------|---------|
| 42   | `foo(x)`       | `foo(x, y)` | 目标仓库中 `foo` 签名已变更，合入时适配了新签名 |
| 87   | `return 0;`    | `return ret;` | 冲突解决：目标仓库要求返回错误码 |
| —    | （不存在）       | `#include "compat.h"` | 冲突解决时新增的依赖头文件 |

> 无差异则写 "合入内容与原始 patch 完全一致，无逐行差异。"

## 冲突解决过程

> 如果使用了 git am 直接成功且无差异，写 "未发生冲突，git am 直接合入成功。"

- **冲突文件**: <列出有冲突的文件，无则写"无">
- **冲突类型**: <函数签名不匹配 / 上下文行偏移 / 变量名冲突 / 新增代码冲突 / 无>
- **解决策略**: <描述具体如何解决的>

### 思考过程

```
<记录冲突解决时的分析思路：
- 为什么选择这种解决方式？
- 放弃了哪些替代方案？为什么？
- 目标仓库中哪些已有代码影响了决策？
- 是否有需要注意的隐患？>
```

## 风险评级

| 项 | 评估 |
|----|------|
| **风险等级** | 🟢 LOW / 🟡 MEDIUM / 🟠 HIGH / 🔴 CRITICAL |
| **差异程度** | N 行不同 / 总共 M 行（N/M = X%） |
| **合入策略** | git am / 冲突解决 / git apply --3way / git apply |
| **涉及子系统** | <kernel core / 驱动 / 文件系统 / 网络 / 架构相关 / ...> |
| **判定依据** | <根据风险评级标准逐条说明> |
```

---

### 风险评级总结

全部 patch 合入后生成，写入 `<source_dir>/.patchset-analysis/summary.md`。

```markdown
# Patchset 合入风险评级总结

## 整体评估

| 项 | 值 |
|----|-----|
| 整体风险等级 | 🟢 LOW / 🟡 MEDIUM / 🟠 HIGH / 🔴 CRITICAL |
| 总 patch 数 | N |
| CRITICAL | N |
| HIGH | N |
| MEDIUM | N |
| LOW | N |

## 风险热力图

| # | Patch | 风险 | 差异行数 | 合入策略 | 涉及子系统 | 需关注点 |
|---|-------|------|---------|---------|-----------|---------|
| 1 | <title> | 🟢 LOW | 0/45 | ① git am | net/core | — |
| 2 | <title> | 🟠 HIGH | 12/67 | ⑦ 手解冲突 | drivers/hdbss | 函数签名变更 |
| 3 | <title> | 🟡 MEDIUM | 3/30 | ⑤ git apply --3way | fs/ext4 | 上下文偏移 |

## 需重点关注的 patch

> 仅列出 HIGH 和 CRITICAL 级别的 patch

### patch #2: <title> (🟠 HIGH)
- **差异原因**: 目标仓库中 `hdbss_init()` 多了一个 `flags` 参数
- **潜在风险**: 如果未来上游 patch 修改同一函数，需要再次适配
- **建议**: 合入后人工 review `drivers/hdbss/core.c` 的合入结果

## 各 patch 分析文档

| # | Patch | 分析文档 |
|---|-------|---------|
| 1 | <title> | [analysis](./0001-<slug>-analysis.md) |
| 2 | <title> | [analysis](./0002-<slug>-analysis.md) |
```

---

### 风险评级标准

对每个 patch 按以下标准评级：

#### 🔴 CRITICAL — 必须人工 review
触发任一条件：
- 合入后编译失败
- 冲突解决时**删除了目标仓库已有的代码**（非 patch 意图删除的行）
- 修改了核心数据结构定义（`struct`、`union`、`enum` 的成员变更）
- 修改了导出函数签名（`EXPORT_SYMBOL` 的函数参数或返回值变更）
- 涉及安全相关代码（权限检查、内存屏障、加密）

#### 🟠 HIGH — 建议人工 review
触发任一条件：
- 使用了冲突解决（策略②），实际合入与源 patch 差异 ≥ 10 行
- 差异行数超过 patch 总行数的 20%
- 涉及 Kconfig / Makefile / CMakeLists.txt 变更
- 涉及多个子系统的交叉修改
- 涉及设备树（.dts / .dtsi）变更

#### 🟡 MEDIUM — 注意但不阻塞
触发任一条件：
- 使用了 `git apply --3way`（策略③）而非 `git am`
- 差异行数在 5%~20% 之间
- 涉及设备驱动代码（`drivers/`）
- 上下文行偏移超过 10 行

#### 🟢 LOW — 可直接合入
满足全部条件：
- `git am` 直接成功（策略①）
- 实际合入内容与源 patch 完全一致（0 行差异）
- 编译通过
- 不涉及核心数据结构或安全代码

---

### 输出规则

1. **每个相位的输出必须在进入下一相位前完成**，不得省略
2. **相位 1 和交互模式场景**输出后必须等待用户确认，不得自动继续
3. **进度输出使用 N/M 格式**，让用户清楚知道当前进度
4. **所有表格必须用 Markdown 表格**，不得用纯文本罗列
5. **三种输出职责分离**：
   - 对话输出：给用户即时看，简洁可扫读
   - 分析文档（`.patchset-analysis/`）：每个 patch 的逐行 diff 对比和思考过程，供事后审计
   - 汇总报告（`.patchset-diff.md` + `summary.md`）：全局视图和风险评级
6. **状态图标统一**：✓ 成功 / ✗ 失败 / ⊘ 跳过 / ⚠ 等待决策 / — 不适用
7. **风险图标统一**：🟢 LOW / 🟡 MEDIUM / 🟠 HIGH / 🔴 CRITICAL
8. **每个 patch 合入后立即生成分析文档**，不得等到全部合入后再补（防止遗忘冲突解决细节）
9. **源 patch vs 实际合入的 diff 必须逐文件展示**，不得省略或概括
10. **思考过程必须用自然语言记录**分析时的判断依据，不得留空或写"无"
