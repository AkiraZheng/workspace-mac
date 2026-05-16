# HDBSS VFIO Migration Bug 总结报告

## 一、问题现象

**场景**: 带 VFIO 加速器设备 (hisi_zip)，两次热迁移后第二次报错

**报错信息**:
```
qemu-system-aarch64: get_pci_config_device: Bad config data: i=0x4a read: 0 device: 8 cmask: ff wmask: 0 w1cmask:0
qemu-system-aarch64: Failed to load PCIDevice:config
qemu-system-aarch64: Failed to load VFIOPCIDevice:pdev
qemu-system-aarch64: 0000:1d:00.1: Failed to load device config space
```

**差异**: EVB 正常，FPGA 失败；不带 HDBSS 正常，带 HDBSS 失败

---

## 二、根本原因分析

### 2.1 核心问题

**Kernel Bug**: HDBSS 给 VFIO MMIO 区域错误添加 DBM 位

```c
// arch/arm64/kvm/mmu.c:1682 (Bug 代码)
#ifdef CONFIG_ARM64_HDBSS
    if (kvm->enable_hdbss && logging_active)  // ← 缺少 !device 检查
        prot |= KVM_PGTABLE_PROT_DBM;
#endif
```

**影响链**:
```
1. VFIO MMIO BAR 的 Stage-2 PTE 被添加 DBM 位
   ↓
2. HDBSS 硬件尝试跟踪 MMIO 区域的脏状态
   ↓
3. MMIO 不是真正的内存，硬件行为异常
   ↓
4. 设备 MMIO 访问可能受影响
   ↓
5. 设备内部状态不一致
```

### 2.2 QEMU 框架缺陷

**VFIO 普通迁移缺少 cmask 限制机制**:

```c
// hw/vfio/cpr.c:99-111 (CPR 迁移专用)
static int vfio_cpr_pci_pre_load(void *opaque)
{
    for (i = 0; i < size; i++) {
        pdev->cmask[i] &= vdev->emulated_config_bits[i];  ← 限制 cmask
    }
}

// 但这个函数只在 CPR 迁移模式调用
// 普通热迁移不调用，cmask 保持 ff (检查所有位)
```

**问题**:
- cmask=ff: 检查所有位变化，包括硬件只读位
- wmask=0: 硬件只读位不应该变化
- 但硬件只读位在迁移前后必然不一致（源端和目标端是不同物理设备）
- 结果：迁移验证失败

### 2.3 PCI Config 偏移 0x4a 分析

**偏移含义**:
- 0x4a (74 bytes) 在 PCI capability 区域
- 可能是设备状态寄存器、能力标志位等
- wmask=0: 硬件只读位，反映设备内部状态

**报错参数解读**:
| 参数 | 值 | 含义 |
|------|-----|------|
| i | 0x4a | PCI config 偏移 74 |
| read | 0 | 源端保存值（QEMU 缓存的旧值）|
| device | 8 | 目标端当前值（设备硬件实际状态）|
| cmask | ff | 检查所有位（不应该！）|
| wmask | 0 | 硬件只读位 |
| w1cmask | 0 | 无 write-1-to-clear 位 |

---

## 三、对比校验机制

### 3.1 迁移验证逻辑

```c
// hw/pci/pci.c:814-816
for (i = 0; i < size; ++i) {
    if ((config[i] ^ s->config[i]) &  // config[i]=源端文件值，s->config[i]=目标端当前值
        s->cmask[i] & ~s->wmask[i] & ~s->w1cmask[i]) {
        error_report("Bad config data: ...");
        return -EINVAL;
    }
}
```

**对比双方**:
- `config[i]`: 从迁移文件读取 = 源端 QEMU 缓存的值
- `s->config[i]`: 目标端设备当前值（VFIO 初始化时从硬件读取）

### 3.2 保存流程（不重新读取硬件）

```c
// 源端保存时
vfio_pci_save_config()
  ↓
vmstate_save_state()
  ↓
put_pci_config_device()
  ↓
qemu_put_buffer(f, s->config, size);  // ← 直接保存 QEMU 缓存，不重新读取硬件
```

### 3.3 加载流程（读取硬件）

```c
// 目标端加载时
vfio_pci_load_config()
  ↓
vmstate_load_state()
  ↓
get_pci_config_device()
  ↓
qemu_get_buffer(f, config, size);  // ← 从文件读取源端值
  ↓
比较 config[i] vs s->config[i]     // ← s->config[i] 是 VFIO 初始化时从硬件读取的
```

---

## 四、为什么 EVB 正常，FPGA 失败

### 4.1 可能的差异

