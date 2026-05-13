#!/bin/bash
# fix-ssh-config.sh - 修复openEuler云镜像SSH密码认证问题

usage() {
    echo "用法: $0 -i <镜像文件> [-p <密码>]"
    echo ""
    echo "参数:"
    echo "  -i  镜像文件路径 (qcow2/img)"
    echo "  -p  root密码 (默认: {VM_PASSWORD})"
    echo ""
    echo "功能:"
    echo "  1. 生成SSH host keys"
    echo "  2. 启用密码认证"
    echo "  3. 设置root密码"
    echo ""
    echo "示例:"
    echo "  $0 -i openEuler.qcow2"
    echo "  $0 -i openEuler.qcow2 -p mypassword"
    exit 1
}

IMAGE=""
PASSWORD="{VM_PASSWORD}"

while getopts "i:p:h" opt; do
    case $opt in
        i) IMAGE="$OPTARG" ;;
        p) PASSWORD="$OPTARG" ;;
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

which ssh-keygen > /dev/null || {
    echo "错误: ssh-keygen 未安装"
    exit 1
}

echo "修复镜像: $IMAGE"

modprobe nbd max_part=8 2>/dev/null || {
    echo "警告: 无法加载nbd模块，尝试继续..."
}

echo "连接镜像..."
qemu-nbd --connect=/dev/nbd0 "$IMAGE"
sleep 2

if [ ! -e /dev/nbd0p2 ]; then
    echo "错误: 未找到根分区"
    qemu-nbd --disconnect /dev/nbd0 2>/dev/null
    exit 1
fi

MOUNT_DIR="/tmp/qemu-ssh-fix"
mkdir -p "$MOUNT_DIR"

echo "挂载根分区..."
mount /dev/nbd0p2 "$MOUNT_DIR" || {
    echo "错误: 无法挂载分区"
    qemu-nbd --disconnect /dev/nbd0 2>/dev/null
    exit 1
}

SSH_DIR="$MOUNT_DIR/etc/ssh"

echo "步骤1: 修复SSH host keys..."
rm -f "$SSH_DIR"/ssh_host_*_key*

ssh-keygen -t rsa -b 4096 -f "$SSH_DIR/ssh_host_rsa_key" -N "" -q 2>/dev/null
ssh-keygen -t ecdsa -b 256 -f "$SSH_DIR/ssh_host_ecdsa_key" -N "" -q 2>/dev/null
ssh-keygen -t ed25519 -f "$SSH_DIR/ssh_host_ed25519_key" -N "" -q 2>/dev/null

chown root:polkitd "$SSH_DIR"/ssh_host_*_key 2>/dev/null || chown root:root "$SSH_DIR"/ssh_host_*_key
chmod 600 "$SSH_DIR"/ssh_host_*_key

echo "步骤2: 启用密码认证..."
rm -f "$SSH_DIR/sshd_config.d/50-cloud-init.conf"
mkdir -p "$SSH_DIR/sshd_config.d"
echo "PasswordAuthentication yes" > "$SSH_DIR/sshd_config.d/01-password.conf"
chmod 644 "$SSH_DIR/sshd_config.d/01-password.conf"

echo "步骤3: 修改cloud.cfg防止重置密码认证..."
CLOUD_CFG="$MOUNT_DIR/etc/cloud/cloud.cfg"
if [ -f "$CLOUD_CFG" ]; then
    sed -i 's/ssh_pwauth: false/ssh_pwauth: true/' "$CLOUD_CFG"
    echo "已修改 ssh_pwauth: true"
else
    echo "警告: cloud.cfg 不存在"
fi

echo "步骤4: 防止cloud-init删除SSH keys..."
mkdir -p "$MOUNT_DIR/etc/cloud/cloud.cfg.d"
echo "ssh_deletekeys: false" > "$MOUNT_DIR/etc/cloud/cloud.cfg.d/99-ssh-keys.cfg"
chmod 644 "$MOUNT_DIR/etc/cloud/cloud.cfg.d/99-ssh-keys.cfg"

echo "步骤5: 设置root密码..."
HASH=$(openssl passwd -6 "$PASSWORD")
SHADOW_FILE="$MOUNT_DIR/etc/shadow"

echo "root:$HASH:19000:0:99999:7:::" > "$SHADOW_FILE.new"
tail -n +2 "$SHADOW_FILE" >> "$SHADOW_FILE.new"
mv "$SHADOW_FILE.new" "$SHADOW_FILE"

chmod 640 "$SHADOW_FILE"
chown root:root "$SHADOW_FILE"

echo "清理..."
umount "$MOUNT_DIR"
qemu-nbd --disconnect /dev/nbd0 2>/dev/null

echo ""
echo "修复完成！"
echo "密码: $PASSWORD"
echo ""
echo "启动虚拟机后，使用以下命令登录:"
echo "  sshpass -p '$PASSWORD' ssh -o StrictHostKeyChecking=no root@localhost -p 2222"