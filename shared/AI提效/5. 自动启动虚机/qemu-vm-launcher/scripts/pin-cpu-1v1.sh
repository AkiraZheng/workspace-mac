#!/bin/bash
# pin-cpu-1v1.sh - 1v1绑核脚本

set -e

QEMU_PID=""
CPU_LIST=""

usage() {
    echo "Usage: $0 <qemu_pid> <cpu_list>"
    echo "示例: $0 12345 0,2,4,6"
    exit 1
}

if [ $# -lt 2 ]; then
    usage
fi

QEMU_PID="$1"
CPU_LIST="$2"

if ! ps -p "$QEMU_PID" > /dev/null 2>&1; then
    echo "错误: 进程 $QEMU_PID 不存在"
    exit 1
fi

get_vcpu_threads() {
    local threads=""
    for tid in $(ls /proc/$QEMU_PID/task/); do
        if [ -f /proc/$QEMU_PID/task/$tid/comm ]; then
            comm=$(cat /proc/$QEMU_PID/task/$tid/comm)
            if [[ "$comm" == "CPU "* ]]; then
                threads="$threads $tid"
            fi
        fi
    done
    echo "$threads"
}

IFS=',' read -ra CPUS <<< "$CPU_LIST"

VCPU_THREADS=$(get_vcpu_threads)

if [ -z "$VCPU_THREADS" ]; then
    echo "未找到vCPU线程"
    echo "请确保QEMU进程正在运行"
    exit 1
fi

echo "绑定vCPU线程..."
echo ""

i=0
for tid in $VCPU_THREADS; do
    if [ $i -lt ${#CPUS[@]} ]; then
        cpu=${CPUS[$i]}
        taskset -pc "$cpu" "$tid" 2>/dev/null
        vcpu_num=$(cat /proc/$QEMU_PID/task/$tid/comm | sed 's/CPU //')
        echo "vCPU $vcpu_num -> CPU $cpu (thread $tid)"
        ((i++))
    else
        echo "警告: vCPU数量超过CPU列表，跳过绑定"
        break
    fi
done

echo ""
echo "绑核完成"