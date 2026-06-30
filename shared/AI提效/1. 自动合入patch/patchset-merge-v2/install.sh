#!/bin/bash
# patchset-merge-v2 一键安装脚本

echo "=== Patchset-Merge 分层架构安装脚本 ==="

ask_yn() {
    # $1 = prompt, $2 = timeout seconds (default 5)
    local ans timeout=${2:-5}
    read -r -t "$timeout" -p "$1 [y/N](${timeout}s 超时自动跳过): " ans
    case "$ans" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *)                 return 1 ;;
    esac
}

# 步骤 1: 检测技能目录
SKILL_DIR="$HOME/.agents/skills/patchset-merge-v2"
if [ ! -d "$SKILL_DIR" ]; then
    mkdir -p "$SKILL_DIR"
    echo "✅ 创建技能目录: $SKILL_DIR"
fi

# 步骤 1.5: 创建 Python venv 环境
echo "创建 Python virtual environment..."
VENV_DIR="$SKILL_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR" || {
        echo "❌ Python venv 创建失败，请检查 python3 是否安装"
        exit 1
    }
    echo "  ✅ venv 创建成功: $VENV_DIR"

    # b4 为可选加速工具（message-id 下载），不安装不影响核心流程
    echo ""
    if command -v b4 &>/dev/null; then
        echo "  ✅ b4 已存在（系统安装），跳过 pip 安装"
    elif [ -f "$VENV_DIR/bin/b4" ]; then
        echo "  ✅ b4 已存在（venv），跳过安装"
    elif ask_yn "  b4 未安装，是否尝试 pip install b4？" 5; then
        echo "  正在 pip install b4 --timeout 10 --retries 1 ..."
        if "$VENV_DIR/bin/pip" install b4 --timeout 10 --retries 1 >/dev/null 2>&1; then
            echo "  ✅ b4 安装成功"
        else
            echo "  ℹ b4 安装失败（网络不可达），message-id 下载将使用 wget 替代"
        fi
    else
        echo "  ℹ 已跳过 b4，message-id 下载自动降级为 wget"
        echo "  手动安装: pip install b4"
    fi
else
    echo "  ✅ venv 已存在，跳过创建"
fi

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

# 步骤 4: 创建 symlink（兼容 Claude Code 和 OpenCode）
CLAUDE_SKILL_DIR="$HOME/.claude/skills"
OPENCODE_SKILL_DIR="$HOME/.config/opencode/skills"

mkdir -p "$CLAUDE_SKILL_DIR"
mkdir -p "$OPENCODE_SKILL_DIR"

ln -sf "$SKILL_DIR" "$CLAUDE_SKILL_DIR/patchset-merge-v2" || true
ln -sf "$SKILL_DIR" "$OPENCODE_SKILL_DIR/patchset-merge-v2" || true
echo "  ✅ Symlink 创建成功"

# 步骤 5: b4 状态报告
if command -v b4 &>/dev/null; then
    echo "  ✅ b4: $(b4 --version 2>&1 | head -1)"
elif [ -f "$SKILL_DIR/.venv/bin/b4" ]; then
    echo "  ✅ b4: $( $SKILL_DIR/.venv/bin/b4 --version 2>&1 | head -1)"
else
    echo "  ℹ b4: 未安装（message-id 下载自动降级为 wget）"
fi

# 步骤 6: 验证安装
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

# 步骤 7: 运行集成测试
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
  ✅ b4（message-id 格式：<xxx@xxx>）— 如未安装，自动降级为 wget
  ✅ wget（URL 格式：https://...）
  ✅ 本地路径（复制 .patch 文件）

设计文档：docs/superpowers/specs/2026-06-10-*.md
实现计划：docs/superpowers/plans/2026-06-10-*.md
"