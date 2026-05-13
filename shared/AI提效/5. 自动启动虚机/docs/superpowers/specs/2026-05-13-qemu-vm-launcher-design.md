# QEMU VM Launcher Skill 设计文档

**日期**: 2026-05-13
**作者**: AI Assistant
**状态**: 设计阶段

---

## 一、概述

### 1.1 目标

创建一个skill，帮助用户快速启动QEMU虚拟机，提供：
- 自动镜像准备（openEuler qcow2下载或minifs构建）
- 分层配置向导（核心配置+高级配置）
- QEMU命令自动生成
- 完整的脚本工具集

### 1.2 使用场景

- **内部团队工具**: 帮助团队成员快速启动测试虚机进行开发调试
- **自动化测试**: 集成到CI/CD流程中自动准备测试环境

### 1.3 目标架构

固定支持 **aarch64** 架构，暂不支持x86_64。

---

## 二、整体架构

### 2.1 目录结构

```
qemu-vm-launcher/
├── SKILL.md                      # 主skill文件（向导逻辑+命令生成）
├── docs/
│   ├── qemu-commands.md          # QEMU命令详细说明书
│   ├── qemu-params.yaml          # 参数校验规则和默认值
│   └── qemu-reference.md         # QEMU aarch64参数参考（自包含）
├── templates/
│   ├── basic.yaml                # 基础启动模板
│   ├── numa.yaml                 # NUMA拓扑模板
│   ├── vfio.yaml                 # VFIO直通模板
│   ├── migration.yaml            # 热迁移模板
│   └── virtio.yaml               # VIRTIO设备模板
└── scripts/
    ├── check-kvm.sh              # 环境检查脚本
    ├── download-image.sh         # 镜像下载脚本
    ├── build-minifs.sh           # minifs构建脚本
    ├── pin-cpu-1v1.sh            # 1v1绑核脚本
    └── pin-cpu-range.sh          # 范围绑核脚本
```

### 2.2 工作流程

```
1. 环境检查 → check-kvm.sh
2. 镜像准备 → download-image.sh / build-minifs.sh
3. 配置向导 → 分层交互
4. 命令生成 → 读取模板+叠加参数
5. 参数校验 → qemu-params.yaml
6. 输出执行 → 打印/保存脚本/立即执行
```

---

## 三、镜像准备模块

### 3.1 检查逻辑

1. **检查路径**: 当前工作目录（相对路径）
2. **用户自定义路径**: 支持指定路径
3. **若已存在**: 跳过下载/构建
4. **若不存在**: 执行下载或构建

### 3.2 openEuler qcow2下载

**脚本**: `scripts/download-image.sh`

**功能**:
- 从openEuler官方源下载aarch64 qcow2镜像
- 支持指定版本（默认最新LTS）
- 支持断点续传
- 校验镜像完整性（checksum）

**下载地址**:
```
https://repo.openeuler.org/openEuler-<version>/virtual_machine_img/aarch64/
```

**参数**:
- `-o`: 输出路径
- `-v`: 版本号（如24.03-LTS）

**示例**:
```bash
./scripts/download-image.sh -o ./images -v 24.03-LTS
```

### 3.3 minifs构建

**脚本**: `scripts/build-minifs.sh`

**功能**:
- 构建aarch64最小化rootfs镜像
- 包含: busybox, 网络工具(ip/ping/ssh), 测试工具, 基础调试工具(strace/lsof)
- 输出大小: 100-200MB

**参数**:
- `-o`: 输出路径
- `-s`: 镜像大小
- `--with-dev-tools`: 包含开发工具（gcc/make等）

**示例**:
```bash
./scripts/build-minifs.sh -o ./minifs.img -s 200M
```

### 3.4 文件命名

- 下载/构建完成后，记录实际文件名
- 传递给后续命令生成环节
- 支持用户自定义命名

---

## 四、配置向导模块

### 4.1 分层设计

采用分层模式：默认精简，可选进入高级配置。

### 4.2 第一层：核心配置（必选）

**问题1: 启动方式**
```
A) KVM加速（Linux硬件虚拟化）
B) TCG模拟（纯软件，跨平台兼容）
```

