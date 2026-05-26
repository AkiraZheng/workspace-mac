#!/bin/bash
# tests/test_detect_build_target.sh — detect_build_target.sh 测试
set -euo pipefail

SCRIPT="$(dirname "$0")/../scripts/detect_build_target.sh"
PASS=0
FAIL=0

check() {
    local desc="$1" expected="$2"
    shift 2
    set +e
    actual=$(bash "$SCRIPT" "$@" 2>/dev/null)
    rc=$?
    set -e
    if [ "$actual" = "$expected" ]; then
        echo "  [OK] $desc → '$actual'"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $desc → expected='$expected' actual='$actual'"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== detect_build_target.sh tests ==="

# 核心文件 → Image
check "核心 arch 文件"       "Image"       --files "arch/arm64/mm/mmu.c"
check "内核 kernel 文件"     "Image"       --files "kernel/sched/core.c"
check "内存管理"             "Image"       --files "mm/memory.c"

# 驱动文件（无 .config 检测时保守策略 → Image）
check "驱动无 .config"       "Image"       --files "drivers/gpu/drm/drm_ioctl.c"

# 带 .config 的驱动检测
REPO=$(mktemp -d)
cat > "$REPO/.config" << 'CONFEOF'
CONFIG_DRM=m
CONFIG_SOUND=m
CONFIG_PHY=m
CONFEOF
check "驱动 CONFIG=m"        "Image modules" --files "drivers/gpu/drm/drm_ioctl.c" --repo-path "$REPO"
check "sound CONFIG=m"       "Image modules" --files "sound/pci/hda/hda_codec.c" --repo-path "$REPO"
check "驱动未匹配 CONFIG=m"  "Image"       --files "drivers/irqchip/irq-gic.c" --repo-path "$REPO"
rm -rf "$REPO"

# 模块目录 → 保守检测
check "内核模块支持代码"     "Image modules" --files "arch/arm64/kernel/module.c"

# 空文件列表 → 报错
set +e
bash "$SCRIPT" 2>/dev/null
rc=$?
set -e
if [ "$rc" -ne 1 ]; then
    echo "  [FAIL] 空参数应返回错误"
    FAIL=$((FAIL + 1))
else
    echo "  [OK] 空参数返回错误"
    PASS=$((PASS + 1))
fi

echo ""
echo "Result: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
