# Cross-Platform Skills 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 merge-patchset 和 revert-patchset 从 Claude Code 独占改造为 Claude Code + OpenCode 双平台原生支持，并自动生成 Tier 2 降级版本。

**Architecture:** 单一 SKILL.md 源文件通过平台感知的前置加载段同时服务 Claude Code 和 OpenCode；install.sh 自动检测环境部署到对应路径，并用标记段裁剪生成 Tier 2 自包含版本。

**Tech Stack:** Bash, sed, YAML frontmatter

---

### Task 1: 更新 merge-patchset SKILL.md

**Files:**
- Modify: `SKILL.md:1-53`

- [ ] **Step 1: 修改 frontmatter，添加 `compatibility` 字段**

在 `description` 和 `allowed-tools` 之间插入一行：

```yaml
---
name: merge-patchset
description: Use when the user provides a lore.kernel.org patch URL, runs /merge-patchset, or asks to merge/apply/合入 a Linux kernel patchset into a source tree. Handles downloading patchsets with b4, applying patches one-by-one with escalating strategies, conflict resolution, compile verification, and diff reporting.
compatibility: claude-code, opencode
allowed-tools: Bash(b4:*), Bash(pip install b4), Bash(git:*), Bash(make:*), Bash(bash:*), Bash(mkdir:*), Bash(grep:*), Bash(sed:*), Bash(cat:*), Bash(ls:*), Bash(find:*), Bash(rm:*), Bash(echo:*), Write(*)
---
```

- [ ] **Step 2: 在前置技能加载段首尾添加裁剪标记**

在 `## 前置技能加载（必须）` 上方插入开始标记，在 `加载完成后，再继续执行下面的工作流。**缺少任何一个都不能继续。**` 下方插入结束标记。

```markdown
<!-- @preamble-start -->
## 前置技能加载（必须）

**开始任何合入工作前，验证并加载以下技能。不通过则不继续。**

...（中间内容后续步骤替换）...

加载完成后，再继续执行下面的工作流。**缺少任何一个都不能继续。**

<!-- @preamble-end -->
```

- [ ] **Step 3: 替换前置技能加载段内容为平台感知版本**

将整个 `## 前置技能加载（必须）` 段（两个标记之间的内容）替换为：

```markdown
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
```

- [ ] **Step 4: 验证文件完整性**

```bash
grep "compatibility:" SKILL.md && echo "✓ compatibility added"
grep "@preamble-start" SKILL.md && echo "✓ preamble-start marker"
grep "@preamble-end" SKILL.md && echo "✓ preamble-end marker"
grep "Claude Code" SKILL.md && grep "OpenCode" SKILL.md && echo "✓ platform-aware preamble"
```

- [ ] **Step 5: Commit**

```bash
git add SKILL.md
git commit -m "feat: make merge-patchset cross-platform (Claude Code + OpenCode)

Add compatibility field to frontmatter, rewrite preamble for
platform-aware skill loading. Add markers for degraded generation.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: 同步更新 revert-patchset SKILL.md

**Files:**
- Modify: `revert-patchset-SKILL.md:1-42`

- [ ] **Step 1: 修改 frontmatter，添加 `compatibility` 字段**

```yaml
---
name: revert-patchset
description: Use when the user wants to revert commits from a git repository, runs /revert-patchset, or asks to revert/回退/撤销 a commit range, topic keyword, or patchset. Handles identifying commits, reverting one-by-one in reverse order with conflict resolution, compile verification, and diff reporting.
compatibility: claude-code, opencode
allowed-tools: Bash(git:*), Bash(make:*), Bash(bash:*), Bash(mkdir:*), Bash(grep:*), Bash(sed:*), Bash(cat:*), Bash(ls:*), Bash(find:*), Bash(rm:*), Bash(echo:*), Write(*)
---
```

- [ ] **Step 2: 添加裁剪标记并替换前置段**

在 `## 前置技能加载（必须）` 上方插入 `<!-- @preamble-start -->`，在 `**缺少任何一个都不能继续。**` 下方插入 `<!-- @preamble-end -->`。

将两标记之间的内容替换为：

