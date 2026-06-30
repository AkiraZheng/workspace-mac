# HDBSS + VFIO Debug 流程文档

## 问题背景

**场景**: 带 VFIO 加速器设备，两次热迁移后第二次报错
**报错**: `get_pci_config_device: Bad config data: i=0x4a read: 0 device: 8 cmask: ff wmask: 0`
**差异**: EVB 正常，FPGA 失败

## 核心假设

**DBM 位被错误添加到 VFIO MMIO 区域，导致设备状态同步异常**

---

## 一、调试 Patch 应用

### 1.1 编译内核

```bash
# 应用 debug patch
cd /root/openeuler/kernel
git apply /mnt/shared/HDBSS/HDBSS_v4_patch/DS/debug_hdbss_vfio.patch

# 或者手动添加 debug 打印（见下文）

# 编译
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc)
```

### 1.2 Debug 打印关键点

| 文件 | 函数 | Debug 内容 |
|------|------|-----------|
| `mmu.c` | `user_mem_abort()` | Device 检测 + DBM 决策 |
| `handle_exit.c` | `kvm_flush_hdbss_buffer()` | 脏页记录内容 |
| `arm.c` | `kvm_cap_arm_enable_hdbss()` | 启用/禁用时机 |

---

## 二、调试步骤

### 2.1 准备环境

**源端 (Host A)**:
```bash
# 启用 kernel log
echo 8 > /proc/sys/kernel/printk

# 创建 debug 日志目录
mkdir -p /tmp/hdbss_debug
```

**目标端 (Host B)**:
```bash
# 同样启用 kernel log
echo 8 > /proc/sys/kernel/printk
mkdir -p /tmp/hdbss_debug
```

### 2.2 第一次迁移 (A → B)

**源端启动**:
```bash
qemu-system-aarch64 -machine virt,kernel_irqchip=on,gic-version=3,nvdimm=on \
-accel kvm -net none -nographic \
-kernel ${mypath}/Image -initrd ${mypath}/minifs_full.cpio.gz \
-cpu host,pmu=off,sve=on,sve128=on,sve256=off \
-m 4G,maxmem=20G,slots=3 -smp 4 \
-append 'rdinit=init console=ttyAMA0 earlycon=pl011,0x9000000' \
-device vfio-pci,host=1d:00.1,enable-migration=on,x-pre-copy-dirty-page-tracking=off

# 同时捕获 kernel log
dmesg -w > /tmp/hdbss_debug/hostA_migration1.log &
```

**目标端启动**:
```bash
qemu-system-aarch64 -machine virt,kernel_irqchip=on,gic-version=3,nvdimm=on \
-accel kvm -net none -nographic \
-kernel ${mypath}/Image -initrd ${mypath}/minifs_full.cpio.gz \
-cpu host,pmu=off,sve=on,sve128=on,sve256=off \
-m 4G,maxmem=20G,slots=3 -smp 4 \
-append 'rdinit=init console=ttyAMA0 earlycon=pl011,0x9000000' \
-device vfio-pci,host=1d:00.2,enable-migration=on,x-pre-copy-dirty-page-tracking=off \
-incoming tcp:0:7777

# 同时捕获 kernel log
dmesg -w > /tmp/hdbss_debug/hostB_migration1.log &
```

**迁移执行**:
```bash
# (qemu) migrate tcp:0:7777
```

### 2.3 在目标端运行 Workload

**Guest 内**:
```bash
# 加载加速器驱动
insmod /lib/modules/$(uname -r)/uacce.ko
insmod /lib/modules/$(uname -r)/hisi_qm.ko
insmod /lib/modules/$(uname -r)/hisi_zip.ko uacce_mode=2

# 运行 workload
kp_utools u_accv1 -a gzip -t 1 -n compress-stream-4K -k 1024 -s 0 -d hisi_zip-0 v -L300 &
```

**目标端 Host**:
```bash
# 持续捕获 kernel log
dmesg -w > /tmp/hdbss_debug/hostB_workload.log &
```

