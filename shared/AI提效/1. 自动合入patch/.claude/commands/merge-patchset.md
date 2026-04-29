# Merge Patchset Command

使用 b4 从 lore.kernel.org 下载并合入 patchset 到指定源码。

## 使用方式

```
/merge-patchset <patch_url> --source <源码目录> --branch <分支名>
```

## 参数
- `patch_url`: lore.kernel.org 上任意一个 patch 的 URL
- `--source`: 目标源码仓库路径（默认：当前目录）
- `--branch`: Merge 使用的分支名（默认：从 patch 标题生成）

## 示例

```
/merge-patchset https://lore.kernel.org/linux-kernel/xxx.patch
/merge-patchset https://lore.kernel.org/lkml/xxx/ --source /path/to/linux --branch my-branch
```

## 输出

1. 自动检查并安装 b4（如需要）
2. 下载完整 patchset mbox 文件
3. 创建 git worktree 隔离分支
4. 应用 patchset
5. 生成差异报告 `.patchset-diff.md`