```markdown
<!-- @preamble-start -->
## 前置技能加载（必须）

**开始任何 revert 工作前，验证并加载前置技能。不通过则不继续。**

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
1. `superpowers:using-superpowers`
2. `karpathy-guidelines`

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
```

- [ ] **Step 3: 验证**

```bash
grep "compatibility:" revert-patchset-SKILL.md && echo "✓ compatibility added"
grep "@preamble-start" revert-patchset-SKILL.md && echo "✓ preamble marker"
grep "OpenCode" revert-patchset-SKILL.md && echo "✓ platform-aware"
```

- [ ] **Step 4: Commit**

```bash
git add revert-patchset-SKILL.md
git commit -m "feat: make revert-patchset cross-platform (Claude Code + OpenCode)

Sync frontmatter and preamble changes from merge-patchset.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: 重写 install.sh

**Files:**
- Rewrite: `install.sh`

- [ ] **Step 1: 编写环境检测和辅助函数**

```bash
#!/bin/bash
# Patchset Merge Skill 一键安装脚本（多平台支持）
# 自动检测 Claude Code / OpenCode / Gemini CLI 并部署到对应路径
# 同时生成 Copilot / Cursor / 通用 Markdown 降级版本到 dist/
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Patchset Merge Skill 安装（多平台）==="

# --- 环境检测 ---
DETECTED_PLATFORMS=()
command -v claude &>/dev/null && DETECTED_PLATFORMS+=("claude")
command -v opencode &>/dev/null && DETECTED_PLATFORMS+=("opencode")
command -v gemini &>/dev/null && DETECTED_PLATFORMS+=("gemini")

