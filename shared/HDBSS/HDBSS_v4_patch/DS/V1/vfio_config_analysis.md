# VFIO PCI Config Space 迁移问题分析

## 一、报错信息解读

```
qemu-system-aarch64: get_pci_config_device: Bad config data: i=0x4a read: 0 device: 8 cmask: ff wmask: 0 w1cmask:0
qemu-system-aarch64: Failed to load PCIDevice:config
qemu-system-aarch64: Failed to load VFIOPCIDevice:pdev
```

### 1.1 参数含义

| 参数 | 值 | 含义 |
|------|-----|------|
| i | 0x4a | PCI config space 偏移 74 字节 (capability 区域) |
| read | 0 | **源端保存的值** = 0 |
| device | 8 | **目标端当前值** = 8 (bit 3 = 1) |
| cmask | ff | 允许检查所有位 |
| wmask | 0 | **所有位不可写** (硬件只读位) |
| w1cmask | 0 | 无 write-1-to-clear 位 |

### 1.2 检查逻辑 (hw/pci/pci.c:815-816)

```c
if ((config[i] ^ s->config[i]) &
    s->cmask[i] & ~s->wmask[i] & ~s->w1cmask[i]) {
    error_report(...);
    return -EINVAL;
}
```

**条件计算**：
```
(0 ^ 8) & ff & ~0 & ~0 = 8 & ff = 8 ≠ 0
```

结果：报错！因为硬件只读位在迁移前后不一致。

---

## 二、PCI Config Space 偏移 0x4a 分析

### 2.1 PCI Config Space 布局

```
0x00-0x3F: Standard PCI Header (64 bytes)
  - 0x00-0x01: Vendor ID
  - 0x02-0x03: Device ID
  - 0x34:      Capabilities Pointer

0x40-0xFF: PCI Capability Structures (192 bytes)
  - Power Management (PM) cap: 8 bytes
  - MSI cap: 10+ bytes
  - PCIe cap: 60+ bytes
  - MSI-X cap: 12 bytes

0x100+: PCIe Extended Config Space (只支持 PCIe)
```

### 2.2 0x4a 偏移可能对应的寄存器

**假设 capability 从 0x40 开始**：

```
0x40: Cap ID (如 0x01 = PM, 0x10 = PCIe)
0x41: Next Cap Pointer
0x42-0x47: Capability specific registers
0x48-0x4F: 下一个 capability 或继续当前 capability
0x4a: 可能是某个 capability 的内部寄存器
```

**常见的 capability 结构**：
- **Power Management (PM)**:
  - Offset +0: Cap ID (0x01)
  - Offset +1: Next Cap Pointer
  - Offset +2-3: PM Caps (硬件只读)
  - Offset +4-5: PM Control/Status (部分可写)
  - Offset +6-7: PM Bridge Extensions

- **PCI Express (PCIe)**:
  - Offset +0: Cap ID (0x10)
  - Offset +1: Next Cap Pointer
  - Offset +2-3: PCIe Caps (硬件只读)
  - Offset +4-5: Device Caps (硬件只读)
  - Offset +6-7: Device Control (可写)
  - Offset +8-9: Device Status (部分 write-1-to-clear)
  - ...

### 2.3 hisi_zip 设备可能的结构

需要查看具体设备的 capability 列表：
```bash
# 在 Host 上查看设备的 config space
lspci -xxx -s 0000:1d:00.1 | head -20

# 或者使用 hexdump
hexdump -C /sys/bus/pci/devices/0000:1d:00.1/config | head -20
```

---

## 三、VFIO PCI Config Space 保存/加载流程

### 3.1 保存流程 (源端)

```
QEMU migration
  ↓
vfio_save_state() (hw/vfio/migration.c:684)
  ↓
vfio_save_device_config_state() (migration.c:255)
  ↓
vfio_pci_save_config() (hw/vfio/pci.c:2877)
  ↓
vmstate_save_state(&vmstate_vfio_pci_config) (pci.c:2881)
  ↓
VMSTATE_PCI_DEVICE(parent_obj)
  ↓
vmstate_info_pci_config.put() = put_pci_config_device() (pci.c:840)
  ↓
qemu_put_buffer(f, *v, size) ← 保存 s->config[] 到文件
```

**关键点**：`s->config[]` 的值来自：
1. QEMU 模拟的位 (emulated_config_bits)
2. VFIO 硬件读取的位 (通过 vfio_pci_read_config)

### 3.2 加载流程 (目标端)

```
QEMU migration load
  ↓
vfio_load_state() (migration.c:739)
  ↓
vfio_load_device_config_state() (migration.c:280)
  ↓
vfio_pci_load_config() (pci.c:2885)
  ↓
vmstate_load_state(&vmstate_vfio_pci_config) (pci.c:2897)
  ↓
VMSTATE_PCI_DEVICE(parent_obj)
  ↓
vmstate_info_pci_config.get() = get_pci_config_device() (pci.c:803)
  ↓
qemu_get_buffer(f, config, size) ← 从文件读取源端 config
  ↓
比较 config[i] vs s->config[i] ← **报错发生在这里！**
```

