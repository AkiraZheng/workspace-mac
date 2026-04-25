#!/bin/bash
#==============================================================================
# OpenEuler Kernel Build Script
#==============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

KERNEL_SOURCE_DIR="/root/openeuler_code/kernel"
BUILD_MODE="native"

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

show_help() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --help            Show this help"
    echo "  --dir DIR         Kernel source directory (default: $KERNEL_SOURCE_DIR)"
    echo "  --mode MODE       Build mode: 'native' or 'stage2' (default: native)"
    echo ""
    echo "  stage2 mode will add CONFIG_PTDUMP_STAGE2_DEBUGFS=y to existing .config"
}

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --help)
            show_help
            exit 0
            ;;
        --dir)
            KERNEL_SOURCE_DIR="$2"
            shift 2
            ;;
        --mode)
            BUILD_MODE="$2"
            if [[ "$BUILD_MODE" != "native" && "$BUILD_MODE" != "stage2" ]]; then
                log_error "Invalid mode: $BUILD_MODE (must be 'native' or 'stage2')"
                exit 1
            fi
            shift 2
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

echo "============================================"
echo "  Kernel Build Script"
echo "  Mode: $BUILD_MODE"
echo "============================================"
echo ""

# 切换到源码目录
if [[ -n "$KERNEL_SOURCE_DIR" && -d "$KERNEL_SOURCE_DIR" ]]; then
    if [[ "$PWD" != "$KERNEL_SOURCE_DIR" ]]; then
        log_info "Switching to: $KERNEL_SOURCE_DIR"
        cd "$KERNEL_SOURCE_DIR"
    fi
fi

# 检查或生成 .config
if [[ ! -f .config ]]; then
    log_info ".config not found, generating from /boot/config-$(uname -r)..."

    CONFIG_FILE="/boot/config-$(uname -r)"
    if [[ ! -f "$CONFIG_FILE" ]]; then
        CONFIG_FILE=$(ls -1 /boot/config-* 2>/dev/null | head -1)
        log_warn "Using: $CONFIG_FILE"
    fi

    if [[ -f "$CONFIG_FILE" ]]; then
        cp "$CONFIG_FILE" .config
    else
        log_warn "No config in /boot, using defconfig"
        make defconfig
    fi

    # 启用虚拟化
    scripts/config --enable CONFIG_VIRTUALIZATION
    scripts/config --enable CONFIG_KVM
    make olddefconfig
    log_info ".config generated"
else
    log_info ".config exists, checking mode..."

    # stage2 模式：追加配置
    if [[ "$BUILD_MODE" == "stage2" ]]; then
        log_info "Adding stage2 debug config..."

        # 追加配置项（避免重复）
        if ! grep -q "^CONFIG_PTDUMP_STAGE2_DEBUGFS=y" .config 2>/dev/null; then
            cat >> .config << EOF

# Added by build_kernel.sh (stage2 mode)
CONFIG_PTDUMP_CORE=y
CONFIG_PTDUMP_DEBUGFS=y
CONFIG_PTDUMP_STAGE2_DEBUGFS=y
CONFIG_DEBUG_FS=y
CONFIG_DEBUG_KERNEL=y
CONFIG_KVM=y
CONFIG_VIRTUALIZATION=y
EOF
            log_info "Stage2 config appended"
        else
            log_info "Stage2 config already present"
        fi
    fi
fi

echo ""

# 编译内核
log_info "=== Building kernel ==="
make -j$(nproc) Image

if [[ ! -f arch/arm64/boot/Image ]]; then
    log_error "Kernel build failed!"
    exit 1
fi
log_info "Built: arch/arm64/boot/Image"
ls -lh arch/arm64/boot/Image
echo ""

# 编译安装模块
log_info "=== Building modules ==="
make -j$(nproc) modules
echo ""

log_info "=== Installing modules ==="
make modules_install
echo ""

# 安装内核
log_info "=== Installing kernel ==="
make install
echo ""

# 更新 grub
log_info "=== Updating grub ==="
grub2-mkconfig -o /boot/grub2/grub.cfg

if [[ -f /boot/efi/EFI/openeuler/grub.cfg ]]; then
    grub2-mkconfig -o /boot/efi/EFI/openeuler/grub.cfg
fi
echo ""

log_info "=== Done ==="
echo "Reboot and select new kernel from grub."
