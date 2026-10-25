# VFIO 直通鲲鹏 ZIP 加速器 - 虚机内 non-SVA (NOIOMMU) 模式测试方案

## 1. 环境背景

| 项 | 值 |
|----|----|
| 宿主机 | 192.168.90.60, openEuler 24.03 LTS SP3 aarch64 (鲲鹏920), 内核 6.6.0-132.0.0.111.oe2403sp3 |
| 虚机 | openEuler 24.03 LTS qcow2, 内核 6.6.0-28.0.0.34.oe2403, KVM 加速 |
| 加速器 | HiSilicon ZIP Engine (vendor 19e5, device a250), 4G内存/4核 |
| 直通设备 | 0000:31:00.0 (IOMMU group 25, 独占分组) |
| 宿主机保留 | 0000:33:00.0 (第二个 ZIP Engine, 不直通) |
| 虚机 SSH | 在宿主机上执行: ssh root@localhost -p 2222 (root / VM_PASSWORD) |

## 2. 为什么用 non-SVA (NOIOMMU) 模式

uacce 框架有两种用户态工作模式:

| 模式 | 依赖 | 说明 |
|------|------|------|
| SVA | IOMMU + PASID | 进程虚拟地址直接 DMA; QEMU 8.2 模拟 SMMU 无法为直通设备提供 DMA 翻译, 不可用 |
| NOIOMMU (non-SVA) | 无 IOMMU 依赖 | 队列 mmap 时 pin user pages, DMA 用物理地址; VFIO 已把 guest 物理内存全部映射进宿主机 SMMU, 直通场景天然可用 |

**关键参数**: hisi_zip 模块参数 uacce_mode (openEuler 24.03 LTS 内核 6.6.0-28.0.0.34 枚举):

| 值 | 含义 | 行为 |
|----|------|------|
| 0 | UACCE_MODE_NOUACCE (默认) | 只注册 crypto (内核态 acomp), 不注册 uacce |
| 1 | UACCE_MODE_SVA | SVA 模式; 虚机无 IOMMU 时报 iommu not support sva! + fail to alloc uacce (-22) |
| 2 | UACCE_MODE_NOIOMMU | non-SVA 模式, 本方案使用; dmesg 打印 register to noiommu mode 警告属正常 |

注意: 不同内核版本枚举顺序不同 (modinfo hisi_zip 查看参数说明, 以实测为准)。

## 3. 宿主机侧准备 (已自动化)

启动脚本 /home/zt/vm-bootkit/start-vm-vfio.sh 自动完成:

1. fuser 检查 qcow2 镜像未被占用 (防止同一镜像双开损坏)
2. 加载 vfio-pci 模块
3. echo vfio-pci > /sys/bus/pci/devices/0000:31:00.0/driver_override
4. 解绑宿主机 hisi_zip 驱动, 绑定 vfio-pci
5. 启动 QEMU, 关键参数 -device vfio-pci,host=0000:31:00.0

```bash
# 交互式前台启动:
/home/zt/vm-bootkit/start-vm-vfio.sh

# 后台启动 (串口日志落盘):
cd /home/zt && setsid nohup /home/zt/vm-bootkit/start-vm-vfio.sh > /home/zt/vm-console.log 2>&1 < /dev/null &
```

启动后确认宿主机侧绑定:

```bash
lspci -k -s 31:00.0 | grep "Kernel driver"    # 预期: Kernel driver in use: vfio-pci
```

## 4. 虚机内加载驱动并验证

等待约 45 秒虚机启动完成后, 在宿主机上进入虚机:

```bash
sshpass -p "VM_PASSWORD" ssh -o StrictHostKeyChecking=no root@localhost -p 2222
```

### 4.1 加载驱动 (non-SVA 模式)

```bash
modprobe uacce
modprobe hisi_zip uacce_mode=2
```

### 4.2 验证清单

