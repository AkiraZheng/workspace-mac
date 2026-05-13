#!/bin/bash
# install-deps.sh - 安装openEuler所需依赖包

echo "检查并安装QEMU虚拟机启动所需依赖..."

PKGS="qemu-system-aarch64 edk2-aarch64 xorriso sshpass openssl"

for pkg in $PKGS; do
    if rpm -qa | grep -q "^${pkg}"; then
        echo "✓ $pkg 已安装"
    else
        echo "安装 $pkg..."
        yum install -y $pkg
    fi
done

echo ""
echo "检查nbd模块..."
if modprobe nbd max_part=8 2>/dev/null; then
    echo "✓ nbd模块已加载"
else
    echo "⚠ nbd模块无法加载，请检查内核配置"
fi

echo ""
echo "依赖安装完成！"
echo ""
echo "运行环境检查:"
echo "  ./scripts/check-kvm.sh"