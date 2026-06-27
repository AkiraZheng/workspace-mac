---
name: conflict-resolver
description: >
  内核 patch 合入时的 Git 冲突自动解决。含 git am --3way / --reject 降级链、
  .rej 文件循环处理、Ours/Theirs 决策表（10 场景）、最多 10 次重试。
  触发条件：git am 失败、产生 .rej 文件、patch 合入冲突。
---

# Conflict Resolver — Git Patch 冲突自动解决

## 职责

将 patch 文件应用到目标 git 仓库，遇到冲突时自动决策并修复。适用于 Linux 内核及任何 git 仓库。

## 输入

| 参数 | 说明 |
|------|------|
| `patch_file` | .patch 文件绝对路径 |
| `repo_path` | 目标 git 仓库路径 |

不依赖任何层间 JSON 文件，只依赖 git 工具。

## 执行流程

### 步骤 1: git am --3way

```bash
cd "$repo_path"

git am --3way --ignore-space-change --keep-cr "$patch_file"

if [ $? -eq 0 ]; then
  echo "✅ git am 成功，无冲突"
  exit 0
fi
```

### 步骤 2: 降级 → git am --reject

```bash
git am --abort
git am --3way --ignore-space-change --keep-cr --reject "$patch_file"

# 此时会生成 .rej 文件在对应目录下
```

### 步骤 3: 循环处理 .rej 文件

```bash
while [ -n "$(find . -name '*.rej')" ]; do
  for rej_file in $(find . -name "*.rej"); do
    # 1. 读取 .rej 文件内容
    Read: "$rej_file"

    # 2. 确定目标文件路径（.rej 文件名去掉 .rej 后缀）
    target_file="${rej_file%.rej}"

    # 3. 读取目标文件当前内容
    Read: "$target_file"

    # 4. AI 按 Ours/Theirs 决策表判断每个 hunk
    #    参考 references/decision_table.md

    # 5. 编辑目标文件
    Edit: "$target_file"

    # 6. 删除已处理的 .rej 文件
    rm "$rej_file"
  done

  # 7. stage 所有变更并尝试继续
  git add -A
  git am --continue

  if [ $? -eq 0 ]; then
    echo "✅ 冲突解决成功"
    break
  fi

  RETRY_COUNT=$((RETRY_COUNT + 1))
  if [ $RETRY_COUNT -ge 10 ]; then
    echo "❌ git am 已重试 10 次仍失败"
    exit 1
  fi
done
```

### 步骤 4: Ours/Theirs 决策

参考 `references/decision_table.md`，核心原则：

| 场景 | 抉择 | 理由 |
|------|------|------|
| patch 的 `+` 行（新增代码） | **Theirs** | 这是 patch 的核心意图，不可丢弃 |
| 引用的 introduced_symbols 所在行 | **Theirs** | 核心符号定义不可删 |
| 上下文行差异 | **Ours** | 上下文是定位锚点，目标仓库代码是真实代码 |
| 上游重构 vs 本地 | **Theirs** | 上游版本更权威 |
| 下游特有补丁 vs 上游 | **人工裁定** | 下游特有修改不可丢弃 |
| 新功能 vs 本地 hack | **建议 Theirs** | 记录本地历史供评估 |
| 无法自动判定 | **暂停** | 输出两方代码对比给用户裁定 |

### 步骤 5: 最小修改原则

1. 只改冲突区域的代码，同行文件其他部分不动
2. 保持目标仓库代码风格（缩进、命名、注释）
3. 不改 Makefile/Kconfig，不碰 .config 逻辑

## 上下文缺失的处理

patch 中以空格开头的上下文行是 git 的定位依据，不是必须存在的代码。缺失上下文时直接让 `git am --reject` 处理，AI 在步骤 3 中处理 .rej 即可。**不在 git am 前分析上下文完整性**。

## 输出

| 状态 | 含义 |
|------|------|
| exit 0 | patch 已成功应用，所有 .rej 已处理 |
| exit 1 | 重试 10 次后仍失败，暂停等用户决策 |
