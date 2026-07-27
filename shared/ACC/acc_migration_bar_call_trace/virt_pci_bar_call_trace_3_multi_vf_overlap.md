# 多 VF 同 PCI Bus BAR2 重叠导致 S2 失效 —— 第3篇

## 1. 前提与问题

### 1.1 已修复：单 VF 正常工作

通过在第2篇的修复（`hisi_acc_vfio_pci_mmap` 中对 `end` 做 `ALIGN(end, PAGE_SIZE)`），单 VF 场景已正常：

```
ALIGN(32KB, 64KB) = 64KB → mmap 检查通过 → ram_device MR = 64KB
  → KVM memslot 注册 → S2 映射 → Guest ldp 直接 S2 访问 ✅
```

**但遗留问题**：`hisi_acc_get_resource_len` 本身仍返回 32KB（用于 `VFIO_DEVICE_GET_REGION_INFO` ioctl），导致 Guest 通过 BAR wmask 读到的 BAR2 = **32KB**。

### 1.2 新问题：双 VF 同一 PCI Bus 下仍然崩溃

同时直通两个 VF 到同一 PCI Bus（无 PCIe Root Port 隔离）时，即使 mmap 已修复，仍然出现相同的 `hisi_qm_wait_mb_ready` SEA call trace。使用 PCIe Root Port 隔离后问题消失。

---

## 2. 根因：两层尺寸不一致

核心矛盾在于 **Guest 和 QEMU 对 BAR2 大小的认知不同**：

| 层 | 值 | 来源 | 说明 |
|---|---|---|---|
| PCI 台账 `r->size` | **32KB** | `hisi_acc_get_resource_len` → ioctl → wmask | Guest 枚举读到的 BAR 大小 |
| ram_device MR size | **64KB** | mmap 成功, 内核对齐到 PAGE_SIZE | QEMU 实际注册的 MR 大小 |

### 2.1 Guest 按 32KB 分配 → 两个 VF 挤进同一 64KB 页

Guest PCI 枚举时读 BAR wmask → 推断 BAR2=32KB → 分配 GPA：

```
Dev1 BAR2: GPA 0x8000_200000 (32KB 对齐)
Dev2 BAR2: GPA 0x8000_208000 (32KB 间隔, 紧挨着 Dev1)
```

两个 BAR2 的 GPA 在同一 64KB 物理页内。

### 2.2 QEMU 注册的 MR 是 64KB → GPA 重叠

QEMU mmap 成功，`mmaps[0].mem` = **64KB**。通过 `pci_update_mappings` 挂入 GPA：

```
QEMU 实际注册:
  Dev1 BAR2 ram_device: GPA [0x8000_200000, 0x8000_20ffff]  64KB
  Dev2 BAR2 ram_device: GPA [0x8000_208000, 0x8000_217fff]  64KB
                         └── 重叠 32KB! ──┘
                         GPA 0x8000_208000 ~ 0x8000_20ffff 同时被两个 MR 覆盖!
```

**Guest 以为间隔 32KB，QEMU 注册了 64KB，重叠 32KB。**

---

## 3. sub_page_bar 降优先级 → 乒乓覆盖

### 3.1 触发条件

`vfio_sub_page_bar_update_mapping` 在 Guest 写 BAR 寄存器（改变 BAR GPA）时触发：

**`hw/vfio/pci.c:1341-1346`**:

```c
if (old_addr[bar] != pdev->io_regions[bar].addr &&      // GPA 变了
    vdev->bars[bar].region.size > 0 &&
    vdev->bars[bar].region.size < qemu_real_host_page_size()) {  // 32KB < 64KB
    vfio_sub_page_bar_update_mapping(pdev, bar);    // ← 触发!
}
```

### 3.2 救了 mmap，改了 Priority

sub_page_bar 将 MR 扩大到 PAGE_SIZE，同时把 priority 从 1 降到 0：

**`hw/vfio/pci.c:1217-1221`**:

```c
memory_region_del_subregion(r->address_space, base_mr);     // 删除旧 MR
memory_region_add_subregion_overlap(r->address_space,
                                    bar_addr, base_mr, 0);  // priority=0 加回!
```

**原始注册**（`hw/pci/pci.c:1547`）:
```c
memory_region_add_subregion_overlap(..., bar->mr, 1);   // priority=1
```

### 3.3 乒乓效应

```
Round 1: Dev1 sub_page_bar → Dev1 MR 64KB, priority=0
         FlatView: Dev1 64KB vs Dev2 32KB priority=1
         → Dev2 priority=1 覆盖 Dev1 重叠区 → Dev1 被截为 32KB

Round 2: Dev1 被截断 → VFIO listener 再次触发 sub_page_bar → priority=0
         FlatView: Dev1 64KB vs Dev2 32KB priority=1
         → 同 priority, Dev1 后注册 → Dev1 覆盖 Dev2 重叠区 → Dev2 被截为 32KB

Round 3: Dev2 被截断 → sub_page_bar → priority=0
         → Dev2 后注册 → Dev2 覆盖 Dev1 → Dev1 被截

...无限循环!
```