if [ ${#DETECTED_PLATFORMS[@]} -eq 0 ]; then
    echo "[→] 未检测到 Claude Code / OpenCode / Gemini CLI"
    echo "[→] 将仅生成降级版本到 dist/ 目录"
fi

echo "[→] 检测到平台: ${DETECTED_PLATFORMS[*]:-(仅生成降级版本)}"

# --- 辅助函数 ---

deploy_skill() {
    local skill_name=$1
    local source_file=$2
    local target_dir=$3
    mkdir -p "$target_dir"
    cp "$SCRIPT_DIR/$source_file" "$target_dir/SKILL.md"
    echo "  [✓] $skill_name → $target_dir/SKILL.md"
}

deploy_karpathy() {
    local target_dir=$1
    mkdir -p "$target_dir"
    local updated=false
    local remote="${KARPATHY_GUIDELINES_REPO:-https://raw.githubusercontent.com/karpathy/guidelines/main/SKILL.md}"
    if command -v curl &>/dev/null; then
        if curl -fsSL --connect-timeout 5 "$remote" -o "$target_dir/SKILL.md.tmp" 2>/dev/null; then
            if grep -q "karpathy-guidelines" "$target_dir/SKILL.md.tmp" 2>/dev/null; then
                mv "$target_dir/SKILL.md.tmp" "$target_dir/SKILL.md"
                echo "  [✓] karpathy-guidelines (远程) → $target_dir/SKILL.md"
                updated=true
            else
                rm -f "$target_dir/SKILL.md.tmp"
            fi
        fi
    fi
    if [ "$updated" = false ]; then
        cp "$SCRIPT_DIR/karpathy-guidelines-SKILL.md" "$target_dir/SKILL.md"
        echo "  [✓] karpathy-guidelines (本地) → $target_dir/SKILL.md"
    fi
}

generate_degraded() {
    local skill_name=$1
    local source_file=$2
    local platform=$3
    local output_dir="$SCRIPT_DIR/dist/$platform"
    mkdir -p "$output_dir"
    local output="$output_dir/${skill_name}.md"

    {
        echo "# ${skill_name} (${platform} 自包含版本)"
        echo ""
        echo "> 自动生成于 $(date '+%Y-%m-%d %H:%M')，内联 karpathy-guidelines 行为准则"
        echo "> 适用于没有 skill 系统的 AI 编码平台"
        echo ""
        echo "---"
        echo ""
        # Inline karpathy-guidelines body (skip YAML frontmatter between --- markers)
        awk 'BEGIN { n=0 } /^---$/ { n++; next } n>=2' "$SCRIPT_DIR/karpathy-guidelines-SKILL.md"
        echo ""
        echo "---"
        echo ""
        # Insert skill content without preamble section
        sed '/<!-- @preamble-start -->/,/<!-- @preamble-end -->/d' "$SCRIPT_DIR/$source_file"
    } > "$output"
    echo "  [✓] ${skill_name} → $output"
}
```

- [ ] **Step 2: 编写平台部署逻辑（续接上一步）**

```bash
# --- b4 检查 ---
echo ""
if command -v b4 &>/dev/null; then
    echo "[✓] b4 已安装: $(b4 --version 2>&1)"
else
    echo "[→] 安装 b4..."
    pip install b4 && echo "[✓] b4 安装完成"
fi

# --- 部署到检测到的平台 ---
for platform in "${DETECTED_PLATFORMS[@]}"; do
    echo ""
    echo "--- 部署到 $platform ---"
    case "$platform" in
        claude)
            deploy_skill "merge-patchset" "SKILL.md" "$HOME/.claude/skills/merge-patchset"
            deploy_skill "revert-patchset" "revert-patchset-SKILL.md" "$HOME/.claude/skills/revert-patchset"
            deploy_karpathy "$HOME/.claude/skills/karpathy-guidelines"
            if [ -d "$HOME/.claude/plugins/cache/claude-plugins-official/superpowers" ]; then
                echo "  [✓] superpowers 插件已安装"
            else
                echo "  [!] 请安装 superpowers 插件:"
                echo "      claude plugins install superpowers@claude-plugins-official"
            fi
            ;;
        opencode)
            deploy_skill "merge-patchset" "SKILL.md" "$HOME/.config/opencode/skills/merge-patchset"
            deploy_skill "revert-patchset" "revert-patchset-SKILL.md" "$HOME/.config/opencode/skills/revert-patchset"
            deploy_karpathy "$HOME/.config/opencode/skills/karpathy-guidelines"
            echo "  [✓] OpenCode 自动发现 skill，在 opencode.json 中可通过 permission.skill 控制"
            ;;
        gemini)
            generate_degraded "merge-patchset" "SKILL.md" "gemini"
            generate_degraded "revert-patchset" "revert-patchset-SKILL.md" "gemini"
            mkdir -p "$HOME/.agents/skills/merge-patchset" "$HOME/.agents/skills/revert-patchset"
            cp "$SCRIPT_DIR/dist/gemini/merge-patchset.md" "$HOME/.agents/skills/merge-patchset/SKILL.md"
            cp "$SCRIPT_DIR/dist/gemini/revert-patchset.md" "$HOME/.agents/skills/revert-patchset/SKILL.md"
            echo "  [✓] merge-patchset → ~/.agents/skills/merge-patchset/SKILL.md"
            echo "  [✓] revert-patchset → ~/.agents/skills/revert-patchset/SKILL.md"
            ;;
    esac
done

# --- 生成所有 Tier 2 降级版本（无论检测到什么平台都生成） ---
echo ""
echo "--- 生成 Tier 2 降级版本 ---"
for platform in copilot cursor gemini generic; do
    generate_degraded "merge-patchset" "SKILL.md" "$platform"
    generate_degraded "revert-patchset" "revert-patchset-SKILL.md" "$platform"
done
```

- [ ] **Step 3: 编写安装完成总结（续接）**

```bash
# --- 总结 ---
echo ""
echo "=== 安装完成 ==="
echo ""
echo "已部署的 skill:"
echo "  - merge-patchset  (合入 patchset)"
echo "  - revert-patchset (回退 commit)"
echo "  - karpathy-guidelines (行为准则)"
echo ""
echo "支持平台:"
for platform in "${DETECTED_PLATFORMS[@]}"; do
    echo "  - $platform ✓"
