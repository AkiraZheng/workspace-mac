# QEMU VM Launcher Skill 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建一个完整的QEMU虚拟机启动skill，包含镜像准备、配置向导、命令生成等功能。

**Architecture:** 采用模块化设计，skill主文件引导用户交互，文档/模板/脚本分离，便于维护和更新。

**Tech Stack:** Shell脚本、Markdown文档、YAML配置

---

## 文件结构

```
qemu-vm-launcher/
├── SKILL.md                      # 主skill文件
├── docs/
│   ├── qemu-commands.md          # QEMU命令说明书
│   ├── qemu-params.yaml          # 参数校验规则
│   └── qemu-reference.md         # 参数参考文档
├── templates/
│   ├── basic.yaml                # 基础模板
│   ├── numa.yaml                 # NUMA模板
│   ├── vfio.yaml                 # VFIO模板
│   ├── migration.yaml            # 热迁移模板
│   └── virtio.yaml               # VIRTIO模板
└── scripts/
    ├── check-kvm.sh              # 环境检查
    ├── download-image.sh         # 镜像下载
    ├── build-minifs.sh           # minifs构建
    ├── pin-cpu-1v1.sh            # 1v1绑核
    └── pin-cpu-range.sh          # 范围绑核
```

---

## Task 1: 创建目录结构

**Files:**
- Create: `qemu-vm-launcher/`
- Create: `qemu-vm-launcher/docs/`
- Create: `qemu-vm-launcher/templates/`
- Create: `qemu-vm-launcher/scripts/`

- [ ] **Step 1: 创建skill目录结构**

```bash
mkdir -p qemu-vm-launcher/docs qemu-vm-launcher/templates qemu-vm-launcher/scripts
```

Run: 在工作目录执行
Expected: 目录创建成功

- [ ] **Step 2: 验证目录结构**

```bash
ls -la qemu-vm-launcher/
```

Expected: 显示docs、templates、scripts三个子目录

---

## Task 2: 编写环境检查脚本

**Files:**
- Create: `qemu-vm-launcher/scripts/check-kvm.sh`

- [ ] **Step 1: 编写check-kvm.sh脚本**

```bash
#!/bin/bash
# check-kvm.sh - 环境检查脚本
# 输出JSON格式报告

check_kvm() {
    if [ -e /dev/kvm ] && [ -w /dev/kvm ]; then
        echo "true"
    else
        echo "false"
    fi
}

check_hugepages() {
    local hp_2m=0
    local hp_1g=0
    
    if [ -f /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages ]; then
        hp_2m=$(cat /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages)
    fi
    
    if [ -f /sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages ]; then
        hp_1g=$(cat /sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages)
    fi
    
    echo "{\"2m\": $hp_2m, \"1g\": $hp_1g}"
}

check_transparent_hugepage() {
    if [ -f /sys/kernel/mm/transparent_hugepage/enabled ]; then
        cat /sys/kernel/mm/transparent_hugepage/enabled | grep -o '\[.*\]' | tr -d '[]'
    else
        echo "unknown"
    fi
}

check_vfio() {
    if lsmod | grep -q vfio_pci; then
        echo "true"
    else
        echo "false"
    fi
}

check_qemu() {
    if command -v qemu-system-aarch64 &> /dev/null; then
        echo "true"
    else
        echo "false"
    fi
}

# 主输出
echo "{"
echo "  \"kvm\": $(check_kvm),"
echo "  \"hugepages\": $(check_hugepages),"
echo "  \"transparent_hugepage\": \"$(check_transparent_hugepage)\","
echo "  \"vfio_pci_loaded\": $(check_vfio),"
echo "  \"qemu_installed\": $(check_qemu)"
echo "}"
```

- [ ] **Step 2: 设置脚本执行权限**

```bash
chmod +x qemu-vm-launcher/scripts/check-kvm.sh
```

- [ ] **Step 3: 测试脚本**

```bash
./qemu-vm-launcher/scripts/check-kvm.sh
```

Expected: 输出JSON格式环境报告

---

## Task 3: 编写镜像下载脚本

**Files:**
- Create: `qemu-vm-launcher/scripts/download-image.sh`

- [ ] **Step 1: 编写download-image.sh脚本**

```bash
#!/bin/bash
# download-image.sh - openEuler镜像下载脚本

set -e

DEFAULT_VERSION="24.03-LTS"
BASE_URL="https://repo.openeuler.org/openEuler-${DEFAULT_VERSION}/virtual_machine_img/aarch64/"
IMAGE_NAME="openEuler-${DEFAULT_VERSION}-aarch64.qcow2.xz"

OUTPUT_DIR="."
VERSION=""

usage() {
    echo "Usage: $0 [-o output_dir] [-v version]"
    echo "  -o: 输出目录 (默认当前目录)"
    echo "  -v: openEuler版本 (默认 ${DEFAULT_VERSION})"
    exit 1
}

while getopts "o:v:h" opt; do
    case $opt in
        o) OUTPUT_DIR="$OPTARG" ;;
        v) VERSION="$OPTARG" ;;
        h) usage ;;
        *) usage ;;
    esac
done

if [ -z "$VERSION" ]; then
    VERSION="$DEFAULT_VERSION"
fi

BASE_URL="https://repo.openeuler.org/openEuler-${VERSION}/virtual_machine_img/aarch64/"
IMAGE_XZ="openEuler-${VERSION}-aarch64.qcow2.xz"
IMAGE_QCOW2="openEuler-${VERSION}-aarch64.qcow2"

mkdir -p "$OUTPUT_DIR"

if [ -f "$OUTPUT_DIR/$IMAGE_QCOW2" ]; then
    echo "镜像已存在: $OUTPUT_DIR/$IMAGE_QCOW2"
    echo "跳过下载"
    exit 0
fi

echo "下载地址: ${BASE_URL}${IMAGE_XZ}"
echo "输出目录: $OUTPUT_DIR"

wget -c "${BASE_URL}${IMAGE_XZ}" -O "$OUTPUT_DIR/$IMAGE_XZ"

echo "解压镜像..."
xz -d "$OUTPUT_DIR/$IMAGE_XZ"

echo "镜像下载完成: $OUTPUT_DIR/$IMAGE_QCOW2"
echo "文件大小: $(du -h "$OUTPUT_DIR/$IMAGE_QCOW2" | cut -f1)"
```

