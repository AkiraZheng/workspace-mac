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

A) 下载openEuler qcow2
B) 构建minifs

**下载openEuler**:
```bash
./scripts/download-image.sh -o . -v 24.03-LTS
```

**构建minifs**:
```bash
./scripts/build-minifs.sh -o ./minifs.img -s 200M
```

---

### 步骤3: 配置向导

#### 第一层：核心配置（必选）

**问题1: 启动方式**

A) KVM加速（需要/dev/kvm）
B) TCG模拟（纯软件）

若选择KVM但不可用，提示并建议TCG。

**问题2: CPU配置**

- 核数（默认4）
- CPU类型（默认host）

**问题3: 内存配置**

- 大小（默认4G）
- 单位（M/G）

**问题4: 镜像选择**

列出可用镜像，或重新下载/构建。

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

**两种启动方案**：

| 方案 | 适用场景 | 说明 |
|------|---------|------|
| UEFI启动 | 标准QEMU | 使用-bios或pflash加载固件 |
| 直接内核启动 | 定制QEMU或UEFI异常 | 使用-kernel/-initrd绕过固件 |

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