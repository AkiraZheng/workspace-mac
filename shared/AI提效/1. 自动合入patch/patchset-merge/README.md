# Patchset Merge Skill

Claude Code / OpenCode skill，智能 patchset 合入。内置多场景检测：自动判断是否需要先 revert 旧代码、是否需要从上游拉取依赖 patch、是否部分已合入。

纯指令驱动 —— `SKILL.md` 定义完整工作流，AI 读取后用 bash + Agent 直接执行，不依赖 Python 代码。

## 安装

```bash
cd patchset-merge
./install.sh
```

安装脚本自动检测 Claude Code / OpenCode 并部署到对应路径。

## 依赖

| 依赖 | 类型 | 说明 |
|------|------|------|
| `karpathy-guidelines` | Skill | AI 行为准则（install.sh 自动部署） |
| `superpowers` | Claude Code 插件 | Claude Code 需要，OpenCode 不需要（install.sh 自动处理） |

## 使用

### Claude Code

【推荐用法】直接描述需求，claude 自动发现并加载 skill。例如：

```
帮我合入 /tmp/patches/ 下的 patchset，目标仓库是 /root/openeuler/kernel
这些 patch 来自 linux-stable，上游仓库在 /root/linux，帮我检查有没有缺失的依赖
```

使用参数：
```
/merge-patchset <patch_dir> [--source <目标仓库>] [--upstream <源仓库>] [--branch <分支名>]
```

- `patch_dir`: 包含 .patch 文件的文件夹路径
- `--source`: 目标源码 git 仓库路径
- `--upstream`: 上游仓库，用于自动查找是否缺少相关的依赖patches
- `--branch`: merge操作的目标分支名

### OpenCode

【推荐用法】直接描述需求，OpenCode 自动发现并加载 skill。例如：

```
帮我合入 /tmp/patches/ 下的 patchset，目标仓库是 /root/openeuler/kernel
这些 patch 来自 linux-stable，上游仓库在 /root/linux，帮我检查有没有缺失的依赖
```

使用参数：
```
/merge-patchset <patch_dir> [--source <目标仓库>] [--upstream <源仓库>] [--branch <分支名>]
```

- `patch_dir`: 包含 .patch 文件的文件夹路径
- `--source`: 目标源码 git 仓库路径
- `--upstream`: 上游仓库，用于自动查找是否缺少相关的依赖patches
- `--branch`: merge操作的目标分支名

## 工作流

### 相位 0 — 前置检测（并行 agent）
1. Agent A：冲突预检 — 扫描目标仓库，判断每个 patch 的冲突风险
2. Agent B：依赖检测 — 在上游仓库查找缺失的依赖 commit（需 `--upstream`）
3. Agent C：已合入检测 — 检查哪些 patch 已存在于目标仓库

### 相位 1 — 场景判定
汇总 agent 结果，判定场景（A~E），向用户展示确认：

| 场景 | 触发条件 | 前置操作 |
|------|---------|---------|
| A — 干净合入 | 冲突风险低，无依赖缺失 | 直接 merge |
| B — 先 Revert | 高冲突 + 有旧版本 commit | 逆序 revert 旧 commit |
| C — 补依赖 | 上游有缺失的依赖 commit | 从上游拉取 patch |
| D — 部分跳过 | 部分 patch 已合入 | 跳过已合入的 |
| E — 路径适配 | patch 文件路径在目标仓库不存在 | 搜索实际路径并映射 |

### 相位 2 — 执行 merge
1. 按场景执行前置操作（revert / 拉依赖 / 路径适配）
2. 创建新分支（自动命名或用户指定）
3. 逐个合入：`git apply --check` → `git am` → 解冲突 → `git apply --3way` → `git apply`
4. 每个 patch 单独 commit + 编译验证
5. 遇问题在对话中交互决策
6. 生成差异报告

## 核心约束

- 逐个合入，不跳过任何 patch（除非确认已合入）
- 每个 patch 单独 commit；revert 也单独 commit
- 遇错即停，不擅自决定
- 分支保留不删除
- revert 时逆序执行
- 所有输出中文

## 项目结构

```
patchset-merge/
├── SKILL.md                         # merge-patchset 源文件
├── karpathy-guidelines-SKILL.md     # 行为准则
├── install.sh                       # 安装脚本
├── CLAUDE.md
└── README.md
```
