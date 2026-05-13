---
name: qemu-vm-launcher
description: QEMU虚拟机启动助手，提供镜像准备、配置向导、命令生成等功能。触发条件：启动QEMU虚拟机、配置虚机、QEMU命令生成、openEuler镜像下载、minifs构建。**注意：本skill仅支持openEuler系统**。
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a subagent task, skip this skill.
</SUBAGENT-STOP>

# QEMU VM Launcher Skill

本skill帮助用户快速启动QEMU aarch64虚拟机，提供完整的镜像准备、配置向导和命令生成流程。

**适用系统**: openEuler (aarch64)

**核心功能**:
- 镜像准备：openEuler qcow2下载或minifs构建
- 分层配置向导：核心配置 + 高级配置（可选）
- QEMU命令自动生成
- SSH密码认证修复
- 完整脚本工具集

**使用场景**:
- openEuler开发调试
- CI/CD自动化测试环境
-鲲鹏平台虚拟化测试

---

## 二、工作流程

### ⚠️ 强制约束：自测验证

**重要**: 在生成启动脚本或执行命令前，必须进行自测验证：

1. **必须验证启动命令能正常运行**
   - 根据启动模式设置不同超时时间：
     - **KVM模式**: `timeout 30` (30秒足够)
     - **TCG模式**: `timeout 60` 或更长 (纯软件模拟启动较慢)
   - 观察输出是否正常进入系统启动流程
   - 若出现UEFI异常（如 "Synchronous Exception"），需要调整方案

2. **验证流程**：
   ```bash
   # KVM模式测试（超时30秒）
   timeout 30 qemu-system-aarch64 -machine virt,accel=kvm <参数...> 2>&1 | tail -100
   
   # TCG模式测试（超时60秒，建议更长时间）
   timeout 60 qemu-system-aarch64 -machine virt,accel=tcg <参数...> 2>&1 | tail -100
   
   # 检查关键输出
   # - 成功标志：systemd启动、网络设备初始化
   # - 失败标志：Synchronous Exception、固件错误
   ```

3. **未通过验证的处理**：
   - 调整启动方案（如从UEFI改为直接内核启动）
   - 重新测试直到成功
   - 验证通过后再生成最终脚本

---

### 步骤1: 环境检查

调用脚本检查环境状态：

```bash
./scripts/check-kvm.sh
```

输出JSON格式报告，包含：
- KVM可用性
- 大页内存状态
- VFIO模块状态
- QEMU安装状态
- **QEMU版本信息**（检查是否为定制版本）

**检查必要软件包（openEuler）**：
```bash
# 检查QEMU
rpm -qa | grep qemu-system-aarch64

# 若未安装
yum install qemu-system-aarch64

# 检查固件包
rpm -qa | grep edk2-aarch64

# 若未安装
yum install edk2-aarch64

# 检查nbd模块支持
modprobe nbd max_part=8 || echo "需要配置nbd模块"

# 检查xorriso（创建ISO）
which xorriso || yum install xorriso

# 检查sshpass（SSH测试）
which sshpass || yum install sshpass
```

**特别检查华为鲲鹏定制QEMU**：
```bash
# 检查是否为华为鲲鹏定制版本
qemu-system-aarch64 --version | grep -i "kunpeng\|huawei\|ubios"

# 若输出包含UBIOS相关信息，需要使用直接内核启动方案
```

根据报告提示用户可用选项。

---

### 步骤2: 镜像准备

**检查当前目录**:
```bash
ls *.qcow2 *.img 2>/dev/null
```

**若已有镜像**: 跳过准备，记录文件名

**若无镜像**: 询问用户选择：

**问题0: 镜像方案选择（必须首先询问）**

A) 下载/使用qcow2镜像（完整系统，支持SSH）
B) 构建Minimal Initramfs虚拟机（raw格式，快速测试）
C) 使用现有镜像（列出当前目录的镜像）

**下载openEuler qcow2**:
```bash
./scripts/download-image.sh -o . -v 24.03-LTS
```

**构建Minimal Initramfs**（参见步骤2-B详细流程）:
```bash
./scripts/build-minifs.sh -o ./minifs.img -s 200M
# 然后按步骤2-B.1至2-B.7构建initramfs
```

---

## 步骤2-B: 构建Minimal Initramfs虚拟机（分步骤）

**适用场景**：
- 无KVM环境，需要TCG模拟启动
- 无UEFI固件或固件不兼容
- 快速测试，不需要完整系统功能
- Raw格式镜像需求

**特点**：
- 使用Host系统内核（无需UEFI固件）
- Raw格式镜像（非qcow2）
- Minimal busybox系统，无SSH/网络功能
- 直接在串口控制台交互
- 启动速度快

### 2-B.1 检查环境和安装依赖

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

### 2-B.2 构建minifs raw镜像

```bash
# 创建空文件
dd if=/dev/zero of=minifs.img bs=1 count=0 seek=200M

# 创建ext4文件系统
mkfs.ext4 -F minifs.img

# 验证
file minifs.img
# 输出应为: minifs.img: data
ls -lh minifs.img
# 输出应为: 约200M大小的文件
```

### 2-B.3 构建minimal initramfs

**关键点**：
1. busybox动态链接器必须放在正确的路径 `/lib/ld-linux-aarch64.so.1`
2. **busybox不一定支持所有命令**（如vi），需检查后创建链接
3. PS1显示路径需要特殊处理（busybox ash限制）

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

# 【关键】检查busybox是否支持特定命令
busybox --list | grep vi
# 输出: 如果没有"vi"，说明busybox不支持！
# 可用编辑器: ed, hexedit（而非vi）

