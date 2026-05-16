# HDBSS VFIO Migration Debug 方案 (更新版)

## 一、问题根本原因（已确认）

**双重 Bug**:
1. **Kernel Bug**: HDBSS 给 VFIO MMIO 区域错误添加 DBM
2. **QEMU Bug**: VFIO 普通迁移缺少 cmask 限制机制

**对比校验机制**:
- 源端保存：QEMU 缓存的 config space 值（保存时不重新读取硬件）
- 目标端验证：从迁移文件读取的值 vs VFIO 初始化时从硬件读取的值
- 硬件只读位（wmask=0）在迁移前后必然不一致

---

## 二、核心 Debug 目标

### 2.1 Kernel Debug 目标

**验证点 1**: MMIO fault 的 `device` 变量是否正确设置

```
mmu.c:1609
if (kvm_is_device_pfn(pfn)) {
    device = true;  ← 这里是否正确执行？
}
```

**验证点 2**: DBM 决策逻辑是否正确

```
mmu.c:1682 (修复前)
if (kvm->enable_hdbss && logging_active)  ← 是否缺少 !device？

mmu.c:1682 (修复后)
if (!device && kvm->enable_hdbss && logging_active)  ← 是否生效？
```

**验证点 3**: HDBSS buffer 是否包含 MMIO GPA

```
handle_exit.c:331
kvm_vcpu_mark_page_dirty(vcpu, gpa >> PAGE_SHIFT);
← gpa 是否包含 VFIO MMIO BAR 地址？
```

### 2.2 QEMU Debug 目标

**验证点 1**: cmask 是否被正确限制

```
pci.c:815-816
if ((config[i] ^ s->config[i]) &
    s->cmask[i] & ~s->wmask[i] & ~s->w1cmask[i])
← cmask[0x4a] 是否为 ff（应该被限制）？
```

**验证点 2**: emulated_config_bits 是否正确设置

```
pci.c:1391
emu_bits = vdev->emulated_config_bits[addr];
← emulated_config_bits[0x4a] 是否为 0（硬件位）？
```

**验证点 3**: 源端保存的值来自哪里

```
pci.c:1385
vfio_pci_read_config(pdev, addr, len)
← 返回的是硬件值还是 QEMU 缓存值？
```

---

## 三、EVB vs FPGA 对比方案

### 3.1 对比目标

| 对比项 | EVB | FPGA | 重要性 |
|--------|-----|------|--------|
| **pfn_is_map_memory()** 对 MMIO 返回 | ? | ? | 高 - 决定 device 变量 |
| **device 变量值** | ? | ? | 高 - DBM 决策关键 |
| **DBM 是否添加到 MMIO** | ? | ? | 高 - Bug 核心表现 |
| **HDBSS 硬件行为** | ? | ? | 高 - 可能忽略 MMIO DBM |
| **PCI config[0x4a]稳定性** | ? | ? | 中 - 触发验证失败 |
| **emulated_config_bits** 设置 | ? | ? | 中 - QEMU 侧差异 |

### 3.2 Kernel 对比 Debug

**在两个平台都添加相同 debug patch，对比输出**

```bash
# 1. 应用 0001-kernel-hdbss-vfio-debug.patch
# 2. 编译部署到 EVB 和 FPGA
# 3. 运行相同的 VM 和 VFIO workload
# 4. 收集 kernel log
```

**对比关键点**:

```bash
# EVB 输出
grep "HDBSS_DEBUG_MMIO_FAULT" /var/log/kern.log | head -20
grep "HDBSS_DEBUG_DBM_DECISION" /var/log/kern.log | grep "device=1"
grep "HDBSS_DEBUG_DBM_RESULT" /var/log/kern.log

# FPGA 输出
grep "HDBSS_DEBUG_MMIO_FAULT" /var/log/kern.log | head -20
grep "HDBSS_DEBUG_DBM_DECISION" /var/log/kern.log | grep "device=1"
grep "HDBSS_DEBUG_DBM_RESULT" /var/log/kern.log

# 对比差异
diff evb_hdbss.log fpga_hdbss.log
```

**关键对比项**:

| 检查项 | EVB 输出期望 | FPGA 输出分析 |
|--------|-------------|--------------|
| MMIO fault 检测 | `device=1` | `device=?` (关键!) |
| DBM 决策 | `device=1` → 无 DBM 结果 | `device=?` → 是否有 DBM？ |
| HDBSS buffer GPA | 只有 RAM 地址 | 是否有 MMIO 地址？ |
| PFN 值 | MMIO PFN 范围 | MMIO PFN 范围是否不同？ |

### 3.3 QEMU 对比 Debug

