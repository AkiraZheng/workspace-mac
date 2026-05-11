# Patchset Merge Skill

Claude Code / OpenCode skill，从 lore.kernel.org 下载并逐个合入 Linux kernel patchset。

纯指令驱动 —— `SKILL.md` 定义完整工作流，AI 读取后用 bash 直接执行，不依赖 Python 代码。

## 安装

```bash
cd patchset-merge
./install.sh
```

安装脚本自动检测当前环境（Claude Code / OpenCode / Gemini CLI）并部署到对应路径。
同时生成 Copilot、Cursor、通用 Markdown 降级版本到 `dist/` 目录。

## 平台支持

| 平台 | 支持级别 | 安装方式 |
|------|---------|---------|
| Claude Code | 原生（完整） | `install.sh` 自动部署到 `~/.claude/skills/` |
| OpenCode | 原生（完整） | `install.sh` 自动部署到 `~/.config/opencode/skills/` |
| Gemini CLI | 降级（自包含） | `install.sh` 生成到 `~/.agents/skills/` |
| GitHub Copilot | 降级（自包含） | 将 `dist/copilot/*.md` 复制到 `.github/copilot-instructions.md` |
| Cursor | 降级（自包含） | 将 `dist/cursor/*.md` 复制到 `.cursorrules` |
| 通用 Markdown | 降级（自包含） | 使用 `dist/generic/*.md` |

**原生**：保留 superpowers + karpathy-guidelines 完整体验，skill 间可互相调用。
**降级**：自包含单文件，内联 karpathy-guidelines 行为准则，无外部依赖。

## 依赖

| 依赖 | 类型 | 说明 |
|------|------|------|
| `b4` | CLI 工具 | 下载 lore.kernel.org patchset（install.sh 自动安装） |
| `karpathy-guidelines` | Skill | AI 行为准则（install.sh 自动部署，降级版内联） |
| `superpowers` | Claude Code 插件 | Claude Code 需要，OpenCode 不需要（install.sh 自动处理） |

## 使用

### Claude Code

```
/merge-patchset <patch_url> [--source <源码目录>] [--branch <分支名>]
/revert-patchset <commit|范围|关键词> [--source <源码目录>] [--branch <分支名>]
```

### OpenCode

直接描述需求，OpenCode 自动发现并加载对应 skill。例如：

```
帮我合入这个 patchset: https://lore.kernel.org/lkml/xxx/
回退 hdbss 相关的 commit --source /root/openeuler/kernel
```

### 其他平台

将 `dist/<platform>/` 下的 `.md` 文件内容作为 AI 的系统指令 / 规则文件使用。

## 工作流

1. 加载前置 skill（平台感知：Claude Code 用 Skill 工具，OpenCode 自动发现）
2. 检查 b4 → 下载 patchset mbox
3. 拆分 mbox 为单个 patch
4. 创建新分支（自动命名或用户指定）
5. 按顺序逐个合入：`git am` → 解冲突 → `git apply --3way` → `git apply`
6. 每个 patch 单独 commit + 编译验证
7. 遇问题在对话中交互决策，不跳过
8. 生成差异报告

## 核心约束

- 逐个合入，不跳过任何 patch
- 每个 patch 单独 commit
- 遇错即停，不擅自决定
- 分支保留不删除
- 所有输出中文

## 项目结构

```
patchset-merge/
├── SKILL.md                         # merge-patchset 源文件
├── revert-patchset-SKILL.md         # revert-patchset 源文件
├── karpathy-guidelines-SKILL.md     # 行为准则（Tier 1 独立部署，Tier 2 内联）
├── install.sh                       # 多平台安装脚本
├── CLAUDE.md
├── README.md
└── dist/                            # 生成的 Tier 2 降级版本
    ├── copilot/
    ├── cursor/
    ├── gemini/
    └── generic/
```