- [ ] **Step 2: 设置执行权限**

```bash
chmod +x qemu-vm-launcher/scripts/download-image.sh
```

---

## Task 4: 编写minifs构建脚本

**Files:**
- Create: `qemu-vm-launcher/scripts/build-minifs.sh`

- [ ] **Step 1: 编写build-minifs.sh脚本**

```bash
#!/bin/bash
# build-minifs.sh - 最小化rootfs构建脚本

set -e

OUTPUT_PATH="minifs.img"
IMAGE_SIZE="200M"
INCLUDE_DEV_TOOLS=false
INCLUDE_DIR=""

usage() {
    echo "Usage: $0 [-o output_path] [-s size] [--with-dev-tools] [--include-dir path]"
    echo "  -o: 输出文件路径 (默认 minifs.img)"
    echo "  -s: 镜像大小 (默认 200M)"
    echo "  --with-dev-tools: 包含开发工具"
    echo "  --include-dir: 预置文件目录"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -o) OUTPUT_PATH="$2"; shift 2 ;;
        -s) IMAGE_SIZE="$2"; shift 2 ;;
        --with-dev-tools) INCLUDE_DEV_TOOLS=true; shift ;;
        --include-dir) INCLUDE_DIR="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) usage ;;
    esac
done

echo "构建minifs镜像..."
echo "输出路径: $OUTPUT_PATH"
echo "镜像大小: $IMAGE_SIZE"

# 检查必要工具
if ! command -v dd &> /dev/null; then
    echo "错误: 需要dd工具"
    exit 1
fi

if ! command -v mkfs.ext4 &> /dev/null; then
    echo "错误: 需要mkfs.ext4工具"
    exit 1
fi

# 创建临时目录
TMPDIR=$(mktemp -d)
ROOTFS="$TMPDIR/rootfs"

mkdir -p "$ROOTFS"

# 创建镜像文件
dd if=/dev/zero of="$OUTPUT_PATH" bs=1 count=0 seek="$IMAGE_SIZE" status=progress

# 创建ext4文件系统
mkfs.ext4 -F "$OUTPUT_PATH"

# 挂载镜像
MOUNT_POINT="$TMPDIR/mount"
mkdir -p "$MOUNT_POINT"
mount -o loop "$OUTPUT_PATH" "$MOUNT_POINT"

# 创建基础目录结构
mkdir -p "$MOUNT_POINT"/{bin,sbin,etc,proc,sys,dev,tmp,var,usr,root}

# 创建基础配置文件
cat > "$MOUNT_POINT/etc/passwd" << 'EOF'
root:x:0:0:root:/root:/bin/sh
EOF

cat > "$MOUNT_POINT/etc/group" << 'EOF'
root:x:0:
EOF

# 安装busybox（如果可用）
if command -v busybox &> /dev/null; then
    cp "$(which busybox)" "$MOUNT_POINT/bin/"
    cd "$MOUNT_POINT/bin"
    for cmd in sh ls cat mkdir rm cp mv echo sleep mount umount; do
        ln -sf busybox "$cmd"
    done
    cd "$OLDPWD"
else
    echo "警告: busybox未找到，请手动安装"
fi

# 预置文件目录
if [ -n "$INCLUDE_DIR" ] && [ -d "$INCLUDE_DIR" ]; then
    echo "预置文件目录: $INCLUDE_DIR"
    cp -r "$INCLUDE_DIR"/* "$MOUNT_POINT/" 2>/dev/null || true
fi

# 开发工具
if [ "$INCLUDE_DEV_TOOLS" = true ]; then
    mkdir -p "$MOUNT_POINT/usr/bin"
    for tool in gcc make gdb strace lsof; do
        if command -v "$tool" &> /dev/null; then
            cp "$(which $tool)" "$MOUNT_POINT/usr/bin/" 2>/dev/null || echo "警告: $tool 未找到"
        fi
    done
fi

# 创建init脚本
cat > "$MOUNT_POINT/init" << 'EOF'
#!/bin/sh
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
exec /bin/sh
EOF
chmod +x "$MOUNT_POINT/init"

# 清理
umount "$MOUNT_POINT"
rm -rf "$TMPDIR"

echo "minifs镜像构建完成: $OUTPUT_PATH"
echo "文件大小: $(du -h "$OUTPUT_PATH" | cut -f1)"
```

- [ ] **Step 2: 设置执行权限**

```bash
chmod +x qemu-vm-launcher/scripts/build-minifs.sh
```

---

## Task 5: 编写1v1绑核脚本

**Files:**
- Create: `qemu-vm-launcher/scripts/pin-cpu-1v1.sh`

- [ ] **Step 1: 编写pin-cpu-1v1.sh脚本**

```bash
#!/bin/bash
# pin-cpu-1v1.sh - 1v1绑核脚本

set -e

QEMU_PID=""
CPU_LIST=""

usage() {
    echo "Usage: $0 <qemu_pid> <cpu_list>"
    echo "示例: $0 12345 0,2,4,6"
    exit 1
}

if [ $# -lt 2 ]; then
    usage
fi

QEMU_PID="$1"
CPU_LIST="$2"

# 检查进程是否存在
if ! ps -p "$QEMU_PID" > /dev/null 2>&1; then
    echo "错误: 进程 $QEMU_PID 不存在"
    exit 1
fi

# 获取vCPU线程
get_vcpu_threads() {
    local threads=""
    for tid in $(ls /proc/$QEMU_PID/task/); do
        if [ -f /proc/$QEMU_PID/task/$tid/comm ]; then
            comm=$(cat /proc/$QEMU_PID/task/$tid/comm)
            if [[ "$comm" == "CPU "* ]]; then
                threads="$threads $tid"
            fi
        fi
    done
    echo "$threads"
}

# 解析CPU列表
IFS=',' read -ra CPUS <<< "$CPU_LIST"

# 获取vCPU线程
VCPU_THREADS=$(get_vcpu_threads)

if [ -z "$VCPU_THREADS" ]; then
    echo "未找到vCPU线程"
    echo "请确保QEMU进程正在运行"
    exit 1
fi

echo "绑定vCPU线程..."
echo ""

i=0
for tid in $VCPU_THREADS; do
    if [ $i -lt ${#CPUS[@]} ]; then
        cpu=${CPUS[$i]}
        taskset -pc "$cpu" "$tid" 2>/dev/null
        vcpu_num=$(cat /proc/$QEMU_PID/task/$tid/comm | sed 's/CPU //')
        echo "vCPU $vcpu_num -> CPU $cpu (thread $tid)"
        ((i++))
    else
        echo "警告: vCPU数量超过CPU列表，跳过绑定"
        break
    fi
done

echo ""
echo "绑核完成"
```