**在两个平台都添加 QEMU debug patch，对比输出**

```bash
# 1. 应用 0003-qemu-vfio-config-debug.patch
# 2. 编译 QEMU
# 3. 运行 VFIO migration 测试
# 4. 收集 QEMU log
```

**对比关键点**:

```bash
# 第一次迁移时 (A→B)
# EVB 输出
grep "VFIO_DEBUG_READ_0x4a" evb_qemu_mig1.log

# FPGA 输出
grep "VFIO_DEBUG_READ_0x4a" fpga_qemu_mig1.log

# 第二次迁移时 (B→A)
# EVB 输出
grep "VFIO_DEBUG_VALIDATION" evb_qemu_mig2.log

# FPGA 输出
grep "VFIO_DEBUG_VALIDATION" fpga_qemu_mig2.log
```

**关键对比项**:

| 检查项 | EVB | FPGA |
|--------|-----|------|
| 第一次迁移 config[0x4a] | 值1 | 值2 |
| 第二次迁移保存的值 | 值A | 值B |
| 第二次迁移目标端读取的值 | 值C | 值D |
| 验证失败？ | 无 | 有 |
| cmask[0x4a] | ? | ff |
| emulated_bits[0x4a] | ? | ? |

### 3.4 设备硬件状态对比

**检查两个平台的 VFIO 设备硬件**

```bash
# 在 Host 上检查设备 config space
# EVB
lspci -xxx -s 0000:1d:00.1 | head -20
hexdump -C /sys/bus/pci/devices/0000:1d:00.1/config | grep "000004a"

# FPGA
lspci -xxx -s 0000:1d:00.1 | head -20
hexdump -C /sys/bus/pci/devices/0000:1d:00.1/config | grep "000004a"
```

**检查 MMIO BAR 地址范围**

```bash
# EVB
lspci -vv -s 0000:1d:00.1 | grep "Region"

# FPGA
lspci -vv -s 0000:1d:00.1 | grep "Region"
```

**检查 memblock 内存布局**

```bash
# EVB
cat /sys/kernel/debug/memblock/memory | grep "1d"
cat /proc/iomem | grep "1d"

# FPGA
cat /sys/kernel/debug/memblock/memory | grep "1d"
cat /proc/iomem | grep "1d"
```

---

## 四、完整 Debug 流程

### 4.1 准备阶段

**环境准备**:
```bash
# EVB 平台
cd /path/to/kernel_evb
git clean -fdx
git checkout master

# FPGA 平台
cd /path/to/kernel_fpga
git clean -fdx
git checkout master

# 都应用相同的 debug patch
git apply /mnt/shared/HDBSS/HDBSS_v4_patch/DS/0001-kernel-hdbss-vfio-debug.patch
```

**QEMU 准备**:
```bash
# EVB 和 FPGA 都编译相同版本的 QEMU
cd /path/to/qemu
git apply /mnt/shared/HDBSS/HDBSS_v4_patch/DS/0003-qemu-vfio-config-debug.patch
make clean && make
```

### 4.2 单平台测试（先测 FPGA）

**FPGA 第一次迁移 (A→B)**:

```bash
# Host A (FPGA)
# 启用 kernel log
echo 8 > /proc/sys/kernel/printk
dmesg -C

# 启动 VM + VFIO
qemu-system-aarch64 ... -device vfio-pci,host=1d:00.1 ...

# 运行 workload
(qemu) ... workload ...

# 发起迁移
(qemu) migrate tcp:0:7777

# 收集 log
dmesg > /tmp/fpga_hostA_mig1.log
```

```bash
# Host B (FPGA)
echo 8 > /proc/sys/kernel/printk
dmesg -C

# 启动 VM (incoming)
qemu-system-aarch64 ... -device vfio-pci,host=1d:00.2 ... -incoming tcp:0:7777

# 收集 log
dmesg > /tmp/fpga_hostB_mig1.log
```

**FPGA workload 运行**:

```bash
# Guest 内
insmod hisi_zip.ko uacce_mode=2
kp_utools u_accv1 -a gzip ... &
jobs

# Host B 收集 log
dmesg > /tmp/fpga_workload.log
```

**FPGA 第二次迁移 (B→A)**:

```bash
# Host B 发起迁移
(qemu) migrate tcp:0:6666

# 收集 log (应该看到报错)
dmesg > /tmp/fpga_hostB_mig2.log

# QEMU log 检查报错
grep "Bad config data" /tmp/fpga_qemu_mig2.log
```

### 4.3 对比测试（EVB）

**重复相同流程，对比输出**

