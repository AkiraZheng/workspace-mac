# Patchset Merge Skill

从 lore.kernel.org 下载并自动合入 patchset 的 Claude Code Skill。

## 功能

- 使用 b4 工具从 lore.kernel.org 下载完整 patchset
- 创建独立的 git worktree 隔离分支进行 merge
- 自动解决合并冲突（优先保留 patchset 内容）
- 生成差异报告记录所有修改

## 使用方式

```
/merge-patchset <patch_url> --source <源码目录> --branch <分支名>
```

## 目录结构

```
patchset-merge/
├── __init__.py           # 包入口
├── skill.py              # Skill 入口
├── b4_installer.py       # b4 安装检查
├── patchset_downloader.py # 下载 patchset
├── merger.py             # 核心 Merge 引擎
├── diff_tracker.py       # 差异追踪
└── conflict_resolver.py  # 冲突解决策略
```