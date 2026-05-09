#!/bin/bash
# Patchset Merge Skill 一键安装脚本
# 每次运行都会更新所有 skill 到最新版本
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Patchset Merge Skill 安装 ==="

# 1. 检查并安装 b4
if command -v b4 &> /dev/null; then
    echo "[✓] b4 已安装: $(b4 --version 2>&1)"
else
    echo "[→] 安装 b4..."
    pip install b4
    echo "[✓] b4 安装完成"
fi

# 2. 部署 merge-patchset skill
SKILL_DIR="$HOME/.claude/skills/merge-patchset"
mkdir -p "$SKILL_DIR"
cp "$SCRIPT_DIR/SKILL.md" "$SKILL_DIR/"
echo "[✓] merge-patchset → $SKILL_DIR/SKILL.md"

# 3. 部署/更新 karpathy-guidelines skill
#    优先尝试从已知源获取最新版本，失败则使用项目自带版本
KARPA_DIR="$HOME/.claude/skills/karpathy-guidelines"
mkdir -p "$KARPA_DIR"

KARPA_UPDATED=false
KARPA_REPO="${KARPATHY_GUIDELINES_REPO:-https://raw.githubusercontent.com/karpathy/guidelines/main/SKILL.md}"

# 尝试从远程拉取最新版本
if command -v curl &> /dev/null; then
    echo "[→] 尝试获取最新 karpathy-guidelines..."
    if curl -fsSL --connect-timeout 5 "$KARPA_REPO" -o "$KARPA_DIR/SKILL.md.tmp" 2>/dev/null; then
        if grep -q "karpathy-guidelines" "$KARPA_DIR/SKILL.md.tmp" 2>/dev/null; then
            mv "$KARPA_DIR/SKILL.md.tmp" "$KARPA_DIR/SKILL.md"
            echo "[✓] karpathy-guidelines 已从远程更新 → $KARPA_DIR/SKILL.md"
            KARPA_UPDATED=true
        else
            rm -f "$KARPA_DIR/SKILL.md.tmp"
            echo "[!] 远程内容无效，回退到本地版本"
        fi
    else
        echo "[!] 远程获取失败（网络不可达或仓库不存在），使用本地版本"
    fi
fi

# 远程获取失败则使用项目自带版本
if [ "$KARPA_UPDATED" = false ]; then
    cp "$SCRIPT_DIR/karpathy-guidelines-SKILL.md" "$KARPA_DIR/SKILL.md"
    echo "[✓] karpathy-guidelines → $KARPA_DIR/SKILL.md (本地版本)"
fi

# 4. 部署 revert-patchset skill
REVERT_DIR="$HOME/.claude/skills/revert-patchset"
mkdir -p "$REVERT_DIR"
cp "$SCRIPT_DIR/revert-patchset-SKILL.md" "$REVERT_DIR/SKILL.md"
echo "[✓] revert-patchset → $REVERT_DIR/SKILL.md"

# 5. 确保 superpowers 插件已安装
echo ""
echo "[→] 检查 superpowers 插件..."
if [ -d "$HOME/.claude/plugins/cache/claude-plugins-official/superpowers" ]; then
    echo "[✓] superpowers 插件已安装"
else
    if command -v claude &> /dev/null; then
        echo "[→] 安装 superpowers..."
        if claude plugins install superpowers@claude-plugins-official 2>&1; then
            echo "[✓] superpowers 安装完成"
        else
            echo "[!] 自动安装失败，请在 Claude Code 中运行:"
            echo "    /plugin install superpowers@claude-plugins-official"
        fi
    else
        echo "[!] claude CLI 不可用，请在 Claude Code 中运行:"
        echo "    /plugin install superpowers@claude-plugins-official"
    fi
fi

echo ""
echo "=== 安装完成 ==="
echo ""
echo "已部署的 skill:"
echo "  - merge-patchset  (合入 patchset)"
echo "  - revert-patchset (回退 commit)"
echo "  - karpathy-guidelines (行为准则)"
echo ""
echo "如需更新 skill，重新运行此脚本即可。"
echo "如果 superpowers 插件是首次安装，请重启 Claude Code 后使用。"
echo ""
echo "使用方式 (在 Claude Code 中):"
echo "  /merge-patchset <patch_url> [--source <源码目录>] [--branch <分支名>]"
echo "  /revert-patchset <commit|范围|关键词> [--source <源码目录>] [--branch <分支名>]"
echo ""
echo "示例:"
echo "  /merge-patchset https://lore.kernel.org/lkml/xxx/"
echo "  /revert-patchset abc123..def456 --source /root/openeuler/kernel"
echo "  /revert-patchset hdbss --source /root/openeuler/kernel --branch revert-hdbss"
