#!/bin/bash
# ssh-test.sh - SSH连接测试脚本（自动清理known_hosts）
# 解决 HOST IDENTIFICATION HAS CHANGED 错误

set -e

HOST="localhost"
PORT="2222"
USER="root"
PASSWORD="{VM_PASSWORD}"
MAX_RETRY=10
RETRY_INTERVAL=5

usage() {
    echo "Usage: $0 [-h host] [-p port] [-u user] [-P password] [-r retry_count] [-i interval]"
    echo "  -h: 目标主机 (默认 localhost)"
    echo "  -p: SSH端口 (默认 2222)"
    echo "  -u: 用户名 (默认 root)"
    echo "  -P: 密码 (默认 {VM_PASSWORD})"
    echo "  -r: 最大重试次数 (默认 10)"
    echo "  -i: 重试间隔秒数 (默认 5)"
    exit 1
}

while getopts "h:p:u:P:r:i:" opt; do
    case $opt in
        h) HOST="$OPTARG" ;;
        p) PORT="$OPTARG" ;;
        u) USER="$OPTARG" ;;
        P) PASSWORD="$OPTARG" ;;
        r) MAX_RETRY="$OPTARG" ;;
        i) RETRY_INTERVAL="$OPTARG" ;;
        *) usage ;;
    esac
done

echo "============================================"
echo "SSH连接测试"
echo "============================================"
echo "目标: ${USER}@${HOST}:${PORT}"
echo ""

# 步骤1: 清理known_hosts（解决HOST IDENTIFICATION错误）
echo "[步骤1] 清理known_hosts中的旧记录..."
ssh-keygen -R "[${HOST}]:${PORT}" 2>/dev/null || true
ssh-keygen -R "${HOST}" 2>/dev/null || true
echo "✓ known_hosts已清理"
echo ""

# 步骤2: 检查sshpass是否可用
echo "[步骤2] 检查sshpass..."
if ! command -v sshpass &> /dev/null; then
    echo "安装sshpass..."
    yum install -y sshpass 2>/dev/null || apt install -y sshpass 2>/dev/null || {
        echo "✗ 无法安装sshpass"
        exit 1
    }
fi
echo "✓ sshpass已就绪"
echo ""

# 步骤3: 检查端口是否可达
echo "[步骤3] 检查端口..."
if ! nc -z "${HOST}" "${PORT}" 2>/dev/null; then
    echo "✗ 端口 ${PORT} 不可达"
    echo "  请确认虚机是否启动: ps aux | grep qemu"
    exit 1
fi
echo "✓ 端口 ${PORT} 已开放"
echo ""

# 步骤4: 尝试SSH连接（自动重试）
echo "[步骤4] 尝试SSH连接..."
for i in $(seq 1 $MAX_RETRY); do
    echo "尝试连接 ($i/$MAX_RETRY)..."
    
    if sshpass -p "$PASSWORD" ssh \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o ConnectTimeout=5 \
        "${USER}@${HOST}" -p "${PORT}" \
        'echo "SSH连接成功"; hostname; uname -a' 2>/dev/null; then
        
        echo ""
        echo "============================================"
        echo "✓ SSH连接成功！"
        echo "============================================"
        echo ""
        echo "使用方式:"
        echo "  sshpass -p '$PASSWORD' ssh -o StrictHostKeyChecking=no ${USER}@${HOST} -p ${PORT}"
        echo "  或配置免密登录后直接: ssh ${USER}@${HOST} -p ${PORT}"
        echo ""
        exit 0
    fi
    
    echo "连接失败，等待 ${RETRY_INTERVAL} 秒后重试..."
    sleep $RETRY_INTERVAL
done

echo ""
echo "============================================"
echo "✗ SSH连接失败，已尝试 $MAX_RETRY 次"
echo "============================================"
echo ""
echo "排查建议:"
echo "  1. 检查虚机是否启动: ps aux | grep qemu"
echo "  2. 检查端口是否正确: ss -tlnp | grep ${PORT}"
echo "  3. 检查虚机内sshd: 虚机内执行 systemctl status sshd"
echo "  4. 检查防火墙: 虚机内执行 firewall-cmd --list-all"
echo "  5. 若密码认证被禁用，需修复镜像SSH配置:"
echo "     pkill -f qemu-system-aarch64  # 停止虚机"
echo "     $SKILL_DIR/scripts/fix-ssh-config.sh -i openEuler.qcow2"
echo ""
exit 1