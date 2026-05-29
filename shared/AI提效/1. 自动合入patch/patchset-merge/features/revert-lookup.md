# Revert 查找规则设计

> ✅ 已实现于 `detect_duplicate.py --version-upgrade`

## 三层策略（全限定涉改目录 + 当前分支）

```
策略 1: diff + symbol 匹配 (主线)
  -- search_candidates: git log --grep + -S pickaxe
  -- combined_similarity(diff, symbol), upgrade 阈值 30/15, backport 阈值 80/50
  -- 找到高匹配 commit 作为锚点

策略 2: 关键词 + 目录 + 时间窗口聚合 (主扩展)
  -- 从新 patch 提取专用关键词 (AI: feature_signature.keywords, fallback: 大写缩写)
  -- _search_keyword_commits: git log --grep=<kw> --no-merges -- <patch_dirs>
  -- 按时间窗口分组, 不限作者
  -- 不再依赖作者 (离职/交接/bugfix 由不同人完成是常态)

策略 3: 向前搜索 bugfix (补充)
  -- 从最后一个 core commit 向 HEAD 方向搜索
  -- git log --grep=<kw> --no-merges -- <patch_dirs>
  -- 捕获后续 bugfix (不同作者/不同时间)
```

## 与旧版区别

| 维度 | 旧版 | 新版 |
|------|------|------|
| 分组依据 | author | keyword + directory + time window |
| 扩展方式 | ancestry-path (2856无关commit) | 直接使用关键词匹配结果 |
| 搜索范围 | reflog + fsck → 仅当前分支 | 始终仅当前分支 |
| 关键词来源 | 脚本自动 | AI (agent_analysis.feature_signature) + 脚本 fallback |
| bugfix 覆盖 | 无 | 向前搜索补全 |

## 关键词职责

- **AI (agent_analysis)**: 分析 commit message + diff → 提取 feature_signature
- **脚本 (fallback)**: _build_keywords_from_patches → 从 Subject 提取大写缩写
- **脚本 (过滤)**: _search_keyword_commits → 只使用 isupper() 关键词，排除 KVM/arm64 等通用词
