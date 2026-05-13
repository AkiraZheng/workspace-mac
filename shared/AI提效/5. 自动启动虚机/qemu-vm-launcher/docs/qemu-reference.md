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