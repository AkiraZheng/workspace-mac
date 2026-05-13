# QEMU VM Launcher 详细参考文档

本文档包含详细的构建步骤、错误排查表格、脚本使用示例等内容。

---

## 目录

1. Minimal Initramfs 详细构建步骤
2. qcow2镜像SSH密码认证修复详解
3. 内核提取详细流程
4. 常见错误排查表格
5. 工具命令分类表
6. 经验总结

---

## 1. Minimal Initramfs 详细构建步骤

### 1.1 检查环境和安装依赖

```bash
# 检查QEMU是否安装
which qemu-system-aarch64 || yum install qemu-system-aarch64

# 检查并安装busybox
which busybox || yum install -y busybox

# 确认busybox路径
BUSYBOX_PATH=$(which busybox || echo "/sbin/busybox")
echo "Busybox路径: $BUSYBOX_PATH"

# 检查busybox是否为动态链接（关键步骤）
file $BUSYBOX_PATH | grep "dynamically linked"
# 若输出包含 "dynamically linked"，需要复制动态库
```

### 1.2 构建minifs raw镜像

```bash
# 创建空文件
dd if=/dev/zero of=minifs.img bs=1 count=0 seek=200M

# 创建ext4文件系统
mkfs.ext4 -F minifs.img

# 验证
file minifs.img
ls -lh minifs.img
```

### 1.3 构建minimal initramfs

```bash
# 创建initramfs目录结构
mkdir -p initramfs/{bin,sbin,lib,etc,proc,sys,dev,mnt,root,usr/lib64}
mkdir -p initramfs/etc/init.d

# 步骤1: 复制busybox
cp $BUSYBOX_PATH initramfs/bin/busybox

# 步骤2: 创建命令符号链接（重要：先检查busybox支持哪些命令）
cd initramfs/bin

# 查看busybox支持的命令（约300+）
busybox --list | wc -l
busybox --list | head -50

# 添加所有busybox支持的命令（推荐）
for cmd in $(busybox --list); do
    [ -e "$cmd" ] || ln -sf busybox $cmd
done

cd ..

# 步骤3: 复制动态链接器和库
readelf -l $BUSYBOX_PATH | grep interpreter
cp -L /lib/ld-linux-aarch64.so.1 initramfs/lib/
cp -L /usr/lib64/libm.so.6 initramfs/usr/lib64/
cp -L /usr/lib64/libresolv.so.2 initramfs/usr/lib64/
cp -L /usr/lib64/libc.so.6 initramfs/usr/lib64/

# 步骤4: 创建init
ln -sf bin/busybox init

# 步骤5: 创建profile（设置PS1显示路径）
cat > etc/profile << 'EOF'
PS1='$(pwd)# '
export PS1
EOF
chmod +x etc/profile

# 步骤6: 创建rcS启动脚本
cat > etc/init.d/rcS << 'EOF'
#!/bin/sh
mount -t proc none /proc
mount -t sysfs none /sys
mount -t devtmpfs none /dev

export PATH=/bin:/sbin
export TERM=linux
export HOME=/root
export ENV=/etc/profile

PS1='$(pwd)# '
export PS1

echo "=========================================="
echo "Welcome to Minimal VM!"
echo "=========================================="
echo "可用编辑器: ed, hexedit"
echo "常用命令: ls, cd, cat, grep, ps, free..."
echo "=========================================="
echo ""

exec /bin/sh
EOF
chmod +x etc/init.d/rcS

# 步骤7: 打包initramfs
find . | cpio -H newc -o | gzip > ../initrd-minimal.img
cd ..
ls -lh initrd-minimal.img
```

### 1.4 获取内核文件

```bash
# 自动检测Host内核
KERNEL=$(ls -t /boot/vmlinuz-*aarch64 | grep -v rescue | head -1)
echo "内核: $KERNEL"

# 验证内核文件存在
ls -lh $KERNEL
```

### 1.5 测试启动命令

```bash
timeout 60 qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a72 \
  -smp 4 \
  -m 2G \
  -kernel $KERNEL \
  -initrd ./initrd-minimal.img \
  -append "console=ttyAMA0" \
  -drive file=./minifs.img,if=virtio,format=raw \
  -nographic 2>&1 | tail -50

# ✓ 成功: 显示 "Welcome to Minimal VM!" 和 shell提示符
# ✗ 失败: 显示 "Kernel panic" 或 "Failed to execute /init"
```

### 1.6 生成启动脚本

```bash
KERNEL_VER=$(basename $KERNEL | sed 's/vmlinuz-//')

cat > start-minimal-vm.sh << EOF
#!/bin/bash
#========================================
# Minimal Initramfs虚拟机启动脚本
#========================================
# 虚机类型: Minimal Initramfs (无SSH/网络)
# 镜像格式: raw
# 内核版本: $KERNEL_VER
#
# 交互方式:
#   直接在串口控制台操作
#   提示符显示当前路径: /path#
#
# 可用编辑器: ed, hexedit (不支持vi)
# 常用命令: ls, cd, cat, grep, ps, free, df
#
# 退出虚拟机: Ctrl+A 然后按 X
#========================================

qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a72 \
  -smp 4 \
  -m 2G \
  -kernel $KERNEL \
  -initrd ./initrd-minimal.img \
  -append "console=ttyAMA0" \
  -drive file=./minifs.img,if=virtio,format=raw \
  -nographic
EOF

chmod +x start-minimal-vm.sh
```

