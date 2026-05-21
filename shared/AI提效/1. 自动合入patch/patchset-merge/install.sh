#!/bin/bash
# Patchset Merge Skill 一键安装脚本（多平台支持）
# 自动检测 Claude Code / OpenCode / Gemini CLI 并部署到对应路径
# 同时生成 Copilot / Cursor / 通用 Markdown 降级版本到 dist/
set -euo pipefail

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

# --- 生成所有 Tier 2 降级版本（排除已被 Tier 1 处理的平台） ---
echo ""
echo "--- 生成 Tier 2 降级版本 ---"
TIER2_PLATFORMS=(copilot cursor generic)
# 如果 gemini 作为 Tier 1 已处理则跳过，否则补生成
if ! printf '%s\n' "${DETECTED_PLATFORMS[@]}" | grep -qx "gemini"; then
    TIER2_PLATFORMS+=(gemini)
fi
for platform in "${TIER2_PLATFORMS[@]}"; do
    generate_degraded "merge-patchset" "SKILL.md" "$platform"
    generate_degraded "revert-patchset" "revert-patchset-SKILL.md" "$platform"
done

# --- 总结 ---
echo ""
echo "=== 安装完成 ==="
echo ""
echo "已部署的 skill:"
echo "  - merge-patchset  (合入 patchset)"
echo "  - revert-patchset (回退 commit)"
echo "  - karpathy-guidelines (行为准则)"
echo ""
if [ ${#DETECTED_PLATFORMS[@]} -gt 0 ]; then
    echo "支持平台:"
    for platform in "${DETECTED_PLATFORMS[@]}"; do
        echo "  - $platform ✓"
    done
    echo ""
fi
echo "Tier 2 降级版本（手动部署）:"
echo "  - dist/generic/   → 通用 Markdown"
echo "  - dist/copilot/   → GitHub Copilot (.github/copilot-instructions.md)"
echo "  - dist/cursor/    → Cursor (.cursorrules)"
echo "  - dist/gemini/    → Gemini CLI"
echo ""
echo "使用方式:"
echo "  Claude Code: /merge-patchset <patch_dir>    /revert-patchset <commit>"
echo "  OpenCode:    直接描述需求，skill 自动加载"
echo "  Copilot:     将 dist/copilot/*.md 内容复制到 .github/copilot-instructions.md"
echo "  Cursor:      将 dist/cursor/*.md 内容复制到 .cursorrules"
echo ""
echo "如需更新 skill，重新运行此脚本即可。"