### 2.4 第二次迁移 (B → A)

**目标端 (现在作为源)**:
```bash
# (qemu) migrate tcp:0:6666

# Kernel log 持续记录
dmesg -w > /tmp/hdbss_debug/hostB_migration2.log &
```

**源端 (现在作为目标)**:
```bash
qemu-system-aarch64 ... -incoming tcp:0:6666

# Kernel log 持续记录
dmesg -w > /tmp/hdbss_debug/hostA_migration2.log &
```

### 2.5 检查失败时的 Log

**如果失败，检查**:
```bash
# 查看最后的错误
grep -i "error\|fail\|Bad config" /tmp/hdbss_debug/*.log

# 查看 HDBSS debug 输出
grep "HDBSS_DEBUG" /tmp/hdbss_debug/*.log
```

---

## 三、关键信息分析

### 3.1 Device 检测是否正确

**期望输出**:
```
HDBSS_DEBUG: Device MMIO fault detected! fault_ipa=0x... pfn=0x... device=true
```

**分析**:
- 如果 `device=true`，说明正确识别了 MMIO
- 如果 `device=false`，说明 `pfn_is_map_memory()` 返回了错误值

### 3.2 DBM 决策是否正确

**期望输出 (MMIO)**:
```
HDBSS_DEBUG: DBM decision: fault_ipa=0x... device=1 enable_hdbss=1 logging_active=1 writable=1
```

**分析**:
- `device=1` 时，即使 `enable_hdbss=1`，DBM 也**不应该**被添加
- 修复后的代码: `if (!device && kvm->enable_hdbss && logging_active)`
- Bug 代码: `if (kvm->enable_hdbss && logging_active)` ← 缺少 `!device` 检查

### 3.3 HDBSS Buffer 内容

**期望输出**:
```
HDBSS_DEBUG: Marking page dirty gpa=0x... (entry X/Y)
```

**分析**:
- 如果 MMIO GPA 出现在这里，说明 DBM 被错误添加
- MMIO 地址通常是高地址（如 `0x...1d...`）

### 3.4 FPGA vs EVB 差异对比

| 对比项 | EVB | FPGA |
|--------|-----|------|
| `pfn_is_map_memory()` 对 MMIO 的返回 | 可能返回 false | 可能返回 true? |
| Device 检测 | device=true | device=false? |
| DBM 添加 | 正常不添加 | 可能被添加 |
| HDBSS buffer | 只有 RAM 脏页 | 可能包含 MMIO |

---

## 四、核心 Bug 验证

### 4.1 Bug 代码 (修复前)

```c
// mmu.c:1682
#ifdef CONFIG_ARM64_HDBSS
	if (kvm->enable_hdbss && logging_active)  // ← 缺少 !device 检查
		prot |= KVM_PGTABLE_PROT_DBM;
#endif
```

**问题**: 
- `device` 在第 1620 行设置
- 但 DBM 添加在第 1682 行，没有检查 `device`
- `prot |= KVM_PGTABLE_PROT_DEVICE` 在第 1690 行，**在 DBM 之后**

### 4.2 修复代码

```c
#ifdef CONFIG_ARM64_HDBSS
	if (!device && kvm->enable_hdbss && logging_active)
		prot |= KVM_PGTABLE_PROT_DBM;
#endif
```

---

## 五、Debug Log 分析脚本