---

## 2. qcow2镜像SSH密码认证修复详解

### 2.1 问题原因

openEuler云镜像默认：
1. SSH host keys为空（0字节）
2. cloud-init禁用密码认证（`PasswordAuthentication no`）
3. cloud.cfg设置 `ssh_pwauth: false`
4. root密码未设置

### 2.2 修复步骤

```bash
# 1. 加载nbd模块
modprobe nbd max_part=8

# 2. 连接镜像
qemu-nbd --connect=/dev/nbd0 image.qcow2
sleep 2

# 3. 挂载根分区（通常是p2）
mount /dev/nbd0p2 /mnt

# 4. 删除空key文件并重新生成
rm -f /mnt/etc/ssh/ssh_host_*_key*
ssh-keygen -t rsa -b 4096 -f /mnt/etc/ssh/ssh_host_rsa_key -N "" -q
ssh-keygen -t ecdsa -b 256 -f /mnt/etc/ssh/ssh_host_ecdsa_key -N "" -q
ssh-keygen -t ed25519 -f /mnt/etc/ssh/ssh_host_ed25519_key -N "" -q

chown root:polkitd /mnt/etc/ssh/ssh_host_*_key
chmod 600 /mnt/etc/ssh/ssh_host_*_key

# 5. 启用密码认证（两项修改）
rm /mnt/etc/ssh/sshd_config.d/50-cloud-init.conf
echo "PasswordAuthentication yes" > /mnt/etc/ssh/sshd_config.d/01-password.conf
chmod 644 /mnt/etc/ssh/sshd_config.d/01-password.conf

sed -i 's/ssh_pwauth: false/ssh_pwauth: true/' /mnt/etc/cloud/cloud.cfg

# 6. 设置root密码
HASH=$(openssl passwd -6 '{VM_PASSWORD}')
echo "root:$HASH:19000:0:99999:7:::" > /mnt/etc/shadow.new
tail -n +2 /mnt/etc/shadow >> /mnt/etc/shadow.new
mv /mnt/etc/shadow.new /mnt/etc/shadow
chmod 640 /mnt/etc/shadow
chown root:root /mnt/etc/shadow

# 7. 断开连接
umount /mnt
qemu-nbd --disconnect /dev/nbd0
```

### 2.3 SSH连接测试

```bash
# 清除旧host keys
ssh-keygen -R "[localhost]:2222"

# 使用sshpass测试
sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222 'hostname'
```

---

## 3. 内核提取详细流程

```bash
# 1. 加载nbd模块
modprobe nbd max_part=8

# 2. 连接镜像
qemu-nbd --connect=/dev/nbd0 image.qcow2
sleep 2

# 3. 查看分区
ls /dev/nbd0*

# 4. 挂载boot分区（通常是p1）
mount /dev/nbd0p1 /mnt

# 5. 复制文件
cp /mnt/vmlinuz-* ./vmlinuz
cp /mnt/initramfs-* ./initramfs.img

# 6. 断开
umount /mnt
qemu-nbd --disconnect /dev/nbd0
```

---

## 4. 常见错误排查表格

### Minimal Initramfs错误

| 错误现象 | 原因 | 解决方法 |
|---------|------|---------|
| `Failed to execute /init (error -2)` | 动态链接器路径错误 | 确保 `/lib/ld-linux-aarch64.so.1` 存在 |
| `Kernel panic - not syncing` | init脚本格式错误 | 使用 `ln -sf bin/busybox init` 而非脚本 |
| `vi: applet not found` | busybox不支持vi | 使用ed或hexedit替代 |
| `touch: not found` | 命令符号链接缺失 | 添加所有busybox支持的命令 |
| shell不显示当前路径 | PS1设置无效 | 使用 `PS1='$(pwd)# '` |
| initramfs太小(<1M) | 动态库未复制 | 检查并复制 libm/libresolv/libc |

### qcow2镜像错误

| 错误现象 | 原因 | 解决方法 |
|---------|------|---------|
| SSH "Permission denied" | 密码认证被禁用 | 执行SSH修复脚本 |
| UEFI "Synchronous Exception" | 华为鲲鹏UBIOS不兼容标准固件 | 使用直接内核启动 |
| qemu-nbd连接失败 | nbd模块未加载 | `modprobe nbd max_part=8` |

---

## 5. 工具命令分类表

