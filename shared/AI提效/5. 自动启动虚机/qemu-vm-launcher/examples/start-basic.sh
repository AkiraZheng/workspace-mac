#!/bin/bash
# start-basic.sh - 基础启动示例（支持UEFI和直接内核两种模式）

set -e

IMAGE=""
KERNEL=""
INITRD=""
SSH_PORT=2222

for f in *.qcow2 *.img; do
    if [ -f "$f" ]; then
        IMAGE="$f"
        break
    fi
done

if [ -z "$IMAGE" ]; then
    echo "错误: 未找到镜像文件"
    echo "请先下载镜像或构建minifs"
    exit 1
fi

ACCEL="tcg"
if [ -e /dev/kvm ] && [ -w /dev/kvm ]; then
    ACCEL="kvm"
fi

CPU_TYPE="cortex-a72"
if qemu-system-aarch64 -cpu help 2>/dev/null | grep -q "Kunpeng"; then
    CPU_TYPE="Kunpeng-920"
    echo "检测到鲲鹏定制QEMU，将使用直接内核启动"
fi

for k in vmlinuz vmlinuz-*; do
    if [ -f "$k" ]; then
        KERNEL="$k"
        break
    fi
done

for i in initramfs.img initramfs-*; do
    if [ -f "$i" ]; then
        INITRD="$i"
        break
    fi
done

if [ -n "$KERNEL" ] && [ -n "$INITRD" ]; then
    echo "使用直接内核启动模式..."
    echo "镜像: $IMAGE"
    echo "内核: $KERNEL"
    echo "CPU: $CPU_TYPE"
    
    qemu-system-aarch64 \
      -machine virt \
      -cpu $CPU_TYPE \
      -smp 4 \
      -m 4G \
      -kernel "$KERNEL" \
      -initrd "$INITRD" \
      -append "console=ttyAMA0 root=/dev/vda2 rw" \
      -drive file="$IMAGE",if=virtio,format=qcow2 \
      -netdev user,id=net0,hostfwd=tcp::${SSH_PORT}-:22 \
      -device virtio-net-pci,netdev=net0 \
      -nographic
else
    BIOS=""
    for path in /usr/share/edk2/aarch64 /usr/share/AAVMF /usr/share/qemu; do
        if [ -f "$path/QEMU_EFI.fd" ]; then
            BIOS="$path/QEMU_EFI.fd"
            break
        fi
        if [ -f "$path/AAVMF_CODE.fd" ]; then
            BIOS="$path/AAVMF_CODE.fd"
            break
        fi
    done
    
    if [ -z "$BIOS" ]; then
        echo "错误: 未找到UEFI固件"
        echo "请安装固件包: yum install edk2-aarch64"
        echo "或提取内核使用直接启动模式"
        exit 1
    fi
    
    echo "使用UEFI启动模式..."
    echo "固件: $BIOS"
    echo "镜像: $IMAGE"
    echo "CPU: $CPU_TYPE"
    echo "加速: $ACCEL"
    
    qemu-system-aarch64 \
      -machine virt,accel=$ACCEL \
      -cpu $CPU_TYPE \
      -smp 4 \
      -m 4G \
      -bios "$BIOS" \
      -drive file="$IMAGE",if=virtio,format=qcow2 \
      -netdev user,id=net0,hostfwd=tcp::${SSH_PORT}-:22 \
      -device virtio-net-pci,netdev=net0 \
      -nographic
fi

echo ""
echo "SSH登录: ssh root@localhost -p $SSH_PORT"
echo "密码: {VM_PASSWORD}"