# 添加基础命令
for cmd in sh ash ls cat echo mount umount mkdir mknod sleep ln rm cp mv; do
    ln -sf busybox $cmd
done

# 添加常用工具（先检查是否支持）
for cmd in touch grep sed awk head tail ps kill free df du dmesg hostname uname; do
    if busybox --list | grep -q "^$cmd$"; then
        ln -sf busybox $cmd
    else
        echo "警告: busybox不支持 $cmd"
    fi
done

# 添加编辑器（busybox通常支持ed和hexedit，不一定支持vi）
busybox --list | grep -E "vi|ed|nano|hexedit"
ln -sf busybox ed
ln -sf busybox hexedit  # 如果支持

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
# 设置PS1显示当前路径（busybox ash使用$PWD或$(pwd)）
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

# 设置ENV变量，shell启动时自动加载profile
export ENV=/etc/profile

# 直接设置PS1（双保险）
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

**常见错误排查**：

| 错误现象 | 原因 | 解决方法 |
|---------|------|---------|
| `Failed to execute /init (error -2)` | 动态链接器路径错误 | 确保 `/lib/ld-linux-aarch64.so.1` 存在 |
| `Kernel panic - not syncing` | init脚本格式错误 | 使用 `ln -sf bin/busybox init` 而非脚本 |
| `vi: applet not found` | busybox不支持vi | 使用ed或hexedit替代 |
| `builtin: not found` | busybox ash不支持builtin | profile中不要使用builtin命令 |
| `touch: not found` | 命令符号链接缺失 | 先检查busybox是否支持该命令 |
| shell不显示当前路径 | PS1设置无效 | 使用 `PS1='$(pwd)# '` |
| cd后路径不更新 | busybox ash限制 | 使用`$(pwd)`动态获取，无需特殊函数 |

**已验证的功能列表**（测试通过）：

| 功能 | 命令 | 测试结果 |
|-----|------|---------|
| 目录操作 | mkdir, cd, pwd | ✓ 正常 |
| 文件操作 | touch, cat, echo | ✓ 正常 |
| 搜索过滤 | grep | ✓ 正常 |
| 系统信息 | ps, free, df | ✓ 正常 |
| 路径显示 | PS1='$(pwd)# ' | ✓ 正常 |
| 编辑器 | ed | ✓ 可用 |

**重要提示**：
- **busybox不支持vi**：openEuler的busybox编译时未包含vi applet
- **可用编辑器**：ed（行编辑器）、hexedit（十六进制编辑器）
- **PS1动态路径**：使用 `PS1='$(pwd)# '`，无需额外函数或builtin
- **已添加386个命令**：添加所有busybox支持的命令

---

### 2-B.4 确认用户需要的工具

**在打包initramfs前，引导用户确认需要的工具**：

```bash
echo "=========================================="
echo "当前已添加的工具:"
echo "=========================================="
ls -la initramfs/bin | grep "^l" | awk '{print $NF}' | tr '\n' ' '
echo ""
echo ""

echo "=========================================="
echo "请确认是否需要添加其他工具:"
echo "=========================================="
echo ""

# 显示busybox支持的工具分类
echo "【文件操作】"
echo "已添加: ls, cat, cp, mv, rm, touch"
busybox --list | grep -E "more|less|head|tail|find|xargs|sort|uniq|cut|tr" | tr '\n' ' '
echo ""
echo ""

echo "【编辑器】"
busybox --list | grep -E "ed|hexedit|sed|awk" | tr '\n' ' '
echo ""
echo "注意: busybox不支持vi/vim"
echo ""

echo "【系统信息】"
echo "已添加: ps, free, df, du, uname, hostname"
busybox --list | grep -E "top|uptime|loadavg|dmesg|lsof" | tr '\n' ' '
echo ""
echo ""

echo "【网络工具】"
busybox --list | grep -E "ifconfig|ip|ping|wget|curl|route|netstat|nc|telnet|httpd" | tr '\n' ' '
echo ""
echo ""

echo "【进程管理】"
busybox --list | grep -E "kill|killall|pkill|pgrep|top|nice|renice|nohup" | tr '\n' ' '
echo ""
echo ""

# 交互式确认
read -p "是否添加网络工具? [y/N]: " add_net
if [[ "$add_net" == "y" ]]; then
    for cmd in ifconfig ip ping wget curl nc; do
        if busybox --list | grep -q "^$cmd$"; then
            ln -sf busybox initramfs/bin/$cmd
            echo "已添加: $cmd"
        fi
    done
fi

read -p "是否添加进程管理工具? [y/N]: " add_proc
if [[ "$add_proc" == "y" ]]; then
    for cmd in killall pkill pgrep top; do
        if busybox --list | grep -q "^$cmd$"; then
            ln -sf busybox initramfs/bin/$cmd
            echo "已添加: $cmd"
        fi
    done
fi

read -p "是否添加所有busybox支持的命令? [y/N]: " add_all
if [[ "$add_all" == "y" ]]; then
    for cmd in $(busybox --list); do
        [ -e "initramfs/bin/$cmd" ] || ln -sf busybox initramfs/bin/$cmd
    done
    echo "已添加所有命令: $(busybox --list | wc -l) 个"
fi

read -p "是否添加其他特定命令? (输入命令名，空格分隔): " custom_cmds
if [ -n "$custom_cmds" ]; then
    for cmd in $custom_cmds; do
        if busybox --list | grep -q "^$cmd$"; then
            ln -sf busybox initramfs/bin/$cmd
            echo "已添加: $cmd"
        else
            echo "警告: busybox不支持 '$cmd'"
        fi
    done
fi

echo ""
echo "最终添加的命令数量: $(ls -la initramfs/bin | grep "^l" | wc -l)"
echo ""

# 确认继续打包
read -p "确认打包initramfs? [Y/n]: " confirm
if [[ "$confirm" != "n" ]]; then
    cd initramfs
    find . | cpio -H newc -o | gzip > ../initrd-minimal.img
    echo "打包完成: ../initrd-minimal.img"
fi
```