| 类别 | 基础命令 | 可选命令 |
|-----|---------|---------|
| 文件操作 | ls, cat, cp, mv, rm, touch | ed, hexedit, more, less, head, tail |
| 查找过滤 | grep, sed, awk | find, xargs, sort, uniq, cut, tr |
| 系统信息 | ps, free, df, du, uname | top, uptime, dmesg |
| 网络 | - | ifconfig, ip, ping, wget, curl, nc |
| 进程控制 | kill | killall, pkill, pgrep |
| 归档 | tar, gzip | bzip2, xz, cpio |
| 磁盘 | mount, umount | fdisk, mkfs, blkid |

**查看busybox支持的命令**：
```bash
busybox --list | wc -l           # 查看总数
busybox --list | grep vi         # 查看特定命令
```

---

## 6. 经验总结

### 6.1 华为鲲鹏定制QEMU兼容性

**识别标志**：
- QEMU版本包含 "UBIOS" 字样
- CPU列表包含 "Kunpeng-920" 等型号

**兼容性问题**：
- 标准AAVMF固件与鲲鹏UBIOS不兼容
- 使用 `-bios` 会触发 "Synchronous Exception"

**解决方案**：
- 必须使用直接内核启动（-kernel/-initrd）
- 从镜像中提取vmlinuz和initramfs

### 6.2 SSH密码认证修复要点

**必须执行两项修改**：
1. 删除 `50-cloud-init.conf`
2. 修改 `cloud.cfg` 中的 `ssh_pwauth: false` 为 `true`

只删除第一项不够，每次启动cloud-init都会重置配置。

### 6.3 TCG模式超时设置

| 场景 | KVM模式 | TCG模式 |
|-----|--------|--------|
| 启动命令验证 | 30秒 | 60秒 |
| 内核启动验证 | 30秒 | 60-90秒 |
| 等待SSH可用 | 40秒 | 90-120秒 |
| 完整启动 | 60秒 | 120秒+ |

### 6.4 CPU类型选择

**鲲鹏环境**：
```bash
qemu-system-aarch64 -cpu help | grep Kunpeng
# 建议: Kunpeng-920 或 cortex-a72
```

**标准环境**：
```bash
# 建议: host 或 cortex-a57
```

### 6.5 驱动器接口选择

**推荐使用 virtio**：
```bash
-drive file=${image},if=virtio,format=qcow2
```

相比传统方式更简洁，性能更好。

### 6.6 内核启动参数

关键参数：
- `console=ttyAMA0`: ARM64标准串口
- `root=/dev/vda2`: virtio磁盘第二分区
- `rw`: 读写模式（必须）

### 6.7 PS1动态路径设置

使用 `PS1='$(pwd)# '`，无需额外函数或builtin。

---

## 7. 工具脚本详细用法

### 7.1 check-kvm.sh

```bash
scripts/check-kvm.sh
```

输出JSON报告，包含：
- KVM可用性
- 大页内存状态
- VFIO模块状态
- QEMU安装状态

### 7.2 download-image.sh

```bash
scripts/download-image.sh -o <output_path> -v <version>
# 示例:
scripts/download-image.sh -o . -v 24.03-LTS
```

### 7.3 fix-ssh-config.sh

```bash
scripts/fix-ssh-config.sh -i <image> [-p <password>]
# 示例:
scripts/fix-ssh-config.sh -i openEuler.qcow2
scripts/fix-ssh-config.sh -i openEuler.qcow2 -p mypassword
```

### 7.4 extract-kernel.sh

```bash
scripts/extract-kernel.sh -i <image>
# 示例:
scripts/extract-kernel.sh -i openEuler.qcow2
```

### 7.5 pin-cpu-1v1.sh

```bash
scripts/pin-cpu-1v1.sh <qemu_pid> <cpu_list>
# 示例:
scripts/pin-cpu-1v1.sh 12345 0,2,4,6
```

### 7.6 pin-cpu-range.sh

```bash
scripts/pin-cpu-range.sh <qemu_pid> <cpu_range>
# 示例:
scripts/pin-cpu-range.sh 12345 0-3
```

---

## 8. 高级配置参数叠加

### NUMA拓扑

```bash
-numa node,nodeid=0,cpus=0-1,mem=2G
-numa node,nodeid=1,cpus=2-3,mem=2G
```

### 大页内存

```bash
# Host端配置
echo 1024 > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages

# QEMU参数
-mem-path /dev/hugepages -mem-prealloc
```

### VFIO直通

```bash
# Host端准备
modprobe vfio_pci
lspci -nn  # 查看设备BDF

# QEMU参数
-device vfio-pci,host=0000:01:00.0
```

### 热迁移

**源端**：
```bash
# 启动虚拟机
qemu-system-aarch64 ... -incoming tcp:0:4444
```

**目标端**：
```bash
# 连接源端
migrate -d tcp:source_ip:4444
```

### 9p文件共享

```bash
-virtfs local,path=/host/path,mount_tag=hostshare,security_model=mapped-xattr,id=hostshare
```

### VIRTIO设备

```bash
-device virtio-balloon      # 内存气球
-device virtio-rng          # 随机数生成器
-device virtio-serial       # 串口设备
```