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

**必须向用户展示**：
- 三个 agent 的检测摘要
- 判定的场景及推荐操作
- 确认后再执行修改操作

---

### 相位 2：前置操作（按场景执行）

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

通过检查后，按以下顺序尝试：

| 序号 | 策略 | 命令 | 成功时 | 失败时 |
|------|------|------|--------|--------|
| ① | `git am` | `git am <file.patch>` | 已自动 commit，继续下一个 | 检查冲突 → 进入② |
| ② | 解冲突 | 读取冲突文件 → 优先保留 patchset 内容 → `git add` + `git commit` | 继续下一个 | 进入③ |
| ③ | `git apply --3way` | `git apply --3way <file.patch>` | `git add .` + `git commit` | 进入④ |
| ④ | `git apply` | `git apply <file.patch>` | `git add .` + `git commit` | **报告用户** |

**冲突解决规则**: 优先保留 patchset 的修改内容。

**检测冲突文件**:
```bash
git diff --name-only --diff-filter=U
```

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

#### 3.7 生成差异报告

合入完成后在源码目录生成 `.patchset-diff.md`:

```markdown
# Patchset 合入报告
## 概要
- 场景: xxx
- 分支: xxx (已保留)
- 总数: X / 成功: X / 跳过: X / 失败: X
- Revert 的旧 commit: N 个（如有）
- 拉取的依赖 patch: N 个（如有）
## 各 patch 状态
| # | 标题 | 状态 | Commit |
|---|------|------|--------|
| 1 | xxx  | ✓    | abc123  |
## 失败详情 (如有)
...错误信息和代码差异...
```

## 交互模式

以下场景必须在对话中向用户展示信息并等待决策，**不自行决定**:

| 场景 | 展示内容 | 用户选项 |
|------|---------|---------|
| 工作区不干净 | 未提交的文件列表 | 继续 / 取消 |
| 场景判定结果 | 三个 agent 的检测摘要、推荐场景、将执行的操作 | 确认执行 / 调整参数 / 取消 |
| Revert 确认 | 要 revert 的 commit 列表（hash + 标题） | 确认 / 逐条选择 / 取消 |
| 依赖拉取确认 | 推荐的依赖 commit 列表 | 全部拉取 / 逐条选择 / 取消 |
| 路径映射 | 原始路径 → 目标路径的映射表 | 确认 / 手动修正 / 取消 |
| 全部策略失败 | patch 编号和标题、错误信息、冲突文件 | 手动处理后继续 / 停止 |
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
