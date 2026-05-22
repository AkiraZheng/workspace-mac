#!/bin/bash
# install.sh — 一键安装 merge-patchset skill
# 从工作区同步到部署目录，自动检测并尝试安装缺失工具
# 用法: bash install.sh

set -o pipefail

WORKSPACE="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="/root/.agents/skills/merge-patchset"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}[OK]${NC} $1"; }
warn() { echo -e "  ${YELLOW}[!!]${NC} $1"; }
info() { echo -e "  ${CYAN}[..]${NC} $1"; }
err()  { echo -e "  ${RED}[XX]${NC} $1"; }

ask_yn() {
    # $1 = prompt
    local ans
    read -r -p "$1 [y/N]: " ans
    case "$ans" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *)                 return 1 ;;
    esac
}

detect_pkg_manager() {
    if command -v dnf &>/dev/null; then
        echo "dnf"
    elif command -v yum &>/dev/null; then
        echo "yum"
    elif command -v apt-get &>/dev/null; then
        echo "apt-get"
    elif command -v pacman &>/dev/null; then
        echo "pacman"
    else
        echo ""
    fi
}

try_install_pkg() {
    # $1 = tool name (for display)
    # $2 = pkg name  (for package manager)
    # $3 = pip name  (fallback, optional)
    local tool="$1" pkg="$2" pip_name="${3:-}"
    local pkg_mgr=$(detect_pkg_manager)

    if [ -n "$pkg_mgr" ]; then
        case "$pkg_mgr" in
            dnf|yum)     sudo "$pkg_mgr" install -y "$pkg" 2>/dev/null && return 0 ;;
            apt-get)     sudo apt-get install -y "$pkg" 2>/dev/null && return 0 ;;
            pacman)      sudo pacman -S --noconfirm "$pkg" 2>/dev/null && return 0 ;;
        esac
    fi

    if [ -n "$pip_name" ] && command -v pip3 &>/dev/null; then
        pip3 install "$pip_name" 2>/dev/null && return 0
    elif [ -n "$pip_name" ] && command -v pip &>/dev/null; then
        pip install "$pip_name" 2>/dev/null && return 0
    fi

    return 1
}

try_install_pip() {
    # $1 = tool name (display)
    # $2 = pip package name
    local tool="$1" pip_name="$2"
    if command -v pip3 &>/dev/null; then
        pip3 install "$pip_name" 2>/dev/null && return 0
    elif command -v pip &>/dev/null; then
        pip install "$pip_name" 2>/dev/null && return 0
    fi
    return 1
}

install_tool() {
    # $1 = tool display name
    # $2 = package name (for system pkg mgr)
    # $3 = pip name (optional)
    # $4 = level: "critical" or "optional"
    local tool="$1" pkg="$2" pip_name="${3:-}" level="${4:-optional}"

    if command -v "$tool" &>/dev/null; then
        ok "$tool 已就绪"
        return 0
    fi

    warn "$tool 未安装"

    if ! ask_yn "  是否尝试自动安装 $tool ?"; then
        if [ "$level" = "critical" ]; then
            err "$tool 是必需工具，无法跳过。请手动安装后重试。"
            return 1
        else
            warn "已跳过 $tool，skill 功能可能受限。"
            return 0
        fi
    fi

    info "正在安装 $tool ..."

    # 策略: 优先系统包管理器，其次 pip
    if try_install_pkg "$tool" "$pkg" "$pip_name"; then
        if command -v "$tool" &>/dev/null; then
            ok "$tool 安装成功"
            return 0
        fi
    fi

    # 如果 pkg 安装失败但提供了 pip_name，单独尝试 pip
    if [ -n "$pip_name" ] && [ "$pkg" != "$pip_name" ]; then
        if try_install_pip "$tool" "$pip_name"; then
            if command -v "$tool" &>/dev/null; then
                ok "$tool 安装成功 (via pip)"
                return 0
            fi
        fi
    fi

    warn "$tool 安装失败"
    if [ "$level" = "critical" ]; then
        err "$tool 是必需工具，请手动安装后重试。"
        return 1
    else
        warn "已跳过 $tool，skill 部分功能可能不可用。"
        return 0
    fi
}

# ==================================================================
echo "============================================"
echo "  merge-patchset skill 一键安装"
echo "============================================"
echo ""

# ==================================================================
# Step 1: 检测并尝试安装依赖工具
# ==================================================================
echo "[1/5] 检测并安装依赖工具..."
echo ""

CRITICAL_FAIL=0

# 关键工具: 缺失且安装失败则中止
install_tool "python3"  "python3" "python"    "critical" || CRITICAL_FAIL=1
install_tool "git"      "git"     ""           "critical" || CRITICAL_FAIL=1

# 推荐工具: 缺失可跳过
install_tool "b4"       "b4"      "b4"         "optional"
install_tool "wget"     "wget"    ""           "optional"
install_tool "make"     "make"    ""           "optional"
install_tool "pytest"   "pytest"  "pytest"     "optional"