**自动化版本（非交互式）**：
```bash
# 直接添加所有busybox命令（推荐）
cd initramfs/bin
for cmd in $(busybox --list); do
    [ -e "$cmd" ] || ln -sf busybox $cmd
done
echo "已添加所有命令: $(ls -la | grep "^l" | wc -l) 个"
cd initramfs
find . | cpio -H newc -o | gzip > ../initrd-minimal.img
```

**常见错误排查**：

| 错误现象 | 原因 | 解决方法 |
|---------|------|---------|
| `Failed to execute /init (error -2)` | 动态链接器路径错误 | 确保 `/lib/ld-linux-aarch64.so.1` 存在 |
| `Kernel panic - not syncing` | init脚本格式错误 | 使用 `ln -sf bin/busybox init` 而非脚本 |
| initramfs太小(<1M) | 动态库未复制 | 检查并复制 libm/libresolv/libc |
| `touch: not found` | 命令符号链接缺失 | 添加更多命令链接（参见步骤2） |
| `vi: not found` | 命令符号链接缺失 | busybox内置vi，需创建链接 |

**常用命令分类表（供用户参考）**：

| 类别 | 基础命令（已添加） | 可选命令（需确认） |
|-----|------------------|------------------|
| 文件操作 | ls, cat, cp, mv, rm, touch, vi | ed, nano, more, less, head, tail, diff, patch |
| 查找过滤 | grep, sed, awk | find, xargs, locate, sort, uniq, cut, tr |
| 系统信息 | ps, free, df, du, uname, hostname | top, uptime, loadavg, lsof, strace |
| 网络 | - | ifconfig, ip, ping, wget, curl, route, netstat, nc |
| 进程控制 | kill | killall, pkill, pgrep, nice, renice, nohup |
| 用户/环境 | - | whoami, id, groups, env, printenv, which, whereis |
| 归档 | tar, gzip, gunzip | bzip2, xz, zip, unzip, cpio |
| 磁盘 | mount, umount | fdisk, mkfs, fsck, blkid, df |
| 时间日期 | date, cal, sleep | crontab, at, hwclock |
| Shell | sh, ash | bash（需额外安装） |

**查看busybox支持的命令列表**：
```bash
busybox --list | wc -l           # 查看总数（约300+）
busybox --list | grep -E "vi|touch|grep|sed"  # 查看特定命令
busybox --list | grep -i net     # 查看网络相关命令
busybox --list | sort | column   # 按字母排序显示
```

### 2-B.5 获取内核文件

```bash
# 自动检测Host内核
KERNEL=$(ls -t /boot/vmlinuz-*aarch64 | grep -v rescue | head -1)
echo "内核: $KERNEL"

# 或手动指定
KERNEL=/boot/vmlinuz-6.6.0-132.0.0.111.oe2403sp3.aarch64

# 验证内核文件存在
ls -lh $KERNEL
```

### 2-B.6 测试启动命令

```bash
# 测试启动（TCG模式需要较长超时）
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

# 检查关键输出
# ✓ 成功: 显示 "Welcome to Minimal VM!" 和 shell提示符 "#"
# ✗ 失败: 显示 "Kernel panic" 或 "Failed to execute /init"
```

### 2-B.7 生成启动脚本（必须包含注释模板）

**重要**：所有启动脚本必须遵循注释模板规范，包含必要信息。

```bash
# 获取内核版本
KERNEL_VER=$(basename $KERNEL | sed 's/vmlinuz-//')

cat > start-minimal-vm.sh << 'EOF'
#!/bin/bash
#========================================
# Minimal Initramfs虚拟机启动脚本
#========================================
# 虚机类型: Minimal Initramfs (无SSH/网络)
# 镜像格式: raw
# 内核版本: KERNEL_VERSION_PLACEHOLDER
#
# 使用方式:
#   ./start-minimal-vm.sh
#
# 交互方式:
#   直接在串口控制台操作（无SSH）
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
  -kernel KERNEL_PATH_PLACEHOLDER \
  -initrd ./initrd-minimal.img \
  -append "console=ttyAMA0" \
  -drive file=./minifs.img,if=virtio,format=raw \
  -nographic
EOF

# 替换占位符
sed -i "s|KERNEL_VERSION_PLACEHOLDER|$KERNEL_VER|g" start-minimal-vm.sh
sed -i "s|KERNEL_PATH_PLACEHOLDER|$KERNEL|g" start-minimal-vm.sh

chmod +x start-minimal-vm.sh

# 验证脚本内容
head -20 start-minimal-vm.sh
```

**注释模板必须包含的信息**：

| 字段 | 说明 | 示例 |
|-----|------|------|
| 虚机类型 | 启动方案类型 | Minimal Initramfs / UEFI / 直接内核启动 |
| 镜像格式 | 镜像文件格式 | raw / qcow2 |
| 内核版本 | 使用的内核版本 | 6.6.0-132.0.0.111.oe2403sp3.aarch64 |
| 使用方式 | 启动命令 | ./start-minimal-vm.sh |
| 交互方式 | SSH或串口 | SSH端口转发 / 串口控制台 |
| 可用工具 | 可用编辑器和命令 | ed, hexedit; ls, cd, cat... |
| 退出方式 | 如何退出虚拟机 | Ctrl+A X / SSH断开 |