### 3.3 VFIO Config Space 读取 (vfio_pci_read_config)

```c
// hw/vfio/pci.c:1385
uint32_t vfio_pci_read_config(PCIDevice *pdev, uint32_t addr, int len)
{
    VFIOPCIDevice *vdev = VFIO_PCI_DEVICE(pdev);
    uint32_t emu_bits, emu_val, phys_val, val;

    // 1. 检查哪些位是 QEMU 模拟的
    emu_bits = vdev->emulated_config_bits[addr];

    // 2. 模拟位从 QEMU 默认配置读取
    if (emu_bits) {
        emu_val = pci_default_read_config(pdev, addr, len);
    }

    // 3. 硬件位从 VFIO 设备读取
    if (~emu_bits & ... ) {
        vfio_pci_config_space_read(vdev, addr, len, &phys_val); ← 关键！
    }

    // 4. 合并模拟位和硬件位
    val = (emu_val & emu_bits) | (phys_val & ~emu_bits);
    return val;
}
```

**vfio_pci_config_space_read() 实现**：
```c
// hw/vfio/pci.c:1114
static int vfio_pci_config_space_read(VFIOPCIDevice *vdev, off_t offset,
                                      uint32_t size, void *data)
{
    return vdev->vbasedev.io_ops->region_read(&vdev->vbasedev,
                                              VFIO_PCI_CONFIG_REGION_INDEX,
                                              offset, size, data);
}
```

---

## 四、问题根源分析

### 4.1 核心问题

**源端保存的 config[0x4a] = 0，目标端当前 config[0x4a] = 8**

这个值是硬件只读位 (wmask=0)，不应该变化！

### 4.2 可能的原因

#### 原因 1: 源端保存时读取了错误的硬件值

```
源端迁移时：
  vfio_pci_read_config(pdev, 0x4a, 1)
    ↓
  vfio_pci_config_space_read(vdev, 0x4a, 1, &phys_val)
    ↓
  region_read(..., VFIO_PCI_CONFIG_REGION_INDEX, ...)
    ↓
  内核 vfio_pci_config_rw()
    ↓
  vfio_config_do_rw()
    ↓
  perm->readfn() 或 pci_user_read_config_byte()
    ↓
  phys_val = ??? ← 返回了 0？
```

**关键问题**：为什么内核读取返回 0？

#### 原因 2: HDBSS 影响 VFIO MMIO BAR 读取

**假设**：
- HDBSS 给 VFIO MMIO BAR 区域添加了 DBM 位
- 设备状态同步时，某些 MMIO 操作可能受到影响
- 导致设备硬件状态不一致

**但 PCI Config Space 不是 MMIO！**

- VFIO_PCI_CONFIG_REGION_INDEX 是特殊的 region
- 读取通过 `vfio_pci_config_rw()` 实现
- 内核使用 `pci_user_read_config_byte()` 或类似函数
- 这些不经过 Stage-2 页表，不受 HDBSS 影响

**但是**，某些设备可能有特殊的 capability 读取逻辑：
- 有些 capability 寄存器可能需要通过 MMIO 访问
- 或者某些状态寄存器的值依赖于 MMIO BAR 的内容

#### 原因 3: 设备状态同步问题

**第二次迁移时的场景**：

```
第一次迁移 (A → B):
  - 源端 A: hisi_zip 设备 1d:00.1
  - 目标端 B: hisi_zip 设备 1d:00.2 (相同型号)
  - 迁移成功

目标端 B 运行 workload:
  - hisi_zip 设备执行压缩任务
  - 设备状态改变 (某些寄存器值变化)

第二次迁移 (B → A):
  - 源端 B: hisi_zip 设备 1d:00.2 (已运行 workload)
  - 目标端 A: hisi_zip 设备 1d:00.1 (之前的源端)
  - **报错！**
```

**关键**：第二次迁移时，源端和目标端的设备硬件状态不一致！

### 4.4 cmask=ff 的异常

**正常情况下，VFIO 设备的 cmask 应该被限制**：

```c
// hw/vfio/cpr.c:99-111
static int vfio_cpr_pci_pre_load(void *opaque)
{
    VFIOPCIDevice *vdev = opaque;
    PCIDevice *pdev = PCI_DEVICE(vdev);
    int size = MIN(pci_config_size(pdev), vdev->config_size);
    int i;

    for (i = 0; i < size; i++) {
        pdev->cmask[i] &= vdev->emulated_config_bits[i]; ← 关键！
    }

    return 0;
}
```

**注释说明**：
> "The kernel may change non-emulated config bits. Exclude them from the changed-bits check."