- [ ] **Step 2: 设置执行权限**

```bash
chmod +x qemu-vm-launcher/scripts/pin-cpu-1v1.sh
```

---

## Task 6: 编写范围绑核脚本

**Files:**
- Create: `qemu-vm-launcher/scripts/pin-cpu-range.sh`

- [ ] **Step 1: 编写pin-cpu-range.sh脚本**

```bash
#!/bin/bash
# pin-cpu-range.sh - 范围绑核脚本

set -e

QEMU_PID=""
CPU_RANGE=""

usage() {
    echo "Usage: $0 <qemu_pid> <cpu_range>"
    echo "示例: $0 12345 0-3"
    echo "      $0 12345 0xf"
    exit 1
}

if [ $# -lt 2 ]; then
    usage
fi

QEMU_PID="$1"
CPU_RANGE="$2"

# 检查进程是否存在
if ! ps -p "$QEMU_PID" > /dev/null 2>&1; then
    echo "错误: 进程 $QEMU_PID 不存在"
    exit 1
fi

echo "绑定QEMU进程 $QEMU_PID 到 CPU $CPU_RANGE"
echo ""

taskset -pc "$CPU_RANGE" "$QEMU_PID"

echo ""
echo "绑核完成"
```

- [ ] **Step 2: 设置执行权限**

```bash
chmod +x qemu-vm-launcher/scripts/pin-cpu-range.sh
```

---

## Task 7: 编写参数校验配置

**Files:**
- Create: `qemu-vm-launcher/docs/qemu-params.yaml`

- [ ] **Step 1: 编写qemu-params.yaml**

```yaml
machine:
  type: virt
  accel:
    - kvm
    - tcg
  default_accel: kvm

cpu:
  types:
    - host
    - cortex-a57
    - cortex-a72
    - max
  default_type: host
  smp:
    default: 4
    min: 1
    max: 128

memory:
  default: 4G
  units:
    - M
    - G
  min: 128M
  max: 256G

bios:
  default: edk2-aarch64-code.fd
  search_paths:
    - /usr/share/qemu
    - /usr/share/AAVMF
    - /opt/homebrew/Cellar/qemu

drive:
  formats:
    - qcow2
    - raw
    - img
  interfaces:
    - virtio-blk-pci
    - virtio-scsi-pci
    - none
  default_interface: virtio-blk-pci

network:
  backends:
    - user
    - tap
    - socket
  default_backend: user
  devices:
    - virtio-net-pci
  default_device: virtio-net-pci
  ssh_port:
    default: 2222
    min: 1024
    max: 65535

numa:
  max_nodes: 8

hugepages:
  sizes:
    - 2M
    - 1G

virtio_devices:
  storage:
    - virtio-blk-pci
    - virtio-scsi-pci
  network:
    - virtio-net-pci
  balloon:
    - virtio-balloon
  rng:
    - virtio-rng
  serial:
    - virtio-serial
    - virtconsole

vfio:
  device_type: vfio-pci

migration:
  protocols:
    - tcp
    - unix
    - exec
  default_port: 4444

communication:
  types:
    - network
    - 9p
    - minifs_embed
```

---

## Task 8: 编写QEMU命令说明书

**Files:**
- Create: `qemu-vm-launcher/docs/qemu-commands.md`

- [ ] **Step 1: 编写qemu-commands.md**

```markdown
# QEMU aarch64 命令说明书

本文档提供QEMU aarch64虚拟机的命令参数说明和使用示例。

## 一、启动方式

### 1.1 KVM加速

KVM是Linux内核虚拟化模块，提供硬件加速支持。

**参数**: `-machine virt,accel=kvm`

**前提条件**:
- Host支持硬件虚拟化
- `/dev/kvm`设备存在且可访问
- qemu-system-aarch64已安装

**检查命令**:
```bash
[ -e /dev/kvm ] && [ -w /dev/kvm ] && echo "KVM可用" || echo "KVM不可用"
```

### 1.2 TCG模拟

TCG(Tiny Code Generator)是纯软件模拟，无需硬件支持。

**参数**: `-machine virt,accel=tcg`

**特点**:
- 跨平台兼容
- 性能较KVM低
- 适合调试和测试

### 1.3 启动方式对比

| 方式 | 性能 | 兼容性 | 适用场景 |
|-----|------|--------|---------|
| KVM | 高 | Linux only | 生产环境、性能测试 |
| TCG | 低 | 跨平台 | 调试、功能测试 |

---

## 二、CPU配置

### 2.1 CPU类型

**参数**: `-cpu <type>`

**支持的类型**:
- `host`: 使用Host CPU特性（推荐，KVM必须）
- `cortex-a57`: ARM Cortex-A57
- `cortex-a72`: ARM Cortex-A72
- `max`: 启用所有支持的特性

### 2.2 SMP配置

**参数**: `-smp <n>` 或 `-smp n,sockets=N,cores=N,threads=N`

**示例**:
```bash
# 4核
-smp 4

# 详细拓扑
-smp 8,sockets=2,cores=4,threads=1
```

### 2.3 NUMA拓扑

**参数**: `-numa node,nodeid=N,cpus=N-N,mem=N`

**示例**:
```bash
# 2节点NUMA
-numa node,nodeid=0,cpus=0-3,mem=4G \
-numa node,nodeid=1,cpus=4-7,mem=4G

# 4节点NUMA带距离
-numa node,nodeid=0,cpus=0-3,mem=4G \
-numa node,nodeid=1,cpus=4-7,mem=4G \
-numa dist,src=0,dst=1,val=20
```

### 2.4 CPU绑核

**方式**: 启动后通过taskset绑定

**1v1绑核**:
```bash
./scripts/pin-cpu-1v1.sh <qemu_pid> 0,2,4,6
```

**范围绑核**:
```bash
./scripts/pin-cpu-range.sh <qemu_pid> 0-3
```

---

## 三、内存配置

### 3.1 基础内存

**参数**: `-m <size>`

**示例**:
```bash
-m 4G
-m 8192M
```

### 3.2 传统大页

**Host配置**:
```bash
# 2M大页
echo 1024 > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages

