# 多 VF 同 PCI Bus BAR2 重叠导致 S2 失效 —— 第3篇

## 1. 前提与问题

### 1.1 已修复：单 VF 通过 mmap ALIGN 检查

第2篇的修复在 `hisi_acc_vfio_pci_mmap` 中将 `end` 值 ALIGN 到 PAGE_SIZE：

```c
end = hisi_acc_get_resource_len(vdev, index);   // 返回 32KB
end = ALIGN(end, PAGE_SIZE);                     // 修复: 32KB → 64KB
if (req_start + req_len > end)                   // 0+64KB > 64KB → false → 通过
    return -EINVAL;
```

单 VF 修复后的结果：
- mmap 通过 → ram_device MR = 64KB → KVM memslot → S2 映射 → Guest ldp 正常 ✅

### 1.2 新问题：双 VF 同一 PCI Bus 下仍然 SEA

同时直通两个 VF 到同一 PCI Bus（无 PCIe Root Port 隔离）时，仍然出现 `hisi_qm_wait_mb_ready` SEA crash。使用 PCIe Root Port 隔离后消失。

### 1.3 核心疑问：mmap 已经是 64KB，为什么还会重叠？

mmap 只改了 ram_device MR 的大小（64KB），**没有改 Guest 看到的 BAR2 大小**。Guest 仍然认为 BAR2=32KB，按 32KB 间隔分配两个 VF 的 GPA → 两个 64KB MR 在 GPA 上重叠。

---

## 2. 两层尺寸不一致的源头

`hisi_acc_get_resource_len` 被两个独立的调用路径使用，**修复只改了其中一个**：

### 2.1 路径1（未修复）：ioctl → VFIO_DEVICE_GET_REGION_INFO → Guest BAR 大小

```
Guest PCI 枚举：读 BAR2 大小
  → VM exit → QEMU [EL0]
  → ioctl(VFIO_DEVICE_GET_REGION_INFO, BAR2)
  → Host 内核 [EL2]:
```

**`drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c:1445-1448`**:

```c
if (info.index == VFIO_PCI_BAR2_REGION_INDEX) {
    info.size = hisi_acc_get_resource_len(vdev, info.index);
    //                                       ↑ 返回 bar_len>>1 = 32KB!
```

→ QEMU `region->size = 32KB`
→ `bar->size = 32KB`
→ `pci_register_bar` → `r->size = 32KB`
→ `wmask = ~(32KB-1)` → Guest 读 BAR → **Guest 认为 BAR2=32KB**

### 2.2 路径2（已修复）：mmap 检查 → ram_device MR 大小

```
QEMU mmap(VFIO_fd, 64KB, BAR2)
  → Host 内核 [EL2]:
```

**`drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c:1382`**:

```c
end = hisi_acc_get_resource_len(vdev, index);   // 32KB
end = ALIGN(end, PAGE_SIZE);                     // 修复: 64KB
if (req_start + req_len > end)                   // 0+64KB > 64KB → pass
```

→ mmap 成功 → ram_device MR = **64KB** ✅

### 2.3 两个路径的值不同

| 路径 | 函数 | 返回/使用值 | 影响 |
|------|------|-----------|------|
| ioctl | `hisi_acc_get_resource_len` | **32KB** | Guest 看到 BAR2=32KB, 台账 r->size=32KB |
| mmap | `hisi_acc_vfio_pci_mmap` (ALIGN 后) | **64KB** | ram_device MR=64KB, KVM memslot 可建立 |

**修复只改了路径2。路径1仍然返回32KB → Guest 看到的 BAR2=32KB。**

---

## 3. 两个 VF 如何挤到同一个 64KB 页

### 3.1 Guest 按 32KB 分配 GPA

Guest PCI 枚举调用链路：

```
Guest [EL1]:
  pbus_assign_resources_sorted (setup-bus.c:493)
    → __assign_resources_sorted
      → pci_assign_resource (setup-res.c:327)
        → _pci_assign_resource → 在 MMIO 窗口中找对齐后的空闲区域
        → pci_update_resource (setup-res.c:126) → 写 BAR = GPA
```