| 平台 | 可能差异 |
|------|---------|
| **EVB** | 真实硬件，可能有隐式防护机制，忽略 MMIO 的 DBM |
| **FPGA** | 模拟/部分实现，严格按照规范处理每个 DBM 位 |

### 4.2 HDBSS 硬件行为差异

**EVB**: HDBSS 硬件可能对 MMIO 区域的 DBM 位有特殊处理（忽略或无害）

**FPGA**: HDBSS 硬件严格按照规范，对 MMIO 区域的 DBM 尝试脏页跟踪，导致异常

### 4.3 设备状态差异

**第二次迁移场景**:
```
第一次迁移 A → B: 成功
目标端 B 运行 workload: hisi_zip 执行压缩任务，设备状态变化
第二次迁移 B → A:
  - 源端 B: 设备状态已变化，但 QEMU 缓存未更新
  - 目标端 A: 设备初始化，读取硬件状态
  - config[0x4a] 不一致: 源端保存=0，目标端读取=8
```

---

## 五、Bug 修复方案

### 5.1 Kernel Bug Fix (已完成)

**文件**: `arch/arm64/kvm/mmu.c:1682`

```c
// 修改前
#ifdef CONFIG_ARM64_HDBSS
    if (kvm->enable_hdbss && logging_active)
        prot |= KVM_PGTABLE_PROT_DBM;
#endif

// 修改后
#ifdef CONFIG_ARM64_HDBSS
    if (!device && kvm->enable_hdbss && logging_active)
        prot |= KVM_PGTABLE_PROT_DBM;
#endif
```

**原理**: DBM 只应该用于 RAM 内存，不用于 Device/MMIO 内存

### 5.2 QEMU Bug Fix (建议)

**文件**: `hw/vfio/pci.c`

为 VFIO 普通迁移添加 pre_load 回调，限制 cmask:

```c
static int vfio_pci_pre_load(void *opaque)
{
    VFIOPCIDevice *vdev = opaque;
    PCIDevice *pdev = PCI_DEVICE(vdev);
    int size = MIN(pci_config_size(pdev), vdev->config_size);
    int i;

    for (i = 0; i < size; i++) {
        pdev->cmask[i] &= vdev->emulated_config_bits[i];
    }
    return 0;
}

static const VMStateDescription vmstate_vfio_pci_config = {
    .name = "VFIOPCIDevice",
    .version_id = 1,
    .minimum_version_id = 1,
    .pre_load = vfio_pci_pre_load,  // ← 添加这个
    .fields = (const VMStateField[]) {
        VMSTATE_PCI_DEVICE(parent_obj, VFIOPCIDevice),
        VMSTATE_MSIX_TEST(parent_obj, VFIOPCIDevice, vfio_msix_present),
        VMSTATE_END_OF_LIST()
    },
    ...
};
```

**原理**: 限制 cmask 只检查 QEMU 模拟的位，不检查硬件只读位

---

## 六、Debug Patch 说明

### 6.1 Kernel Debug Patch

**目的**: 跟踪 HDBSS 对 MMIO 区域的处理

**关键调试点**:
- `mmu.c`: Device 检测 + DBM 决策
- `handle_exit.c`: HDBSS buffer 内容（脏页 GPA）
- `arm.c`: HDBSS 启用/禁用时机

### 6.2 QEMU Debug Patch

**目的**: 跟踪 VFIO config space 保存/加载流程

**关键调试点**:
- `hw/pci/pci.c`: cmask 处理 + 迁移验证
- `hw/vfio/pci.c`: config space 读取 + emulated_config_bits
- `hw/vfio/cpr.c`: pre_load 回调是否调用

---

## 七、验证流程

### 7.1 Kernel 修复验证

1. 应用 Kernel bug fix patch
2. 编译并部署内核
3. 执行两次热迁移测试
4. 检查是否仍报错

### 7.2 QEMU 修复验证

1. 应用 QEMU bug fix patch
2. 编译 QEMU
3. 执行两次热迁移测试
4. 检查迁移是否成功

### 7.3 Debug 信息收集

1. 应用 kernel 和 QEMU debug patch
2. 执行完整迁移流程（两次）
3. 收集 kernel log 和 QEMU log
4. 分析关键调试点输出

---

## 八、结论

**双重 Bug**:

1. **Kernel Bug**: HDBSS 给 MMIO 区域添加 DBM，导致设备访问异常
2. **QEMU Bug**: VFIO 普通迁移缺少 cmask 限制，导致硬件只读位验证失败

**修复优先级**:
- **Kernel Bug Fix**: 必须修复（已完成）
- **QEMU Bug Fix**: 建议修复（解决框架缺陷）

**根本原理**:
- DBM 只用于 RAM，不用于 MMIO
- cmask 只检查模拟位，不检查硬件只读位

---

*整理时间: 2026-05-15*