# Patchset Merge Skill

Claude Code skill，从 lore.kernel.org 下载并逐个合入 Linux kernel patchset。

纯指令驱动 —— `SKILL.md` 定义完整工作流，AI 读取后用 bash 直接执行，不依赖 Python 代码。

## 安装

```bash
cd patchset-merge
./install.sh
```

安装脚本会：

1. 检查/安装 `b4` 工具
2. 部署 `merge-patchset` 和 `karpathy-guidelines` 两个 skill
3. 检查 `superpowers` 插件，缺失时提示安装

## 依赖

| 依赖 | 类型 | 说明 |
|------|------|------|
| `b4` | CLI 工具 | 下载 lore.kernel.org patchset |
| `karpathy-guidelines` | Skill | 减少 AI 过度设计、避免猜测（随项目打包） |
| `superpowers` | 插件 | Skill 系统治理框架（需单独安装） |

## 使用

在 Claude Code 中：

```
/merge-patchset <patch_url> [--source <源码目录>] [--branch <分支名>]
```

**示例：**

```
/merge-patchset https://lore.kernel.org/lkml/xxx/
/merge-patchset https://lore.kernel.org/lkml/xxx/ --source /root/openeuler/kernel --branch my-fix
```

## 工作流

1. 加载前置 skill（using-superpowers + karpathy-guidelines）
2. 检查 b4 → 下载 patchset mbox
3. 拆分 mbox 为单个 patch
4. 创建新分支（自动命名或用户指定）
5. 按顺序逐个合入：`git am` → 解冲突 → `git apply --3way` → `git apply`
6. 每个 patch 单独 commit + 编译验证
7. 遇问题在对话中交互决策，不跳过
8. 生成 `.patchset-diff.md` 差异报告

## 核心约束

- 逐个合入，不跳过任何 patch
- 每个 patch 单独 commit
- 遇错即停，不擅自决定
- 分支保留不删除
- 所有输出中文

## 项目结构

```
patchset-merge/
├── SKILL.md                     # merge-patchset skill 定义
├── karpathy-guidelines-SKILL.md # 前置依赖 skill（随项目打包）
├── install.sh                   # 一键安装
└── README.md                    # 本文件
```
