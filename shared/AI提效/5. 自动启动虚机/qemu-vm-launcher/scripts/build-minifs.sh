#!/bin/bash
# build-minifs.sh - 最小化rootfs构建脚本

set -e

OUTPUT_PATH="minifs.img"
IMAGE_SIZE="200M"
INCLUDE_DEV_TOOLS=false
INCLUDE_DIR=""

usage() {
    echo "Usage: $0 [-o output_path] [-s size] [--with-dev-tools] [--include-dir path]"
    echo "  -o: 输出文件路径 (默认 minifs.img)"
    echo "  -s: 镜像大小 (默认 200M)"
    echo "  --with-dev-tools: 包含开发工具"
    echo "  --include-dir: 预置文件目录"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -o) OUTPUT_PATH="$2"; shift 2 ;;
        -s) IMAGE_SIZE="$2"; shift 2 ;;
        --with-dev-tools) INCLUDE_DEV_TOOLS=true; shift ;;
        --include-dir) INCLUDE_DIR="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) usage ;;
    esac
done

echo "构建minifs镜像..."
echo "输出路径: $OUTPUT_PATH"
echo "镜像大小: $IMAGE_SIZE"

if ! command -v dd &> /dev/null; then
    echo "错误: 需要dd工具"
    exit 1
fi

if ! command -v mkfs.ext4 &> /dev/null; then
    echo "错误: 需要mkfs.ext4工具"
    exit 1
fi

TMPDIR=$(mktemp -d)
ROOTFS="$TMPDIR/rootfs"

mkdir -p "$ROOTFS"

dd if=/dev/zero of="$OUTPUT_PATH" bs=1 count=0 seek="$IMAGE_SIZE" status=progress

mkfs.ext4 -F "$OUTPUT_PATH"

MOUNT_POINT="$TMPDIR/mount"
mkdir -p "$MOUNT_POINT"
mount -o loop "$OUTPUT_PATH" "$MOUNT_POINT"

mkdir -p "$MOUNT_POINT"/{bin,sbin,etc,proc,sys,dev,tmp,var,usr,root}

cat > "$MOUNT_POINT/etc/passwd" << 'EOF'
root:x:0:0:root:/root:/bin/sh
EOF

cat > "$MOUNT_POINT/etc/group" << 'EOF'
root:x:0:
EOF

if command -v busybox &> /dev/null; then
    cp "$(which busybox)" "$MOUNT_POINT/bin/"
    cd "$MOUNT_POINT/bin"
    for cmd in sh ls cat mkdir rm cp mv echo sleep mount umount; do
        ln -sf busybox "$cmd"
    done
    cd "$OLDPWD"
else
    echo "警告: busybox未找到，请手动安装"
fi

if [ -n "$INCLUDE_DIR" ] && [ -d "$INCLUDE_DIR" ]; then
    echo "预置文件目录: $INCLUDE_DIR"
    cp -r "$INCLUDE_DIR"/* "$MOUNT_POINT/" 2>/dev/null || true
fi

if [ "$INCLUDE_DEV_TOOLS" = true ]; then
    mkdir -p "$MOUNT_POINT/usr/bin"
    for tool in gcc make gdb strace lsof; do
        if command -v "$tool" &> /dev/null; then
            cp "$(which $tool)" "$MOUNT_POINT/usr/bin/" 2>/dev/null || echo "警告: $tool 未找到"
        fi
    done
fi

cat > "$MOUNT_POINT/init" << 'EOF'
#!/bin/sh
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
exec /bin/sh
EOF
chmod +x "$MOUNT_POINT/init"

umount "$MOUNT_POINT"
rm -rf "$TMPDIR"

echo "minifs镜像构建完成: $OUTPUT_PATH"
echo "文件大小: $(du -h "$OUTPUT_PATH" | cut -f1)"