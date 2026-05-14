---
name: qemu-vm-launcher
description: QEMU虚拟机启动助手。触发条件：启动QEMU虚拟机、配置虚机、QEMU命令生成、openEuler镜像下载、内核编译。**必须在执行任何操作前完成配置向导,询问所有必选问题**。注意:本skill仅支持openEuler系统,使用qcow2镜像启动虚机。
allowed-tools: Bash(scripts/*), Bash(/usr/bin/*), Bash(/usr/sbin/*), Bash(/usr/local/bin/*), Bash(qemu-system-aarch64), Bash(wget), Bash(taskset), Bash(ls), Bash(find), Bash(cat), Bash(mkdir), Bash(chmod), Bash(xz), Bash(dd), Bash(mkfs.ext4), Bash(mount), Bash(umount), Bash(ps), Bash(du), Bash(grep), Bash(sed), Bash(awk), Bash(cp), Bash(rm), Bash(mv), Bash(ln), Bash(tr), Bash(which), Bash(busybox), Bash(ss), Bash(lsof), Bash(make), Bash(file)
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a subagent task, skip this skill.
</SUBAGENT-STOP>

# QEMU VM Launcher Skill

本skill帮助用户快速启动QEMU aarch64虚拟机。

**适用系统**: openEuler (aarch64)

**启动方案**: qcow2镜像(支持完整系统、SSH、网络)

---

## 产物存放目录

所有启动虚机所需的产物将存放在 **vm-bootkit** 目录下:
- `vm-bootkit/Image` - 编译的自定义内核(如选择编译选项)
- `vm-bootkit/vmlinuz` - 提取的镜像内内核(如选择提取选项)
- `vm-bootkit/initramfs.img` - 提取的initramfs(如选择提取选项)
- `vm-bootkit/openEuler.qcow2` - qcow2镜像
- `vm-bootkit/start-vm.sh` - 启动脚本

该目录将在虚机启动成功后生成,后续可直接使用脚本启动虚机。

---

## ⚠️ 脚本定位方法（执行任何脚本前必读）

skill可能安装在不同位置,执行脚本前必须先定位skill目录:

```bash
# 方法1: 使用find查找（推荐）
SKILL_DIR=$(find ~ -type d -name qemu-vm-launcher 2>/dev/null | head -1)

# 方法2: 查找常见安装位置
for dir in ~/.config/opencode/skills ~/.claude/skills ~/.agents/skills; do
    if [ -d "$dir/qemu-vm-launcher" ]; then
        SKILL_DIR="$dir/qemu-vm-launcher"
        break
    fi
done

# 验证找到
echo "Skill目录: $SKILL_DIR"
ls "$SKILL_DIR/scripts/"

# 执行脚本示例
$SKILL_DIR/scripts/check-kvm.sh
$SKILL_DIR/scripts/download-image.sh -o . -v 24.03-LTS
```

**所有文档中的脚本指令都需要加上 `$SKILL_DIR/scripts/` 前缀。**

---

## ⚠️ 权限要求（必须满足）

**执行前请确认当前用户具备以下权限,否则操作会失败:**

### Root权限操作（必须）

| 操作 | 原因 | 失败后果 |
|------|------|---------|
| `modprobe nbd` | 加载NBD模块以访问qcow2镜像 | 无法提取内核/修复SSH配置 |
| `mount /dev/nbd0p*` | 挂载镜像分区 | 无法修改镜像内文件 |
| 修改 `/etc/shadow` | 设置root密码 | SSH无法密码登录 |
| 修改 `/etc/ssh/sshd_config.d/` | 启用密码认证 | SSH连接被拒绝 |
| `ssh-keygen` 生成host keys | 修复空SSH keys | sshd服务无法启动 |
| 写入 `/sys/kernel/mm/hugepages/` | 配置大页内存 | 大页内存不可用 |

**建议**: 以root用户执行,或使用sudo提权。

### 设备访问权限

| 设备 | 权限 | 说明 |
|------|------|------|
| `/dev/kvm` | 读写 | KVM加速,否则使用TCG（启动慢5-10倍） |
| `/dev/nbd0` 等 | 读写 | NBD设备,用于挂载qcow2镜像 |

**检查命令**:
```bash
ls -la /dev/kvm && echo "KVM可用" || echo "使用TCG模式"
ls -la /dev/nbd0 2>/dev/null && echo "NBD可用" || echo "需加载nbd模块"
```

### 软件包安装权限

| 软件包 | 用途 | 安装命令 |
|--------|------|---------|
| qemu-system-aarch64 | QEMU虚拟机 | `yum install qemu-system-aarch64` |
| sshpass | SSH自动登录测试 | `yum install sshpass` |
| edk2-aarch64 | UEFI固件 | `yum install edk2-aarch64` |

**建议**: 提前安装,或在执行过程中允许yum安装。

### 权限检查脚本

```bash
# 检查当前用户权限
[ "$(id -u)" == "0" ] && echo "✓ Root权限" || echo "⚠ 需要sudo提权"

# 检查关键设备
[ -w /dev/kvm ] && echo "✓ KVM可用" || echo "⚠ 将使用TCG模式"
modprobe nbd max_part=8 2>/dev/null && echo "✓ NBD模块已加载" || echo "⚠ 无法加载NBD模块"

# 检查关键软件
which qemu-system-aarch64 && echo "✓ QEMU已安装" || echo "⚠ 需安装QEMU"
rpm -qa | grep edk2-aarch64 && echo "✓ 固件已安装" || echo "⚠ 需安装固件包"
```

---

## 核心流程（必须遵循）

### ⚠️ 执行顺序（强制）

```
步骤1: 环境检查
  ↓
步骤2: 配置向导（必须询问所有问题）
  ↓
步骤3: 镜像准备 + 内核准备（根据用户选择）
  ↓
步骤4: 启动虚机 + SSH连接验证（强制成功）
  ↓
步骤5: 生成脚本和vm-bootkit目录（验证通过后）
```

**重要**: 
- 步骤2的配置向导是强制性的,必须完成所有问题询问后才能进入步骤3
- 步骤4是任务结束条件,必须SSH成功连接虚机才能进入步骤5
- 步骤4会启动虚机进行实际验证,步骤5生成vm-bootkit目录和启动脚本

---

## 步骤1: 环境检查

检查以下内容:

```bash
# 1. QEMU是否安装
which qemu-system-aarch64 || yum install qemu-system-aarch64

# 2. KVM可用性
ls -la /dev/kvm 2>/dev/null && echo "KVM可用" || echo "将使用TCG模式"

# 3. 检查华为鲲鹏定制QEMU（影响启动方案选择）
qemu-system-aarch64 --version | grep -i "kunpeng\|huawei\|ubios"
# 若输出包含UBIOS,后续必须使用直接内核启动方案

# 4. 固件包（用于UEFI方案）
rpm -qa | grep edk2-aarch64 || yum install edk2-aarch64

# 5. SSH端口自动调度（无需用户选择）
SKILL_DIR=$(find ~ -type d -name qemu-vm-launcher 2>/dev/null | head -1)
PORT_RESULT=$($SKILL_DIR/scripts/check-port.sh)
SSH_PORT=$(echo $PORT_RESULT | python3 -c "import sys,json; print(json.load(sys.stdin)['available_port'])")
echo "自动分配SSH端口: $SSH_PORT"
# 记录端口用于后续命令生成
```

**端口调度逻辑**:
- 起始端口: 2222（默认SSH转发端口）
- 检查方法: ss + lsof双重检查
- 自动递增: 若2222被占用,自动尝试2223、2224...直到找到可用端口
- 最大范围: 65535
- **无需用户选择端口,skill完全自动管理**

---

## 步骤2: 配置向导（强制检查清单）

**必须在执行任何操作前询问以下所有问题。使用 `question` 工具逐一询问。**

### □ 问题1: 启动方式

| 选项 | 说明 |
|------|------|
| A) KVM加速 | 需要 /dev/kvm,启动快（30秒） |
| B) TCG模拟 | 纯软件,启动慢（60-120秒） |

**若用户选择KVM但环境检查显示不可用**: 提示并建议TCG。

---

### □ 问题2: CPU配置

询问:
- 核数（默认 4）
- 若选择TCG模式,CPU类型默认 `cortex-a72`
- 若选择KVM模式,CPU类型默认 `host` 或 `Kunpeng-920`（鲲鹏环境）

---

### □ 问题3: 内存配置

询问:
- 大小（默认 4G）
- 单位（M/G）

---

### □ 问题4: 内核来源选择（关键选择）

| 选项 | 说明 | 适用场景 | 后续流程 |
|------|------|---------|---------|
| A) 镜像内内核 | 提取qcow2内的vmlinuz + initramfs | 正常使用镜像系统 | 提取内核 |
| B) 自定义Image | 使用用户编译的内核Image | 测试内核新功能、调试 | 询问编译或使用已有 |

**若选择A) 镜像内内核**:
- 鲲鹏环境: 必须提取vmlinuz和initramfs.img
- 其他环境: 可选UEFI或直接内核启动

**若选择B) 自定义Image**:

**□ 问题4-B-1: 内核准备方式**

| 选项 | 说明 |
|------|------|
| A) 在本地编译内核 | 提供内核源码路径,自动编译 |
| B) 使用已有的Image | 提供已编译的Image文件路径 |

**若选择A) 在本地编译内核**:
- 询问内核源码路径（必需,如 `/root/openeuler/kernel`）
- 验证路径存在且包含内核源码（检查 `.config` 或 `Makefile`）
- 说明编译流程将:
  1. 修改必要的驱动为内置（virtio、ext4、vfat）
  2. 执行编译
  3. 将产物存放到 vm-bootkit/Image

**若选择B) 使用已有的Image**:
- 询问Image文件路径（必需）
- 验证Image文件存在且有效
- 验证Image是有效的内核: `file <IMAGE_PATH>`（应显示 "Linux kernel ARM64 executable"）
- 将Image复制到 vm-bootkit/Image

---

### □ 问题5: 是否需要高级配置

询问: **是否需要高级配置？**

若选择YES,逐一询问以下模块（可选）:

| 模块 | 配置项 |
|------|--------|
| NUMA拓扑 | 节点数量、CPU分配、内存分配 |
| 大页内存 | 传统大页或透明大页 |
| VFIO直通 | 设备BDF地址 |
| 热迁移 | 源端/目标端、IP和端口 |
| 9p文件共享 | Host目录路径 |
| CPU绑核 | 1v1绑核或范围绑核 |

---

## 步骤3: 镜像准备 + 内核准备

### 3-1: qcow2镜像准备

> ⚠️ **华为鲲鹏环境重要提示**:
> 鲕鹏定制QEMU使用标准UEFI固件会报"Synchronous Exception"错误。
> **必须使用直接内核启动方案**,提取镜像中的vmlinuz和initramfs.img。

**执行顺序**:

1. **下载openEuler镜像**:
   ```bash
   $SKILL_DIR/scripts/download-image.sh -o vm-bootkit -v 24.03-LTS
   ```

2. **SSH密码认证修复**（必须执行）:
   ```bash
   $SKILL_DIR/scripts/fix-ssh-config.sh -i vm-bootkit/openEuler.qcow2
   ```
   否则SSH无法密码登录。

---

### 3-2: 内核准备（根据问题4选择）

#### 方案A: 提取镜像内内核

若用户选择"镜像内内核":

```bash
$SKILL_DIR/scripts/extract-kernel.sh -i vm-bootkit/openEuler.qcow2 -o vm-bootkit
```

提取 vmlinuz 和 initramfs.img 文件到 vm-bootkit 目录。

**判断是否需要内核提取**:
- 检查QEMU是否为鲲鹏定制版本: `qemu-system-aarch64 -cpu help | grep Kunpeng`
- 若存在Kunpeng相关输出 → **必须提取内核**
- 若UEFI启动报"Synchronous Exception" → **必须提取内核**

---

#### 方案B: 使用自定义Image

若用户选择"自定义Image",根据问题4-B-1的子选择执行:

##### B-1: 本地编译内核

**步骤1: 验证内核源码路径**

```bash
# 验证路径存在
ls -la <KERNEL_SRC_PATH>

# 验证是内核源码目录
ls <KERNEL_SRC_PATH>/.config <KERNEL_SRC_PATH>/Makefile

# 检查现有编译状态
ls -la <KERNEL_SRC_PATH>/arch/arm64/boot/Image
file <KERNEL_SRC_PATH>/arch/arm64/boot/Image
```

**步骤2: 修改必要驱动为内置（关键！）**

使用自定义Image直接启动时无initramfs,必须将以下驱动改为内置（`=y`）:

```bash
# 修改内核配置
cd <KERNEL_SRC_PATH>

# virtio驱动（磁盘和网络）
sed -i 's/^CONFIG_VIRTIO=m/CONFIG_VIRTIO=y/' .config
sed -i 's/^CONFIG_VIRTIO_PCI=m/CONFIG_VIRTIO_PCI=y/' .config
sed -i 's/^CONFIG_VIRTIO_PCI_LIB=m/CONFIG_VIRTIO_PCI_LIB=y/' .config
sed -i 's/^CONFIG_VIRTIO_BLK=m/CONFIG_VIRTIO_BLK=y/' .config
sed -i 's/^CONFIG_VIRTIO_NET=m/CONFIG_VIRTIO_NET=y/' .config

# 文件系统驱动
sed -i 's/^CONFIG_FAT_FS=m/CONFIG_FAT_FS=y/' .config
sed -i 's/^CONFIG_VFAT_FS=m/CONFIG_VFAT_FS=y/' .config
sed -i 's/^CONFIG_EXT4_FS=m/CONFIG_EXT4_FS=y/' .config

# 验证修改
grep -E "^CONFIG_VIRTIO=|^CONFIG_VIRTIO_PCI=|^CONFIG_VIRTIO_BLK=|^CONFIG_VIRTIO_NET=|^CONFIG_VFAT_FS=|^CONFIG_EXT4_FS=" .config
```

**预期输出**:
```
CONFIG_VIRTIO_BLK=y
CONFIG_VIRTIO_NET=y
CONFIG_VIRTIO=y
CONFIG_VIRTIO_PCI_LIB=y
CONFIG_VIRTIO_PCI=y
CONFIG_VFAT_FS=y
CONFIG_EXT4_FS=y
```

**步骤3: 编译内核**

```bash
# 更新配置并编译
cd <KERNEL_SRC_PATH>
make olddefconfig
make -j$(nproc) Image

# 编译完成后验证
ls -la arch/arm64/boot/Image
file arch/arm64/boot/Image
```

**步骤4: 将产物复制到vm-bootkit**

```bash
mkdir -p vm-bootkit
cp <KERNEL_SRC_PATH>/arch/arm64/boot/Image vm-bootkit/Image
ls -la vm-bootkit/Image
```

---

##### B-2: 使用已有Image

若用户选择使用已有的Image文件:

```bash
# 验证Image文件
ls -la <IMAGE_PATH>
file <IMAGE_PATH>

# 预期输出: Linux kernel ARM64 boot executable Image, little-endian, 4K pages

# 复制到vm-bootkit
mkdir -p vm-bootkit
cp <IMAGE_PATH> vm-bootkit/Image
ls -la vm-bootkit/Image
```

---

## 步骤4: 启动虚机 + SSH连接验证（强制成功）

**⚠️ 这是任务关键验证步骤,必须SSH成功连接虚机才能进入步骤5生成脚本。**

本步骤会实际启动虚机并验证SSH连接,避免后续重复启动。

---

### 4-1: 启动虚机

根据启动模式设置超时:
- **KVM模式**: 启动时间约30秒
- **TCG模式**: 启动时间约60-120秒

**启动命令模板**:

#### 镜像内内核启动（提取vmlinuz/initramfs）

```bash
qemu-system-aarch64 \
  -machine virt,accel=<kvm/tcg> \
  -cpu <host/cortex-a72> \
  -smp <CORES> \
  -m <MEMORY> \
  -kernel vm-bootkit/vmlinuz \
  -initrd vm-bootkit/initramfs.img \
  -append "console=ttyAMA0 root=/dev/vda2 rw" \
  -drive file=vm-bootkit/openEuler.qcow2,if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::<SSH_PORT>-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

#### 自定义Image启动（无initramfs）

```bash
qemu-system-aarch64 \
  -machine virt,accel=<kvm/tcg> \
  -cpu <host/cortex-a72> \
  -smp <CORES> \
  -m <MEMORY> \
  -kernel vm-bootkit/Image \
  -append "console=ttyAMA0 root=/dev/vda2 rw" \
  -drive file=vm-bootkit/openEuler.qcow2,if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::<SSH_PORT>-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

**关键参数说明**:
| 参数 | 说明 |
|------|------|
| `-kernel vm-bootkit/Image` | 用户编译的内核Image文件 |
| `-append "root=/dev/vda2 rw"` | 内核直接挂载qcow2的第二分区（rootfs） |
| **无 `-initrd`** | 不使用initramfs,内核直接挂载root |

**自定义Image启动前提**:
- 内核必须内置 `virtio-blk`、`virtio-net`、`ext4` 驱动
- 内核配置需启用: `CONFIG_VIRTIO_BLK=y`、`CONFIG_VIRTIO_NET=y`、`CONFIG_EXT4_FS=y`

---

### 4-2: 观察启动过程

启动虚机后,观察串口输出判断启动状态:

**成功标志**:
- systemd启动完成
- 网络初始化完成
- 看到 "localhost login:" 提示
- 自定义内核显示版本: `Kernel 6.6.0+` 或类似

**失败标志**:
- "Synchronous Exception" → 切换到直接内核启动方案
- "Kernel panic - Unable to mount root fs" → 检查内核驱动是否内置
- "Failed to mount /boot" → 检查vfat驱动是否内置

---

### 4-3: 等待虚机完全启动

根据启动模式等待足够时间:

| 模式 | 等待时间 | 说明 |
|------|---------|------|
| KVM | 30-60秒 | 硬件加速,启动快 |
| TCG | 60-120秒 | 纯软件模拟,启动慢 |

```bash
MODE=<kvm/tcg>
if [ "$MODE" == "kvm" ]; then
    WAIT_TIME=45
else
    WAIT_TIME=90
fi

echo "等待虚机启动... ($WAIT_TIME秒)"
sleep $WAIT_TIME
```

---

### 4-4: SSH连接验证

使用 `ssh-test.sh` 进行连接测试:

```bash
# 基础测试（自动重试10次,间隔5秒）
$SKILL_DIR/scripts/ssh-test.sh -h localhost -p <SSH_PORT> -u root -P '{VM_PASSWORD}'

# TCG模式建议增加重试次数
$SKILL_DIR/scripts/ssh-test.sh -h localhost -p <SSH_PORT> -u root -P '{VM_PASSWORD}' -r 20 -i 10
```

**参数说明**:
| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-h` | 目标主机 | localhost |
| `-p` | SSH端口 | 2222 |
| `-u` | 用户名 | root |
| `-P` | 密码 | {VM_PASSWORD} |
| `-r` | 重试次数 | 10 |
| `-i` | 重试间隔(秒) | 5 |

---

### 4-5: 验证连接成功标志

**成功标志**:
```bash
# 成功输出示例
SSH连接成功！
主机名: localhost.localdomain
```

执行远程命令验证:
```bash
sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p <SSH_PORT> 'hostname; whoami; uname -a'

# 预期输出
localhost.localdomain
root
Linux localhost.localdomain 6.6.0+ (或5.10.0-xxx) aarch64 GNU/Linux
```

---

### 4-6: 连接失败排查

若SSH连接失败,按以下顺序排查:

| 错误 | 排查步骤 |
|------|---------|
| Permission denied | 1. 确认fix-ssh-config.sh已执行<br>2. 停止虚机,重新修复镜像后重启 |
| Connection reset by peer | 1. 等待更长时间（TCG需90-120秒）<br>2. 增加重试次数 |
| Connection refused | 1. 确认虚机已启动<br>2. 等待sshd服务启动 |
| REMOTE HOST IDENTIFICATION HAS CHANGED | 清理known_hosts: `ssh-keygen -R "[localhost]:2222"` |

---

### 4-7: 验证通过判定

**必须满足以下条件才能进入步骤5**:

1. ✅ SSH连接成功（无报错）
2. ✅ 能执行远程命令并返回结果
3. ✅ `hostname` 命令返回主机名

**若无法满足,需要继续排查直到SSH连接成功。**

---

## 步骤5: 生成启动脚本和vm-bootkit目录

**⚠️ 只有步骤4验证通过后才能生成脚本。**

生成的脚本可直接用于后续启动,无需再次验证。

---

### 5-1: 创建vm-bootkit目录结构

确保vm-bootkit目录包含所有必要文件:

```bash
ls -la vm-bootkit/

# 应包含:
# - Image 或 vmlinuz + initramfs.img（内核）
# - openEuler.qcow2（镜像）
# - start-vm.sh（启动脚本）
```

---

### 5-2: 生成启动脚本

#### 镜像内内核脚本

```bash
#!/bin/bash
#========================================
# qcow2虚拟机启动脚本
#========================================
# SSH连接方式:
#   ssh root@localhost -p <SSH_PORT>
# 
# 登录账号: root
# 登录密码: {VM_PASSWORD}
#
# 或使用sshpass自动登录:
#   sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p <SSH_PORT>
#========================================

qemu-system-aarch64 \
  -machine virt,accel=<kvm/tcg> \
  -cpu <host/cortex-a72> \
  -smp <CORES> \
  -m <MEMORY> \
  -kernel vm-bootkit/vmlinuz \
  -initrd vm-bootkit/initramfs.img \
  -append "console=ttyAMA0 root=/dev/vda2 rw" \
  -drive file=vm-bootkit/openEuler.qcow2,if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::<SSH_PORT>-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

#### 自定义内核脚本

```bash
#!/bin/bash
#========================================
# qcow2虚拟机启动脚本（自定义内核）
#========================================
# 内核: vm-bootkit/Image
# 说明: 使用自定义编译的内核Image,无initramfs
#       qcow2作为磁盘,内核直接挂载rootfs
#
# SSH连接方式:
#   ssh root@localhost -p <SSH_PORT>
# 
# 登录账号: root
# 登录密码: {VM_PASSWORD}
#
# 或使用sshpass自动登录:
#   sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p <SSH_PORT>
#========================================

qemu-system-aarch64 \
  -machine virt,accel=<kvm/tcg> \
  -cpu <host/cortex-a72> \
  -smp <CORES> \
  -m <MEMORY> \
  -kernel vm-bootkit/Image \
  -append "console=ttyAMA0 root=/dev/vda2 rw" \
  -drive file=vm-bootkit/openEuler.qcow2,if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::<SSH_PORT>-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

---

## 工具脚本参考

**脚本路径查找**:

skill目录可能安装在不同位置,执行前先查找:
```bash
SKILL_DIR=$(find ~ -type d -name qemu-vm-launcher 2>/dev/null | head -1)
echo "Skill目录: $SKILL_DIR"
```

**常见安装位置**:
- `~/.config/opencode/skills/qemu-vm-launcher/`
- `~/.claude/skills/qemu-vm-launcher/`

**脚本列表**:

| 脚本 | 功能 | 用法 |
|------|------|------|
| check-kvm.sh | 环境检查 | 输出JSON报告 |
| check-port.sh | 端口可用性检查 | `-p <port>` |
| ssh-test.sh | SSH连接测试 | `-h <host> -p <port>` |
| download-image.sh | 下载镜像 | `-o <path> -v <version>` |
| fix-ssh-config.sh | SSH密码认证修复 | `-i <image>` |
| extract-kernel.sh | 内核提取 | `-i <image> -o <output>` |
| pin-cpu-1v1.sh | 1v1绑核 | `<pid> <cpu_list>` |
| pin-cpu-range.sh | 范围绑核 | `<pid> <cpu_range>` |

---

## SSH连接指南

### SSH连接常见问题

**问题1: REMOTE HOST IDENTIFICATION HAS CHANGED**

解决:
```bash
ssh-keygen -R "[localhost]:2222"
sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222
```

**问题2: Permission denied (publickey,gssapi-with-mic)**

解决: 修复镜像SSH配置（必须停止虚机后执行）
```bash
pkill -f qemu-system-aarch64
$SKILL_DIR/scripts/fix-ssh-config.sh -i vm-bootkit/openEuler.qcow2
```

**问题3: SSH每次重启后失败**

解决: 确保fix-ssh-config.sh完整执行（含cloud.cfg修复）

---

### SSH连接方式

```bash
# 方式1: 使用sshpass（推荐）
sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222

# 方式2: 手动输入密码
ssh -o StrictHostKeyChecking=no root@localhost -p 2222
# 输入密码: {VM_PASSWORD}
```

---

## 常见问题速查

| 问题 | 解决方法 |
|------|---------|
| UEFI "Synchronous Exception" | 使用直接内核启动,提取镜像中的vmlinuz/initramfs |
| SSH无法密码登录 | 执行 scripts/fix-ssh-config.sh |
| SSH每次重启后失败 | 检查cloud.cfg的ssh_pwauth配置 |
| SSH host key每次变化 | 检查ssh_deletekeys是否设置为false |
| TCG模式启动慢 | 正常现象,等待60-120秒 |
| 华为鲲鹏定制QEMU | 必须使用直接内核启动方案,不能用UEFI |
| 自定义Image无法挂载root | 内核需内置virtio-blk/ext4驱动 |
| 编译内核失败 | 检查内核源码路径和依赖 |

---

## 必须内置的驱动清单（自定义Image）

使用自定义Image启动（无initramfs）时,以下驱动必须设为`=y`:

| 驋动 | 配置项 | 用途 |
|------|--------|------|
| virtio核心 | CONFIG_VIRTIO=y | virtio总线 |
| virtio PCI | CONFIG_VIRTIO_PCI=y | virtio PCI设备 |
| virtio_blk | CONFIG_VIRTIO_BLK=y | virtio磁盘驱动 |
| virtio_net | CONFIG_VIRTIO_NET=y | virtio网卡驱动 |
| ext4 | CONFIG_EXT4_FS=y | rootfs文件系统 |
| vfat | CONFIG_VFAT_FS=y | /boot分区（EFI） |
| fat | CONFIG_FAT_FS=y | FAT文件系统核心 |

---

## 详细参考文档

- **REFERENCE.md**: 详细步骤、错误排查、经验总结
- **docs/qemu-commands.md**: QEMU命令说明书

---

## 重要经验总结

1. **配置向导是强制性的**: 不询问完所有问题就跳过会导致配置不完整
2. **SSH修复必须完整执行**: fix-ssh-config.sh已包含cloud.cfg修复
3. **SSH验证在生成脚本前**: 步骤4验证通过后才能生成vm-bootkit
4. **TCG模式超时要长**: 纯软件模拟启动慢,需要60-120秒
5. **鲲鹏定制QEMU特殊性**: UBIOS不兼容标准固件,必须用直接内核启动
6. **脚本注释模板**: 生成的脚本必须包含SSH连接信息和密码
7. **自定义Image无initramfs**: 内核必须内置virtio驱动
8. **vm-bootkit目录**: 所有启动产物统一存放,方便后续使用
9. **内核编译流程**: 自动修改驱动配置为内置,确保能启动