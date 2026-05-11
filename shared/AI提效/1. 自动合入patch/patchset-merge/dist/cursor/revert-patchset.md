# revert-patchset (cursor 自包含版本)

> 自动生成于 2026-05-11 10:13，内联 karpathy-guidelines 行为准则
> 适用于没有 skill 系统的 AI 编码平台

---


# Karpathy Guidelines

Behavioral guidelines to reduce common LLM coding mistakes, derived from [Andrej Karpathy's observations](https://x.com/karpathy/status/2015883857489522876) on LLM coding pitfalls.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

---
name: revert-patchset
description: Use when the user wants to revert commits from a git repository, runs /revert-patchset, or asks to revert/回退/撤销 a commit range, topic keyword, or patchset. Handles identifying commits, reverting one-by-one in reverse order with conflict resolution, compile verification, and diff reporting.
compatibility: claude-code, opencode
allowed-tools: Bash(git:*), Bash(make:*), Bash(bash:*), Bash(mkdir:*), Bash(grep:*), Bash(sed:*), Bash(cat:*), Bash(ls:*), Bash(find:*), Bash(rm:*), Bash(echo:*), Write(*)
---

# Revert Patchset

在源码仓库中按逆序逐个 revert commit，遇问题在对话中交互决策。


## 核心约束

1. **逐个 revert**: 有多少个 commit 就 revert 多少个，不跳过
2. **逐个 commit**: 每个 revert 单独 git commit
3. **逆序执行**: 从最新到最旧，保持依赖关系正确
4. **遇错即停**: 当前 revert 失败时停止，报告用户，不跳到下一个
5. **只取改动行**: revert 时只应用反向修改的实际代码行。diff 中不带 `+`/`-` 前缀的上下文行仅用于定位，**禁止写入源码**
6. **保留分支**: revert 分支保留不删除，不在主干分支上操作
7. **中文输出**: 所有思考、解释、输出使用中文

## 参数

| 参数 | 必需 | 说明 | 示例 |
|------|------|------|------|
| `commit` | 是 | 单个 commit hash、范围 (A..B)、或主题关键词 | `abc123`, `abc..def`, `hdbss` |
| `--source` | 否 | 源码 git 仓库路径 | `--source /root/openeuler/kernel` |
| `--branch` | 否 | revert 使用的分支名（默认自动生成） | `--branch revert-hdbss` |

## 工作流

### 1. 准备

```bash
# 确认是 git 仓库
git -C <source_dir> rev-parse --git-dir

# 确认工作区干净
git -C <source_dir> status --porcelain
```
工作区不干净时警告用户，询问是否继续。

### 2. 定位要 revert 的 commit

根据用户输入的类型自动判断：

**单个 commit hash**:
```bash
git log --oneline -1 <hash>
```

**范围 A..B**:
```bash
git log --oneline <A>..<B>
```

**主题关键词**（在最近 100 万条 commit 中搜索）:
```bash
git log --oneline -n 100000 -i --grep="<keyword>"
```

将找到的 commit 列表展示给用户确认，用户确认后再继续。

### 3. 创建分支

```bash
# 自动生成分支名: revert-<关键词或hash前缀>
# 分支已存在则追加时间戳

git checkout -b <branch_name>
```

### 4. 逐个 revert

对确认的 commit 列表，**从最新到最旧**逆序执行：

| 序号 | 策略 | 命令 | 成功时 | 失败时 |
|------|------|------|--------|--------|
| ① | `git revert` | `git revert --no-edit <hash>` | 已自动 commit，进入⑥ | 有冲突 → 进入②，无冲突 → 进入③ |
| ② | 解冲突 | 读取冲突文件 → 分析两边差异 → 优先保留 revert 后的内容 → `git add` + `git commit` | 继续下一个 | 进入③ |
| ③ | `git revert --abort` + 手动 | `git revert --abort` → 手动 `git diff <hash>^..<hash> \| git apply -R` | `git add .` + `git commit` | **报告用户** |

**冲突解决规则**: 优先保留 revert 后的内容（即去掉被 revert commit 引入的修改）。**关键：只取 patch 中以 `+`/`-` 开头的行，不以 `+`/`-` 开头的上下文行（diff 中不带前缀的行）不得写入源码文件。**

**检测冲突文件**:
```bash
git diff --name-only --diff-filter=U
```

### 5. 每个 revert 后

**编译验证**:
```bash
test -f build.sh && bash build.sh || make -j$(nproc)
```
编译失败 → 向用户展示错误（前 20 行），询问继续或停止。

### 6. 代码残留检查

所有 revert 完成后，在源码目录做一次全量关键词搜索，确认没有遗漏的引用：

```bash
grep -r -i "<keyword>" ./* --include="*.c" --include="*.h" --include="*.cpp" --include="*.hpp" | grep -v ".patchset-diff.md" | grep -v ".revert-diff.md"
```

将结果展示给用户：
- 没有残留 → 确认 clean
- 有残留 → 列出文件及匹配行，让用户判断是否需要进一步处理

### 7. 生成差异报告

revert 及残留检查完成后在源码目录生成 `.revert-diff.md`:

```markdown
# Revert 报告
## 概要
- 分支: xxx (已保留)
- 总数: X / 成功: X / 失败: X
## 各 revert 状态
| # | 原始 Commit | 标题 | 状态 | Revert Commit |
|---|-------------|------|------|---------------|
| 1 | abc123      | xxx  | ✓    | def456        |
## 失败详情 (如有)
...错误信息和代码差异...
```

### 8. 输出总结

向用户展示：分支名、成功/失败数量、差异报告路径、失败详情（如有）。

## 交互模式

以下场景必须在对话中向用户展示信息并等待决策，**不自行决定**:

| 场景 | 展示内容 | 用户选项 |
|------|---------|---------|
| 定位 commit | 搜索到的 commit 列表（hash + 标题） | 确认 / 取消 / 手动指定 |
| 工作区不干净 | 未提交的文件列表 | 继续 / 取消 |
| 全部策略失败 | commit hash 和标题、已尝试的策略、错误信息、冲突文件 | 手动处理后继续 / 停止 |
| 编译失败 | commit hash、编译错误（前 20 行） | 跳过继续 / 停止 |

## 反模式

- 跳过失败的 revert 直接执行下一个
- 在 master/main 等主干分支上操作
- 删除 revert 分支
- 多个 revert 合并为一个 commit
- 不按逆序 revert（从旧到新可能导致依赖错乱）
- 不确认 commit 列表就直接执行
- 遇到问题不询问用户自行决定
- 把 patch diff 中的上下文行（不带 `+`/`-` 前缀的行）写入源码文件