每个 BAR2 看到的都是 32KB → 连续分配时间隔 32KB：

```
Dev1 BAR2 (32KB): GPA 0x8000_200000 ~ 0x8000_207fff
Dev2 BAR2 (32KB): GPA 0x8000_208000 ~ 0x8000_20ffff
```

**两者在同一 64KB 页内（GPA 0x8000_200000 ~ 0x8000_20ffff）。**

### 3.2 QEMU 注册 64KB MR → GPA 重叠

QEMU 侧，每个 BAR2 的 ram_device MR 是 64KB（通过 mmap 修复）。`pci_update_mappings` 将这些 MR 挂到 Guest 分配的 GPA：

```
QEMU FlatView:
  Dev1 BAR2 ram_device (64KB): GPA [0x8000_200000 ──────── 0x8000_20ffff]
  Dev2 BAR2 ram_device (64KB): GPA               [0x8000_208000 ──────── 0x8000_217fff]
                                                  └── 重叠 32KB! ──┘

重叠区间: GPA 0x8000_208000 ~ 0x8000_20ffff
  同时被 Dev1 BAR2 MR 和 Dev2 BAR2 MR 覆盖
```

**重叠的是 GPA**。不是 HPA，不是 HVA，是 Guest 物理地址空间中的 BAR2 区间。

---

## 4. sub_page_bar 降优先级 → FlatView 截断

### 4.1 触发条件

`vfio_sub_page_bar_update_mapping` 在 Guest 写 BAR 配置寄存器时触发。

**`hw/vfio/pci.c:1341-1346`**:

```c
for (bar = 0; bar < PCI_ROM_SLOT; bar++) {
    if (old_addr[bar] != pdev->io_regions[bar].addr &&        // GPA 变了
        vdev->bars[bar].region.size > 0 &&
        vdev->bars[bar].region.size < qemu_real_host_page_size()) {  // 32KB < 64KB
        vfio_sub_page_bar_update_mapping(pdev, bar);    // ← 触发
    }
}
```

调用链路：

```
Guest [EL1] 写 BAR2 = GPA
  → VM exit → QEMU [EL0] 拦截
  → pci_default_write_config (pci.c)
    → pci_update_mappings (pci.c:1511)
      → r->addr = new_addr
      → memory_region_add_subregion_overlap (priority=1)
    → vfio_sub_page_bar_update_mapping (pci.c:1345)
```

### 4.2 sub_page_bar 内部：扩 MR + 降 priority

**`hw/vfio/pci.c:1212-1223`**:

```c
static void vfio_sub_page_bar_update_mapping(PCIDevice *pdev, int bar)
{
    // 1) 把 MR 层级的 size 都扩到 PAGE_SIZE=64KB
    if (vdev->bars[bar].size < size)
        memory_region_set_size(base_mr, PAGE_SIZE);      // bar->mr → 64KB
    memory_region_set_size(region_mr, PAGE_SIZE);         // region.mem → 64KB
    memory_region_set_size(mmap_mr, PAGE_SIZE);           // mmaps[0].mem → 64KB

    // 2) 从 PCI bus 地址空间中删除旧 MR
    memory_region_del_subregion(r->address_space, base_mr);

    // 3) 以 priority=0 重新加回 !!
    memory_region_add_subregion_overlap(r->address_space,
                                        bar_addr, base_mr, 0);  // ← priority=0
}
```

**对比**：原始 BAR 注册 (`pci_update_mappings`, 第1篇 8.1) 用 priority=1。

### 4.3 FlatView 重叠 → 截断

两个 priority=0 的 64KB MR 在 GPA 上重叠，FlatView 按"同 priority 后注册者覆盖先注册者"处理：

