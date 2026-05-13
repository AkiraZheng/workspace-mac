#!/bin/bash
# download-image.sh - openEuler镜像下载脚本

set -e

DEFAULT_VERSION="24.03-LTS"
OUTPUT_DIR="."
VERSION=""

usage() {
    echo "Usage: $0 [-o output_dir] [-v version]"
    echo "  -o: 输出目录 (默认当前目录)"
    echo "  -v: openEuler版本 (默认 ${DEFAULT_VERSION})"
    exit 1
}

while getopts "o:v:h" opt; do
    case $opt in
        o) OUTPUT_DIR="$OPTARG" ;;
        v) VERSION="$OPTARG" ;;
        h) usage ;;
        *) usage ;;
    esac
done

if [ -z "$VERSION" ]; then
    VERSION="$DEFAULT_VERSION"
fi

BASE_URL="https://repo.openeuler.org/openEuler-${VERSION}/virtual_machine_img/aarch64/"
IMAGE_XZ="openEuler-${VERSION}-aarch64.qcow2.xz"
IMAGE_QCOW2="openEuler-${VERSION}-aarch64.qcow2"

mkdir -p "$OUTPUT_DIR"

if [ -f "$OUTPUT_DIR/$IMAGE_QCOW2" ]; then
    echo "镜像已存在: $OUTPUT_DIR/$IMAGE_QCOW2"
    echo "跳过下载"
    exit 0
fi

echo "下载地址: ${BASE_URL}${IMAGE_XZ}"
echo "输出目录: $OUTPUT_DIR"

wget -c "${BASE_URL}${IMAGE_XZ}" -O "$OUTPUT_DIR/$IMAGE_XZ"

echo "解压镜像..."
xz -d "$OUTPUT_DIR/$IMAGE_XZ"

echo "镜像下载完成: $OUTPUT_DIR/$IMAGE_QCOW2"
echo "文件大小: $(du -h "$OUTPUT_DIR/$IMAGE_QCOW2" | cut -f1)"