KVM可用性检查: `[ -e /dev/kvm ] && [ -w /dev/kvm ]`

若用户选择KVM但环境不支持，提示并建议切换TCG。

**问题2: CPU配置**
```
- 核数（默认4）
- CPU类型（host/cortex-a57/cortex-a72/max）
```

**问题3: 内存配置**
```
- 内存大小（默认4G）
- 内存单位（M/G）
```

**问题4: 镜像选择**
```
A) 使用已有镜像（列出当前目录*.qcow2/*.img）
B) 下载openEuler qcow2
C) 构建minifs
```

### 4.3 第二层：高级配置（可选）

询问：**是否需要高级配置？**

若选择yes，逐一询问以下模块（每个模块可选跳过）:

- NUMA拓扑配置
- 大页内存（传统大页/透明大页）
- 设备配置（VFIO/VIRTIO）
- 热迁移配置
- Guest-Host通信方式
- CPU绑核

### 4.4 第三层：启动选项

```
- 是否立即执行命令？
- 是否保存为脚本？
- 是否输出完整命令供复制？
- 是否启用后台运行？
```

---

## 五、QEMU命令生成模块

### 5.1 命令生成流程

```
1. 读取用户配置
2. 根据启动方式选择基础模板
3. 叠加高级配置参数
4. 校验参数合法性（qemu-params.yaml）
5. 拼接完整QEMU命令
6. 输出/执行
```

### 5.2 基础命令框架

```bash
qemu-system-aarch64 \
  -machine virt,accel=${accel} \
  -cpu ${cpu_type} \
  -smp ${smp} \
  -m ${memory}

# 固件
-bios ${bios_path}

# 存储设备
-drive file=${image},if=none,id=hd0,format=${format}
-device ${drive_interface},drive=hd0

# 网络设备
-netdev ${net_backend},id=net0,hostfwd=tcp::${ssh_port}-:22
-device ${net_device},netdev=net0

# 显示
-nographic
```

### 5.3 高级参数叠加

按需添加:
- NUMA: `-numa node,nodeid=N,cpus=N-N,mem=N`
- 大页: `-mem-path /dev/hugepages -mem-prealloc`
- VFIO: `-device vfio-pci,host=DDDD:BB:DD.F`
- 热迁移目标: `-incoming tcp:0:4444`
- 9p共享: `-virtfs local,path=/path,mount_tag=tag,...`

### 5.4 输出形式

1. 打印完整命令
2. 保存为shell脚本（带执行权限）
3. 立即执行（可选后台运行）

---

## 六、文档与模板

### 6.1 qemu-commands.md 结构

```markdown
# QEMU命令说明书

## 一、启动方式
### KVM加速
### TCG模拟

## 二、CPU配置
### 基础配置（-smp, -cpu）
### NUMA拓扑
### CPU绑核

## 三、内存配置
### 基础配置（-m）
### 大页内存
### 内存气球

## 四、存储设备
### virtio-blk-pci
### 启动方式（DTS/ACPI/UEFI）

## 五、网络设备
### virtio-net-pci
### user/tap网络

## 六、设备直通
### VFIO直通
### VIRTIO设备

## 七、热迁移
### 迁移参数

## 八、Guest-Host通信
### 网络通信
### 9p文件共享
### 文件固化到minifs

## 九、常用示例
```

### 6.2 qemu-params.yaml 结构

```yaml
machine:
  type: virt
  accel: [kvm, tcg]

cpu:
  types: [host, cortex-a57, cortex-a72, max]
  smp:
    default: 4
    min: 1
    max: 128

memory:
  default: 4G
  units: [M, G]

bios:
  default: edk2-aarch64-code.fd

drive:
  formats: [qcow2, raw, img]
  interfaces: [virtio-blk-pci, virtio-scsi-pci, none]

network:
  backends: [user, tap, socket]
  devices: [virtio-net-pci]
```

### 6.3 qemu-reference.md

自包含的QEMU aarch64参数参考文档，不依赖用户本地QEMU源码。

内容包括:
- 机器类型说明
- CPU类型支持列表
- 内存配置参数
- NUMA配置详解
- VFIO直通参数
- 热迁移参数
- 9p文件共享参数
- VIRTIO设备参数

---

## 七、脚本工具集

