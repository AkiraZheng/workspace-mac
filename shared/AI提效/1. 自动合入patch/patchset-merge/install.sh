#!/bin/bash
# Patchset Merge Skill 一键安装脚本

set -e

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Patchset Merge Skill 安装 ==="
echo "安装目录: $SCRIPT_DIR"

# 1. 检查并安装 b4
if command -v b4 &> /dev/null; then
    echo "[✓] b4 已安装"
else
    echo "[→] 安装 b4..."
    pip install b4
fi

# 2. 安装 Python 包
echo "[→] 安装 patchset_merge 包..."
cd "$SCRIPT_DIR"
pip install -e .

# 3. 复制 Claude Code 命令
echo "[→] 配置 Claude Code 命令..."
mkdir -p ~/.claude/commands
cp "$SCRIPT_DIR/.claude/commands/merge-patchset.md" ~/.claude/commands/

echo ""
echo "=== 安装完成 ==="
echo ""
echo "使用方式："
echo "1. Claude Code 中: /merge-patchset <patch_url> [--source <源码目录>] [--branch <分支名>]"
echo "2. 命令行: python3 -m patchset_merge.skill <patch_url> <源码目录> <分支名>"
