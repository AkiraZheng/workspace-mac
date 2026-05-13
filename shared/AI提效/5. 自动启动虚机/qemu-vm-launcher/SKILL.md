---
name: qemu-vm-launcher
description: QEMU虚拟机启动助手。触发条件：启动QEMU虚拟机、配置虚机、QEMU命令生成、openEuler镜像下载、minifs构建。**必须在执行任何操作前完成配置向导，询问所有必选问题**。注意：本skill仅支持openEuler系统。
allowed-tools: Bash(scripts/*), Bash(/usr/bin/*), Bash(/usr/sbin/*), Bash(/usr/local/bin/*), Bash(qemu-system-aarch64), Bash(wget), Bash(taskset), Bash(ls), Bash(find), Bash(cat), Bash(mkdir), Bash(chmod), Bash(xz), Bash(dd), Bash(mkfs.ext4), Bash(mount), Bash(umount), Bash(ps), Bash(du), Bash(grep), Bash(sed), Bash(awk), Bash(cp), Bash(rm), Bash(mv), Bash(ln), Bash(tr), Bash(which), Bash(busybox), Bash(ss), Bash(lsof)
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a subagent task, skip this skill.
</SUBAGENT-STOP>

# QEMU VM Launcher Skill

本skill帮助用户快速启动QEMU aarch64虚拟机。

**适用系统**: openEuler (aarch64)

---

## ⚠️ 脚本定位方法（执行任何脚本前必读）

skill可能安装在不同位置，执行脚本前必须先定位skill目录：

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

**执行前请确认当前用户具备以下权限，否则操作会失败：**

### Root权限操作（必须）

| 操作 | 原因 | 失败后果 |
|------|------|---------|
| `modprobe nbd` | 加载NBD模块以访问qcow2镜像 | 无法提取内核/修复SSH配置 |
| `mount /dev/nbd0p*` | 挂载镜像分区 | 无法修改镜像内文件 |
| 修改 `/etc/shadow` | 设置root密码 | SSH无法密码登录 |
| 修改 `/etc/ssh/sshd_config.d/` | 启用密码认证 | SSH连接被拒绝 |
| `ssh-keygen` 生成host keys | 修复空SSH keys | sshd服务无法启动 |
| 写入 `/sys/kernel/mm/hugepages/` | 配置大页内存 | 大页内存不可用 |

**建议**：以root用户执行，或使用sudo提权。

### 设备访问权限

| 设备 | 权限 | 说明 |
|------|------|------|
| `/dev/kvm` | 读写 | KVM加速，否则使用TCG（启动慢5-10倍） |
| `/dev/nbd0` 等 | 读写 | NBD设备，用于挂载qcow2镜像 |

**检查命令**：
```bash
ls -la /dev/kvm && echo "KVM可用" || echo "使用TCG模式"
ls -la /dev/nbd0 2>/dev/null && echo "NBD可用" || echo "需加载nbd模块"
```

### 软件包安装权限

| 软件包 | 用途 | 安装命令 |
|--------|------|---------|
| qemu-system-aarch64 | QEMU虚拟机 | `yum install qemu-system-aarch64` |
| busybox | Minimal系统构建 | `yum install busybox` |
| edk2-aarch64 | UEFI固件 | `yum install edk2-aarch64` |
| sshpass | SSH自动登录测试 | `yum install sshpass` |

**建议**：提前安装，或在执行过程中允许yum安装。

### 权限检查脚本

```bash
# 检查当前用户权限
[ "$(id -u)" == "0" ] && echo "✓ Root权限" || echo "⚠ 需要sudo提权"

# 检查关键设备
[ -w /dev/kvm ] && echo "✓ KVM可用" || echo "⚠ 将使用TCG模式"
modprobe nbd max_part=8 2>/dev/null && echo "✓ NBD模块已加载" || echo "⚠ 无法加载NBD模块"

# 检查关键软件
which qemu-system-aarch64 && echo "✓ QEMU已安装" || echo "⚠ 需安装QEMU"
which busybox && echo "✓ Busybox已安装" || echo "⚠ 需安装Busybox"
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
步骤3: 镜像准备（根据用户选择）
  ↓
步骤4: 测试验证（必须通过）
  ↓
步骤5: 生成脚本
```

**重要**: 步骤2的配置向导是强制性的，必须完成所有问题询问后才能进入步骤3。

---

## 步骤1: 环境检查

检查以下内容：

```bash
# 1. QEMU是否安装
which qemu-system-aarch64 || yum install qemu-system-aarch64

# 2. KVM可用性
ls -la /dev/kvm 2>/dev/null && echo "KVM可用" || echo "将使用TCG模式"

# 3. 检查华为鲲鹏定制QEMU（影响启动方案选择）
qemu-system-aarch64 --version | grep -i "kunpeng\|huawei\|ubios"
# 若输出包含UBIOS，后续必须使用直接内核启动方案

# 4. Busybox（用于Minimal方案）
which busybox || yum install busybox

# 5. 固件包（用于qcow2 UEFI方案）
rpm -qa | grep edk2-aarch64 || yum install edk2-aarch64
```

---

## 步骤2: 配置向导（强制检查清单）

**必须在执行任何操作前询问以下所有问题。使用 `question` 工具逐一询问。**

### □ 问题0: 镜像方案选择（第一步必问）

| 选项 | 说明 | 后续流程 |
|------|------|---------|
| A) qcow2镜像 | 完整系统，支持SSH/网络，需要UEFI固件或内核提取 | 步骤2-A |
| B) Minimal Initramfs | Host内核+最小系统，无SSH/网络，快速启动测试，镜像格式raw | 步骤2-B |

---

### □ 问题1: 启动方式

| 选项 | 说明 |
|------|------|
| A) KVM加速 | 需要 /dev/kvm，启动快（30秒） |
| B) TCG模拟 | 纯软件，启动慢（60-120秒） |

**若用户选择KVM但环境检查显示不可用**：提示并建议TCG。

---

### □ 问题2: CPU配置

询问：
- 核数（默认 4）
- 若选择TCG模式，CPU类型默认 `cortex-a72`
- 若选择KVM模式，CPU类型默认 `host` 或 `Kunpeng-920`（鲲鹏环境）

---

### □ 问题3: 内存配置

询问：
- 大小（默认：qcow2方案 4G，Minimal方案 2G）
- 单位（M/G）

---

### □ 问题4: 镜像选择（根据问题0）

**若选择A) qcow2**：
- 检查当前目录是否有qcow2镜像
- 若无：询问是否下载openEuler镜像（使用 scripts/download-image.sh）
- 询问SSH端口（默认 2222）
- **自动检查端口可用性**：调用 scripts/check-port.sh
  - 若端口被占用：自动递增寻找可用端口（2222 → 2223 → 2224...）
  - 提示用户：`端口 2222 已被占用，将使用端口 2223`
  - 记录最终端口用于后续命令生成

**若选择B) Minimal**：
- 确认是否需要构建minifs镜像（使用脚本或手动构建）
- 确认是否需要构建initramfs（询问需要的工具命令）

---

### □ 问题5: 是否需要高级配置

询问：**是否需要高级配置？**

若选择YES，逐一询问以下模块（可选）：

| 模块 | 配置项 |
|------|--------|
| NUMA拓扑 | 节点数量、CPU分配、内存分配 |
| 大页内存 | 传统大页或透明大页 |
| VFIO直通 | 设备BDF地址 |
| 热迁移 | 源端/目标端、IP和端口 |
| 9p文件共享 | Host目录路径 |
| CPU绑核 | 1v1绑核或范围绑核 |

---

### □ 问题6: 启动选项

| 选项 | 说明 |
|------|------|
| A) 保存为脚本(推荐) | 生成 start-vm.sh |
| B) 立即执行 | 直接运行QEMU命令 |
| C) 后台运行 | nohup ... & |

---

## 步骤3: 镜像准备（根据方案选择）

### 方案A: qcow2镜像准备 

> ⚠️ **华为鲲鹏环境重要提示**：
> 鲲鹏定制QEMU使用标准UEFI固件会报"Synchronous Exception"错误。
> **必须使用直接内核启动方案**，提取镜像中的vmlinuz和initramfs.img。

**执行顺序**：

1. **下载openEuler镜像**：
   ```bash
   $SKILL_DIR/scripts/download-image.sh -o <path> -v 24.03-LTS
   ```

2. **SSH密码认证修复**（必须执行）：
   ```bash
   $SKILL_DIR/scripts/fix-ssh-config.sh -i openEuler.qcow2
   ```
   否则SSH无法密码登录。

3. **内核提取**（鲲鹏环境必须，其他环境可选）：
   ```bash
   $SKILL_DIR/scripts/extract-kernel.sh -i openEuler.qcow2
   ```
   提取 vmlinuz 和 initramfs.img 文件。

**判断是否需要内核提取**：
- 检查QEMU是否为鲲鹏定制版本：`qemu-system-aarch64 -cpu help | grep Kunpeng`
- 若存在Kunpeng相关输出 → **必须提取内核**
- 若UEFI启动报"Synchronous Exception" → **必须提取内核**

---

### 方案B: Minimal Initramfs准备

详细步骤请查看：**REFERENCE.md** 第2-B节

**关键步骤摘要**：
1. 创建 raw 镜像：`dd if=/dev/zero of=minifs.img bs=1 count=0 seek=200M && mkfs.ext4 -F minifs.img`
2. 构建 initramfs：复制busybox、创建命令链接、复制动态库、创建init和rcS
3. 打包：`find . | cpio -H newc -o | gzip > initrd-minimal.img`
4. 获取内核：使用 `/boot/vmlinuz-*aarch64`

**重要提示**：
- busybox不支持vi，可用编辑器：ed、hexedit
- 必须复制动态链接器 `/lib/ld-linux-aarch64.so.1`
- PS1设置：`PS1='$(pwd)# '`

---

## 步骤4: 测试验证（强制）

**在生成启动脚本前必须执行自测验证**

根据启动模式设置超时：
- **KVM模式**: `timeout 30`
- **TCG模式**: `timeout 60-90`

```bash
# 方案A测试（UEFI或直接内核）
timeout 30 qemu-system-aarch64 -machine virt,accel=<kvm/tcg> <其他参数> 2>&1 | tail -50

# 方案B测试（Minimal）
timeout 60 qemu-system-aarch64 -kernel <KERNEL> -initrd initrd-minimal.img <其他参数> 2>&1 | tail -50
```

**成功标志**：
- 方案A：systemd启动、网络初始化、看到登录提示
- 方案B：显示 "Welcome to Minimal VM!" 和 shell提示符

**失败标志**：
- "Synchronous Exception" → 切换到直接内核启动方案
- "Failed to execute /init" → 检查动态链接器路径
- "Kernel panic" → 检查init脚本格式

---

## 步骤5: 生成启动脚本

### 脚本注释模板（必须遵循）

```bash
#!/bin/bash
#========================================
# <虚机类型>启动脚本
#========================================
# SSH连接方式（qcow2方案）:
#   ssh root@localhost -p <SSH_PORT>
# 
# 登录账号: root
# 登录密码: <PASSWORD>
#
# 或使用sshpass自动登录:
#   sshpass -p '<PASSWORD>' ssh -o StrictHostKeyChecking=no root@localhost -p <SSH_PORT>
#
# 交互方式（Minimal方案）:
#   直接在串口控制台操作
#   退出: Ctrl+A 然后按 X
#========================================
```

### 方案A命令模板

**UEFI启动**（适用于标准QEMU，非鲲鹏定制版本）：

> ⚠️ **注意**：华为鲲鹏定制QEMU不支持标准UEFI固件，使用此方式会报"Synchronous Exception"。

**固件查找顺序**：
```bash
# 优先查找openEuler标准路径
find /usr/share/edk2/aarch64 -name "QEMU_EFI.fd" 2>/dev/null
find /usr/share/AAVMF -name "*.fd" 2>/dev/null
find /usr/share/qemu -name "*.fd" 2>/dev/null
```

**推荐固件路径**：
- openEuler: `/usr/share/edk2/aarch64/QEMU_EFI.fd`
- 其他: `/usr/share/AAVMF/AAVMF_CODE.fd`

```bash
qemu-system-aarch64 \
  -machine virt,accel=<kvm/tcg> \
  -cpu <host/cortex-a72> \
  -smp <CORES> \
  -m <MEMORY> \
  -bios <FIRMWARE> \
  -drive file=<IMAGE>,if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::<SSH_PORT>-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

**直接内核启动**（鲲鹏定制QEMU或UEFI异常）：
```bash
qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a72 \
  -smp <CORES> \
  -m <MEMORY> \
  -kernel vmlinuz \
  -initrd initramfs.img \
  -append "console=ttyAMA0 root=/dev/vda2 rw" \
  -drive file=<IMAGE>,if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::<SSH_PORT>-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

### 方案B命令模板

```bash
qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a72 \
  -smp <CORES> \
  -m <MEMORY> \
  -kernel <KERNEL_PATH> \
  -initrd initrd-minimal.img \
  -append "console=ttyAMA0" \
  -drive file=minifs.img,if=virtio,format=raw \
  -nographic
```

---

## 工具脚本参考

**脚本路径查找**：

skill目录可能安装在不同位置，执行前先查找：
```bash
# 查找skill目录
SKILL_DIR=$(find ~ -type d -name qemu-vm-launcher 2>/dev/null | head -1)
echo "Skill目录: $SKILL_DIR"

# 然后使用脚本
$SKILL_DIR/scripts/check-kvm.sh
```

**常见安装位置**：
- `~/.config/opencode/skills/qemu-vm-launcher/`
- `~/.claude/skills/qemu-vm-launcher/`

**脚本列表**：

| 脚本 | 功能 | 用法 |
|------|------|------|
| check-kvm.sh | 环境检查 | 输出JSON报告 |
| check-port.sh | 端口可用性检查 | `-p <port>` |
| ssh-test.sh | SSH连接测试（自动清理known_hosts） | `-h <host> -p <port>` |
| download-image.sh | 下载镜像 | `-o <path> -v <version>` |
| fix-ssh-config.sh | SSH密码认证修复（镜像内） | `-i <image>` |
| extract-kernel.sh | 内核提取 | `-i <image>` |
| build-minifs.sh | 构建minifs | `-o <path> -s <size>` |
| pin-cpu-1v1.sh | 1v1绑核 | `<pid> <cpu_list>` |
| pin-cpu-range.sh | 范围绑核 | `<pid> <cpu_range>` |

---

## SSH连接指南

### 测试SSH连接

虚机启动后，使用 `ssh-test.sh` 测试连接：

```bash
# 基础测试（自动清理known_hosts）
$SKILL_DIR/scripts/ssh-test.sh

# 自定义参数
$SKILL_DIR/scripts/ssh-test.sh -h localhost -p 2222 -u root -P '{VM_PASSWORD}'
```

**脚本功能**：
- 自动清理 known_hosts 中的旧记录（解决HOST IDENTIFICATION错误）
- 重试连接（默认10次，间隔5秒）
- 输出详细排查建议

### SSH连接常见问题

**问题1: REMOTE HOST IDENTIFICATION HAS CHANGED**

原因：之前连接过该端口但主机已更换（不同虚机使用同一端口）

解决：
```bash
# 方法1：清理known_hosts
ssh-keygen -R "[localhost]:2222"

# 方法2：使用StrictHostKeyChecking=no（推荐）
sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222
```

**问题2: Connection reset by peer / kex_exchange_identification错误**

原因：SSH服务未完全启动或SSH配置问题

解决：
```bash
# 方法1：等待虚机完全启动（TCG模式需要60-90秒）
sleep 60

# 方法2：使用ssh-test.sh自动重试
$SKILL_DIR/scripts/ssh-test.sh -r 20 -i 10  # 重试20次，间隔10秒

# 方法3：检查SSH配置是否已修复
# 确保 fix-ssh-config.sh 已执行
$SKILL_DIR/scripts/fix-ssh-config.sh -i openEuler.qcow2
```

**问题3: Permission denied (publickey,gssapi-with-mic)**

原因：SSH禁止密码登录（openEuler默认配置）

解决：修复镜像SSH配置（必须停止虚机后执行）
```bash
# 停止虚机
pkill -f qemu-system-aarch64

# 修复SSH配置
$SKILL_DIR/scripts/fix-ssh-config.sh -i openEuler.qcow2

# 重启虚机后SSH可正常登录
```

### SSH连接方式

**推荐方式（自动清理known_hosts）**：
```bash
$SKILL_DIR/scripts/ssh-test.sh
```

**手动连接**：
```bash
# 使用密码登录（跳过known_hosts验证）
sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222

# 若遇到HOST IDENTIFICATION错误，先清理：
ssh-keygen -R "[localhost]:2222"
sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222
```

---

## 脚本列表

```bash
# 方式1: 使用sshpass（需要密码）
sshpass -p '{VM_PASSWORD}' ssh -o StrictHostKeyChecking=no root@localhost -p 2222

# 方式2: 免密登录（配置后）
ssh root@localhost -p 2222

# 方式3: 手动输入密码
ssh -o StrictHostKeyChecking=no root@localhost -p 2222
# 输入密码: {VM_PASSWORD}

---

## 详细参考文档

- **REFERENCE.md**: 详细构建步骤、错误排查、经验总结
- **docs/qemu-commands.md**: QEMU命令说明书
- **docs/qemu-params.yaml**: 参数校验规则
- **templates/*.yaml**: 配置模板

---

## 常见问题速查

| 问题 | 解决方法 |
|------|---------|
| UEFI "Synchronous Exception" | 使用直接内核启动，提取镜像中的vmlinuz/initramfs |
| SSH无法密码登录 | 执行 scripts/fix-ssh-config.sh 修复 |
| Minimal虚拟机命令找不到 | 检查busybox支持哪些命令：`busybox --list`，添加链接 |
| busybox不支持vi | 使用ed或hexedit替代 |
| Shell不显示当前路径 | 使用 `PS1='$(pwd)# '` |
| TCG模式启动慢 | 正常现象，等待60-120秒 |
| 华为鲲鹏定制QEMU | 必须使用直接内核启动方案，不能用UEFI |

---

## 重要经验总结

1. **配置向导是强制性的**：不询问完所有问题就跳过会导致配置不完整
2. **SSH修复必须执行**：openEuler云镜像默认禁用密码认证
3. **自测验证必须通过**：生成脚本前必须测试启动命令能正常运行
4. **TCG模式超时要长**：纯软件模拟启动慢，需要60-120秒
5. **鲲鹏定制QEMU特殊性**：UBIOS不兼容标准固件，必须用直接内核启动
6. **脚本注释模板**：生成的脚本必须包含SSH连接信息和密码
