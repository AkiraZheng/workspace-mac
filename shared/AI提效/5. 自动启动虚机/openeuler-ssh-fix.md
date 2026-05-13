# openEuler云镜像SSH密码认证修复指南

## 问题根源

openEuler云镜像默认配置导致SSH密码认证失败，主要原因：

1. **SSH host keys为空文件**（0字节）→ sshd服务启动失败
2. **密码认证被禁用**（`PasswordAuthentication no`）
3. **cloud-init每次启动重置配置**（`ssh_pwauth: false` + `ssh_deletekeys: true`）
4. **root密码未设置**
5. **SSH key文件权限和所有者错误**

---

## 完整修复流程

### 步骤1：挂载镜像

```bash
# 加载nbd模块
modprobe nbd max_part=8

# 连接qcow2镜像到nbd设备
qemu-nbd --connect=/dev/nbd0 openEuler.qcow2
sleep 2

# 查看分区
ls /dev/nbd0*
# 通常输出：/dev/nbd0 /dev/nbd0p1 /dev/nbd0p2
# p1: /boot分区
# p2: /根分区

# 挂载根分区
mount /dev/nbd0p2 /mnt
```

---

### 步骤2：生成SSH host keys

**问题**：镜像中的`/etc/ssh/ssh_host_*_key`文件为空（0字节），导致sshd无法启动。

```bash
# 删除旧的空文件
rm -f /mnt/etc/ssh/ssh_host_*_key*

# 生成新的SSH keys
ssh-keygen -t rsa -b 4096 -f /mnt/etc/ssh/ssh_host_rsa_key -N "" -q
ssh-keygen -t ecdsa -b 256 -f /mnt/etc/ssh/ssh_host_ecdsa_key -N "" -q
ssh-keygen -t ed25519 -f /mnt/etc/ssh/ssh_host_ed25519_key -N "" -q

# 设置正确的所有者和权限
chown root:polkitd /mnt/etc/ssh/ssh_host_*_key
chmod 600 /mnt/etc/ssh/ssh_host_*_key

# 验证
ls -lh /mnt/etc/ssh/ssh_host_*_key
# 应输出非0字节的key文件
```

---

### 步骤3：启用密码认证

**问题**：`/etc/ssh/sshd_config.d/50-cloud-init.conf`包含`PasswordAuthentication no`。

```bash
# 删除cloud-init的禁用配置
rm -f /mnt/etc/ssh/sshd_config.d/50-cloud-init.conf

# 创建目录（如果不存在）
mkdir -p /mnt/etc/ssh/sshd_config.d

# 启用密码认证
echo "PasswordAuthentication yes" > /mnt/etc/ssh/sshd_config.d/01-password.conf
chmod 644 /mnt/etc/ssh/sshd_config.d/01-password.conf

# 验证
cat /mnt/etc/ssh/sshd_config.d/01-password.conf
# 应输出：PasswordAuthentication yes
```

---

### 步骤4：修改cloud.cfg防止重置

**【关键步骤】** 如果不修改，每次启动cloud-init都会重新禁用密码认证。

```bash
# 修改ssh_pwauth配置
sed -i 's/ssh_pwauth: false/ssh_pwauth: true/' /mnt/etc/cloud/cloud.cfg

# 验证修改
grep ssh_pwauth /mnt/etc/cloud/cloud.cfg
# 应输出：ssh_pwauth: true
```

---

### 步骤5：防止cloud-init删除SSH keys

**【关键步骤】** cloud-init默认会删除并重新生成SSH keys，导致每次启动keys变化。

```bash
# 创建配置文件
mkdir -p /mnt/etc/cloud/cloud.cfg.d
echo "ssh_deletekeys: false" > /mnt/etc/cloud/cloud.cfg.d/99-ssh-keys.cfg

# 验证
cat /mnt/etc/cloud/cloud.cfg.d/99-ssh-keys.cfg
# 应输出：ssh_deletekeys: false
```

---

### 步骤6：设置root密码

**问题**：openEuler云镜像默认没有root密码。

