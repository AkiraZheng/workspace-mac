#!/bin/bash
# patchset-merge-v2 一键安装脚本

echo "=== Patchset-Merge 分层架构安装脚本 ==="

SKILL_DIR="$HOME/.agents/skills/patchset-merge-v2"

# 步骤 1: 创建技能目录
mkdir -p "$SKILL_DIR"
echo "✅ 技能目录: $SKILL_DIR"

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

# Layer 2 agents
mkdir -p "$SKILL_DIR/layer2-search/agents"
cp -r layer2-search/agents/* "$SKILL_DIR/layer2-search/agents/" 2>/dev/null || true
echo "  ✅ layer2-search agents"

# 通用 Skills
cp -r conflict-resolver "$SKILL_DIR/"
echo "  ✅ conflict-resolver"
cp -r linux-kernel-review "$SKILL_DIR/"
echo "  ✅ linux-kernel-review"

# Shared scripts
cp -r shared-scripts "$SKILL_DIR/"
echo "  ✅ shared-scripts"

# 步骤 3: 设置脚本权限
echo "设置脚本权限..."

# 先用 find 确保工作区源文件有 +x（git clone 可能丢失）
find . -type f \( -name "*.sh" -o -name "*.py" \) ! -path "./.venv/*" -exec chmod +x {} \;

# 部署后再用 find 确保目标目录有 +x（不依赖 shell glob 展开）
find "$SKILL_DIR" -type f \( -name "*.sh" -o -name "*.py" \) -exec chmod +x {} \;

echo "  ✅ 所有脚本可执行权限已设置"

# 步骤 4: 创建 symlink（兼容 Claude Code 和 OpenCode）
CLAUDE_SKILL_DIR="$HOME/.claude/skills"
OPENCODE_SKILL_DIR="$HOME/.config/opencode/skills"

mkdir -p "$CLAUDE_SKILL_DIR" "$OPENCODE_SKILL_DIR"

ln -sf "$SKILL_DIR" "$CLAUDE_SKILL_DIR/patchset-merge-v2" || true
ln -sf "$SKILL_DIR" "$OPENCODE_SKILL_DIR/patchset-merge-v2" || true
echo "  ✅ Symlink 创建成功"

# 步骤 5: 验证安装
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

# 步骤 6: 运行集成测试
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

使用方法：
  Skill tool: patchset-merge-orchestrator
  输入: '合入 <message-id> 到 ~/code/openeuler/kernel 的 patch-xxx 分支'

下载方式支持：
  ✅ b4（message-id 格式：<xxx@xxx>）— 可选: pip install b4
  ✅ wget（URL 格式：https://...）
  ✅ 本地路径（复制 .patch 文件）
"
