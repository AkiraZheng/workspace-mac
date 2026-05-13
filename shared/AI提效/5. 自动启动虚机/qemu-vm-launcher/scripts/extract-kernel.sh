#!/bin/bash
# extract-kernel.sh - 从qcow2镜像中提取内核和initramfs

usage() {
    echo "用法: $0 -i <镜像文件> [-o <输出目录>]"
    echo ""
    echo "参数:"
    echo "  -i  镜像文件路径 (qcow2/img)"
    echo "  -o  输出目录 (默认当前目录)"
    echo ""
    echo "示例:"
    echo "  $0 -i openEuler.qcow2"
    echo "  $0 -i openEuler.qcow2 -o /tmp/kernel"
    exit 1
}

IMAGE=""
OUTPUT_DIR="."

while getopts "i:o:h" opt; do
    case $opt in
        i) IMAGE="$OPTARG" ;;
        o) OUTPUT_DIR="$OPTARG" ;;
        h) usage ;;
        *) usage ;;
    esac
done

if [ -z "$IMAGE" ]; then
    echo "错误: 必须指定镜像文件"
    usage
fi

if [ ! -f "$IMAGE" ]; then
    echo "错误: 镜像文件不存在: $IMAGE"
    exit 1
fi

which qemu-nbd > /dev/null || {
    echo "错误: qemu-nbd 未安装"
    exit 1
}

modprobe nbd max_part=8 2>/dev/null || {
    echo "警告: 无法加载nbd模块，尝试继续..."
}

echo "连接镜像到nbd设备..."
qemu-nbd --connect=/dev/nbd0 "$IMAGE"
sleep 2

if [ ! -e /dev/nbd0p1 ]; then
    echo "错误: 未找到分区，请检查镜像格式"
    qemu-nbd --disconnect /dev/nbd0 2>/dev/null
    exit 1
fi

MOUNT_DIR="/tmp/qemu-kernel-mount"
mkdir -p "$MOUNT_DIR"

echo "挂载boot分区..."
mount /dev/nbd0p1 "$MOUNT_DIR" || {
    echo "错误: 无法挂载分区"
    qemu-nbd --disconnect /dev/nbd0 2>/dev/null
    exit 1
}

echo "复制内核和initramfs..."
mkdir -p "$OUTPUT_DIR"

VMLINUZ=""
INITRAMFS=""

for f in "$MOUNT_DIR"/vmlinuz-*; do
    if [ -f "$f" ]; then
        VMLINUZ="$f"
        break
    fi
done

for f in "$MOUNT_DIR"/initramfs-*; do
    if [ -f "$f" ]; then
        INITRAMFS="$f"
        break
    fi
done

if [ -z "$VMLINUZ" ] || [ -z "$INITRAMFS" ]; then
    echo "错误: 未找到内核或initramfs文件"
    echo "分区内容:"
    ls -la "$MOUNT_DIR"
    umount "$MOUNT_DIR"
    qemu-nbd --disconnect /dev/nbd0 2>/dev/null
    exit 1
fi

cp "$VMLINUZ" "$OUTPUT_DIR/vmlinuz"
cp "$INITRAMFS" "$OUTPUT_DIR/initramfs.img"

echo "清理..."
umount "$MOUNT_DIR"
qemu-nbd --disconnect /dev/nbd0 2>/dev/null

echo ""
echo "提取完成:"
echo "  内核: $OUTPUT_DIR/vmlinuz"
echo "  Initramfs: $OUTPUT_DIR/initramfs.img"
echo ""
echo "使用方法:"
echo "  qemu-system-aarch64 -kernel $OUTPUT_DIR/vmlinuz -initrd $OUTPUT_DIR/initramfs.img ..."