```bash
# 生成密码hash（密码：{VM_PASSWORD}）
HASH=$(openssl passwd -6 '{VM_PASSWORD}')

# 更新shadow文件中的root密码
# 方法1：替换第一行
sed -i "1s|^root:.*|root:$HASH:19000:0:99999:7:::|" /mnt/etc/shadow

# 方法2：使用临时文件（更安全）
echo "root:$HASH:19000:0:99999:7:::" > /mnt/etc/shadow.tmp
tail -n +2 /mnt/etc/shadow >> /mnt/etc/shadow.tmp
mv /mnt/etc/shadow.tmp /mnt/etc/shadow

# 设置权限
chmod 640 /mnt/etc/shadow
chown root:root /mnt/etc/shadow

# 验证（检查第一行是否包含hash）
head -1 /mnt/etc/shadow
# 应输出：root:$6$...:19000:0:99999:7:::
```

---

### 步骤7：断开并启动虚拟机

```bash
# 断开nbd连接
umount /mnt
qemu-nbd --disconnect /dev/nbd0

# 验证断开
ls /dev/nbd0* 2>/dev/null || echo "Disconnected successfully"

# 启动虚拟机（使用直接内核启动）
qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a72 \
  -smp 4 \
  -m 4G \
  -kernel vmlinuz \
  -initrd initramfs.img \
  -append "console=ttyAMA0 root=/dev/vda2 rw" \
  -drive file=openEuler.qcow2,if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic

# TCG模式启动需要60-120秒，请耐心等待
```

---

### 步骤8：测试SSH连接

```bash
# 方法1：使用sshpass自动输入密码（推荐）
sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222 'hostname'
# 应输出：localhost.localdomain

# 方法2：手动连接（需要先清除旧host key）
ssh-keygen -R "[localhost]:2222"
ssh root@localhost -p 2222
# 输入密码：{VM_PASSWORD}
```

---

## 关键点总结

| 步骤 | 解决的问题 | 配置文件 | 关键性 |
|-----|-----------|---------|--------|
| 生成SSH keys | keys为空→sshd启动失败 | `/etc/ssh/ssh_host_*_key` | **必须** |
| 设置权限 | 所有者错误导致sshd拒绝 | key文件权限 | **必须** |
| 启用密码认证 | PasswordAuthentication no | `/etc/ssh/sshd_config.d/01-password.conf` | **必须** |
| 修改ssh_pwauth | 每次启动重置配置 | `/etc/cloud/cloud.cfg` | **最关键** |
| ssh_deletekeys | cloud-init覆盖keys | `/etc/cloud/cloud.cfg.d/99-ssh-keys.cfg` | **最关键** |
| 设置root密码 | 无法登录 | `/etc/shadow` | **必须** |

---

## 常见错误诊断

### 错误1: sshd启动失败

**现象**：
```
FAILED: Failed to start OpenSSH server daemon
See 'systemctl status sshd.service' for details
```

**原因**：SSH host keys为空文件（0字节）

**检查**：
```bash
# 挂载后检查key文件大小
ls -la /mnt/etc/ssh/ssh_host_*_key
# 若显示0字节，说明问题存在
```

**解决**：重新生成SSH keys（见步骤2）

---

### 错误2: Permission denied

**现象**：
```
Permission denied (publickey,gssapi-with-mic)
```

**原因**：密码认证未启用

**检查**：
```bash
# 检查是否有禁用配置
ls /mnt/etc/ssh/sshd_config.d/50-cloud-init.conf
cat /mnt/etc/ssh/sshd_config.d/50-cloud-init.conf
```

**解决**：删除50-cloud-init.conf + 创建01-password.conf（见步骤3）

---

### 错误3: 每次重启SSH失败

**现象**：第一次启动SSH正常，重启后又失败

**原因**：cloud-init每次启动都会重新禁用密码认证并删除SSH keys

**检查**：
```bash
# 检查cloud.cfg配置
grep ssh_pwauth /mnt/etc/cloud/cloud.cfg
# 若输出"ssh_pwauth: false"，说明问题存在

# 检查是否有防止删除keys的配置
cat /mnt/etc/cloud/cloud.cfg.d/99-ssh-keys.cfg
# 若文件不存在或内容为"ssh_deletekeys: true"，说明问题存在
```

**解决**：修改cloud.cfg + 创建99-ssh-keys.cfg（见步骤4、5）

---

### 错误4: SSH host key变化

**现象**：
```
WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED
```

**原因**：每次启动cloud-init重新生成SSH keys

**解决**：
```bash
# 方法1：每次连接前清除旧key
ssh-keygen -R "[localhost]:2222"

# 方法2：使用sshpass跳过host key检查
sshpass -p 'password' ssh -o StrictHostKeyChecking=no root@localhost -p 2222

# 方法3：彻底解决 - 配置ssh_deletekeys: false（见步骤5）
```

