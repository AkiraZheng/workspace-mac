# 搜索策略指南

agent_target_revert 和 agent_upstream_deps Subagent 使用的搜索方法。

## 搜索工具链

按优先级逐级深入：

### 1. 关键词聚合（git log --grep）
```bash
# 限定涉改目录，使用 AI 提取的关键词
for kw in ${keywords[@]}; do
  git log --grep="$kw" --oneline -n 50 "${files[@]}" > /tmp/kw_search_$kw.txt
done
```

### 2. Revert 追溯（git log --grep）
```bash
# 从 revert commit 反向定位原始 commit
git log --grep="Revert" --grep="$kw" -i --all-match --oneline -n 30 > /tmp/revert_search.txt
```

### 3. 符号追溯（git log -S）
```bash
# 按符号名追溯引入历史
for sym in ${symbols[@]}; do
  git log -S "$sym" --oneline -n 20 "${files[@]}" > /tmp/sym_search_$sym.txt
done
```

### 4. 文件追溯（git log --）
```bash
# 按涉改文件追溯 commit 历史
git log --oneline -n 20 "${files[@]}" > /tmp/file_search.txt
```

## 深入理解

对每个候选 commit，AI 需要：
1. 读取 commit message（`git show --no-patch <hash>`）
2. 读取 commit diff（`git show <hash>`）
3. 判断：是否是旧版本功能实现（→ confirm）、无关注释/格式/doc（→ reject）

## merge commit 处理（强制）

**检测**：
```bash
PARENT_COUNT=$(git rev-list --parents -n 1 "$commit" | wc -w)
# PARENT_COUNT > 2 表示 merge commit
```

**展开**：
```bash
git log --oneline "$commit~1..$commit"
```

**规则**：
- ❌ 禁止写入 merge commit hash
- ✅ 必须写入展开后的子 commit hash，每个子 commit 单独一个 candidate entry

## 去重合并

将关键词聚合、revert 追溯、符号追溯、文件追溯的结果合并去重：
- 同一 commit hash 出现在多个来源 → 保留一个，标记所有来源
- 按相似度评分排序 → 取 Top-N
