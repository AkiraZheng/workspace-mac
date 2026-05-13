#!/bin/bash
# check-port.sh - 端口可用性检查脚本
# 检查端口是否被占用，若占用则自动寻找可用端口

set -e

DEFAULT_START_PORT=2222
MAX_PORT=65535
MIN_PORT=1024

usage() {
    echo "Usage: $0 [-p start_port] [-m max_port]"
    echo "  -p: 起始检查端口 (默认 $DEFAULT_START_PORT)"
    echo "  -m: 最大端口范围 (默认 $MAX_PORT)"
    echo ""
    echo "输出: JSON格式"
    echo "  {\"available_port\": 2222, \"original_port\": 2222, \"changed\": false}"
    exit 1
}

START_PORT=$DEFAULT_START_PORT
MAX_CHECK_PORT=$MAX_PORT

while getopts "p:m:h" opt; do
    case $opt in
        p) START_PORT="$OPTARG" ;;
        m) MAX_CHECK_PORT="$OPTARG" ;;
        h) usage ;;
        *) usage ;;
    esac
done

check_port() {
    local port=$1
    
    # 检查端口是否被监听
    if ss -tuln | grep -q ":${port} "; then
        return 1  # 端口被占用
    fi
    
    # 检查端口是否被进程使用
    if lsof -i :${port} >/dev/null 2>&1; then
        return 1  # 端口被占用
    fi
    
    # 检查端口范围是否有效
    if [ "$port" -lt "$MIN_PORT" ] || [ "$port" -gt "$MAX_PORT" ]; then
        return 1
    fi
    
    return 0  # 端口可用
}

find_available_port() {
    local port=$START_PORT
    
    while [ "$port" -le "$MAX_CHECK_PORT" ]; do
        if check_port "$port"; then
            echo "$port"
            return 0
        fi
        port=$((port + 1))
    done
    
    echo ""
    return 1
}

AVAILABLE_PORT=$(find_available_port)

if [ -z "$AVAILABLE_PORT" ]; then
    echo "{\"error\": \"no_available_port\", \"message\": \"未找到可用端口 ($START_PORT-$MAX_CHECK_PORT)\"}"
    exit 1
fi

CHANGED="false"
if [ "$AVAILABLE_PORT" != "$START_PORT" ]; then
    CHANGED="true"
fi

echo "{\"available_port\": $AVAILABLE_PORT, \"original_port\": $START_PORT, \"changed\": $CHANGED}"