done
echo ""
echo "Tier 2 降级版本（手动部署）:"
echo "  - dist/generic/   → 通用 Markdown"
echo "  - dist/copilot/   → GitHub Copilot (.github/copilot-instructions.md)"
echo "  - dist/cursor/    → Cursor (.cursorrules)"
echo "  - dist/gemini/    → Gemini CLI"
echo ""
echo "使用方式:"
echo "  Claude Code: /merge-patchset <url>    /revert-patchset <commit>"
echo "  OpenCode:    直接描述需求，skill 自动加载"
echo "  Copilot:     将 dist/copilot/*.md 内容复制到 .github/copilot-instructions.md"
echo "  Cursor:      将 dist/cursor/*.md 内容复制到 .cursorrules"
echo ""
echo "如需更新 skill，重新运行此脚本即可。"
```

- [ ] **Step 4: 验证 install.sh 语法**

```bash
bash -n install.sh && echo "✓ syntax OK"
```

- [ ] **Step 5: 测试运行 install.sh**

```bash
bash install.sh
```

Expected: 根据当前环境检测到 claude，部署到 `~/.claude/skills/` 和 `~/.config/opencode/skills/`（如果有），生成 dist/ 目录。

- [ ] **Step 6: 验证生成文件**

```bash
# 验证 dist/ 目录结构
ls dist/generic/ && echo "✓ generic"
ls dist/copilot/ && echo "✓ copilot"
ls dist/cursor/ && echo "✓ cursor"

# 验证降级版本不含 preamble 标记
grep -L "@preamble" dist/generic/merge-patchset.md && echo "✓ preamble stripped"

# 验证降级版本内联了 karpathy-guidelines
grep "Karpathy Guidelines" dist/generic/merge-patchset.md && echo "✓ guidelines inlined"
```

- [ ] **Step 7: Commit**

```bash
git add install.sh
git commit -m "feat: rewrite install.sh for multi-platform deployment

Detect Claude Code / OpenCode / Gemini CLI, deploy to native paths.
Generate degraded self-contained versions for Copilot/Cursor/Generic.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: 更新 README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 在 README 中添加多平台说明**

在 `## 安装` 段后添加平台支持表。

把当前文件末尾的平台特定内容改为多平台表格。完整替换为：

```markdown
# Patchset Merge Skill

Claude Code skill，从 lore.kernel.org 下载并逐个合入 Linux kernel patchset。

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
回退 hdbss 相关的 commit: --source /root/openeuler/kernel
```

### 其他平台

将 `dist/<platform>/` 下的 `.md` 文件内容作为 AI 的系统指令 / 规则文件使用。

**示例：**

```
/merge-patchset https://lore.kernel.org/lkml/xxx/
/merge-patchset https://lore.kernel.org/lkml/xxx/ --source /root/openeuler/kernel --branch my-fix
/revert-patchset hdbss --source /root/openeuler/kernel
```

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
```

- [ ] **Step 2: 验证 README 可读性**

```bash
wc -l README.md
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README for multi-platform support

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: 端到端验证

- [ ] **Step 1: 运行 install.sh，确认所有文件正确部署**

```bash
bash install.sh
```

检查：
- `~/.claude/skills/merge-patchset/SKILL.md` 存在且含 `compatibility` 和 `@preamble`
- `~/.claude/skills/karpathy-guidelines/SKILL.md` 存在
- `dist/generic/merge-patchset.md` 不含 `@preamble`，含 `Karpathy Guidelines`

- [ ] **Step 2: 验证 merge-patchset SKILL.md 在 Claude Code 中可正常加载**

```bash
grep "compatibility: claude-code, opencode" ~/.claude/skills/merge-patchset/SKILL.md && echo "✓"
grep "Claude Code" ~/.claude/skills/merge-patchset/SKILL.md && echo "✓"
grep "OpenCode" ~/.claude/skills/merge-patchset/SKILL.md && echo "✓"
```

- [ ] **Step 3: 确认 sync 规则——两个 skill 的前置段一致**

```bash
# Extract preamble from both files and diff
sed -n '/@preamble-start/,/@preamble-end/p' SKILL.md > /tmp/pre-merge.txt
sed -n '/@preamble-start/,/@preamble-end/p' revert-patchset-SKILL.md > /tmp/pre-revert.txt
diff /tmp/pre-merge.txt /tmp/pre-revert.txt && echo "✓ preambles in sync" || echo "✗ preambles differ — review"
```

- [ ] **Step 4: 清理并确认 .gitignore 包含 dist/**

```bash
echo "dist/" >> .gitignore 2>/dev/null || true
git status
```