# 1G大页
echo 4 > /sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages
```

**QEMU参数**:
```bash
-m 4G -mem-path /dev/hugepages -mem-prealloc
```

### 3.3 透明大页

**Host配置**:
```bash
echo always > /sys/kernel/mm/transparent_hugepage/enabled
```

**QEMU**: 无需额外参数，内核自动管理。

### 3.4 内存气球

**参数**: `-device virtio-balloon`

**功能**: 动态调整Guest内存

---

## 四、存储设备

### 4.1 virtio-blk-pci

**参数**:
```bash
-drive file=disk.qcow2,if=none,id=hd0,format=qcow2
-device virtio-blk-pci,drive=hd0
```

### 4.2 virtio-scsi-pci

**参数**:
```bash
-device virtio-scsi-pci,id=scsi0
-drive file=disk.qcow2,if=none,id=hd0,format=qcow2
-device scsi-hd,drive=hd0,bus=scsi0.0
```

### 4.3 启动方式

**UEFI/ACPI启动**（推荐）:
```bash
-bios edk2-aarch64-code.fd
-machine virt,acpi=on
```

**DTS启动**:
```bash
-machine virt,dtb=device-tree.dtb
```

### 4.4 热插拔

**冷插**: 启动参数中指定（如上）

**热插**:
```bash
# 在QEMU monitor中
(qemu) drive_add 0 file=hotplug.qcow2,format=qcow2,if=none,id=hotdisk
(qemu) device_add virtio-blk-pci,drive=hotdisk
```

---

## 五、网络设备

### 5.1 virtio-net-pci

**参数**:
```bash
-netdev user,id=net0,hostfwd=tcp::2222-:22
-device virtio-net-pci,netdev=net0
```

### 5.2 User网络

**特点**: 简单，无需配置Host网络

**参数**:
```bash
-netdev user,id=net0,hostfwd=tcp::2222-:22,hostfwd=tcp::8080-:80
```

### 5.3 Tap网络

**特点**: 性能好，需要配置Host网络

**Host配置**:
```bash
ip tuntap add dev tap0 mode tap
ip link set tap0 up
```

**QEMU参数**:
```bash
-netdev tap,id=net0,ifname=tap0,script=no,downscript=no
-device virtio-net-pci,netdev=net0
```

---

## 六、设备直通

### 6.1 VFIO直通

**前提条件**:
- IOMMU支持
- vfio-pci模块加载
- 设备绑定到vfio-pci

**Host准备**:
```bash
# 加载模块
modprobe vfio_pci

# 查看设备BDF
lspci -nn

# 绑定设备到vfio-pci
echo 0000:04:00.0 > /sys/bus/pci/devices/0000:04:00.0/driver/unbind
echo vfio-pci > /sys/bus/pci/devices/0000:04:00.0/driver_override
```

**QEMU参数**:
```bash
-device vfio-pci,host=0000:04:00.0,id=vfio0
```

### 6.2 VIRTIO设备

**常用设备**:
- `virtio-blk-pci`: 块设备
- `virtio-net-pci`: 网卡
- `virtio-balloon`: 内存气球
- `virtio-rng`: 随机数生成器
- `virtio-serial`: 串口

**示例**:
```bash
-device virtio-balloon
-device virtio-rng
-device virtio-serial
```

---

## 七、热迁移

### 7.1 目标端配置

**参数**:
```bash
-incoming tcp:0:4444
```

### 7.2 源端发起迁移

**在QEMU monitor中**:
```bash
(qemu) migrate tcp:<target_ip>:4444
(qemu) migrate_set_parameter max-bandwidth 100M
(qemu) info migrate
```

### 7.3 迁移参数

- `max-bandwidth`: 最大带宽
- `downtime-limit`: 最大停机时间
- `compression`: 启用压缩

---

## 八、Guest-Host通信

### 8.1 网络通信

**配置**:
```bash
-netdev user,id=net0,hostfwd=tcp::2222-:22
-device virtio-net-pci,netdev=net0
```

**使用**:
```bash
ssh root@localhost -p 2222
```

### 8.2 9p文件共享

**Host端配置**:
```bash
-virtfs local,path=/host/share,mount_tag=hostshare,security_model=mapped-xattr,id=fs0
```

**Guest端挂载**:
```bash
mount -t 9p -o trans=virtio,version=9p2000.L hostshare /mnt/share
```

### 8.3 文件固化到minifs

**构建时预置**:
```bash
./scripts/build-minifs.sh --include-dir /path/to/files
```

---

## 九、常用示例

### 9.1 基础启动

```bash
qemu-system-aarch64 \
  -machine virt,accel=kvm \
  -cpu host \
  -smp 4 \
  -m 4G \
  -bios edk2-aarch64-code.fd \
  -drive file=openEuler.qcow2,if=none,id=hd0,format=qcow2 \
  -device virtio-blk-pci,drive=hd0 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

### 9.2 NUMA拓扑

```bash
qemu-system-aarch64 \
  -machine virt,accel=kvm \
  -cpu host \
  -smp 8 \
  -m 8G \
  -numa node,nodeid=0,cpus=0-3,mem=4G \
  -numa node,nodeid=1,cpus=4-7,mem=4G \
  -bios edk2-aarch64-code.fd \
  -drive file=openEuler.qcow2,if=none,id=hd0,format=qcow2 \
  -device virtio-blk-pci,drive=hd0 \
  -nographic
```

### 9.3 VFIO直通

```bash
qemu-system-aarch64 \
  -machine virt,accel=kvm \
  -cpu host \
  -smp 4 \
  -m 4G \
  -bios edk2-aarch64-code.fd \
  -device vfio-pci,host=0000:04:00.0,id=vfio0 \
  -drive file=openEuler.qcow2,if=none,id=hd0,format=qcow2 \
  -device virtio-blk-pci,drive=hd0 \
  -nographic
```

### 9.4 热迁移目标端

```bash
qemu-system-aarch64 \
  -machine virt,accel=kvm \
  -cpu host \
  -smp 4 \
  -m 4G \
  -bios edk2-aarch64-code.fd \
  -drive file=openEuler.qcow2,if=none,id=hd0,format=qcow2 \
  -device virtio-blk-pci,drive=hd0 \
  -incoming tcp:0:4444 \
  -nographic
```

