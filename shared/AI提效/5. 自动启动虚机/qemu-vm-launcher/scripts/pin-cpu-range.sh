#!/bin/bash
# pin-cpu-range.sh - 范围绑核脚本

set -e

QEMU_PID=""
CPU_RANGE=""

usage() {
    echo "Usage: $0 <qemu_pid> <cpu_range>"
    echo "示例: $0 12345 0-3"
    echo "      $0 12345 0xf"
    exit 1
}

if [ $# -lt 2 ]; then
    usage
fi

QEMU_PID="$1"
CPU_RANGE="$2"

if ! ps -p "$QEMU_PID" > /dev/null 2>&1; then
    echo "错误: 进程 $QEMU_PID 不存在"
    exit 1
fi

echo "绑定QEMU进程 $QEMU_PID 到 CPU $CPU_RANGE"
echo ""

taskset -pc "$CPU_RANGE" "$QEMU_PID"

echo ""
echo "绑核完成"