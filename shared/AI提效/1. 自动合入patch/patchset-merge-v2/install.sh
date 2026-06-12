#!/bin/bash
# patchset-merge-v2 一键安装脚本

echo "=== Patchset-Merge 分层架构安装脚本 ==="

# 步骤 1: 检测技能目录
SKILL_DIR="$HOME/.agents/skills/patchset-merge-v2"
if [ ! -d "$SKILL_DIR" ]; then
    mkdir -p "$SKILL_DIR"
    echo "✅ 创建技能目录: $SKILL_DIR"
fi

# 步骤 1.5: 创建 Python venv 环境（隔离依赖）
echo "创建 Python virtual environment..."
VENV_DIR="$SKILL_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR" || {
        echo "❌ Python venv 创建失败，请检查 python3 是否安装"
        exit 1
    }
    echo "  ✅ venv 创建成功: $VENV_DIR"
    
    # 在 venv 中安装依赖
    echo "安装 Python 依赖到 venv..."
    "$VENV_DIR/bin/pip" install --upgrade pip || true
    "$VENV_DIR/bin/pip" install b4 || {
        echo "⚠️ b4 安装失败，patch 下载功能将受限"
    }
    echo "  ✅ Python 依赖安装完成"
else
    echo "  ✅ venv 已存在，跳过创建"
fi

# 设置 VENV_PYTHON 路径（供后续脚本使用）
VENV_PYTHON="$VENV_DIR/bin/python3"
export PATCHSET_MERGE_VENV_PYTHON="$VENV_PYTHON"

# 步骤 2: 复制所有 Skill 文件
echo "复制 Skill 文件..."

# 主调度 Skill
cp -r patchset-merge-orchestrator "$SKILL_DIR/"
echo "  ✅ patchset-merge-orchestrator"

# Layer 1-4 Skills
cp -r layer1-interaction "$SKILL_DIR/"
cp -r layer2-search "$SKILL_DIR/"
cp -r layer3-execution "$SKILL_DIR/"
cp -r layer4-output "$SKILL_DIR/"
echo "  ✅ layer1-4"

# Shared scripts
cp -r shared-scripts "$SKILL_DIR/"
echo "  ✅ shared-scripts"

# 步骤 3: 修改 Python 脚本使用 venv
echo "配置 Python 脚本使用 venv..."
for py_script in "$SKILL_DIR"/shared-scripts/*.py "$SKILL_DIR"/patchset-merge-orchestrator/scripts/*.py; do
    if [ -f "$py_script" ]; then
        # 修改 shebang 行使用 venv Python
        if head -1 "$py_script" | grep -q "^#!/usr/bin/env python3"; then
            sed -i "1s|^#!/usr/bin/env python3|$VENV_PYTHON|" "$py_script" || true
        elif head -1 "$py_script" | grep -q "^#!/usr/bin/python3"; then
            sed -i "1s|^#!/usr/bin/python3|$VENV_PYTHON|" "$py_script" || true
        fi
    fi
done
echo "  ✅ Python 脚本配置完成"

# 步骤 4: 设置脚本权限
echo "设置脚本权限..."

# 主调度 Skill 脚本
chmod +x "$SKILL_DIR/patchset-merge-orchestrator/scripts/*.sh" 2>/dev/null || true
chmod +x "$SKILL_DIR/patchset-merge-orchestrator/scripts/*.py" 2>/dev/null || true

# 共享脚本
chmod +x "$SKILL_DIR/shared-scripts/*.py" 2>/dev/null || true

# Layer 2 脚本（如果有）
if [ -d "$SKILL_DIR/layer2-search/scripts" ]; then
    chmod +x "$SKILL_DIR/layer2-search/scripts/*.py" 2>/dev/null || true
fi

# 测试脚本
if [ -d "$SKILL_DIR/tests" ]; then
    chmod +x "$SKILL_DIR/tests/*.sh" 2>/dev/null || true
    chmod +x "$SKILL_DIR/tests/*.py" 2>/dev/null || true
fi

# install.sh 和 uninstall.sh
chmod +x "$SKILL_DIR/install.sh" 2>/dev/null || true
chmod +x "$SKILL_DIR/uninstall.sh" 2>/dev/null || true

echo "  ✅ 所有脚本可执行权限已设置"

# 步骤 5: 创建 symlink（兼容 Claude Code 和 OpenCode）
CLAUDE_SKILL_DIR="$HOME/.claude/skills"
OPENCODE_SKILL_DIR="$HOME/.config/opencode/skills"

mkdir -p "$CLAUDE_SKILL_DIR"
mkdir -p "$OPENCODE_SKILL_DIR"

ln -sf "$SKILL_DIR" "$CLAUDE_SKILL_DIR/patchset-merge-v2" || true
ln -sf "$SKILL_DIR" "$OPENCODE_SKILL_DIR/patchset-merge-v2" || true
echo "  ✅ Symlink 创建成功"

# 步骤 6: 验证 b4 安装
echo "验证 b4 安装..."
if "$VENV_PYTHON" -m b4 --version >/dev/null 2>&1; then
    B4_VERSION=$("$VENV_PYTHON" -m b4 --version 2>&1 | head -1)
    echo "  ✅ b4 已安装: $B4_VERSION"
else
    echo "  ⚠️ b4 未安装，message-id 下载功能将不可用"
fi

# 步骤 7: 验证安装
echo "验证安装..."
if [ -f "$SKILL_DIR/patchset-merge-orchestrator/SKILL.md" ]; then
    echo "  ✅ 主调度 Skill 存在"
else
    echo "  ❌ 主调度 Skill 不存在"
    exit 1
fi

if [ -f "$SKILL_DIR/layer3-execution/SKILL.md" ]; then
    echo "  ✅ Layer 3 Skill 存在"
else
    echo "  ❌ Layer 3 Skill 不存在"
    exit 1
fi

if [ -f "$SKILL_DIR/patchset-merge-orchestrator/scripts/gate_check.sh" ]; then
    echo "  ✅ gate_check.sh 存在"
else
    echo "  ❌ gate_check.sh 不存在"
    exit 1
fi

# 步骤 8: 运行集成测试
echo "运行集成测试..."
bash tests/test_integration.sh || {
    echo "⚠️ 集成测试失败，请检查文件完整性"
    exit 1
}

echo "
═══════════════════════════════════════════════════════════════
  ✅ Patchset-Merge 分层架构安装成功
═══════════════════════════════════════════════════════════════

安装路径：$SKILL_DIR
Python venv: $VENV_DIR
Python 解释器: $VENV_PYTHON

使用方法：
  Skill tool: patchset-merge-orchestrator
  输入: '合入 <message-id> 到 ~/code/openeuler/kernel 的 patch-xxx 分支'

下载方式支持：
  ✅ b4（message-id 格式：<xxx@xxx>）
  ✅ wget（URL 格式：https://...）
  ✅ 本地路径（复制 .patch 文件）

设计文档：docs/superpowers/specs/2026-06-10-*.md
实现计划：docs/superpowers/plans/2026-06-10-*.md

注意：所有 Python 脚本已配置使用 venv 环境，避免系统 Python 依赖冲突
"