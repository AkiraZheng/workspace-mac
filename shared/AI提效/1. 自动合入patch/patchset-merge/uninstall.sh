#!/bin/bash
# patchset-merge (v1) 一键卸载脚本

echo "=== Patchset-Merge v1 卸载脚本 ==="

# 步骤 1: 确认卸载
echo "警告：此操作将删除以下内容："
echo "  - $HOME/.agents/skills/merge-patchset"
echo "  - $HOME/.claude/skills/merge-patchset (symlink)"
echo "  - $HOME/.config/opencode/skills/merge-patchset (symlink)"
echo ""
read -p "确认卸载？[y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "取消卸载"
    exit 0
fi

# 步骤 2: 定义路径（注意 v1 的 Skill 名是 merge-patchset）
SKILL_DIR="$HOME/.agents/skills/merge-patchset"
CLAUDE_SKILL_DIR="$HOME/.claude/skills"
OPENCODE_SKILL_DIR="$HOME/.config/opencode/skills"

# 步骤 3: 删除 Skill 目录
echo "删除 Skill 目录..."
if [ -d "$SKILL_DIR" ]; then
    rm -rf "$SKILL_DIR"
    echo "  ✅ 已删除: $SKILL_DIR"
else
    echo "  ⚠️ Skill 目录不存在，跳过"
fi

# 步骤 4: 删除 symlink
echo "删除 symlink..."

if [ -L "$CLAUDE_SKILL_DIR/merge-patchset" ]; then
    rm -f "$CLAUDE_SKILL_DIR/merge-patchset"
    echo "  ✅ 已删除: $CLAUDE_SKILL_DIR/merge-patchset"
elif [ -d "$CLAUDE_SKILL_DIR/merge-patchset" ]; then
    rm -rf "$CLAUDE_SKILL_DIR/merge-patchset"
    echo "  ✅ 已删除: $CLAUDE_SKILL_DIR/merge-patchset"
else
    echo "  ⚠️ Claude symlink 不存在，跳过"
fi

if [ -L "$OPENCODE_SKILL_DIR/merge-patchset" ]; then
    rm -f "$OPENCODE_SKILL_DIR/merge-patchset"
    echo "  ✅ 已删除: $OPENCODE_SKILL_DIR/merge-patchset"
elif [ -d "$OPENCODE_SKILL_DIR/merge-patchset" ]; then
    rm -rf "$OPENCODE_SKILL_DIR/merge-patchset"
    echo "  ✅ 已删除: $OPENCODE_SKILL_DIR/merge-patchset"
else
    echo "  ⚠️ OpenCode symlink 不存在，跳过"
fi

# 步骤 5: 清理空目录
echo "清理空目录..."
[ -d "$HOME/.agents/skills" ] && [ -z "$(ls -A $HOME/.agents/skills 2>/dev/null)" ] && rm -rf "$HOME/.agents/skills" && echo "  ✅ 已删除空目录: $HOME/.agents/skills"
[ -d "$CLAUDE_SKILL_DIR" ] && [ -z "$(ls -A $CLAUDE_SKILL_DIR 2>/dev/null)" ] && rm -rf "$CLAUDE_SKILL_DIR" && echo "  ✅ 已删除空目录: $CLAUDE_SKILL_DIR"
[ -d "$OPENCODE_SKILL_DIR" ] && [ -z "$(ls -A $OPENCODE_SKILL_DIR 2>/dev/null)" ] && rm -rf "$OPENCODE_SKILL_DIR" && echo "  ✅ 已删除空目录: $OPENCODE_SKILL_DIR"

# 步骤 6: 验证卸载
echo "验证卸载..."
if [ -d "$SKILL_DIR" ]; then
    echo "  ❌ 卸载失败：Skill 目录仍然存在"
    exit 1
else
    echo "  ✅ 卸载成功：Skill 目录已删除"
fi

# 步骤 7: 检查 patch_analysis 目录（用户数据）
echo "检查残留数据..."
KERNEL_REPO="${KERNEL_REPO_PATH:-}"
if [ -n "$KERNEL_REPO" ] && [ -d "$KERNEL_REPO/patch_analysis" ]; then
    echo "  ⚠️ 发现残留数据: $KERNEL_REPO/patch_analysis"
    echo "     此目录包含 patch 分析结果，可能需要保留"
    echo "     如需删除，请手动执行: rm -rf $KERNEL_REPO/patch_analysis"
fi

echo "
═══════════════════════════════════════════════════════════════
  ✅ Patchset-Merge v1 已完全卸载
═══════════════════════════════════════════════════════════════

删除内容：
  - Skill 目录及其所有文件
  - Claude Code symlink
  - OpenCode symlink

注意：
  - patch_analysis 目录（包含分析结果）未删除
  - 如需删除分析结果，请手动执行

如需重新安装，运行：
  cd /mnt/shared/shared/AI提效/1. 自动合入patch/patchset-merge
  bash install.sh
"