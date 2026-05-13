#!/bin/bash
# start-direct-kernel.sh - 直接内核启动示例（适用于鲲鹏定制QEMU）

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
    exit 1
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

if [ -z "$KERNEL" ] || [ -z "$INITRD" ]; then
    echo "错误: 未找到内核或initramfs文件"
    echo "请从镜像中提取内核:"
    echo "  modprobe nbd max_part=8"
    echo "  qemu-nbd --connect=/dev/nbd0 $IMAGE"
    echo "  mount /dev/nbd0p1 /mnt"
    echo "  cp /mnt/vmlinuz-* ./vmlinuz"
    echo "  cp /mnt/initramfs-* ./initramfs.img"
    echo "  umount /mnt"
    echo "  qemu-nbd --disconnect /dev/nbd0"
    exit 1
fi

echo "启动QEMU虚机（直接内核启动）..."
echo "镜像: $IMAGE"
echo "内核: $KERNEL"
echo "Initrd: $INITRD"
echo "SSH端口: $SSH_PORT"
echo ""

qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a72 \
  -smp 4 \
  -m 4G \
  -kernel "$KERNEL" \
  -initrd "$INITRD" \
  -append "console=ttyAMA0 root=/dev/vda2 rw" \
  -drive file="$IMAGE",if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::${SSH_PORT}-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic

echo ""
echo "SSH登录: ssh root@localhost -p $SSH_PORT"
echo "密码: {VM_PASSWORD}"