### 2-B.8 启动虚拟机

```bash
./start-minimal-vm.sh

# 在虚拟机shell中可执行:
# ls          # 列出文件
# cat /proc/cpuinfo  # 查看CPU信息
# free -h     # 查看内存
# mount       # 查看挂载

# 退出: Ctrl+A 然后按 X
```

**文件清单**：
```
minifs.img           # Raw格式磁盘镜像 (200M)
initrd-minimal.img   # Minimal initramfs (1-2M)
start-minimal-vm.sh  # 启动脚本
```

---

### 步骤3: 配置向导

**⚠️ 重要：启动虚拟机前必须询问用户核心需求**

#### 第一层：核心配置（必选）

**问题0: 镜像方案选择（第一步必须询问）**

A) qcow2镜像方案（完整系统）
   - 使用openEuler等完整镜像
   - 支持SSH、网络、完整功能
   - 需要UEFI固件或内核提取
   - 镜像格式：qcow2

B) Minimal Initramfs方案（最小系统）
   - 使用Host内核 + 自建initramfs
   - 无SSH/网络，串口交互
   - 快速启动，适合测试
   - 镜像格式：raw

**根据用户选择进入不同流程**：

| 用户选择 | 后续流程 | 参考步骤 |
|---------|---------|---------|
| A) qcow2 | 标准配置流程 | 步骤2-A, 步骤4 |
| B) Minimal | 简化配置流程 | 步骤2-B |

---

**问题1: 启动方式**

A) KVM加速（需要/dev/kvm）
B) TCG模拟（纯软件）

若选择KVM但不可用，提示并建议TCG。

**问题2: CPU配置**

- 核数（默认4）
- CPU类型（默认host / cortex-a72）

**问题3: 内存配置**

- 大小（默认4G / 2G）
- 单位（M/G）

**问题4: 镜像选择**

根据问题0的选择：

**若选择A) qcow2**：
- 列出当前目录的qcow2镜像
- 或询问是否下载openEuler镜像
- 询问SSH端口（默认2222）

**若选择B) Minimal**：
- 确认是否需要构建minifs镜像
- 确认是否需要构建initramfs
- 询问需要的工具命令（参见步骤2-B.4）

#### 第二层：高级配置（可选）

询问：**是否需要高级配置？**

若选择YES，逐一询问以下模块：

**NUMA拓扑**:
- 是否配置NUMA？
- 节点数量、CPU分配、内存分配

**大页内存**:
- 是否使用大页？
- 传统大页（需要Host配置）或透明大页

**设备配置**:
- VFIO直通（需要设备BDF）
- VIRTIO设备（balloon/rng/serial）

**热迁移**:
- 目标端或源端
- IP地址和端口

**Guest-Host通信**:
- 网络通信（SSH端口转发）
- 9p文件共享（Host目录）
- 文件固化到minifs

**CPU绑核**:
- 启动后是否绑核？
- 1v1绑核或范围绑核

#### 第三层：启动选项

- 立即执行
- 保存为脚本
- 输出命令
- 后台运行

---

### 步骤4: 命令生成与验证

#### 4.1 方案选择

**优先检测QEMU类型**：
```bash
# 检查是否为华为鲲鹏定制版本
qemu-system-aarch64 -cpu help | grep -i Kunpeng
```

**三种启动方案**：

| 方案 | 适用场景 | 镜像格式 | 说明 |
|------|---------|---------|------|
| UEFI启动 | 标准QEMU | qcow2 | 使用-bios或pflash加载固件 |
| 直接内核启动 | 定制QEMU或UEFI异常 | qcow2 | 使用-kernel/-initrd绕过固件，从镜像提取内核 |
| Minimal Initramfs启动 | 快速测试/无KVM环境 | **raw** | 使用Host内核+自定义initramfs，参见步骤2-B |

**方案选择建议**：
- 需要完整系统功能（SSH、网络）→ 选择方案A或B
- 只需要快速测试shell → 选择方案C（Minimal Initramfs）
- 无qcow2镜像或需要raw格式 → 选择方案C

#### 4.2 方案A: UEFI固件启动（标准QEMU）

**固件查找**：
```bash
# 查找可用固件
find /usr/share -name "*edk2*aarch64*" -o -name "*AAVMF*" 2>/dev/null

# 常见固件路径
/usr/share/edk2/aarch64/QEMU_EFI.fd        # 基础固件
/usr/share/edk2/aarch64/QEMU_EFI-pflash.raw  # pflash格式
/usr/share/AAVMF/AAVMF_CODE.fd             # 标准AAVMF
```

**基础框架**:
```bash
qemu-system-aarch64 \
  -machine virt,accel=${accel} \
  -cpu ${cpu} \
  -smp ${smp} \
  -m ${memory} \
  -bios ${bios} \
  -drive file=${image},if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::${ssh_port}-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

#### 4.3 方案B: 直接内核启动（定制QEMU/UEFI异常）

**适用场景**：
- 华为鲲鹏定制QEMU（含UBIOS）
- UEFI固件出现 "Synchronous Exception"
- 需要快速启动无需UEFI

**内核提取步骤**：
```bash
# 1. 检查qemu-nbd是否可用
which qemu-nbd && modprobe nbd max_part=8

# 2. 连接镜像到nbd设备
qemu-nbd --connect=/dev/nbd0 ${image}
sleep 2

# 3. 挂载启动分区
mkdir -p /tmp/mount
mount /dev/nbd0p1 /tmp/mount  # 通常p1是/boot分区

