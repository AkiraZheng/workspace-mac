#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="${1:-$SCRIPT_DIR}"
WORK_DIR="$OUTPUT_DIR/initramfs_work"

echo "Building initramfs in $OUTPUT_DIR..."

rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR"/{bin,sbin,etc,proc,sys,dev}

cp /usr/bin/ls "$WORK_DIR/bin/"
cp /usr/bin/cat "$WORK_DIR/bin/"
cp /usr/bin/mkdir "$WORK_DIR/bin/"
cp /usr/bin/sleep "$WORK_DIR/bin/"
cp /usr/bin/umount "$WORK_DIR/bin/"
cp /usr/sbin/switch_root "$WORK_DIR/sbin/"
cp /bin/bash "$WORK_DIR/bin/"
cp /bin/sh "$WORK_DIR/bin/"
cp /bin/mount "$WORK_DIR/bin/"

mkdir -p "$WORK_DIR/bin/lib64"
cp /lib64/libtinfo.so.6 "$WORK_DIR/bin/lib64/"
cp /lib64/libc.so.6 "$WORK_DIR/bin/lib64/"
cp /lib64/libcap.so.2 "$WORK_DIR/bin/lib64/"
cp /lib64/libpcre2-8.so.0 "$WORK_DIR/bin/lib64/"
cp /lib64/libmount.so.1 "$WORK_DIR/bin/lib64/"
cp /lib64/libblkid.so.1 "$WORK_DIR/bin/lib64/"
cp /lib64/libselinux.so.1 "$WORK_DIR/bin/lib64/"
cp /usr/lib/ld-linux-aarch64.so.1 "$WORK_DIR/bin/lib64/"

mkdir -p "$WORK_DIR/sbin/lib64"
cp /usr/lib/ld-linux-aarch64.so.1 "$WORK_DIR/sbin/lib64/"

cd "$WORK_DIR"
rm -rf lib64 lib
ln -s bin/lib64 lib64
ln -s bin/lib64 lib

printf '#!/bin/sh\necho "initramfs booting..."\nmount -t proc none /proc\nmount -t sysfs none /sys\nmount -t devtmpfs none /dev\necho "Welcome to LKVM!"\nexec /bin/sh\n' > "$WORK_DIR/init"
chmod +x "$WORK_DIR/init"

find . | cpio -R root:root -o -H newc | gzip > "$OUTPUT_DIR/initramfs.cpio.gz"

rm -rf "$WORK_DIR"

echo "Done! initramfs.cpio.gz created: $(ls -lh "$OUTPUT_DIR/initramfs.cpio.gz" | awk '{print $5}')"