### 7.1 check-kvm.sh - 环境检查

**功能**:
- 检查KVM可用性
- 检查大页内存状态
- 检查VFIO模块加载状态
- 检查QEMU安装状态

**输出**: JSON格式报告

```json
{
  "kvm": true,
  "hugepages_2m": 1024,
  "hugepages_1g": 0,
  "transparent_hugepage": "always",
  "vfio_pci_loaded": true,
  "qemu_installed": true
}
```

### 7.2 download-image.sh - 镜像下载

**参数**:
- `-o`: 输出路径
- `-v`: 版本号

**功能**:
- 从openEuler官方下载aarch64 qcow2
- 断点续传支持
- checksum校验

### 7.3 build-minifs.sh - minifs构建

**参数**:
- `-o`: 输出路径
- `-s`: 镜像大小
- `--with-dev-tools`: 包含开发工具

**输出**: 100-200MB的rootfs镜像

### 7.4 pin-cpu-1v1.sh - 1v1绑核

**用法**: `./pin-cpu-1v1.sh <qemu_pid> <cpu_list>`

**功能**:
- 获取所有vCPU线程
- 逐个绑定到指定物理CPU
- 输出绑定结果

**示例**:
```bash
./pin-cpu-1v1.sh 12345 0,2,4,6
# 输出:
# vCPU 0 -> CPU 0 (thread 12350)
# vCPU 1 -> CPU 2 (thread 12351)
# vCPU 2 -> CPU 4 (thread 12352)
# vCPU 3 -> CPU 6 (thread 12353)
```

### 7.5 pin-cpu-range.sh - 范围绑核

**用法**: `./pin-cpu-range.sh <qemu_pid> <cpu_range>`

**功能**:
- 使用taskset绑定整个进程
- 支持范围格式（0-3）或掩码格式（0xf）

**示例**:
```bash
./pin-cpu-range.sh 12345 0-3
```

---

## 八、高级功能设计

### 8.1 启动方式

**DTS启动**:
```bash
-machine virt,dtb=device-tree.dtb
```

**ACPI启动**:
```bash
-machine virt,acpi=on
```

**默认**: ACPI启动（推荐）

### 8.2 NUMA拓扑

**参数**:
```bash
-numa node,nodeid=0,cpus=0-3,mem=4G
-numa node,nodeid=1,cpus=4-7,mem=4G
```

**向导流程**:
- 询问节点数量
- 询问每节点CPU列表
- 询问每节点内存大小
- 可选配置节点距离

### 8.3 大页内存

**传统大页**:
```bash
# Host配置
echo 1024 > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages

# QEMU参数
-mem-path /dev/hugepages -mem-prealloc
```

**透明大页**:
```bash
# Host配置（通常默认启用）
echo always > /sys/kernel/mm/transparent_hugepage/enabled

# QEMU无需额外参数
```

### 8.4 VFIO直通

**前置条件**:
- IOMMU支持
- vfio-pci模块加载
- 设备绑定到vfio-pci

**参数**:
```bash
-device vfio-pci,host=0000:04:00.0,id=vfio0
```

### 8.5 VIRTIO设备

**常用设备**:
- `virtio-blk-pci`: 虚拟块设备
- `virtio-net-pci`: 虚拟网卡
- `virtio-balloon`: 内存气球
- `virtio-rng`: 随机数生成器
- `virtio-serial`: 串口设备

### 8.6 热迁移

**目标端**:
```bash
-incoming tcp:0:4444
```

**源端**:
```bash
# QEMU monitor中执行
migrate tcp:<target_ip>:4444
```

### 8.7 Guest-Host通信

**网络通信**:
```bash
-netdev user,id=net0,hostfwd=tcp::2222-:22
ssh root@localhost -p 2222
```

**9p文件共享**:
```bash
# Host端
-virtfs local,path=/host/share,mount_tag=hostshare,security_model=mapped-xattr

# Guest端
mount -t 9p -o trans=virtio hostshare /mnt/share
```

**文件固化到minifs**:
```bash
./build-minifs.sh --include-dir /path/to/files
```

### 8.8 CPU绑核

**1v1绑核**: 精确绑定每个vCPU到物理CPU
**范围绑核**: 使用taskset绑定进程到CPU范围