# 4. 复制内核和initramfs
cp /tmp/mount/vmlinuz-* ./vmlinuz
cp /tmp/mount/initramfs-* ./initramfs.img

# 5. 断开连接
umount /tmp/mount
qemu-nbd --disconnect /dev/nbd0
```

**直接内核启动命令**：
```bash
qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a72 \
  -smp ${smp} \
  -m ${memory} \
  -kernel vmlinuz \
  -initrd initramfs.img \
  -append "console=ttyAMA0 root=/dev/vda2 rw" \
  -drive file=${image},if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::${ssh_port}-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

**内核启动参数说明**：
- `console=ttyAMA0`: ARM串口控制台
- `root=/dev/vda2`: 根分区（virtio磁盘第二分区）
- `rw`: 读写模式

#### 4.4 自测验证（必须执行）

**重要**: TCG模式启动速度比KVM慢5-10倍，需设置更长超时时间。

```bash
# 测试UEFI启动方案
# KVM模式: timeout 30
# TCG模式: timeout 60 (建议)
timeout 30 qemu-system-aarch64 <参数> 2>&1 | tail -100

# 检查结果
# ✓ 成功：显示 "UEFI firmware" 后进入GRUB或系统启动
# ✗ 失败：显示 "Synchronous Exception at 0x..." 

# 若失败，切换到直接内核启动方案
# KVM模式: timeout 30
# TCG模式: timeout 60-90 (TCG启动完整系统需要60-100秒)
timeout 60 qemu-system-aarch64 -kernel vmlinuz <其他参数> 2>&1 | tail -100

# 检查结果
# ✓ 成功：显示 systemd 启动、网络初始化
```

**超时时间建议表**：

| 启动模式 | 验证阶段 | 建议超时时间 |
|---------|---------|------------|
| KVM | UEFI/内核启动验证 | 30秒 |
| KVM | 等待SSH可用 | 40秒 |
| TCG | UEFI/内核启动验证 | 60秒 |
| TCG | 等待SSH可用 | 90-120秒 |
| TCG | 完整系统启动（含cloud-init） | 120秒+ |

#### 4.5 高级参数叠加规则

- NUMA: `-numa node,nodeid=N,cpus=N-N,mem=N`
- 大页: `-mem-path /dev/hugepages -mem-prealloc`
- VFIO: `-device vfio-pci,host=DDDD:BB:DD.F`
- 热迁移目标: `-incoming tcp:0:4444`
- 9p共享: `-virtfs local,path=/path,mount_tag=tag,...`
- balloon: `-device virtio-balloon`
- rng: `-device virtio-rng`

---

### 步骤5: 输出/执行

**输出形式**:
1. 打印完整命令
2. 保存为start-vm.sh脚本（chmod +x）
3. 立即执行（可选后台：nohup ... &）

**脚本模板规范（必须遵循）**:

生成的 `start-vm.sh` 脚本必须包含以下格式的注释：

```bash
#!/bin/bash
#========================================
# QEMU虚拟机启动脚本
#========================================
# SSH连接方式:
#   ssh root@localhost -p <SSH_PORT>
# 
# 登录账号: root
# 登录密码: <PASSWORD>
#
# 注意: 每次重启虚拟机后SSH host key会变化，
#       连接前需先清除旧key:
#       ssh-keygen -R "[localhost]:<SSH_PORT>"
# 
# 或使用sshpass自动登录（忽略host key检查）:
#       sshpass -p '<PASSWORD>' ssh -o StrictHostKeyChecking=no root@localhost -p <SSH_PORT>
#========================================

qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a72 \
  -smp <CPU_CORES> \
  -m <MEMORY> \
  -kernel vmlinuz \
  -initrd initramfs.img \
  -append "console=ttyAMA0 root=/dev/vda2 rw" \
  -drive file=<IMAGE>,if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::<SSH_PORT>-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

**注释字段说明**：
- `SSH_PORT`: SSH端口转发端口（如2222、2223）
- `PASSWORD`: root密码（如{VM_PASSWORD}）
- `<IMAGE>`: 镜像文件名
- `<CPU_CORES>`: CPU核数
- `<MEMORY>`: 内存大小

**SSH连接问题说明**：

每次重启虚拟机后SSH连接可能出现 "REMOTE HOST IDENTIFICATION HAS CHANGED" 错误，原因：
- cloud-init在启动时会重新生成SSH host keys
- Host端的known_hosts中保存的是旧key

**解决方法**：
```bash
# 方法1: 每次连接前清除旧key
ssh-keygen -R "[localhost]:2222"
ssh root@localhost -p 2222

# 方法2: 使用sshpass跳过host key检查（推荐）
sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222
```

**附加提示**:
- SSH登录方式（已在脚本注释中）
- 绑核命令（如配置）
- Monitor命令（如热迁移）

---

### 步骤6: SSH密码认证修复（必须）

**重要**: openEuler云镜像默认禁用SSH密码认证，必须执行修复。

**使用修复脚本**：
```bash
# 修复SSH配置并设置root密码
./scripts/fix-ssh-config.sh -i openEuler.qcow2

