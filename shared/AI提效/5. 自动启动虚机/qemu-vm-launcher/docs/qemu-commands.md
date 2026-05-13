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