---

## 九、模板示例

### 9.1 basic.yaml

```yaml
name: basic
description: 基础虚机启动
params:
  machine: virt
  accel: kvm
  cpu: host
  smp: 4
  memory: 4G
  bios: edk2-aarch64-code.fd
  drive_format: qcow2
  drive_interface: virtio-blk-pci
  net_backend: user
  net_device: virtio-net-pci
  ssh_port: 2222
cmd_template: |
  qemu-system-aarch64 \
    -machine {machine},accel={accel} \
    -cpu {cpu} \
    -smp {smp} \
    -m {memory} \
    -bios {bios} \
    -drive file={drive},if=none,id=hd0,format={drive_format} \
    -device {drive_interface},drive=hd0 \
    -netdev user,id=net0,hostfwd=tcp::{ssh_port}-:22 \
    -device {net_device},netdev=net0 \
    -nographic
```

### 9.2 numa.yaml

```yaml
name: numa
description: NUMA拓扑配置模板
params:
  node_count: 2
  nodes:
    - nodeid: 0
      cpus: "0-3"
      mem: "4G"
    - nodeid: 1
      cpus: "4-7"
      mem: "4G"
```

---

## 十、默认值汇总

| 配置项 | 默认值 |
|-------|--------|
| 架构 | aarch64 |
| 机器类型 | virt |
| 启动方式 | KVM（若可用） |
| CPU核数 | 4 |
| CPU类型 | host |
| 内存大小 | 4G |
| 固件 | edk2-aarch64-code.fd |
| 存储接口 | virtio-blk-pci |
| 网络接口 | virtio-net-pci |
| SSH端口 | 2222 |
| 镜像路径 | 当前目录 |

---

## 十一、SKILL.md 主文件结构

```markdown
---
name: qemu-vm-launcher
description: QEMU虚拟机启动助手，提供镜像准备、配置向导、命令生成等功能
---

# QEMU VM Launcher Skill

## 一、概述

触发条件: 启动QEMU虚拟机、配置虚机、QEMU命令生成、openEuler镜像准备、minifs构建

## 二、工作流程

### 步骤1: 环境检查
调用 scripts/check-kvm.sh

### 步骤2: 镜像准备
- 检查当前目录是否有镜像
- 若无，询问下载或构建

### 步骤3: 配置向导
#### 第一层：核心配置
#### 第二层：高级配置（可选）

### 步骤4: 命令生成
读取模板，叠加参数，校验，输出

### 步骤5: 执行选项

## 三、文档参考

- docs/qemu-commands.md
- docs/qemu-params.yaml
- docs/qemu-reference.md

## 四、模板参考

读取 templates/*.yaml

## 五、脚本使用

- scripts/check-kvm.sh
- scripts/download-image.sh
- scripts/build-minifs.sh
- scripts/pin-cpu-1v1.sh
- scripts/pin-cpu-range.sh
```

---

## 十二、后续任务

1. 实现 SKILL.md 主文件
2. 编写 qemu-commands.md 详细文档
3. 编写 qemu-params.yaml 参数校验规则
4. 编写 qemu-reference.md 参数参考
5. 编写 templates/*.yaml 模板文件
6. 实现 scripts/*.sh 脚本
7. 测试验证

---

## 附录A: openEuler镜像默认信息

- 用户名: root
- 密码: {VM_PASSWORD}

## 附录B: 参考示例

Mac host启动示例:
```shell
qemu-system-aarch64 \
  -machine virt,accel=hvf -cpu host \
  -smp 4 \
  -m 4G \
  -bios edk2-aarch64-code.fd \
  -drive file=openEuler-24.03-LTS-aarch64.qcow2,if=none,id=hd0,format=qcow2 \
  -device virtio-blk-pci,drive=hd0 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

Linux host启动示例:
```shell
qemu-system-aarch64 \
  -machine virt,accel=kvm -cpu host \
  -smp 4 \
  -m 4G \
  -bios edk2-aarch64-code.fd \
  -drive file=openEuler-24.03-LTS-aarch64.qcow2,if=none,id=hd0,format=qcow2 \
  -device virtio-blk-pci,drive=hd0 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```