# 或指定自定义密码
./scripts/fix-ssh-config.sh -i openEuler.qcow2 -p mypassword
```

**修复内容**：
1. 生成SSH host keys（rsa/ecdsa/ed25519）
2. 删除cloud-init的密码禁用配置
3. 设置root密码

**注意**：修复后启动虚拟机即可SSH密码登录，无需cloud-init。

---

## 三、文档参考

阅读以下文档了解详细参数：

- **docs/qemu-commands.md**: QEMU命令说明书
- **docs/qemu-params.yaml**: 参数校验规则和默认值
- **docs/qemu-reference.md**: 完整参数参考

---

## 四、模板参考

使用模板加速配置：

- **templates/basic.yaml**: 基础启动
- **templates/numa.yaml**: NUMA拓扑
- **templates/vfio.yaml**: VFIO直通
- **templates/migration.yaml**: 热迁移
- **templates/virtio.yaml**: VIRTIO设备

---

## 五、脚本工具

**scripts/check-kvm.sh**: 环境检查，输出JSON报告

**scripts/download-image.sh**: 
```bash
./scripts/download-image.sh -o <path> -v <version>
```

**scripts/build-minifs.sh**:
```bash
./scripts/build-minifs.sh -o <path> -s <size> [--with-dev-tools]
```

**scripts/pin-cpu-1v1.sh**:
```bash
./scripts/pin-cpu-1v1.sh <qemu_pid> <cpu_list>
# 示例: ./scripts/pin-cpu-1v1.sh 12345 0,2,4,6
```

**scripts/pin-cpu-range.sh**:
```bash
./scripts/pin-cpu-range.sh <qemu_pid> <cpu_range>
# 示例: ./scripts/pin-cpu-range.sh 12345 0-3
```

---

## 六、快速示例

**基础启动脚本（start-vm.sh）**:
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
  -machine virt,accel=kvm \
  -cpu host \
  -smp 4 \
  -m 4G \
  -bios edk2-aarch64-code.fd \
  -drive file=openEuler.qcow2,if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

**TCG模式启动脚本（无KVM环境）**:
```bash
#!/bin/bash
#========================================
# QEMU虚拟机启动脚本 (TCG模式)
#========================================
# SSH连接方式:
#   ssh root@localhost -p 2222
# 
# 登录账号: root
# 登录密码: {VM_PASSWORD}
#
# 注意: 
# 1. TCG模式启动较慢，请等待60-120秒后SSH连接
# 2. 每次重启虚拟机后SSH host key会变化，
#    连接前需先清除旧key:
#    ssh-keygen -R "[localhost]:2222"
# 
# 或使用sshpass自动登录（推荐）:
#       sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222
#========================================

qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a72 \
  -smp 2 \
  -m 2G \
  -kernel vmlinuz \
  -initrd initramfs.img \
  -append "console=ttyAMA0 root=/dev/vda2 rw" \
  -drive file=openEuler.qcow2,if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```
# 注意: TCG模式启动较慢，需等待60-120秒
#========================================

qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a72 \
  -smp 2 \
  -m 2G \
  -kernel vmlinuz \
  -initrd initramfs.img \
  -append "console=ttyAMA0 root=/dev/vda2 rw" \
  -drive file=openEuler.qcow2,if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

**启动和连接流程**:
```bash
# 1. 启动虚拟机
chmod +x start-vm.sh
./start-vm.sh

# 2. 等待启动完成
# KVM模式: 等待30-40秒
# TCG模式: 等待60-120秒

# 3. SSH连接（参考脚本注释中的信息）
ssh root@localhost -p 2222
# 输入密码: {VM_PASSWORD}

# 或使用sshpass自动输入密码
sshpass -p '{VM_PASSWORD}' ssh root@localhost -p 2222
```
```

---

## 七、注意事项

### 华为鲲鹏定制QEMU特殊处理

**识别标志**：
- QEMU版本包含 "UBIOS" 字样
- CPU列表包含 "Kunpeng-920" 等型号
- 启动日志显示 "ubios-information-table"

**兼容性问题**：
- 标准AAVMF固件与鲲鹏UBIOS不兼容
- 使用 `-bios` 会触发 "Synchronous Exception"

**解决方案**：
- **必须使用直接内核启动**（-kernel/-initrd）
- 提取镜像中的vmlinuz和initramfs

### CPU类型选择

**鲲鹏环境**：
```bash
# 可用CPU类型
qemu-system-aarch64 -cpu help | grep Kunpeng

# 建议使用
-cpu Kunpeng-920    # 鲲鹏920
-cpu cortex-a72     # 通用ARM Cortex-A72
-cpu max            # 启用所有特性
```

**标准环境**：
```bash
-cpu host           # 使用Host CPU特性
-cpu cortex-a57     # ARM Cortex-A57
```

### 固件查找

```bash
find /usr/share -name "edk2-aarch64-code.fd" 2>/dev/null
find /usr/share -name "QEMU_EFI*.fd" 2>/dev/null
find /usr/share -name "AAVMF*.fd" 2>/dev/null
```

### KVM检查

```bash
[ -e /dev/kvm ] && echo "KVM可用" || echo "使用TCG"
```

### 大页配置

```bash
echo 1024 > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages
```

### VFIO准备

```bash
modprobe vfio_pci
lspci -nn  # 查看设备BDF
```

### 驱动器接口

**推荐使用 virtio**：
```bash
-drive file=${image},if=virtio,format=qcow2
```

**相比传统方式的优势**：
- if=virtio 比 if=none + virtio-blk-pci 更简洁
- 性能更好，配置更少

---

## 八、常见问题

### Q: UEFI启动出现 "Synchronous Exception"？

**原因**：华为鲲鹏定制QEMU的UBIOS与标准AAVMF固件不兼容。

**解决**：
1. 使用直接内核启动方案
2. 从镜像中提取vmlinuz和initramfs
3. 使用 `-kernel` 和 `-initrd` 参数启动

---

### Q: 找不到固件文件？

**解决**：
```bash
# 搜索固件
find /usr/share -name "*aarch64*.fd" 2>/dev/null

# 安装固件包（openEuler）
yum install edk2-aarch64
```

