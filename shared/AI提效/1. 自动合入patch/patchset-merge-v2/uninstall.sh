#!/bin/bash
# patchset-merge-v2 一键卸载脚本

echo "=== Patchset-Merge v2 分层架构卸载脚本 ==="

# 步骤 1: 确认卸载
echo "警告：此操作将删除以下内容："
echo "  - $HOME/.agents/skills/patchset-merge-v2"
echo "  - $HOME/.claude/skills/patchset-merge-v2 (symlink)"
echo "  - $HOME/.config/opencode/skills/patchset-merge-v2 (symlink)"
echo "  - Python venv 环境"
echo ""
read -p "确认卸载？[y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "取消卸载"
    exit 0
fi

# 步骤 2: 定义路径
SKILL_DIR="$HOME/.agents/skills/patchset-merge-v2"
CLAUDE_SKILL_DIR="$HOME/.claude/skills"
OPENCODE_SKILL_DIR="$HOME/.config/opencode/skills"
VENV_DIR="$SKILL_DIR/.venv"

# 步骤 3: 删除 Skill 目录
echo "删除 Skill 目录..."
if [ -d "$SKILL_DIR" ]; then
    rm -rf "$SKILL_DIR"
    echo "  ✅ 已删除: $SKILL_DIR"
else
    echo "  ⚠️ Skill 目录不存在，跳过"
fi

# 步骤 4: 删除 Python venv
echo "删除 Python venv..."
if [ -d "$VENV_DIR" ]; then
    rm -rf "$VENV_DIR"
    echo "  ✅ 已删除: $VENV_DIR"
else
    echo "  ⚠️ venv 不存在，跳过"
fi

# 步骤 5: 删除 symlink
echo "删除 symlink..."

if [ -L "$CLAUDE_SKILL_DIR/patchset-merge-v2" ]; then
    rm -f "$CLAUDE_SKILL_DIR/patchset-merge-v2"
    echo "  ✅ 已删除: $CLAUDE_SKILL_DIR/patchset-merge-v2"
elif [ -d "$CLAUDE_SKILL_DIR/patchset-merge-v2" ]; then
    rm -rf "$CLAUDE_SKILL_DIR/patchset-merge-v2"
    echo "  ✅ 已删除: $CLAUDE_SKILL_DIR/patchset-merge-v2"
else
    echo "  ⚠️ Claude symlink 不存在，跳过"
fi

if [ -L "$OPENCODE_SKILL_DIR/patchset-merge-v2" ]; then
    rm -f "$OPENCODE_SKILL_DIR/patchset-merge-v2"
    echo "  ✅ 已删除: $OPENCODE_SKILL_DIR/patchset-merge-v2"
elif [ -d "$OPENCODE_SKILL_DIR/patchset-merge-v2" ]; then
    rm -rf "$OPENCODE_SKILL_DIR/patchset-merge-v2"
    echo "  ✅ 已删除: $OPENCODE_SKILL_DIR/patchset-merge-v2"
else
    echo "  ⚠️ OpenCode symlink 不存在，跳过"
fi

# 步骤 6: 清理空目录
echo "清理空目录..."
[ -d "$CLAUDE_SKILL_DIR" ] && [ -z "$(ls -A $CLAUDE_SKILL_DIR 2>/dev/null)" ] && rm -rf "$CLAUDE_SKILL_DIR" && echo "  ✅ 已删除空目录: $CLAUDE_SKILL_DIR"
[ -d "$OPENCODE_SKILL_DIR" ] && [ -z "$(ls -A $OPENCODE_SKILL_DIR 2>/dev/null)" ] && rm -rf "$OPENCODE_SKILL_DIR" && echo "  ✅ 已删除空目录: $OPENCODE_SKILL_DIR"

# 步骤 7: 验证卸载
echo "验证卸载..."
if [ -d "$SKILL_DIR" ]; then
    echo "  ❌ 卸载失败：Skill 目录仍然存在"
    exit 1
else
    echo "  ✅ 卸载成功：Skill 目录已删除"
fi

echo "
═══════════════════════════════════════════════════════════════
  ✅ Patchset-Merge v2 已完全卸载
═══════════════════════════════════════════════════════════════

删除内容：
  - Skill 目录及其所有文件
  - Python venv 环境（包含 b4）
  - Claude Code symlink
  - OpenCode symlink

如需重新安装，运行：
  cd /mnt/shared/shared/AI提效/1. 自动合入patch/patchset-merge-v2
  bash install.sh
"