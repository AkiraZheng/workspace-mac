#!/bin/bash
# Patchset Merge Skill 一键安装脚本
# 支持 Claude Code 和 OpenCode
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Patchset Merge Skill 安装 ==="

# --- 环境检测 ---
DETECTED_PLATFORMS=()
command -v claude &>/dev/null && DETECTED_PLATFORMS+=("claude")
command -v opencode &>/dev/null && DETECTED_PLATFORMS+=("opencode")

if [ ${#DETECTED_PLATFORMS[@]} -eq 0 ]; then
    echo "[✗] 未检测到 Claude Code 或 OpenCode，退出"
    exit 1
fi

echo "[→] 检测到平台: ${DETECTED_PLATFORMS[*]}"

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

# --- 部署 ---
for platform in "${DETECTED_PLATFORMS[@]}"; do
    echo ""
    echo "--- 部署到 $platform ---"
    case "$platform" in
        claude)
            deploy_skill "merge-patchset" "SKILL.md" "$HOME/.claude/skills/merge-patchset"
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
            deploy_karpathy "$HOME/.config/opencode/skills/karpathy-guidelines"
            echo "  [✓] OpenCode 自动发现 skill，在 opencode.json 中可通过 permission.skill 控制"
            ;;
    esac
done

# --- 总结 ---
echo ""
echo "=== 安装完成 ==="
echo ""
echo "已部署的 skill:"
echo "  - merge-patchset  (智能合入 patchset，含 revert / 依赖检测 / 场景判定)"
echo "  - karpathy-guidelines (行为准则)"
echo ""
echo "支持平台:"
for platform in "${DETECTED_PLATFORMS[@]}"; do
    echo "  - $platform ✓"
done
echo ""
echo "使用方式:"
echo "  Claude Code: /merge-patchset <patch_dir> [--upstream <源仓库>]"
echo "  OpenCode:    直接描述需求，skill 自动加载"
echo ""
echo "如需更新 skill，重新运行此脚本即可。"