```bash
#!/bin/bash
# analyze_hdbss_debug.sh

echo "=== HDBSS Debug Analysis ==="

# 1. 统计 device fault 数量
echo "\n1. Device MMIO faults detected:"
grep "Device MMIO fault detected" /tmp/hdbss_debug/*.log | wc -l

# 2. 检查是否有 MMIO 地址进入 DBM 决策
echo "\n2. DBM decisions for MMIO (device=1):"
grep "DBM decision.*device=1" /tmp/hdbss_debug/*.log | head -10

# 3. 检查 HDBSS buffer 中的 GPA 地址
echo "\n3. Dirty pages marked (GPA range):"
grep "Marking page dirty gpa" /tmp/hdbss_debug/*.log | awk '{print $NF}' | sort -u | head -20

# 4. 检查是否有高地址 (可能是 MMIO)
echo "\n4. High GPA addresses (>4GB or device range):"
grep "Marking page dirty gpa=0x[1-9a-f]" /tmp/hdbss_debug/*.log | grep -v "gpa=0x0" | head -10

# 5. 检查错误信息
echo "\n5. Errors found:"
grep -i "error\|fail\|bad config" /tmp/hdbss_debug/*.log | tail -5
```

---

## 六、期望的 Debug 输出

### 6.1 正常情况 (修复后)

```
# RAM fault - 正常添加 DBM
HDBSS_DEBUG: DBM decision: fault_ipa=0x8000 device=0 enable_hdbss=1 logging_active=1 writable=1
HDBSS_DEBUG: DBM added for RAM fault_ipa=0x8000

# MMIO fault - 不添加 DBM
HDBSS_DEBUG: Device MMIO fault detected! fault_ipa=0x1d000 pfn=0x... device=1
HDBSS_DEBUG: DBM decision: fault_ipa=0x1d000 device=1 enable_hdbss=1 logging_active=1 writable=1
# (没有 "DBM added" 输出，因为 !device 条件不满足)
```

### 6.2 Bug 情况 (修复前，FPGA)

```
# MMIO fault - Bug: DBM 被错误添加
HDBSS_DEBUG: Device MMIO fault detected! fault_ipa=0x1d000 pfn=0x... device=1
HDBSS_DEBUG: DBM decision: fault_ipa=0x1d000 device=1 enable_hdbss=1 logging_active=1 writable=1
# Bug: 这里应该没有 DBM，但代码没有检查 device
# (prot |= KVM_PGTABLE_PROT_DBM 被执行了)

# HDBSS buffer 包含 MMIO 地址
HDBSS_DEBUG: Marking page dirty gpa=0x1d000 (entry 5/10)  ← 这是错误的！
```

---

## 七、根本原因假设

### 7.1 FPGA 特殊情况

**假设 1: pfn_is_map_memory() 在 FPGA 上对 MMIO 返回 true**

```c
// mmu.c:185
static bool kvm_is_device_pfn(unsigned long pfn)
{
    return !pfn_is_map_memory(pfn);
}

// mm/init.c:291
int pfn_is_map_memory(unsigned long pfn)
{
    phys_addr_t addr = PFN_PHYS(pfn);
    return memblock_is_map_memory(addr);
}
```

**FPGA 可能问题**:
- MMIO 地址范围可能在 `memblock` 中声明为有效内存
- 导致 `kvm_is_device_pfn(pfn)` 返回 false
- `device` 变量不会设置为 true

### 7.2 验证方法

```bash
# 在 Guest 中查看设备 BAR 地址
lspci -vv -s 0000:1d:00.1 | grep "Region"

# 输出示例:
# Region 0: Memory at 1d0000000 (64-bit, non-prefetchable) [size=64K]
# Region 2: Memory at 1d0010000 (64-bit, non-prefetchable) [size=64K]

# 在 Host 中查看 memblock
cat /sys/kernel/debug/memblock/memory | grep -i "1d"
```

---

## 八、总结

**调试目标**:
1. 确认 FPGA 上 `device` 是否正确设置
2. 确认 MMIO 地址是否进入 HDBSS buffer
3. 确认 EVB vs FPGA 的差异点

**关键修复**:
- `mmu.c:1682`: 添加 `!device` 检查
- 确保 DBM 只用于 RAM，不用于 MMIO

**后续行动**:
1. 应用 debug patch 并收集 log
2. 分析 FPGA 和 EVB 的差异
3. 确认修复有效
4. 如有必要，进一步调查 `pfn_is_map_memory()` 行为

---

*整理时间: 2026-05-15*