---

## 十、固件查找

**Linux**:
```bash
find /usr/share -name "edk2-aarch64-code.fd" 2>/dev/null
find /usr/share/AAVMF -name "*.fd" 2>/dev/null
```

**Mac**:
```bash
find /opt/homebrew/Cellar/qemu -name "edk2-aarch64-code.fd" 2>/dev/null
```

---

## 附录: openEuler镜像信息

- 用户名: root
- 密码: {VM_PASSWORD}

SSH登录:
```bash
ssh root@localhost -p 2222
```
```

---

## Task 9: 编写参数参考文档

**Files:**
- Create: `qemu-vm-launcher/docs/qemu-reference.md`

- [ ] **Step 1: 编写qemu-reference.md**

```markdown
# QEMU aarch64 参数参考

本文档提供QEMU aarch64的完整参数参考，自包含，不依赖用户本地QEMU源码。

---

## 一、机器类型

### virt

`virt`是QEMU为aarch64提供的通用虚拟机平台。

**参数格式**: `-machine virt[,options]`

**可选参数**:
- `accel=kvm|tcg`: 加速方式
- `acpi=on|off`: ACPI支持
- `dtb=file.dtb`: 设备树文件
- `usb=on|off`: USB支持

**示例**:
```bash
-machine virt,accel=kvm
-machine virt,accel=tcg,acpi=on
```

---

## 二、CPU配置

### 2.1 CPU类型

| 类型 | 说明 | 适用场景 |
|-----|------|---------|
| host | 使用Host CPU特性 | KVM环境，性能最优 |
| cortex-a57 | ARM Cortex-A57模拟 | TCG环境 |
| cortex-a72 | ARM Cortex-A72模拟 | TCG环境 |
| max | 启用所有特性 | 调试测试 |

**参数**: `-cpu <type>[,features]`

**示例**:
```bash
-cpu host
-cpu cortex-a57
-cpu max,pmu=on
```

### 2.2 SMP配置

**参数**: `-smp <n>[,sockets=n][,cores=n][,threads=n]`

**参数说明**:
- `n`: 总CPU核数
- `sockets`: CPU socket数
- `cores`: 每socket核心数
- `threads`: 每核心线程数

**取值范围**:
- 最小: 1
- 最大: 128（取决于实现）

**示例**:
```bash
-smp 4
-smp 8,sockets=2,cores=4,threads=1
```

---

## 三、内存配置

### 3.1 基础内存

**参数**: `-m <size>[,options]`

**大小单位**: M, G

**可选参数**:
- `slots=n`: 内存槽位数（热插）
- `maxmem=size`: 最大内存

**示例**:
```bash
-m 4G
-m 8192M
-m 4G,slots=4,maxmem=16G
```

### 3.2 大页内存

**参数**:
- `-mem-path <path>`: 大页内存路径
- `-mem-prealloc`: 预分配内存

**Host配置**:
```bash
# 2M大页
echo N > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages

# 1G大页
echo N > /sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages

# 验证
cat /proc/meminfo | grep Huge
```

**QEMU示例**:
```bash
-m 4G -mem-path /dev/hugepages -mem-prealloc
```

---

## 四、NUMA配置

### 4.1 NUMA节点定义

**参数**: `-numa node,nodeid=N,cpus=N-N|N,N,N,mem=N`

**参数说明**:
- `nodeid`: 节点ID（0开始）
- `cpus`: CPU列表（范围或逗号分隔）
- `mem`: 节点内存大小

**限制**:
- 最大节点数: 8
- CPU不能重复分配

**示例**:
```bash
-numa node,nodeid=0,cpus=0-3,mem=4G
-numa node,nodeid=1,cpus=4-7,mem=4G
```

### 4.2 NUMA距离

**参数**: `-numa dist,src=N,dst=N,val=N`

**示例**:
```bash
-numa dist,src=0,dst=1,val=20
```

---

## 五、存储设备

### 5.1 drive定义

**参数**: `-drive file=<path>,if=<interface>,id=<id>,format=<format>`

**参数说明**:
- `file`: 镜像文件路径
- `if`: 接口类型
- `id`: 设备ID（用于device绑定）
- `format`: 镜像格式

**接口类型**:
- `none`: 无接口，需配合device
- `ide`: IDE接口
- `scsi`: SCSI接口
- `virtio`: VIRTIO接口

**镜像格式**:
- `qcow2`: QEMU镜像格式（推荐）
- `raw`: 原始格式
- `vmdk`: VMware格式

**示例**:
```bash
-drive file=disk.qcow2,if=none,id=hd0,format=qcow2
```

### 5.2 存储设备

**VIRTIO块设备**:
```bash
-device virtio-blk-pci,drive=hd0[,bus=pci.0][,addr=0x4]
```

**VIRTIO SCSI**:
```bash
-device virtio-scsi-pci,id=scsi0
-device scsi-hd,drive=hd0,bus=scsi0.0
```

---

## 六、网络设备

### 6.1 网络后端

**user模式**（简单）:
```bash
-netdev user,id=<id>[,hostfwd=rule][,restrict=on|off]
```

**参数说明**:
- `hostfwd`: 端口转发规则，格式`tcp::hostport-:guestport`
- `restrict`: 是否限制网络访问

**示例**:
```bash
-netdev user,id=net0,hostfwd=tcp::2222-:22,hostfwd=tcp::8080-:80
```

**tap模式**（高性能）:
```bash
-netdev tap,id=<id>,ifname=<name>,script=<path>,downscript=<path>
```

**示例**:
```bash
-netdev tap,id=net0,ifname=tap0,script=no,downscript=no
```

### 6.2 网络设备

**VIRTIO网卡**:
```bash
-device virtio-net-pci,netdev=<id>[,mac=<addr>]
```

**示例**:
```bash
-device virtio-net-pci,netdev=net0,mac=52:54:00:12:34:56
```

---

## 七、VFIO直通

### 7.1 前提条件

1. IOMMU支持
2. vfio-pci模块加载
3. 设备解绑原驱动并绑定vfio-pci

### 7.2 参数

**格式**: `-device vfio-pci,host=<bdf>,id=<id>`

**BDF格式**: `DDDD:BB:DD.F` (域:总线:设备.功能)

