# merge-patchset (gemini 自包含版本)

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
name: merge-patchset
description: Use when the user provides a lore.kernel.org patch URL, runs /merge-patchset, or asks to merge/apply/合入 a Linux kernel patchset into a source tree. Handles downloading patchsets with b4, applying patches one-by-one with escalating strategies, conflict resolution, compile verification, and diff reporting.
compatibility: claude-code, opencode
allowed-tools: Bash(b4:*), Bash(pip install b4), Bash(git:*), Bash(make:*), Bash(bash:*), Bash(mkdir:*), Bash(grep:*), Bash(sed:*), Bash(cat:*), Bash(ls:*), Bash(find:*), Bash(rm:*), Bash(echo:*), Write(*)
---

# Merge Patchset

从 lore.kernel.org 下载 patchset，逐个合入到源码仓库，遇问题在对话中交互决策。


## 核心约束

1. **逐个合入**: 有多少个 patch 就合入多少个，不跳过
2. **逐个 commit**: 每个 patch 单独 git commit
3. **遇错即停**: 当前 patch 失败时停止，报告用户，不跳到下一个
4. **保留分支**: 合入分支保留不删除，不在主干分支上操作
5. **只取改动行**: 合入 patch 时只应用以 `+`/`-` 开头的实际修改行。diff 中不带前缀的上下文行仅用于定位，**禁止写入源码**
6. **中文输出**: 所有思考、解释、输出使用中文

## 参数

| 参数 | 必需 | 说明 | 默认值 |
|------|------|------|--------|
| `patch_url` | 是 | lore.kernel.org 上 patch series 的 URL | — |
| `--source` | 否 | 源码 git 仓库路径 | 当前目录 `.` |
| `--branch` | 否 | 合入使用的分支名 | 从 patch 主题自动生成 |

## 工作流

### 1. 准备

```bash
# 检查 b4
b4 --version || pip install b4

# 确认是 git 仓库
git -C <source_dir> rev-parse --git-dir
```

### 2. 下载 patchset

```bash
mkdir -p /tmp/patchset-merge
cd /tmp/patchset-merge
b4 am <patch_url>
# 找到生成的 .mbox 文件: ls *.mbox
```

### 3. 拆分 patch

读取 mbox 文件内容，按 `^From \S+@\S+` 行拆分为单个 patch。
用 `^Subject:\s*(.+)$` 提取每个 patch 标题，用 `^\+\+\+ b/(.+)$` 提取涉及文件。

### 4. 创建分支

```bash
# 从首个 patch 的 Subject 生成分支名
# 去掉 [PATCH] [RFC] 等前缀 → 空格换连字符 → 取前40字符 → 去掉特殊字符
# 格式: patch-<关键词>
# 分支已存在则追加时间戳

git checkout -b <branch_name>
```

### 5. 逐个合入

对每个 patch，将内容写入临时 .patch 文件，按以下顺序尝试：

| 序号 | 策略 | 命令 | 成功时 | 失败时 |
|------|------|------|--------|--------|
| ① | `git am` | `git am <file.patch>` | 已自动 commit，继续下一个 | 检查冲突 → 进入②或③ |
| ② | 解冲突 | 读取冲突文件 → 分析两边差异 → 优先保留 patchset 内容 → `git add` + `git commit` | 继续下一个 | 进入③ |
| ③ | `git apply --3way` | `git apply --3way <file.patch>` | `git add .` + `git commit` | 进入④ |
| ④ | `git apply` | `git apply <file.patch>` | `git add .` + `git commit` | **报告用户** |

**冲突解决规则**: 优先保留 patchset 的修改内容。**关键：只取 patch 中以 `+`/`-` 开头的行，不以 `+`/`-` 开头的上下文行（diff 中不带前缀的行）不得写入源码文件。**

**检测冲突文件**:
```bash
git diff --name-only --diff-filter=U
```

### 6. 每个 patch 合入后

**编译验证**:
```bash
# 优先使用项目自带的 build.sh
test -f build.sh && bash build.sh || make -j$(nproc)
```
编译失败 → 向用户展示错误（前 20 行），询问继续或停止。

**接口变化检测**（可选，C/C++/Python 文件）:
对比 patch 合入前后文件的函数签名变化（返回值、参数列表），发现新增/修改的函数，报告用户确认。

### 7. 生成差异报告

合入完成后在源码目录生成 `.patchset-diff.md`:

```markdown
# Patchset 合入报告
## 概要
- 分支: xxx (已保留)
- 总数: X / 成功: X / 失败: X
## 各 patch 状态
| # | 标题 | 状态 | Commit |
|---|------|------|--------|
| 1 | xxx  | ✓    | abc123  |
## 失败详情 (如有)
...错误信息和代码差异...
```

### 8. 输出总结

向用户展示：分支名、成功/失败数量、差异报告路径、失败 patch 列表（如有）。

## 交互模式

以下场景必须在对话中向用户展示信息并等待决策，**不自行决定**:

| 场景 | 展示内容 | 用户选项 |
|------|---------|---------|
| 全部策略失败 | patch 编号和标题、已尝试的 4 种策略、具体错误信息、冲突文件列表 | 手动处理后继续 / 停止整个流程 |
| 编译失败 | patch 编号、编译错误（前 20 行） | 跳过继续 / 停止 |
| 接口变化 | 函数名、旧签名 → 新签名 | 确认继续 / 停止 |

## 反模式

- 跳过失败的 patch 直接合入下一个
- 在 master/main 等主干分支上操作
- 删除合入分支
- 多个 patch 合并为一个 commit
- 写 Python 脚本来替代直接的 bash 调用
- 遇到问题不询问用户自行决定
- 把 patch diff 中的上下文行（不带 `+`/`-` 前缀的行）写入源码文件