```
Dev1 sub_page_bar 先执行:
  FlatView:
    Dev1 MR (64KB, priority=0) @ 0x8000_200000
    Dev2 MR (32KB, priority=1) @ 0x8000_208000
  → Dev2 priority=1 > Dev1 priority=0 → Dev2 覆盖重叠区
  → Dev1 FlatView section 被截为 32KB

Dev2 sub_page_bar 后执行:
  Dev2 MR → 64KB, priority=0
  FlatView:
    Dev1 MR (32KB, priority=0)
    Dev2 MR (64KB, priority=0) ← 后注册, 同 priority 覆盖 Dev1
  → Dev2 覆盖重叠区, Dev1 仍为 32KB
```

**结果**：被截断的那个 BAR 在 FlatView 中只有 32KB。

---

## 5. kvm_align_section → 32KB 不建 memslot

FlatView 中 32KB section 传给 KVM listener：

```
KVM listener → kvm_set_phys_mem
  → kvm_align_section(section, &start_addr)
```

**`accel/kvm/kvm-all.c:266-280`**:

```c
static hwaddr kvm_align_section(MemoryRegionSection *section, hwaddr *start)
{
    hwaddr size = section->size;    // = 32KB (0x8000)

    *start = ROUND_UP(section->offset_within_address_space, PAGE_SIZE);
    // GPA 0x8000_200000 → 已对齐

    hwaddr delta = *start - section->offset_within_address_space;  // 0
    if (delta > size)      // 0 > 0x8000 → false (不触发)
        return 0;

    return (size - delta) & PAGE_MASK;    // 0x8000 & 0xFFFFFFFFFFFF0000
    // = 0!  ← 32KB section 对齐后返回 0!
}
```

**`accel/kvm/kvm-all.c:1338`** — `kvm_set_phys_mem`:

```c
size = kvm_align_section(section, &start_addr);
if (!size) {
    return;    // ← 32KB → kvm_align 返回 0 → 直接跳过, 不建 memslot!
}
```

**结论**：32KB section 无法建 KVM memslot → S2 无映射 → Guest ldp → S2 fault → ISV=0 → SEA。

---

## 6. 完整调用链路（多 VF 场景）

```
═══════════════════════════════════════════════════════════════════
第1步：QEMU 启动 —— ioctl 获取 BAR2 大小
═══════════════════════════════════════════════════════════════════

QEMU [EL0]:
  ioctl(VFIO_DEVICE_GET_REGION_INFO, BAR2)

Host 内核 [EL2]:
  hisi_acc_vfio_pci_ioctl (hisi_acc_vfio_pci.c:1445)
    → info.size = hisi_acc_get_resource_len()  — 返回 bar_len>>1 = 32KB
  ← info->size = 32KB

QEMU [EL0]:
  vfio_region_setup (helpers.c:370):
    region->size = info->size = 32KB
  vfio_bar_prepare (pci.c:1785):
    bar->size = region.size = 32KB
  vfio_bar_register (pci.c:1797):
    memory_region_init_io(bar->mr, ..., bar->size = 32KB)
    vfio_region_mmap → mmap check:
      end = ALIGN(hisi_acc_get_resource_len(), PAGE_SIZE) = 64KB
      → 通过 → ram_device MR = 64KB ← 修复的效果!
    pci_register_bar (pci.c:1298):
      r->size = memory_region_size(bar->mr) = 32KB
      wmask = ~(32KB-1) → Guest 看到 BAR2=32KB

═══════════════════════════════════════════════════════════════════
第2步：Guest PCI 枚举 —— 按 32KB 分配 GPA
═══════════════════════════════════════════════════════════════════

Guest [EL1]:
  读 BAR2 wmask → 32KB
  pbus_assign_resources_sorted → 依次分配
    Dev1 BAR2 (32KB) → GPA 0x8000_200000
    Dev2 BAR2 (32KB) → GPA 0x8000_208000
    两者在同一 64KB 页内!
  pci_update_resource → 写 BAR = GPA

═══════════════════════════════════════════════════════════════════
第3步：QEMU 处理 BAR 写入 → MR 挂入 GPA
═══════════════════════════════════════════════════════════════════

QEMU [EL0]:
  pci_update_mappings (pci.c:1511)
    → r->addr = GPA (Dev1: 0x8000_200000, Dev2: 0x8000_208000)
    → memory_region_add_subregion_overlap(priority=1)
    → vfio_sub_page_bar_update_mapping (region.size=32KB < PAGE_SIZE)
      → 扩展 MR 到 64KB, 重新注册 priority=0

═══════════════════════════════════════════════════════════════════
第4步：FlatView 重叠 → 截断
═══════════════════════════════════════════════════════════════════

QEMU [EL0]:
  memory_region_transaction_commit
    → generate_memory_topology → FlatView
    → Dev1 64KB(priority=0) vs Dev2 32KB(priority=1)
      → Dev2 高 priority 覆盖重叠区 → Dev1 截为 32KB

═══════════════════════════════════════════════════════════════════
第5步：KVM listener → 32KB 不建 memslot
═══════════════════════════════════════════════════════════════════

QEMU [EL0]:
  kvm_set_phys_mem (kvm-all.c:1338)
    → kvm_align_section(32KB) → 返回 0 → return
    → 不建 memslot → S2 无映射

═══════════════════════════════════════════════════════════════════
第6步：Guest 访问 → S2 fault → SEA
═══════════════════════════════════════════════════════════════════

Guest [EL1]:
  hisi_qm_init → qm_mb_read → ldp [io_base + 0x300]
  → S2 无映射 → Translation Fault → ISV=0 → SEA → panic
```