### Q: KVM不可用？

**检查**：
```bash
ls -la /dev/kvm
```

**解决**：
- 检查权限：`chmod 666 /dev/kvm`
- 或使用TCG模式（纯软件模拟）

### Q: 网络无法SSH？

**检查**：
1. hostfwd端口配置：`hostfwd=tcp::2222-:22`
2. Guest内sshd是否运行：`systemctl status sshd`
3. 防火墙规则

### Q: 热迁移失败？

**确保**：
- 两端配置一致
- 存储共享或同步迁移
- 相同QEMU版本

### Q: 如何提取内核文件？

**步骤**：
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
cp /mnt/vmlinuz-* vmlinuz
cp /mnt/initramfs-* initramfs.img

# 6. 断开
umount /mnt
qemu-nbd --disconnect /dev/nbd0
```

### Q: Minimal虚拟机中命令找不到（如touch、vi）？

**原因**：构建initramfs时未创建足够的命令符号链接，或busybox不支持该命令。

**解决方法1：检查busybox支持哪些命令**

```bash
# 查看busybox支持的所有命令
busybox --list | wc -l           # 总数约300+

# 检查特定命令
busybox --list | grep vi         # 查看是否支持vi
busybox --list | grep -E "ed|hexedit"  # 查看可用编辑器

# 如果输出为空，说明busybox不支持该命令
```

**解决方法2：添加支持的命令链接**

```bash
cd initramfs/bin

# 添加前先检查
for cmd in touch grep sed awk ps; do
    if busybox --list | grep -q "^$cmd$"; then
        ln -sf busybox $cmd
        echo "已添加: $cmd"
    else
        echo "busybox不支持: $cmd"
    fi
done

# 添加所有支持的命令
for cmd in $(busybox --list); do
    [ -e "$cmd" ] || ln -sf busybox $cmd
done

# 重新打包
cd initramfs
find . | cpio -H newc -o | gzip > ../initrd-minimal.img
```

**解决方法3：使用替代编辑器**

```bash
# busybox不支持vi，使用以下替代方案：
ed filename      # 行编辑器（基本可用）
hexedit filename # 十六进制编辑器

# 或在虚拟机中使用
cat > file.txt << 'EOF'
内容...
EOF
```

### Q: Shell不显示当前路径或cd后路径不更新？

**原因**：busybox ash不支持PS1的`\w`转义序列。

**解决方法**：使用/etc/profile中的函数方式

```bash
# 在initramfs/etc/profile中添加
cat > etc/profile << 'EOF'
set_prompt() {
    PS1="$(pwd)# "
}
cd() {
    builtin cd "$@" && set_prompt
}
set_prompt
export PS1
EOF

# 确保rcS加载profile
[ -f /etc/profile ] && . /etc/profile
```

**效果**：
- 提示符显示当前路径：`/root# `、`/tmp# `
- cd命令后路径自动更新

### Q: 启动脚本执行报错？

**必须先自测验证**：
```bash
# KVM模式测试
timeout 30 ./start-vm.sh

# TCG模式测试（需要更长超时）
timeout 60 ./start-vm.sh

# 观察输出是否有错误
# 确认能看到systemd启动日志
```

**TCG模式启动慢的原因**：
- 纯软件模拟CPU指令
- 无硬件加速支持
- 启动时间通常是KVM的5-10倍

---

## 九、实战经验总结

### 经验1: 华为鲲鹏定制QEMU兼容性

**问题现象**：
- 使用 `-bios QEMU_EFI.fd` 启动
- UEFI输出后立即出现 `Synchronous Exception at 0x...`
- 无法进入系统

**根本原因**：
- 鲲鹏QEMU内置UBIOS框架
- 标准AAVMF固件未适配UBIOS内存布局
- 固件尝试访问UBIOS预留内存区域时异常

**解决方案**：
- 使用直接内核启动绕过UEFI
- 不依赖固件，直接加载Linux内核

### 经验2: 驱动器接口选择

**对比**：

| 方式 | 命令 | 说明 |
|-----|------|------|
| 传统 | `-drive file=img,if=none,id=hd0 -device virtio-blk-pci,drive=hd0` | 复杂 |
| 简化 | `-drive file=img,if=virtio` | 推荐 |

**推荐使用简化方式**，减少配置复杂度。

### 经验3: 自测验证必要性

**必须执行自测的原因**：
- 不同QEMU版本行为差异大
- 固件兼容性问题难以预测
- 环境差异导致启动失败

**验证标准**：
- ✓ 看到 systemd 启动消息
- ✓ 网络设备初始化成功
- ✓ 能看到登录提示或shell

### 经验4: openEuler云镜像SSH密码认证问题

**问题现象**：
- SSH连接提示 `Permission denied (publickey,gssapi-with-mic)`
- sshd服务启动失败或密码认证被禁用
- 每次重启虚拟机后密码认证失效

**根本原因**：
1. **SSH host keys缺失**：镜像中的 `/etc/ssh/ssh_host_*_key` 文件为空（0字节）
2. **密码认证被cloud-init禁用**：`/etc/ssh/sshd_config.d/50-cloud-init.conf` 包含 `PasswordAuthentication no`
3. **cloud.cfg配置错误**：`/etc/cloud/cloud.cfg` 中 `ssh_pwauth: false` 导致每次启动都禁用密码认证
4. **root密码未设置**：openEuler云镜像默认没有预设root密码

**解决方案**：

