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

# 驱动文件（无 .config 时保守策略 — 需要 modules）
check "驱动无 .config"       "Image modules" --files "drivers/gpu/drm/drm_ioctl.c"

# 带 .config + Makefile 的驱动检测
REPO=$(mktemp -d)
mkdir -p "$REPO/drivers/gpu/drm"
cat > "$REPO/drivers/gpu/drm/Makefile" << 'MKEOF'
obj-$(CONFIG_DRM) += drm.o
obj-$(CONFIG_DRM_KMS_HELPER) += drm_kms_helper.o
obj-y += drm_pci.o
MKEOF

cat > "$REPO/.config" << 'CONFEOF'
CONFIG_DRM=m
CONFIG_SOUND=m
CONFIG_PHY=m
CONFEOF
check "驱动 Makefile CONFIG=m"      "Image modules" --files "drivers/gpu/drm/drm_ioctl.c" --repo-path "$REPO"

# Makefile 有 obj-$(CONFIG_XXX) 但 .config 中不是 m
cat > "$REPO/.config" << 'CONFEOF'
CONFIG_DRM=y
CONFEOF
check "驱动 CONFIG=y 非模块"        "Image"         --files "drivers/gpu/drm/drm_ioctl.c" --repo-path "$REPO"

# 驱动文件 + 所在目录无 Makefile → 保守：需要 modules
mkdir -p "$REPO/drivers/irqchip"
cat > "$REPO/.config" << 'CONFEOF'
CONFIG_ARM_GIC=y
CONFEOF
check "驱动无 Makefile 保守"        "Image modules" --files "drivers/irqchip/irq-gic.c" --repo-path "$REPO"

# 驱动文件 + Makefile 无 obj-$(CONFIG_XXX) → 保守：需要 modules
mkdir -p "$REPO/drivers/base"
echo "obj-y += core.o" > "$REPO/drivers/base/Makefile"
cat > "$REPO/.config" << 'CONFEOF'
CONFEOF
check "驱动 Makefile 无 obj-\$(CONFIG)" "Image modules" --files "drivers/base/core.c" --repo-path "$REPO"

rm -rf "$REPO"

# 带 .config + sound 驱动
REPO2=$(mktemp -d)
mkdir -p "$REPO2/sound/pci/hda"
cat > "$REPO2/sound/pci/hda/Makefile" << 'MKEOF'
obj-$(CONFIG_SND_HDA_INTEL) += snd-hda-intel.o
MKEOF
cat > "$REPO2/.config" << 'CONFEOF'
CONFIG_SND_HDA_INTEL=m
CONFEOF
check "sound Makefile CONFIG=m"     "Image modules" --files "sound/pci/hda/hda_codec.c" --repo-path "$REPO2"
rm -rf "$REPO2"

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