**但是报错时 cmask=ff**，说明：
1. `vfio_cpr_pci_pre_load()` 没被调用
2. 或者 `emulated_config_bits[0x4a] = ff` (所有位都是模拟的？)

---

## 五、HDBSS 可能的影响路径

### 5.1 直接影响 (不太可能)

PCI Config Space 不经过 Stage-2 页表，直接不受 DBM 影响。

### 5.2 间接影响 (可能)

**假设链**：
```
1. HDBSS 给 VFIO MMIO BAR 添加 DBM
   ↓
2. 脏页跟踪记录了 MMIO 区域的 "写入"
   ↓
3. 迁移时，这些 "脏页" 被传输
   ↓
4. 但 MMIO BAR 不是 RAM，不应该被迁移
   ↓
5. 可能导致 VFIO migration 状态不一致
```

**或者**：
```
1. HDBSS 启用时，某些 MMIO fault 路径改变
   ↓
2. VFIO 设备的 MMIO 读取/写入行为可能受影响
   ↓
3. 设备内部状态可能因为 MMIO 访问问题而不一致
   ↓
4. Config space 中的某些状态寄存器反映设备内部状态
   ↓
5. 迁移时，这些寄存器值不一致
```

### 5.3 关键代码路径

**VFIO MMIO BAR 的 Stage-2 映射**：
```c
// Guest 访问 VFIO BAR → Stage-2 fault
user_mem_abort()
  ↓
if (kvm_is_device_pfn(pfn))
  device = true
  ↓
// Bug: DBM 可能被添加！
if (kvm->enable_hdbss && logging_active)  // ← 缺少 !device 检查
  prot |= KVM_PGTABLE_PROT_DBM
  ↓
// Device 内存被错误添加 DBM
```

**这可能导致**：
- MMIO BAR 的 PTE 有 DBM 位
- 硬件可能尝试跟踪 MMIO 区域的脏状态
- 但 MMIO 不是真正的内存，硬件行为可能不正确
- 可能影响设备状态

---

## 六、验证和调试建议

### 6.1 确认 cmask 处理

```bash
# 在 QEMU 中添加 debug 打印
# hw/vfio/cpr.c:107
for (i = 0; i < size; i++) {
    if (i == 0x4a) {
        printf("DEBUG: cmask[0x4a]=%x emulated=%x result=%x\n",
               pdev->cmask[i], vdev->emulated_config_bits[i],
               pdev->cmask[i] & vdev->emulated_config_bits[i]);
    }
    pdev->cmask[i] &= vdev->emulated_config_bits[i];
}
```

### 6.2 确认源端保存的值

```bash
# 在 QEMU 中添加 debug 打印
# hw/vfio/pci.c:1385
if (addr == 0x4a) {
    printf("DEBUG: vfio_pci_read_config addr=0x4a emu_bits=%x phys_val=%x\n",
           emu_bits, phys_val);
}
```

### 6.3 确认内核读取的值

```bash
# 在内核中添加 debug 打印
# drivers/vfio/pci/vfio_pci_config.c:1945
if (*ppos == 0x4a) {
    printk("DEBUG: vfio_config_do_rw read pos=0x4a val=%x\n", val);
}
```

### 6.4 确认 HDBSS 影响

```bash
# 使用之前创建的 debug patch
# 检查 MMIO fault 是否被错误添加 DBM
grep "HDBSS_DEBUG.*device=1" /tmp/hdbss_debug/*.log
```

---

## 七、结论和修复

### 7.1 已确认的修复

**mmu.c:1682** 添加 `!device` 检查：
```c
#ifdef CONFIG_ARM64_HDBSS
    if (!device && kvm->enable_hdbss && logging_active)
        prot |= KVM_PGTABLE_PROT_DBM;
#endif
```

**理由**：DBM 不应该用于 Device/MMIO 内存。

### 7.2 可能的额外问题

1. **cmask 处理问题**：`vfio_cpr_pci_pre_load()` 可能没有被调用
2. **emulated_config_bits 问题**：`emulated_config_bits[0x4a]` 可能设置不正确
3. **设备状态同步问题**：第二次迁移时设备硬件状态不一致

### 7.3 不是用户态内存破坏

**结论**：这个错误不是用户态内存空间被破坏，而是：
- **VFIO 设备硬件状态不一致**
- **迁移时 config space 验证失败**

**原因链**：
1. HDBSS 可能影响了 VFIO MMIO 区域
2. 导致设备状态同步问题
3. Config space 中的硬件只读位在迁移前后不一致
4. QEMU 验证失败，拒绝加载

---

## 八、下一步调试

1. 应用 HDBSS debug patch，确认 MMIO 是否被错误添加 DBM
2. 在 QEMU 中添加 debug，确认 cmask 和 emulated_config_bits 的值
3. 对比 EVB 和 FPGA 的差异（为什么 EVB 正常）
4. 检查第二次迁移时设备状态是否一致

---

*整理时间: 2026-05-15*