**示例**:
```bash
-device vfio-pci,host=0000:04:00.0,id=vfio0
```

### 7.3 Host准备

```bash
# 加载模块
modprobe vfio_pci

# 查看设备
lspci -nn | grep <设备名>

# 解绑并绑定vfio-pci
echo 0000:04:00.0 > /sys/bus/pci/devices/0000:04:00.0/driver/unbind
echo vfio-pci > /sys/bus/pci/devices/0000:04:00.0/driver_override
```

---

## 八、热迁移

### 8.1 目标端

**参数**: `-incoming <protocol>:<address>`

**协议**:
- `tcp`: TCP socket
- `unix`: Unix socket
- `exec`: 执行命令

**示例**:
```bash
-incoming tcp:0:4444
-incoming unix:/tmp/migrate.sock
```

### 8.2 源端命令

**在QEMU monitor中执行**:
```bash
migrate tcp:<target_ip>:<port>
migrate_set_parameter max-bandwidth <bytes/sec>
migrate_set_parameter downtime-limit <ms>
info migrate
```

---

## 九、9p文件共享

### 9.1 Host配置

**参数**: `-virtfs local,path=<path>,mount_tag=<tag>,security_model=<model>,id=<id>`

**参数说明**:
- `path`: Host共享目录
- `mount_tag`: Guest挂载标签
- `security_model`: 安全模型
  - `passthrough`: 直接访问
  - `mapped`: 映射权限
  - `mapped-xattr`: 扩展属性映射

**示例**:
```bash
-virtfs local,path=/data,mount_tag=datashare,security_model=mapped-xattr,id=fs0
```

### 9.2 Guest挂载

```bash
mount -t 9p -o trans=virtio,version=9p2000.L datashare /mnt/data
```

---

## 十、VIRTIO设备

### 10.1 设备列表

| 设备 | 说明 | 参数 |
|-----|------|------|
| virtio-blk-pci | 块设备 | `-device virtio-blk-pci,drive=<id>` |
| virtio-net-pci | 网卡 | `-device virtio-net-pci,netdev=<id>` |
| virtio-balloon | 内存气球 | `-device virtio-balloon` |
| virtio-rng | 随机数 | `-device virtio-rng` |
| virtio-serial | 串口 | `-device virtio-serial` |
| virtconsole | 虚拟终端 | `-device virtconsole,chardev=<id>` |

### 10.2 使用示例

```bash
# 内存气球
-device virtio-balloon

# 随机数生成器
-device virtio-rng

# 串口设备
-device virtio-serial
-chardev socket,path=/tmp/serial.sock,server,nowait,id=serial0
-device virtconsole,chardev=serial0
```

---

## 十一、固件

### 11.1 UEFI固件

**参数**: `-bios <file>`

**常用固件**: `edk2-aarch64-code.fd`

**查找固件**:
```bash
# Linux
find /usr/share -name "edk2-aarch64-code.fd" 2>/dev/null
find /usr/share/AAVMF -name "*.fd" 2>/dev/null

# Mac
find /opt/homebrew/Cellar/qemu -name "edk2-aarch64-code.fd" 2>/dev/null
```

---

## 十二、显示与控制台

### 12.1 无图形模式

**参数**: `-nographic`

**说明**: 使用串口作为控制台

### 12.2 VGA显示

**参数**: `-vga std`

### 12.3 VNC

**参数**: `-vnc <display>`

**示例**:
```bash
-vnc :0  # 监听5900端口
-vnc :1  # 监听5901端口
```

---

## 十三、Monitor控制

### 13.1 stdio monitor

**参数**: `-monitor stdio`

**说明**: 在终端交互式控制

### 13.2 QMP (JSON协议)

**参数**: `-qmp <protocol>:<address>`

**示例**:
```bash
-qmp tcp:localhost:4444,server,nowait
```

### 13.3 常用Monitor命令

| 命令 | 说明 |
|-----|------|
| `info cpus` | 查看CPU状态 |
| `info mem` | 查看内存状态 |
| `info block` | 查看块设备 |
| `info network` | 查看网络设备 |
| `device_add` | 热插设备 |
| `device_del` | 热拔设备 |
| `migrate` | 发起迁移 |
| `quit` | 退出QEMU |
```

---

## Task 10: 编写基础模板

**Files:**
- Create: `qemu-vm-launcher/templates/basic.yaml`

- [ ] **Step 1: 编写basic.yaml**

```yaml
name: basic
description: 基础虚机启动模板
version: "1.0"

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
  display: nographic

defaults:
  accel: kvm
  cpu: host
  smp: 4
  memory: 4G
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
    {display}

notes: |
  - accel: kvm需要/dev/kvm支持，tcg为纯软件模拟
  - bios: 需要UEFI固件，查找路径见qemu-reference.md
  - ssh_port: Host端口转发到Guest 22端口
```

---

## Task 11: 编写NUMA模板

**Files:**
- Create: `qemu-vm-launcher/templates/numa.yaml`

- [ ] **Step 1: 编写numa.yaml**

```yaml
name: numa
description: NUMA拓扑配置模板
version: "1.0"

params:
  machine: virt
  accel: kvm
  cpu: host
  smp: 8
  memory: 8G
  bios: edk2-aarch64-code.fd
  
  # NUMA配置
  numa:
    nodes:
      - nodeid: 0
        cpus: "0-3"
        mem: "4G"
      - nodeid: 1
        cpus: "4-7"
        mem: "4G"
    distances:
      - src: 0
        dst: 1
        val: 20

defaults:
  node_count: 2
  cpus_per_node: 4

cmd_template: |
  qemu-system-aarch64 \
    -machine {machine},accel={accel} \
    -cpu {cpu} \
    -smp {smp} \
    -m {memory} \
    {numa_params} \
    -bios {bios} \
    -drive file={drive},if=none,id=hd0,format=qcow2 \
    -device virtio-blk-pci,drive=hd0 \
    -nographic

numa_param_template: |
  -numa node,nodeid={nodeid},cpus={cpus},mem={mem}

notes: |
  - NUMA节点数量建议不超过8个
  - CPU分配不能重叠
  - 节点距离可选配置
```

---

## Task 12: 编写VFIO模板

**Files:**
- Create: `qemu-vm-launcher/templates/vfio.yaml`

- [ ] **Step 1: 编写vfio.yaml**

```yaml
name: vfio
description: VFIO设备直通模板
version: "1.0"