```bash
# EVB 第一次迁移
dmesg > /tmp/evb_hostA_mig1.log
dmesg > /tmp/evb_hostB_mig1.log

# EVB workload
dmesg > /tmp/evb_workload.log

# EVB 第二次迁移
dmesg > /tmp/evb_hostB_mig2.log
grep "Bad config data" /tmp/evb_qemu_mig2.log  ← 应该没有错误
```

### 4.4 对比分析

**创建对比脚本**:

```bash
cat > /tmp/compare_debug.sh << 'EOF'
#!/bin/bash

echo "=== EVB vs FPGA 对比分析 ==="

echo "\n1. MMIO fault 检测对比"
echo "EVB:"
grep "HDBSS_DEBUG_MMIO_FAULT" /tmp/evb_*.log | wc -l
grep "HDBSS_DEBUG_MMIO_FAULT.*device=" /tmp/evb_*.log | head -5

echo "\nFPGA:"
grep "HDBSS_DEBUG_MMIO_FAULT" /tmp/fpga_*.log | wc -l
grep "HDBSS_DEBUG_MMIO_FAULT.*device=" /tmp/fpga_*.log | head -5

echo "\n2. DBM 决策对比 (MMIO fault)"
echo "EVB:"
grep "HDBSS_DEBUG_DBM_DECISION.*device=1" /tmp/evb_*.log | head -5

echo "\nFPGA:"
grep "HDBSS_DEBUG_DBM_DECISION.*device=1" /tmp/fpga_*.log | head -5

echo "\n3. DBM 结果对比 (是否添加)"
echo "EVB (MMIO faults - 应该无 DBM):"
grep "HDBSS_DEBUG_DBM_RESULT" /tmp/evb_*.log | wc -l
grep "HDBSS_DEBUG_DBM_RESULT" /tmp/evb_*.log | grep "fault_ipa=0x1d" | wc -l

echo "\nFPGA (MMIO faults - 是否有 DBM?):"
grep "HDBSS_DEBUG_DBM_RESULT" /tmp/fpga_*.log | wc -l
grep "HDBSS_DEBUG_DBM_RESULT" /tmp/fpga_*.log | grep "fault_ipa=0x1d" | wc -l

echo "\n4. HDBSS buffer GPA 范围对比"
echo "EVB:"
grep "HDBSS_DEBUG_FLUSH_ENTRY.*gpa=" /tmp/evb_*.log | awk '{print $NF}' | sort -u | head -20

echo "\nFPGA:"
grep "HDBSS_DEBUG_FLUSH_ENTRY.*gpa=" /tmp/fpga_*.log | awk '{print $NF}' | sort -u | head -20

echo "\n5. QEMU config[0x4a] 值对比"
echo "EVB 第一次迁移:"
grep "VFIO_DEBUG_READ_0x4a_RESULT" /tmp/evb_*mig1.log

echo "\nFPGA 第一次迁移:"
grep "VFIO_DEBUG_READ_0x4a_RESULT" /tmp/fpga_*mig1.log

echo "\nEVB 第二次迁移:"
grep "VFIO_DEBUG_VALIDATION" /tmp/evb_*mig2.log

echo "\nFPGA 第二次迁移:"
grep "VFIO_DEBUG_VALIDATION" /tmp/fpga_*mig2.log

echo "\n6. 验证失败对比"
echo "EVB 失败次数:"
grep "VALIDATION_FAIL" /tmp/evb_*.log | wc -l

echo "\nFPGA 失败次数:"
grep "VALIDATION_FAIL" /tmp/fpga_*.log | wc -l
EOF

chmod +x /tmp/compare_debug.sh
/tmp/compare_debug.sh > /tmp/compare_result.txt
```

---

## 五、关键假设验证

### 5.1 假设 1: FPGA 上 pfn_is_map_memory() 对 MMIO 返回 true

**验证方法**:

```bash
# 查看 MMIO fault 的 PFN 值
grep "HDBSS_DEBUG_MMIO_FAULT.*pfn=" /tmp/fpga_*.log | head -10

# 如果 device=0，说明 pfn_is_map_memory() 返回 true
grep "HDBSS_DEBUG_MMIO_FAULT.*device=0" /tmp/fpga_*.log

# 对比 EVB
grep "HDBSS_DEBUG_MMIO_FAULT.*device=1" /tmp/evb_*.log
```

**如果假设成立**:
- FPGA: MMIO fault 时 `device=0`
- EVB: MMIO fault 时 `device=1`
- 说明 FPGA 的 memblock 包含了 MMIO 地址范围

### 5.2 假设 2: HDBSS 硬件对 MMIO DBM 的处理不同

**验证方法**:

```bash
# 即使 device=1，DBM 可能被添加（Bug）
# 检查 FPGA 是否有 MMIO GPA 在 HDBSS buffer

grep "HDBSS_DEBUG_FLUSH_ENTRY.*gpa=0x1d" /tmp/fpga_*.log
```

**如果假设成立**:
- FPGA: MMIO GPA 出现在 HDBSS buffer
- EVB: 没有 MMIO GPA（或硬件忽略了）

### 5.3 假设 3: 设备硬件状态自然变化

**验证方法**:

```bash
# 对比 workload 前后的 config[0x4a] 值

# FPGA 第一次迁移（保存）
grep "VFIO_DEBUG_READ_0x4a_RESULT.*phys_val=" /tmp/fpga_hostA_mig1.log

# FPGA workload 运行后
grep "VFIO_DEBUG_READ_0x4a_RESULT.*phys_val=" /tmp/fpga_workload.log

# FPGA 第二次迁移（加载验证）
grep "VFIO_DEBUG_VALIDATION.*device=" /tmp/fpga_hostB_mig2.log
```

**如果假设成立**:
- Workload 运行后 config[0x4a] 值变化
- 源端保存的旧值 vs 目标端读取的新值不一致

---

## 六、预期对比结果

### 6.1 如果 Bug 存在（FPGA）

| 检查项 | EVB | FPGA |
|--------|-----|------|
| MMIO fault device值 | device=1 | device=0 或 1 |
| DBM 添加到 MMIO | 无（正确） | 有（Bug） |
| HDBSS buffer MMIO GPA | 无 | 有 |
| config[0x4a] 稳定 | 稳定 | 变化 |
| 第二次迁移验证 | 通过 | 失败 |

### 6.2 如果修复生效

| 检查项 | EVB | FPGA (修复后) |
|--------|-----|---------------|
| MMIO fault device值 | device=1 | device=1 |
| DBM 添加到 MMIO | 无 | 无（修复） |
| HDBSS buffer MMIO GPA | 无 | 无 |
| config[0x4a] 稳定 | 稳定 | 稳定（或 cmask 限制） |
| 第二次迁移验证 | 通过 | 通过 |

---

## 七、Debug 输出解读

### 7.1 Kernel Debug 输出解读

**正确的输出（修复后）**:
```
HDBSS_DEBUG_MMIO_FAULT: Device MMIO fault detected! device=1
HDBSS_DEBUG_DBM_DECISION: device=1 enable_hdbss=1 logging_active=1
HDBSS_DEBUG_DBM_CHECK: Checking condition: !device && enable && logging
(无 HDBSS_DEBUG_DBM_RESULT) ← device=1，DBM 不添加
HDBSS_DEBUG_FLUSH_ENTRY: gpa=0x8000... ← 只有 RAM 地址
```

**Bug 的输出（修复前）**:
```
HDBSS_DEBUG_MMIO_FAULT: device=1
HDBSS_DEBUG_DBM_DECISION: device=1 enable=1 logging=1
HDBSS_DEBUG_DBM_RESULT: DBM added ← Bug！应该不添加
HDBSS_DEBUG_FLUSH_ENTRY: gpa=0x1d00... ← MMIO 地址出现
```

### 7.2 QEMU Debug 输出解读

**正确的输出（cmask 限制）**:
```
VFIO_DEBUG_CPR_PRELOAD: cmask limitation applied
VFIO_DEBUG_CPR_PRELOAD_0x4a: cmask BEFORE=ff AFTER=00
(无 VFIO_DEBUG_VALIDATION_FAIL) ← cmask=00，不检查硬件位
```

**Bug 的输出（cmask=ff）**:
```
VFIO_DEBUG_LOAD_START: current config[0x4a]=8
VFIO_DEBUG_VALIDATION_FAIL: read=0 device=8 cmask=ff wmask=0
← cmask=ff 检查所有位，硬件位不一致导致失败
```

---

## 八、总结

### 8.1 Debug 重点

**Kernel**:
- MMIO fault 的 `device` 变量值
- DBM 决策条件是否包含 `!device`
- HDBSS buffer 是否包含 MMIO GPA

**QEMU**:
- cmask 是否被限制（应该）
- emulated_config_bits 设置是否正确
- config[0x4a] 在迁移前后的值变化

### 8.2 EVB vs FPGA 对比重点

**最关键对比**:
1. `device` 变量值是否一致
2. DBM 是否都被正确不添加
3. HDBSS 硬件行为差异
4. 设备状态稳定性差异

**对比目的**:
- 确认假设是否正确
- 找到 EVB 正常的根本原因
- 验证修复的有效性

---

*整理时间: 2026-05-15*