```bash
# 1) PCI 设备可见且驱动绑定 (虚机内无 lspci, 用 sysfs)
ls -l /sys/bus/pci/devices/0000:00:02.0/driver
# 预期: .../bus/pci/drivers/hisi_zip

# 2) uacce 设备注册
ls /sys/class/uacce/
# 预期: hisi_zip-0

# 3) 字符设备节点
ls -la /dev/hisi_zip-0
# 预期: crw------- 244,0 ...  /dev/hisi_zip-0

# 4) 模式确认
cat /sys/class/uacce/hisi_zip-0/flags
# 预期: 2  (UACCE_DEV_NOIOMMU)

# 5) 支持的算法
cat /sys/class/uacce/hisi_zip-0/algorithms
# 预期: zlib gzip deflate lz77_zstd

# 6) 内核态 acomp 后端 (独立于 uacce, 默认就有)
grep -B1 hisi-deflate /proc/crypto
# 预期: name: deflate / driver: hisi-deflate-acomp / module: hisi_zip

# 7) dmesg 关键日志
dmesg | grep -iE "uacce|noiommu|hisi_zip" | tail
# 预期:
#   uacce hisi_zip-0: register to noiommu mode, it is not safe for kernel
#   hisi_zip 0000:00:02.0: qm register to uacce
```

### 4.3 持久化 (重启自动生效)

已配置:

```bash
# /etc/modprobe.d/hisi-zip.conf
options hisi_zip uacce_mode=2

# /etc/modules-load.d/hisi-zip.conf
hisi_zip
uacce
```

## 5. 常见问题排查

| 现象 | 原因与解决 |
|------|-----------|
| /sys/class/uacce 为空 | uacce_mode 未传或为 0 (默认不注册 uacce), modprobe -r hisi_zip 后用 uacce_mode=2 重载 |
| dmesg: iommu not support sva! + fail to alloc uacce (-22) | uacce_mode=1 是 SVA 模式, 虚机无 IOMMU 不支持; 改用 uacce_mode=2 |
| grep 日志漏关键信息 | 排查时 dmesg 过滤模式要含 sva 关键字 (iommu not support sva 这行不含 uacce 字样) |
| 虚机内 lspci: 未找到命令 | 最小化镜像无 pciutils, 用 /sys/bus/pci/devices/ 或 yum install pciutils |
| 驱动模块残留无法卸载 | modprobe -r hisi_zip 前确认无进程占用 /dev/hisi_zip-0; 或直接 unbind/bind 设备 |
| 端口 2222 不可达 | 虚机 sshd 未起完, 等 20-60 秒重试 |
| 虚机重启后直通设备消失 | 检查宿主机侧 31:00.0 是否仍为 vfio-pci 绑定 |

## 6. 宿主机恢复设备 (不再直通时)

```bash
echo 0000:31:00.0 > /sys/bus/pci/drivers/vfio-pci/unbind
echo "" > /sys/bus/pci/devices/0000:31:00.0/driver_override
echo 0000:31:00.0 > /sys/bus/pci/drivers/hisi_zip/bind
```

## 7. 相关文件

| 路径 | 说明 |
|------|------|
| /home/zt/vm-bootkit/start-vm-vfio.sh | 直通启动脚本 (自动解绑/绑定/启动) |
| /home/zt/vm-bootkit/start-vm.sh | 普通启动脚本 (无直通) |
| /home/zt/vm-bootkit/openEuler-24.03-LTS-aarch64.qcow2 | 虚机镜像 |
| /home/zt/vm-bootkit/vmlinuz / initramfs.img | 从镜像提取的内核 |
| /home/zt/vm-console.log | 虚机串口日志 |
| /home/zt/skill-scripts/ | 工具脚本 (ssh-test/fix-ssh-config/extract-kernel 等) |

## 8. 本次踩坑经验

1. uacce 没注册的根因是 uacce_mode 默认为 0, 而非 IOMMU 缺失; non-SVA 不需要 IOMMU
2. 24.03 LTS 内核 (6.6.0-28.0.0.34) 枚举 1=SVA, 2=NOIOMMU; 与新版内核 (SP3) 描述不同, 必须 modinfo + 实测确认
3. uacce.c 对 NOIOMMU 只打警告不阻止注册; hisi_qm 的 qm_alloc_uacce 在非 SVA 模式下对无 IOMMU 完全兼容
4. ssh 远程执行 pkill -f qemu-system-aarch64 会误杀外层 bash (命令行含同名字符串), 用 pkill 按进程名或 fuser 按文件占用检查
5. 排查设备问题时 dmesg grep 模式要覆盖 iommu/sva/uacce/qm 全部关键字
