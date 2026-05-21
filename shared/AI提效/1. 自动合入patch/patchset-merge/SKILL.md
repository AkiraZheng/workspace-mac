---
name: merge-patchset
description: Use when the user provides a patch folder path, runs /merge-patchset, or asks to merge/apply/合入/打补丁 a patchset into a source tree — especially Linux kernel patches. Handles applying patches one-by-one from a folder with escalating strategies, conflict resolution, compile verification, and diff reporting. Trigger on: 合入patch、合入补丁、打patch、apply patchset、merge patchset、/merge-patchset.
compatibility: claude-code, opencode
allowed-tools: Bash(git:*), Bash(make:*), Bash(bash:*), Bash(mkdir:*), Bash(grep:*), Bash(sed:*), Bash(cat:*), Bash(ls:*), Bash(find:*), Bash(rm:*), Bash(echo:*), Write(*)
---

# Merge Patchset

从用户指定的 patch 文件夹逐个合入到源码仓库，遇问题在对话中交互决策。

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

### 其他平台

本文件如果是 install.sh 生成的降级版本，karpathy-guidelines 行为准则已内联在文件头部。如你看到此段但头部没有内联准则，说明文件部署有误，请重新运行 `./install.sh`。

**缺少前置技能或验证不通过则不能继续。**

<!-- @preamble-end -->

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
| `patch_dir` | 是 | 包含 .patch 文件的文件夹路径 | — |
| `--source` | 否 | 源码 git 仓库路径 | 当前目录 `.` |
| `--branch` | 否 | 合入使用的分支名 | 从首个 patch 主题自动生成 |

## 工作流

### 1. 准备

```bash
# 确认是 git 仓库
git -C <source_dir> rev-parse --git-dir

# 确认工作区干净
git -C <source_dir> status --porcelain
```
工作区不干净时警告用户，展示未提交文件列表，询问是否继续。

### 2. 验证 patch 文件夹

```bash
# 确认文件夹存在且包含 .patch 文件
test -d <patch_dir> && echo "✓ 文件夹存在" || echo "✗ 文件夹不存在"
ls <patch_dir>/*.patch 2>/dev/null | wc -l
```

没有找到 .patch 文件 → 报告用户并停止。

### 3. 解析 patch 文件

列出文件夹中所有 .patch 文件，按文件名排序：

```bash
ls <patch_dir>/*.patch | sort
```

读取每个 .patch 文件内容，用 `^Subject:\s*(.+)$` 提取标题，用 `^\+\+\+ b/(.+)$` 提取涉及文件。检查是否有空文件或格式无效的 patch。

### 4. 创建分支

```bash
# 从首个 patch 的 Subject 生成分支名
# 1. 去掉 [PATCH] [RFC] [vN] 等前缀
# 2. 空格/特殊字符换连字符
# 3. 移除所有非字母数字连字符下划线的字符
# 4. 取前 50 字符
# 5. 确保不以数字开头（git 允许但避免混乱），以数字开头则加 "patch-" 前缀
# 格式: patch-<关键词>
# 分支已存在则追加 -$(date +%m%d%H%M)

git checkout -b <branch_name>
```

### 5. 逐个合入

对每个 patch：

**前置检查**：先用 `git apply --check <file.patch>` 检测 patch 是否已合入。如果提示 "already applied" 或 "patch does not apply"，向用户报告该 patch 状态并询问是否跳过。

通过检查后，将内容写入临时 .patch 文件，按以下顺序尝试：

| 序号 | 策略 | 命令 | 成功时 | 失败时 |
|------|------|------|--------|--------|
| ① | `git am` | `git am <file.patch>` | 已自动 commit，继续下一个 | 检查冲突 → 进入②或③ |
| ② | 解冲突 | 读取冲突文件 → 分析两边差异 → 优先保留 patchset 内容 → `git add` + `git commit` | 继续下一个 | 进入③ |
| ③ | `git apply --3way` | `git apply --3way <file.patch>` | `git add .` + `git commit` | 进入④ |
| ④ | `git apply` | `git apply <file.patch>` | `git add .` + `git commit` | **报告用户** |

**冲突解决规则**: 优先保留 patchset 的修改内容。

**检测冲突文件**:
```bash
git diff --name-only --diff-filter=U
```

### 6. 每个 patch 合入后

**编译验证**:
```bash
# 按优先级尝试编译命令
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
| 工作区不干净 | 未提交的文件列表 | 继续 / 取消 |
| 全部策略失败 | patch 编号和标题、已尝试的 4 种策略、具体错误信息、冲突文件列表 | 手动处理后继续 / 停止整个流程 |
| 编译失败 | patch 编号、编译错误（前 20 行） | 跳过继续 / 停止 |
| patch 已合入或无效 | patch 文件名、`git apply --check` 输出 | 跳过 / 停止 |

## 反模式

- 跳过失败的 patch 直接合入下一个
- 在 master/main 等主干分支上操作
- 删除合入分支
- 多个 patch 合并为一个 commit
- 写 Python 脚本来替代直接的 bash 调用
- 遇到问题不询问用户自行决定
- 把 patch diff 中的上下文行（不带 `+`/`-` 前缀的行）写入源码文件
