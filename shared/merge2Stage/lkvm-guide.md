# LKVM 虚机启动指南

本文档介绍如何使用 lkvm 启动虚拟机的完整流程，包括创建最小根文件系统。

## 目录

- [环境准备](#环境准备)
- [创建最小根文件系统](#创建最小根文件系统)
- [启动 LKVM 虚机](#启动-lkvm-虚机)
- [常用命令](#常用命令)
- [常见问题](#常见问题)

---

## 环境准备

### 检查 LKVM

确保 lkvm 可执行文件存在：

```bash
ls -la lkvm Image
```

输出示例：

```
-rwxr-xr-x 1 root root 3081064 Apr  2 12:41 lkvm
-rw-r--r-- 1 root root 32991744 Apr  2 12:42 Image
```

### 查看 LKVM 帮助信息

```bash
./lkvm run --help
```

---

## 创建最小根文件系统

当没有现成的 rootfs 镜像时，可以创建一个简单的 initramfs（初始 RAM 文件系统）来启动虚机。

> **提示**: 也可以直接使用脚本自动完成以下步骤：
> ```bash
> /mnt/kernel/merge2Stage/build-initramfs.sh /root/openeuler_code/lkvm_test
> ```
> 脚本会自动在指定目录下创建 `initramfs.cpio.gz`。

### 1. 创建目录结构

```bash
mkdir -p /root/openeuler_code/lkvm_test/initramfs/{bin,sbin,etc,proc,sys,dev,lib,lib64}
```

### 2. 复制基础二进制文件

```bash
# 复制 shell 和基础命令
cp /usr/bin/ls /root/openeuler_code/lkvm_test/initramfs/bin/ls
cp /usr/bin/cat /root/openeuler_code/lkvm_test/initramfs/bin/cat
cp /usr/bin/echo /root/openeuler_code/lkvm_test/initramfs/bin/echo
cp /usr/bin/mkdir /root/openeuler_code/lkvm_test/initramfs/bin/mkdir
cp /usr/sbin/switch_root /root/openeuler_code/lkvm_test/initramfs/sbin/switch_root
cp /bin/bash /root/openeuler_code/lkvm_test/initramfs/bin/bash
cp /bin/sh /root/openeuler_code/lkvm_test/initramfs/bin/sh
```

### 3. 复制动态链接库

首先查看依赖：

```bash
ldd /bin/bash
```

输出示例：

```
    linux-vdso.so.1
    libtinfo.so.6 => /lib64/libtinfo.so.6
    libc.so.6 => /lib64/libc.so.6
    /lib/ld-linux-aarch64.so.1
```

复制所需库：

```bash
cp /lib64/libtinfo.so.6 /root/openeuler_code/lkvm_test/initramfs/lib64/
cp /lib64/libc.so.6 /root/openeuler_code/lkvm_test/initramfs/lib64/
cp /lib64/libdl.so.2 /root/openeuler_code/lkvm_test/initramfs/lib64/
cp /lib64/libc.so.6 /root/openeuler_code/lkvm_test/initramfs/lib/
cp /lib/ld-linux-aarch64.so.1 /root/openeuler_code/lkvm_test/initramfs/lib/
```

### 4. 创建 init 脚本

```bash
cat > /root/openeuler_code/lkvm_test/initramfs/init << 'EOF'
#!/bin/sh
echo "initramfs booting..."
mount -t proc none /proc
mount -t sysfs none /sys
mount -t devtmpfs none /dev
echo "Welcome to LKVM!"
/bin/sh
EOF
chmod +x /root/openeuler_code/lkvm_test/initramfs/init
```

### 5. 打包 initramfs

```bash
cd /root/openeuler_code/lkvm_test/initramfs
find . | cpio -o -H newc | gzip > /root/openeuler_code/lkvm_test/initramfs.cpio.gz
```

生成文件大小：

```bash
ls -lh /root/openeuler_code/lkvm_test/initramfs.cpio.gz
# -rw-r--r-- 1 root root 3.0M Apr  2 13:19 /root/openeuler_code/lkvm_test/initramfs.cpio.gz
```

---

## 启动 LKVM 虚机

### 基本启动命令

```bash
./lkvm run --name testvm \
    -k Image \
    --initrd /root/openeuler_code/lkvm_test/initramfs.cpio.gz \
    --console serial \
    --params "console=ttyS0 rdinit=/init" \
    -m 512 \
    --nodefaults
```

### 参数说明

| 参数 | 说明 |
|------|------|
| `--name <name>` | 虚机名称 |
| `-k, --kernel <file>` | 内核镜像文件 |
| `--initrd <file>` | 初始 RAM disk 文件 |
| `--console <type>` | 控制台类型：serial, virtio, hv |
| `--params <cmdline>` | 内核命令行参数 |
| `-m, --mem <size>` | 内存大小（默认单位 MB） |
| `-c, --cpus <n>` | CPU 数量 |
| `--nodefaults` | 禁用默认配置 |

### 完整参数列表

```bash
./lkvm run --help
```

**Basic options:**

```bash
    --name <guest name>          # 虚机名称
-c, --cpus <n>                   # CPU 数量
-m, --mem <size[BKMGTP]>         # 内存大小
-d, --disk <image or rootfs_dir> # 磁盘镜像或 rootfs 目录
    --vnc                        # 启用 VNC 帧缓冲
    --gtk                        # 启用 GTK 帧缓冲
    --sdl                        # 启用 SDL 帧缓冲
    --console <serial|virtio|hv> # 控制台类型
    --tty <tty id>               # 映射 Guest TTY 到主机 pty
    --9p <dir,tag>               # 启用 9p 共享目录
    --network <params>            # 网络配置
```

**Kernel options:**

```bash
-k, --kernel <kernel>            # 内核镜像
-i, --initrd <initrd>            # 初始 RAM disk
-p, --params <params>           # 内核命令行参数
```

**Arch-specific options:**

```bash
    --aarch32                    # 运行 AArch32 Guest
    --pmu                        # 创建 PMUv3 设备
    --disable-mte               # 禁用 Memory Tagging Extension
    --irqchip <gicv2|gicv3>     # 中断控制器类型
```

---

## 常用命令

### 查看运行中的虚机

```bash
./lkvm list
```

输出示例：

```
   PID NAME                 STATE
------------------------------------
 2298 testvm               running
```

### 停止虚机

```bash
./lkvm stop --name testvm
```

### 强制停止（如果普通停止无效）

```bash
pkill -9 lkvm
```

### 清理残留文件

```bash
rm -rf /root/.lkvm/*
```

### 后台运行虚机

```bash
./lkvm run --name testvm -k Image --initrd /root/openeuler_code/lkvm_test/initramfs.cpio.gz \
    --console serial --params "console=ttyS0 rdinit=/init" \
    -m 512 --nodefaults 2>&1 &
```

### 查看虚机输出

虚机输出会写入 `/root/.lkvm/` 目录下的日志文件，或通过后台任务输出查看。

---

## 常见问题

### 1. "Fatal: unable to save initial standard input settings"

**问题原因**: 终端配置问题

**解决方法**: 使用 `--nodefaults` 选项，或在后台运行

### 2. "Guest socket file /root/.lkvm/testvm.sock already exists"

**问题原因**: 残留的 socket 文件

**解决方法**:

```bash
rm -rf /root/.lkvm/*
pkill -9 lkvm
```

### 3. "KVM: HYP mode not available"

**问题原因**: 当前环境不支持硬件虚拟化或 KVM 未加载

**说明**: 这是一个警告，虚机仍可以运行（使用软件模拟）

### 4. "Kernel panic - not syncing: VFS: Unable to mount root fs"

**问题原因**: 没有可用的根文件系统

**解决方法**:
- 提供 `--initrd` 参数指定 initramfs
- 或使用 `--disk` 参数指定磁盘镜像/目录作为根文件系统

### 5. initramfs 中命令找不到

**问题原因**: initramfs 中缺少必要的命令

**解决方法**: 在 initramfs 中添加所需命令的副本及其依赖库

---

## 进阶用法

### 使用磁盘镜像

```bash
# 创建空磁盘镜像
dd if=/dev/zero of=disk.img bs=1M count=1024

# 格式化为 ext4
mkfs.ext4 -F disk.img

# 启动时挂载
./lkvm run --name testvm -k Image --disk disk.img \
    --console serial -m 512
```

### 共享主机目录（9p）

```bash
./lkvm run --name testvm -k Image \
    --9p /path/on/host,tag_name \
    --params "console=ttyS0 root=9p rootfstype=9p" \
    -m 512
```

### 启用网络

```bash
./lkvm run --name testvm -k Image \
    --network mode=tap \
    --console serial -m 512
```

### 启用 VNC

```bash
./lkvm run --name testvm -k Image \
    --console virtio --vnc \
    -m 512
```

---

## 参考资料

- LKVM 是 User-mode Linux KVM 工具
- 本测试环境使用 ARM64 架构（linux,dummy-virt）
- 内核版本：6.6.0+