**根本原因**：sub_page_bar 将 priority 从 1 降到 0，两个 priority=0 的 64KB MR 在同一 GPA 区域中交替覆盖。被截断的那个触发新的 sub_page_bar → 它变成后注册者 → 覆盖前一个 → 循环往复。

---

## 4. 被截断的 BAR → kvm_align_section 返回 0 → 不建 memslot

FlatView 中被截断的 BAR 只有 32KB。KVM listener 处理时：

**`accel/kvm/kvm-all.c:266-280`** — `kvm_align_section()`:

```c
static hwaddr kvm_align_section(MemoryRegionSection *section, hwaddr *start)
{
    hwaddr size = section->size;    // 32KB

    *start = ROUND_UP(section->offset_within_address_space, PAGE_SIZE);
    hwaddr delta = *start - section->offset_within_address_space;
    if (delta > size)
        return 0;                   // ← 32KB section → 对齐后返回 0!
}
```

`kvm_set_phys_mem` 收到 0 → 直接 return → 不建 memslot → S2 无映射 → Guest ldp → S2 fault → ISV=0 → SEA。

---

## 5. 同一 PCI Bus vs Root Port 隔离

```
同一 PCI Bus (无 Root Port, 一个 address_space_mem):
  GPEX io_mmio
  ├── Dev1 BAR2 MR (64KB, priority=0) ─┐
  └── Dev2 BAR2 MR (64KB, priority=0) ─┤ 重叠 → 乒乓
                                        └─→ S2 失效

Root Port 隔离 (独立 address_space_mem):
  Root Port 1 Bridge Window         Root Port 2 Bridge Window
  ┌────────────────────┐           ┌────────────────────┐
  │ Dev1 BAR2 (64KB)   │           │ Dev2 BAR2 (64KB)   │
  └────────────────────┘           └────────────────────┘
   ↑ 独立 MR namespace               ↑ 独立 MR namespace
   两个 MR 不重叠 → FlatView 不截断 → memslot 正常 → S2 OK
```

---

## 6. 完整故障链

```
hisi_acc_get_resource_len → 32KB (ioctl 仍返回 32KB)
  → r->size = 32KB → Guest 看到 BAR2 = 32KB
  → Guest 分配: Dev1 @ 0x8000_200000, Dev2 @ 0x8000_208000

mmap 修复: end 已 ALIGN → mmap 成功 → ram_device MR = 64KB
  → QEMU 注册: Dev1 64KB, Dev2 64KB → GPA 上重叠 32KB

Guest 写 BAR → sub_page_bar 触发:
  → MR 扩展到 PAGE_SIZE → priority 1→0
  → FlatView 重叠 → 被截断的 BAR 32KB

kvm_align_section(32KB) → 返回 0 → 不建 memslot
  → S2 无映射 → Guest ldp → S2 fault → ISV=0 → SEA
```

---

## 7. 修复方案

**彻底修复**：让 `hisi_acc_get_resource_len` 的返回值与 mmap 允许的值一致：

```c
if (hisi_acc_vdev->drv_mode == HW_ACC_MIG_VF_CTRL) {
    ret_len = bar_len >> 1;
    ret_len = ALIGN(ret_len, PAGE_SIZE);   // 32KB → 64KB
    return ret_len;
}
```

修复后的三层一致：

| 层 | 修复前 | 修复后 |
|---|---|---|
| `r->size` (台账, Guest 看到) | 32KB | **64KB** |
| ram_device MR size | 64KB | 64KB |
| BAR 注册 priority | 0 (sub_page_bar 降级) | **1 (不需要 sub_page_bar, region.size=64KB)** |
| Guest 分配间隔 | 32KB (重叠!) | **≥64KB (不重叠)** |
| FlatView 截断? | 是 | **否** |

---

## 8. 涉及的关键源码

| 文件 | 行号 | 内容 |
|------|------|------|
| `drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c` | 1335 | `hisi_acc_get_resource_len` — `bar_len>>1`=32KB |
| `hw/pci/pci.c` | 1323 | `r->size = size` — 台账固化 |
| `hw/vfio/pci.c` | 1171 | `vfio_sub_page_bar_update_mapping` — 补救机制 |
| `hw/vfio/pci.c` | 1220 | `priority=0` — 降级 |
| `hw/vfio/pci.c` | 1341 | `old_addr != new_addr` — 触发条件 |
| `system/memory.c` | 953 | `address_space_update_topology_pass` — 两遍扫描 |
| `accel/kvm/kvm-all.c` | 266 | `kvm_align_section` — 32KB 返回 0 |
| `accel/kvm/kvm-all.c` | 1338 | `kvm_set_phys_mem` — IO MR 跳过 |
| `virt/kvm/kvm_main.c` | 2141 | `kvm_check_memslot_overlap` — 重叠拒绝 |