---

## 7. 修复方案

让 `hisi_acc_get_resource_len` 的返回值与 mmap 允许的值一致：

```c
static size_t hisi_acc_get_resource_len(...)
{
    if (hisi_acc_vdev->drv_mode == HW_ACC_MIG_VF_CTRL) {
        ret_len = bar_len >> 1;
        ret_len = ALIGN(ret_len, PAGE_SIZE);   // 修复: 32KB → 64KB
        return ret_len;
    }
    return bar_len;
}
```

修复后：

| | 修复前（仅 mmap） | 修复后（ioctl 也 ALIGN） |
|---|---|---|
| ioctl 返回 | 32KB | **64KB** |
| `r->size` (台账) | 32KB | **64KB** |
| Guest BAR enum | 32KB | **64KB** |
| 两个 VF BAR2 间隔 | 32KB (挤同一页) | **≥64KB (不同页)** |
| sub_page_bar 触发? | 是 (32KB<PAGE_SIZE) | **否 (64KB=PAGE_SIZE)** |
| FlatView 截断? | 是 | **否** |
| KVM memslot | 建不上 | **正常** |

---

## 8. 涉及的关键源码

| 文件 | 行号 | 内容 |
|------|------|------|
| `hisi_acc_vfio_pci.c` | 1335 | `hisi_acc_get_resource_len` — `bar_len>>1`=32KB |
| `hisi_acc_vfio_pci.c` | 1448 | ioctl 使用此返回值 → `info.size=32KB` |
| `hisi_acc_vfio_pci.c` | 1382 | mmap 使用此返回值 (已 ALIGN 修复) |
| `hw/pci/pci.c` | 1323 | `r->size = size` — 台账 32KB 固化 |
| `hw/pci/pci.c` | 1330 | `wmask = ~(size-1)` — Guest 通过它读 BAR 大小 |
| `hw/vfio/pci.c` | 1341-1346 | sub_page_bar 触发条件 |
| `hw/vfio/pci.c` | 1212-1223 | sub_page_bar 内部: 扩 MR + 降 priority=0 |
| `hw/pci/pci.c` | 1547 | 原始注册 priority=1 |
| `accel/kvm/kvm-all.c` | 266-280 | `kvm_align_section` — 32KB 返回 0 |
| `accel/kvm/kvm-all.c` | 1338 | `kvm_set_phys_mem` — IO MR 跳过 |
