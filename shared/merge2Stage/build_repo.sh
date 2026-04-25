#!/bin/bash
set -e

KERNEL_DIR="/root/openeuler/kernel"
BOOT_CONFIG="/boot/config-$(uname -r)"
CONFIG_BACKUP="../cpConfig"

FULL_RUN=false
STAGE2=false

usage() {
    echo "Usage: $0 [-f|--full] [-s|--stage2]"
    echo "  -f, --full    Run full setup (copy config, disable certs, etc.)"
    echo "  -s, --stage2  Build stage2 kernel with CONFIG_PTDUMP_STAGE2_DEBUGFS=y"
    echo "  (default)     Skip setup, start directly from make"
    exit 1
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -f|--full)
            FULL_RUN=true
            shift
            ;;
        -s|--stage2)
            STAGE2=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

cd "$KERNEL_DIR"

if [ "$FULL_RUN" = true ]; then
    echo "=== 0. Make mrproper ==="
    make mrproper

    echo "=== 1. Copy original config ==="
    mkdir -p "$CONFIG_BACKUP"
    cp -v "$BOOT_CONFIG" "$CONFIG_BACKUP/"

    echo "=== 2. Install dependencies ==="
    yum install -y ncurses-devel elfutils-libelf-devel openssl-devel bc flex bison

    echo "=== 3. Copy config to kernel source ==="
    if [ ! -f .config ] || ! grep -q "CONFIG_" .config; then
        cp -v "$BOOT_CONFIG" .config
    fi

    echo "=== 4. Generate .config (make oldconfig) ==="
    if [ -f .config ] && grep -q "CONFIG_" .config; then
        echo ".config already exists, skipping make oldconfig"
    else
        yes "" | make oldconfig
    fi

    echo "=== 5. Disable certificates and BTF ==="
    # Disable certificate verification and BTF
    echo '
CONFIG_SYSTEM_TRUSTED_KEYRING=n
CONFIG_SYSTEM_TRUSTED_KEYS=""
CONFIG_SYSTEM_REVOCATION_KEYS=""
CONFIG_SYSTEM_REVOCATION_LIST=n
CONFIG_MODULE_SIG=n
CONFIG_MODULE_SIG_KEY_TYPE_RSA=n
CONFIG_TRUSTED_KEYS=n
CONFIG_TRUSTED_KEYS_TPM=n
CONFIG_INTEGRITY_TRUSTED_KEYRING=n
CONFIG_SECONDARY_TRUSTED_KEYRING=n
CONFIG_DEBUG_INFO_BTF=n
CONFIG_SYSTEM_EXTRA_CERTIFICATE=n
' >> .config

    if [ "$STAGE2" = true ]; then
        echo "=== Enable stage2 ptdump debugfs ==="
        echo "CONFIG_PTDUMP_STAGE2_DEBUGFS=y" >> .config
    fi

    make olddefconfig
else
    if [ ! -f .config ] || ! grep -q "CONFIG_" .config; then
        echo "Error: .config not found or invalid. Please run with --full first."
        exit 1
    fi

    echo "=== Skip setup, starting from make ==="

    if [ "$STAGE2" = true ]; then
        echo "=== Enable stage2 ptdump debugfs ==="
        if ! grep -q "CONFIG_PTDUMP_STAGE2_DEBUGFS=y" .config; then
            echo "CONFIG_PTDUMP_STAGE2_DEBUGFS=y" >> .config
        else
            echo "CONFIG_PTDUMP_STAGE2_DEBUGFS already set"
        fi
    fi
fi

echo "=== 6. Compile kernel ==="
if [ "$STAGE2" = true ]; then
    echo "Building stage2 kernel with CONFIG_PTDUMP_STAGE2_DEBUGFS=y"
fi
make -j$(nproc)

echo "=== 7. Install modules and kernel ==="
make modules_install
make install

echo "=== 8. Update grub ==="
grub2-mkconfig -o /boot/grub2/grub.cfg

echo "=== Done! Reboot to use new kernel ==="
