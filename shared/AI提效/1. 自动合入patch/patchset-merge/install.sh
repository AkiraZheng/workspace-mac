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

# --- 拉取 karpathy-guidelines（只拉一次，各平台共享） ---
KARPATHY_SRC=""
KARPATHY_REMOTE="${KARPATHY_GUIDELINES_REPO:-https://raw.githubusercontent.com/multica-ai/andrej-karpathy-skills/main/SKILL.md}"
if command -v curl &>/dev/null; then
    echo "[→] 尝试从 GitHub 拉取 karpathy-guidelines..."
    KARPATHY_TMP="$(mktemp)"
    if curl -fsSL --connect-timeout 5 --max-time 10 "$KARPATHY_REMOTE" -o "$KARPATHY_TMP" 2>/dev/null; then
        if grep -q "karpathy-guidelines" "$KARPATHY_TMP" 2>/dev/null; then
            KARPATHY_SRC="$KARPATHY_TMP"
            echo "[✓] karpathy-guidelines (远程拉取成功)"
        else
            rm -f "$KARPATHY_TMP"
        fi
    else
        rm -f "$KARPATHY_TMP"
    fi
fi
if [ -z "$KARPATHY_SRC" ]; then
    KARPATHY_SRC="$SCRIPT_DIR/karpathy-guidelines-SKILL.md"
    echo "[✓] karpathy-guidelines (使用本地副本)"
fi

# --- 平台前置检查 ---
check_platform() {
    local platform=$1
    case "$platform" in
        claude)
            if [ -d "$HOME/.claude/plugins/cache/claude-plugins-official/superpowers" ]; then
                echo "  [✓] superpowers 插件已安装"
                return 0
            else
                echo "  [!] superpowers 插件未安装，请执行:"
                echo "      claude plugins install superpowers@claude-plugins-official"
                return 1
            fi
            ;;
        opencode)
            if [ -d "$HOME/.config/opencode/skills/using-superpowers" ]; then
                echo "  [✓] superpowers skills 已安装"
                return 0
            else
                echo "  [!] superpowers skills 未安装，请执行:"
                echo "      opencode plugins install superpowers@claude-plugins-official"
                return 1
            fi
            ;;
    esac
}

# --- 部署 ---
for platform in "${DETECTED_PLATFORMS[@]}"; do
    echo ""
    echo "--- 部署到 $platform ---"
    check_platform "$platform" || true
    case "$platform" in
        claude)
            deploy_skill "merge-patchset" "SKILL.md" "$HOME/.claude/skills/merge-patchset"
            mkdir -p "$HOME/.claude/skills/karpathy-guidelines"
            cp "$KARPATHY_SRC" "$HOME/.claude/skills/karpathy-guidelines/SKILL.md"
            echo "  [✓] karpathy-guidelines → $HOME/.claude/skills/karpathy-guidelines/SKILL.md"
            ;;
        opencode)
            deploy_skill "merge-patchset" "SKILL.md" "$HOME/.config/opencode/skills/merge-patchset"
            mkdir -p "$HOME/.config/opencode/skills/karpathy-guidelines"
            cp "$KARPATHY_SRC" "$HOME/.config/opencode/skills/karpathy-guidelines/SKILL.md"
            echo "  [✓] karpathy-guidelines → $HOME/.config/opencode/skills/karpathy-guidelines/SKILL.md"
            echo "  [✓] OpenCode 自动发现 skill，在 opencode.json 中可通过 permission.skill 控制"
            ;;
    esac
done

# --- 清理临时文件 ---
[ -n "${KARPATHY_TMP:-}" ] && rm -f "$KARPATHY_TMP"

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