echo ""
if [ "$CRITICAL_FAIL" -eq 1 ]; then
    err "关键工具缺失且安装失败，无法继续。"
    exit 1
fi

# 显示版本信息
echo "  当前工具版本:"
command -v python3 &>/dev/null && echo "    python3: $(python3 --version 2>&1)"
command -v git     &>/dev/null && echo "    git:     $(git --version 2>&1 | head -1)"
command -v b4      &>/dev/null && echo "    b4:      $(b4 --version 2>/dev/null | head -1 || echo '已安装')"
command -v wget    &>/dev/null && echo "    wget:    已安装"
command -v make    &>/dev/null && echo "    make:    $(make --version 2>&1 | head -1)"
command -v pytest  &>/dev/null && echo "    pytest:  $(pytest --version 2>&1)"

echo ""

# ==================================================================
# Step 2: 校验工作区文件
# ==================================================================
echo "[2/5] 校验工作区文件..."

REQUIRED_FILES=(
    "$WORKSPACE/SKILL.md"
    "$WORKSPACE/scripts/download_patches.py"
    "$WORKSPACE/scripts/generate_diff_report.py"
    "$WORKSPACE/references/diagnostic-guide.md"
    "$WORKSPACE/references/output-templates.md"
    "$WORKSPACE/references/code-review-expert/SKILL.md"
)

ALL_OK=true
for f in "${REQUIRED_FILES[@]}"; do
    if [ -f "$f" ]; then
        ok "$f"
    else
        err "缺失: $f"
        ALL_OK=false
    fi
done

if [ "$ALL_OK" = false ]; then
    echo ""
    err "工作区文件不完整，请先执行实现计划。"
    exit 1
fi
echo ""

# ==================================================================
# Step 3: 运行单元测试
# ==================================================================
echo "[3/5] 运行单元测试..."

if ! command -v pytest &>/dev/null && ! command -v python3 &>/dev/null; then
    warn "pytest 或 python3 不可用，跳过测试。"
else
    cd "$WORKSPACE"
    if python3 -m pytest tests/ -q 2>&1; then
        ok "全部测试通过"
    else
        err "测试失败，请修复后再安装"
        exit 1
    fi
fi
echo ""

# ==================================================================
# Step 4: 安装到部署目录
# ==================================================================
echo "[4/5] 安装到部署目录..."

mkdir -p "$SKILL_DIR/references/code-review-expert"
mkdir -p "$SKILL_DIR/scripts"

cp "$WORKSPACE/SKILL.md" "$SKILL_DIR/SKILL.md"
ok "SKILL.md"

cp "$WORKSPACE/references/diagnostic-guide.md" \
   "$SKILL_DIR/references/diagnostic-guide.md"
cp "$WORKSPACE/references/output-templates.md" \
   "$SKILL_DIR/references/output-templates.md"
cp "$WORKSPACE/references/code-review-expert/SKILL.md" \
   "$SKILL_DIR/references/code-review-expert/SKILL.md"
ok "references/ (3 文件)"

cp "$WORKSPACE/scripts/download_patches.py" \
   "$SKILL_DIR/scripts/download_patches.py"
cp "$WORKSPACE/scripts/generate_diff_report.py" \
   "$SKILL_DIR/scripts/generate_diff_report.py"
ok "scripts/ (2 文件)"

cp "$SKILL_DIR/SKILL.md" "$WORKSPACE/SKILL.md"
ok "双向同步完成"
echo ""

# ==================================================================
# Step 5: 验证部署完整性
# ==================================================================
echo "[5/5] 验证部署..."

echo "  部署清单:"
echo "  ─────────────────────────────────────────"
ls -1 "$SKILL_DIR/"
echo "  ─────────────────────────────────────────"
echo "  references/:"
ls -1 "$SKILL_DIR/references/"
echo "  ─────────────────────────────────────────"
echo "  scripts/:"
ls -1 "$SKILL_DIR/scripts/" 2>/dev/null || echo "  (空)"

# 确认 symlink
for link in /root/.claude/skills/merge-patchset /root/.config/opencode/skills/merge-patchset; do
    if [ -L "$link" ]; then
        echo "  ─────────────────────────────────────────"
        ok "$(basename "$(dirname "$link")"):  $(readlink "$link")"
    fi
done

echo ""
echo "============================================"
echo "  安装完成!"
echo "============================================"
echo ""
echo "  部署位置: $SKILL_DIR"
echo "  SKILL.md: $(wc -l < "$SKILL_DIR/SKILL.md") 行"
echo ""

# 提示缺少的工具
if ! command -v b4 &>/dev/null; then
    warn "b4 不可用 — 无法从 message-id 下载 patchset"
fi
if ! command -v wget &>/dev/null && ! command -v curl &>/dev/null; then
    warn "wget/curl 均不可用 — 无法从 URL 下载 patchset"
fi
if ! command -v make &>/dev/null; then
    warn "make 不可用 — 无法进行内核编译验证"
fi