**步骤1：修复SSH host keys**
```bash
# 挂载镜像
modprobe nbd max_part=8
qemu-nbd --connect=/dev/nbd0 image.qcow2
mount /dev/nbd0p2 /mnt

# 删除空key文件并重新生成
rm -f /mnt/etc/ssh/ssh_host_*_key*
ssh-keygen -t rsa -b 4096 -f /mnt/etc/ssh/ssh_host_rsa_key -N "" -q
ssh-keygen -t ecdsa -b 256 -f /mnt/etc/ssh/ssh_host_ecdsa_key -N "" -q
ssh-keygen -t ed25519 -f /mnt/etc/ssh/ssh_host_ed25519_key -N "" -q

# 设置权限
chown root:polkitd /mnt/etc/ssh/ssh_host_*_key
chmod 600 /mnt/etc/ssh/ssh_host_*_key
```

**步骤2：启用密码认证（必须执行两项修改）**
```bash
# 删除cloud-init的禁用配置
rm /mnt/etc/ssh/sshd_config.d/50-cloud-init.conf

# 添加密码认证配置
echo "PasswordAuthentication yes" > /mnt/etc/ssh/sshd_config.d/01-password.conf
chmod 644 /mnt/etc/ssh/sshd_config.d/01-password.conf

# 【关键】修改cloud.cfg防止每次启动重置
sed -i 's/ssh_pwauth: false/ssh_pwauth: true/' /mnt/etc/cloud/cloud.cfg
```

**步骤3：设置root密码**
```bash
# 生成密码hash
HASH=$(openssl passwd -6 '{VM_PASSWORD}')

# 更新shadow文件
echo "root:$HASH:19000:0:99999:7:::" > /mnt/etc/shadow.new
tail -n +2 /mnt/etc/shadow >> /mnt/etc/shadow.new
mv /mnt/etc/shadow.new /mnt/etc/shadow

# 设置权限
chmod 640 /mnt/etc/shadow
chown root:root /mnt/etc/shadow
```

**步骤4：断开并启动**
```bash
umount /mnt
qemu-nbd --disconnect /dev/nbd0

# 启动虚拟机
qemu-system-aarch64 -kernel vmlinuz -initrd initramfs.img ...
```

**重要提示**：
- 只删除 `50-cloud-init.conf` 不够，必须修改 `cloud.cfg` 中的 `ssh_pwauth`
- 否则每次启动cloud-init都会重新禁用密码认证
- 使用 `sshpass` 连接可避免host key变化问题

### 经验5: 内核启动参数

**关键参数**：
- `console=ttyAMA0`: ARM64标准串口
- `root=/dev/vda2`: virtio磁盘第二分区
- `rw`: 读写模式（必须）

**分区说明**：
- vda1: /boot分区（存放内核）
- vda2: / 根分区（系统）
- 可通过 `ls /dev/nbd0*` 确认

### 经验6: SSH测试命令

**使用sshpass测试密码登录**：
```bash
# 清除旧host keys
ssh-keygen -R "[localhost]:2222"
rm -f ~/.ssh/known_hosts

# 使用sshpass测试
sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222 'hostname'
```

**注意**：
- 非交互模式下SSH在host key变化时会禁用密码认证
- 必须先清除known_hosts或使用sshpass工具

### 经验7: TCG模式启动超时设置

**问题现象**：
- TCG模式下使用30秒超时测试
- 输出被截断，无法看到完整启动过程
- 误判为启动失败

**根本原因**：
- TCG是纯软件CPU模拟，无硬件加速
- 启动速度比KVM慢5-10倍
- openEuler完整启动需要60-100秒

**超时时间建议**：

| 场景 | KVM模式 | TCG模式 |
|-----|--------|--------|
| 启动命令验证 | 30秒 | 60秒 |
| 内核启动验证 | 30秒 | 60-90秒 |
| 等待SSH服务可用 | 40秒 | 90-120秒 |
| 完整启动（含cloud-init） | 60秒 | 120秒+ |

**验证命令示例**：
```bash
# TCG模式完整启动验证
timeout 90 qemu-system-aarch64 \
  -machine virt,accel=tcg \
  -cpu cortex-a72 \
  -kernel vmlinuz \
  -initrd initramfs.img \
  -append "console=ttyAMA0 root=/dev/vda2 rw" \
  -drive file=image.qcow2,if=virtio \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic 2>&1 | tail -100
```

**判断成功的标准**：
- ✓ 看到 "Started Serial Getty on ttyAMA0"
- ✓ 看到 "Reached target Login Prompts"
- ✓ 看到 "localhost login:" 提示
- ✓ 网络设备状态显示 "DRIVER OK"

### 经验8: 脚本模板规范的重要性

**问题现象**：
- 生成的start-vm.sh脚本缺少SSH连接信息
- 用户不知道如何连接虚拟机
- 账号密码信息缺失，无法登录

**规范要求**：
生成的脚本必须包含以下注释块：
```bash
#!/bin/bash
#========================================
# QEMU虚拟机启动脚本
#========================================
# SSH连接方式:
#   ssh root@localhost -p <SSH_PORT>
# 
# 登录账号: root
# 登录密码: <PASSWORD>
#========================================
```

**为什么要遵循此规范**：
1. **信息完整性**: 用户无需额外查找连接方式
2. **自动化友好**: 脚本可被其他工具解析提取连接信息
3. **文档化**: 脚本本身就是使用文档
4. **一致性**: 所有生成的脚本格式统一

**错误示例**（缺少注释）：
```bash
#!/bin/bash
qemu-system-aarch64 -machine virt ...  # 用户不知道如何连接
```

**正确示例**（包含完整注释）：
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
#========================================

qemu-system-aarch64 -machine virt ...
```