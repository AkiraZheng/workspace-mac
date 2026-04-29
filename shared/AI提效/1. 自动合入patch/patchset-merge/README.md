# Patchset Merge Skill

Claude Code 中使用的 patchset 合入工具。

## 安装

```bash
pip install git+https://your-repo-url.git
```

或本地安装：
```bash
git clone <repo-url>
cd patchset-merge
pip install .
```

## 使用

在 Claude Code 中：

```
/merge-patchset <patch_url> --source <源码目录> --branch <分支名>
```

**示例：**

```
/merge-patchset https://lore.kernel.org/lkml/xxx/
/merge-patchset https://lore.kernel.org/lkml/xxx/ --source /path/to/linux --branch my-branch
```

## 功能

1. 自动检查并安装 b4 工具
2. 使用 `b4 am` 下载完整 patchset mbox 文件
3. 创建 git worktree 隔离分支
4. 应用 patchset 到源码
5. 生成差异报告 `.patchset-diff.md`

## 冲突解决策略

- **确定性优先**: 相同 patchset + 相同源码 = 100% 相同输出
- **Patchset 内容优先**: 冲突时保留 patchset 的修改
- **差异可追溯**: 所有与原 patchset 的偏差都会记录

## 项目结构

```
patchset-merge/
├── install.sh                 # 一键安装脚本
├── patchset_merge/            # Python 包
│   ├── __init__.py
│   ├── b4_installer.py         # b4 工具安装
│   ├── patchset_downloader.py  # 下载 patchset
│   ├── diff_tracker.py         # 差异追踪
│   ├── conflict_resolver.py    # 冲突解决
│   ├── merger.py              # 核心 merge 引擎
│   └── skill.py              # Skill 入口
├── tests/                     # 测试文件
├── .claude/commands/         # Claude Code 命令
└── pyproject.toml
```