params:
  machine: virt
  accel: kvm
  cpu: host
  smp: 4
  memory: 4G
  bios: edk2-aarch64-code.fd
  
  # VFIO配置
  vfio:
    devices:
      - bdf: "0000:04:00.0"
        id: "vfio0"

prerequisites:
  - IOMMU支持
  - vfio-pci模块加载
  - 设备绑定到vfio-pci

cmd_template: |
  qemu-system-aarch64 \
    -machine {machine},accel={accel} \
    -cpu {cpu} \
    -smp {smp} \
    -m {memory} \
    -bios {bios} \
    {vfio_params} \
    -drive file={drive},if=none,id=hd0,format=qcow2 \
    -device virtio-blk-pci,drive=hd0 \
    -nographic

vfio_param_template: |
  -device vfio-pci,host={bdf},id={id}

host_preparation: |
  # 加载vfio-pci模块
  modprobe vfio_pci
  
  # 查看设备BDF
  lspci -nn | grep <设备名>
  
  # 解绑原驱动
  echo <bdf> > /sys/bus/pci/devices/<bdf>/driver/unbind
  
  # 绑定vfio-pci
  echo vfio-pci > /sys/bus/pci/devices/<bdf>/driver_override

notes: |
  - VFIO直通需要IOMMU支持
  - 设备必须先绑定到vfio-pci驱动
  - BDF格式: DDDD:BB:DD.F
```

---

## Task 13: 编写热迁移模板

**Files:**
- Create: `qemu-vm-launcher/templates/migration.yaml`

- [ ] **Step 1: 编写migration.yaml**

```yaml
name: migration
description: 热迁移配置模板
version: "1.0"

params:
  machine: virt
  accel: kvm
  cpu: host
  smp: 4
  memory: 4G
  bios: edk2-aarch64-code.fd
  
  # 迁移配置
  migration:
    role: target  # target 或 source
    protocol: tcp
    address: "0:4444"
    parameters:
      max_bandwidth: "100M"
      downtime_limit: "300ms"

roles:
  target:
    description: 迁移目标端，等待接收
    extra_params: "-incoming {protocol}:{address}"
    
  source:
    description: 迁移源端，发起迁移
    monitor_command: "migrate {protocol}:{address}"

cmd_template_target: |
  qemu-system-aarch64 \
    -machine {machine},accel={accel} \
    -cpu {cpu} \
    -smp {smp} \
    -m {memory} \
    -bios {bios} \
    -drive file={drive},if=none,id=hd0,format=qcow2 \
    -device virtio-blk-pci,drive=hd0 \
    -incoming tcp:0:{port} \
    -nographic

cmd_template_source: |
  qemu-system-aarch64 \
    -machine {machine},accel={accel} \
    -cpu {cpu} \
    -smp {smp} \
    -m {memory} \
    -bios {bios} \
    -drive file={drive},if=none,id=hd0,format=qcow2 \
    -device virtio-blk-pci,drive=hd0 \
    -monitor stdio \
    -nographic

migration_commands: |
  # 在源端QEMU monitor中执行
  migrate tcp:<target_ip>:4444
  migrate_set_parameter max-bandwidth 100M
  migrate_set_parameter downtime-limit 300
  info migrate

notes: |
  - 目标端和源端需要相同配置
  - 存储需要共享或同时迁移
  - 迁移期间Guest继续运行
```

---

## Task 14: 编写VIRTIO模板

**Files:**
- Create: `qemu-vm-launcher/templates/virtio.yaml`

- [ ] **Step 1: 编写virtio.yaml**

```yaml
name: virtio
description: VIRTIO设备配置模板
version: "1.0"

params:
  machine: virt
  accel: kvm
  cpu: host
  smp: 4
  memory: 4G
  bios: edk2-aarch64-code.fd
  
  # VIRTIO设备配置
  virtio:
    storage:
      type: virtio-blk-pci
      drive_format: qcow2
    
    network:
      type: virtio-net-pci
      backend: user
      ssh_port: 2222
    
    balloon: true
    rng: true
    serial: false

devices:
  virtio-blk-pci:
    description: VIRTIO块设备
    params: "-device virtio-blk-pci,drive=<id>"
    
  virtio-net-pci:
    description: VIRTIO网卡
    params: "-device virtio-net-pci,netdev=<id>"
    
  virtio-balloon:
    description: 内存气球，动态调整内存
    params: "-device virtio-balloon"
    
  virtio-rng:
    description: 随机数生成器
    params: "-device virtio-rng"
    
  virtio-serial:
    description: VIRTIO串口
    params: "-device virtio-serial"

cmd_template: |
  qemu-system-aarch64 \
    -machine {machine},accel={accel} \
    -cpu {cpu} \
    -smp {smp} \
    -m {memory} \
    -bios {bios} \
    -drive file={drive},if=none,id=hd0,format={drive_format} \
    -device virtio-blk-pci,drive=hd0 \
    -netdev user,id=net0,hostfwd=tcp::{ssh_port}-:22 \
    -device virtio-net-pci,netdev=net0 \
    {virtio_extra_devices} \
    -nographic

extra_devices_template: |
  {balloon}  # -device virtio-balloon
  {rng}      # -device virtio-rng
  {serial}   # -device virtio-serial

notes: |
  - VIRTIO设备性能优于模拟设备
  - balloon: 动态调整Guest内存
  - rng: 提供随机数，加速启动
  - serial: 用于串口通信
```

---

## Task 15: 编写SKILL.md主文件

**Files:**
- Create: `qemu-vm-launcher/SKILL.md`

- [ ] **Step 1: 编写SKILL.md**

```markdown
---
name: qemu-vm-launcher
description: QEMU虚拟机启动助手，提供镜像准备、配置向导、命令生成等功能。触发条件：启动QEMU虚拟机、配置虚机、QEMU命令生成、openEuler镜像下载、minifs构建。
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, skip this skill.
</SUBAGENT-STOP>

# QEMU VM Launcher Skill

本skill帮助用户快速启动QEMU aarch64虚拟机，提供完整的镜像准备、配置向导和命令生成流程。

---

## 一、概述

**支持架构**: aarch64（固定）

**核心功能**:
- 镜像准备：openEuler qcow2下载或minifs构建
- 分层配置向导：核心配置 + 高级配置（可选）
- QEMU命令自动生成
- 完整脚本工具集