---

## 一键修复脚本

将完整流程封装为脚本：

```bash
#!/bin/bash
# fix-ssh-config.sh - openEuler云镜像SSH密码认证修复

IMAGE="${1:-openEuler.qcow2}"
PASSWORD="${2:-{VM_PASSWORD}}"

echo "修复镜像: $IMAGE"

# 挂载
modprobe nbd max_part=8
qemu-nbd --connect=/dev/nbd0 "$IMAGE"
sleep 2
mount /dev/nbd0p2 /mnt

# 生成SSH keys
rm -f /mnt/etc/ssh/ssh_host_*_key*
ssh-keygen -t rsa -b 4096 -f /mnt/etc/ssh/ssh_host_rsa_key -N "" -q
ssh-keygen -t ecdsa -b 256 -f /mnt/etc/ssh/ssh_host_ecdsa_key -N "" -q
ssh-keygen -t ed25519 -f /mnt/etc/ssh/ssh_host_ed25519_key -N "" -q
chown root:polkitd /mnt/etc/ssh/ssh_host_*_key
chmod 600 /mnt/etc/ssh/ssh_host_*_key

# 启用密码认证
rm -f /mnt/etc/ssh/sshd_config.d/50-cloud-init.conf
mkdir -p /mnt/etc/ssh/sshd_config.d
echo "PasswordAuthentication yes" > /mnt/etc/ssh/sshd_config.d/01-password.conf
chmod 644 /mnt/etc/ssh/sshd_config.d/01-password.conf

# 修改cloud.cfg
sed -i 's/ssh_pwauth: false/ssh_pwauth: true/' /mnt/etc/cloud/cloud.cfg

# 防止删除keys
mkdir -p /mnt/etc/cloud/cloud.cfg.d
echo "ssh_deletekeys: false" > /mnt/etc/cloud/cloud.cfg.d/99-ssh-keys.cfg

# 设置密码
HASH=$(openssl passwd -6 "$PASSWORD")
sed -i "1s|^root:.*|root:$HASH:19000:0:99999:7:::|" /mnt/etc/shadow
chmod 640 /mnt/etc/shadow

# 断开
umount /mnt
qemu-nbd --disconnect /dev/nbd0

echo "修复完成！密码: $PASSWORD"
echo "连接命令: sshpass -p '$PASSWORD' ssh -o StrictHostKeyChecking=no root@localhost -p 2222"
```

**使用方法**：
```bash
chmod +x fix-ssh-config.sh
./fix-ssh-config.sh openEuler.qcow2
```

---

## 附录：直接内核启动说明

### 为什么使用直接内核启动

openEuler云镜像需要从镜像中提取内核文件：

```bash
# 挂载boot分区
mount /dev/nbd0p1 /mnt/boot

# 复制内核和initramfs
cp /mnt/boot/vmlinuz-* ./vmlinuz
cp /mnt/boot/initramfs-* ./initramfs.img

# 内核启动参数说明
-append "console=ttyAMA0 root=/dev/vda2 rw"
# console=ttyAMA0: ARM64串口控制台
# root=/dev/vda2: virtio磁盘第二分区（根分区）
# rw: 读写模式
```

### 启动脚本模板

```bash
#!/bin/bash
#========================================
# QEMU虚拟机启动脚本
#========================================
# SSH连接方式:
#   ssh root@localhost -p 2222
# 
# 登录账号: root
# 登录密码: {VM_PASSWORD}
#
# 注意: 每次重启虚拟机后SSH host key会变化，
#       连接前需先清除旧key:
#       ssh-keygen -R "[localhost]:2222"
# 
# 或使用sshpass自动登录（推荐）:
#       sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222
#========================================

qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a72 \
  -smp 4 \
  -m 4G \
  -kernel vmlinuz \
  -initrd initramfs.img \
  -append "console=ttyAMA0 root=/dev/vda2 rw" \
  -drive file=openEuler.qcow2,if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

---

## 参考资料

- openEuler官方文档：https://docs.openeuler.org
- cloud-init配置说明：https://cloudinit.readthedocs.io
- QEMU文档：https://qemu.org/docs

---

**文档版本**: v1.0  
**更新日期**: 2026-05-13  
**适用版本**: openEuler 22.03-LTS / 24.03-LTS