**使用场景**:
- 内部团队开发调试
- CI/CD自动化测试环境

---

## 二、工作流程

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

### 步骤4: 命令生成

**读取模板**:
```yaml
# 参考 templates/basic.yaml
```

**叠加参数**:
- 基础框架 + 用户配置
- 高级参数按需添加

**校验参数**:
```yaml
# 参考 docs/qemu-params.yaml
```

**拼接命令**:

基础框架:
```bash
qemu-system-aarch64 \
  -machine virt,accel=${accel} \
  -cpu ${cpu} \
  -smp ${smp} \
  -m ${memory} \
  -bios ${bios} \
  -drive file=${image},if=none,id=hd0,format=qcow2 \
  -device virtio-blk-pci,drive=hd0 \
  -netdev user,id=net0,hostfwd=tcp::${ssh_port}-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

高级参数叠加规则:
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

**附加提示**:
- SSH登录方式
- 绑核命令（如配置）
- Monitor命令（如热迁移）

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

**基础启动**:
```bash
qemu-system-aarch64 \
  -machine virt,accel=kvm \
  -cpu host \
  -smp 4 \
  -m 4G \
  -bios edk2-aarch64-code.fd \
  -drive file=openEuler.qcow2,if=none,id=hd0,format=qcow2 \
  -device virtio-blk-pci,drive=hd0 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic

# SSH登录
ssh root@localhost -p 2222
# 密码: {VM_PASSWORD}
```

---

## 七、注意事项

**固件查找**:
```bash
find /usr/share -name "edk2-aarch64-code.fd" 2>/dev/null
```

**KVM检查**:
```bash
[ -e /dev/kvm ] && echo "KVM可用" || echo "使用TCG"
```

**大页配置**:
```bash
echo 1024 > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages
```

**VFIO准备**:
```bash
modprobe vfio_pci
lspci -nn  # 查看设备BDF
```

---

## 八、常见问题

**Q: 找不到固件文件？**
A: 使用find命令搜索，或安装AAVMF包

**Q: KVM不可用？**
A: 检查/dev/kvm权限，或使用TCG模式

**Q: 网络无法SSH？**
A: 检查hostfwd端口配置，确认Guest内sshd运行

**Q: 热迁移失败？**
A: 确保两端配置一致，存储共享或同步迁移
```

---

## Task 16: 验证文件结构

- [ ] **Step 1: 列出所有创建的文件**

```bash
find qemu-vm-launcher -type f | sort
```

Expected: 显示15个文件

- [ ] **Step 2: 验证脚本权限**

```bash
ls -la qemu-vm-launcher/scripts/
```

Expected: 所有脚本有执行权限（-rwxr-xr-x）

- [ ] **Step 3: 测试check-kvm.sh**

```bash
./qemu-vm-launcher/scripts/check-kvm.sh
```

Expected: 输出JSON格式环境报告

---

## Task 17: 创建使用示例脚本

**Files:**
- Create: `qemu-vm-launcher/examples/start-basic.sh`

- [ ] **Step 1: 创建示例脚本**

```bash
#!/bin/bash
# start-basic.sh - 基础启动示例

# 设置固件路径
BIOS=""
for path in /usr/share/qemu /usr/share/AAVMF /opt/homebrew/Cellar/qemu/*/share/qemu; do
    if [ -f "$path/edk2-aarch64-code.fd" ]; then
        BIOS="$path/edk2-aarch64-code.fd"
        break
    fi
done

if [ -z "$BIOS" ]; then
    echo "错误: 未找到UEFI固件"
    exit 1
fi

# 设置镜像路径
IMAGE=""
for f in *.qcow2 *.img; do
    if [ -f "$f" ]; then
        IMAGE="$f"
        break
    fi
done

if [ -z "$IMAGE" ]; then
    echo "错误: 未找到镜像文件"
    echo "请先下载镜像: ./scripts/download-image.sh"
    exit 1
fi

# 检查KVM
ACCEL="tcg"
if [ -e /dev/kvm ] && [ -w /dev/kvm ]; then
    ACCEL="kvm"
fi

echo "启动QEMU虚机..."
echo "固件: $BIOS"
echo "镜像: $IMAGE"
echo "加速: $ACCEL"

qemu-system-aarch64 \
  -machine virt,accel=$ACCEL \
  -cpu host \
  -smp 4 \
  -m 4G \
  -bios "$BIOS" \
  -drive file="$IMAGE",if=none,id=hd0,format=qcow2 \
  -device virtio-blk-pci,drive=hd0 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

- [ ] **Step 2: 设置执行权限**

```bash
chmod +x qemu-vm-launcher/examples/start-basic.sh
```

- [ ] **Step 3: 创建examples目录**

需要先创建目录:
```bash
mkdir -p qemu-vm-launcher/examples
```

---

## Task 18: 最终验证

- [ ] **Step 1: 验证完整目录结构**

```bash
tree qemu-vm-launcher/ || find qemu-vm-launcher -type f | sort
```

Expected: 显示完整目录结构

- [ ] **Step 2: 验证文档内容**

```bash
wc -l qemu-vm-launcher/docs/*.md qemu-vm-launcher/docs/*.yaml
```

Expected: 显示文档行数

- [ ] **Step 3: 验证模板内容**

```bash
wc -l qemu-vm-launcher/templates/*.yaml
```

Expected: 显示模板行数

---

## 实现完成

所有任务完成后，skill目录结构如下：

```
qemu-vm-launcher/
├── SKILL.md                      # 主skill文件
├── docs/
│   ├── qemu-commands.md          # 命令说明书
│   ├── qemu-params.yaml          # 参数校验
│   └── qemu-reference.md         # 参数参考
├── templates/
│   ├── basic.yaml                # 基础模板
│   ├── numa.yaml                 # NUMA模板
│   ├── vfio.yaml                 # VFIO模板
│   ├── migration.yaml            # 热迁移模板
│   └── virtio.yaml               # VIRTIO模板
├── scripts/
│   ├── check-kvm.sh              # 环境检查
│   ├── download-image.sh         # 镜像下载
│   ├── build-minifs.sh           # minifs构建
│   ├── pin-cpu-1v1.sh            # 1v1绑核
│   └── pin-cpu-range.sh          # 范围绑核
└── examples/
    └── start-basic.sh            # 启动示例
```