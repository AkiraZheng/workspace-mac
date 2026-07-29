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

→ mmap 成功 → ram_device MR 创建 (初始 size = `mmaps[0].size` = 32KB)
→ 后续 `vfio_sub_page_bar_update_mapping` 将 MR size 扩到 **64KB** ✅

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

### 3.2 QEMU 注册 64KB MR 到 Guest 分配的 GPA → 重叠

Guest 分配好 GPA 后写入 BAR 寄存器，触发 QEMU `pci_update_mappings`。这个函数**把 QEMU 的 MR（64KB）挂到 Guest 分配的 GPA（32KB 间隔）上**——GPA 是 Guest 决定的，MR 大小是 QEMU 决定的，两者不匹配导致重叠。

**`hw/pci/pci.c:1511-1553`** — `pci_update_mappings`:

```c
static void pci_update_mappings(PCIDevice *d)
{
    PCIIORegion *r;
    int i;
    pcibus_t new_addr;

    for (i = 0; i < PCI_NUM_REGIONS; i++) {
        r = &d->io_regions[i];                       // PCI 台账
        if (!r->size) continue;

        new_addr = pci_bar_address(d, i, r->type, r->size);
        // ★ 从 PCI 配置空间读出 Guest 写入的 BAR 值
        //    = GPA (Guest 在 3.1 分配的: 0x8000_200000 / 0x8000_208000)
        //    校验对齐: new_addr &= ~(r->size - 1) = ~(32KB-1)

        if (new_addr == r->addr) continue;            // 没变, 跳过

        // 删除旧映射
        if (r->addr != PCI_BAR_UNMAPPED)
            memory_region_del_subregion(r->address_space, r->memory);

        r->addr = new_addr;                           // 记录 Guest 分配的 GPA

        if (r->addr != PCI_BAR_UNMAPPED) {
            // ★ 把 bar->mr (含 64KB ram_device) 挂到 Guest 分配的 GPA
            //   r->address_space = GPEX io_mmio
            //   r->addr     = GPA offset (0x8000_200000 - base_mmio = 0x00200000)
            //   r->memory   = bar->mr, 其内部的 mmaps[0].mem = 64KB!
            //   priority = 1
            memory_region_add_subregion_overlap(
                r->address_space, r->addr, r->memory, 1);
        }
    }
}
```

**重叠是怎么发生的——逐步追踪**:

```
Dev1 Guest 写 BAR2 = GPA 0x8000_200000:
  → pci_update_mappings
  → r->addr = GPA 0x8000_200000
  → bar->mr (含 64KB ram_device) 挂到 GPA 0x8000_200000
  → 覆盖 GPA 区间: [0x8000_200000, 0x8000_20ffff]  ← 64KB

Dev2 Guest 写 BAR2 = GPA 0x8000_208000:
  → pci_update_mappings
  → r->addr = GPA 0x8000_208000
  → bar->mr (含 64KB ram_device) 挂到 GPA 0x8000_208000
  → 覆盖 GPA 区间: [0x8000_208000, 0x8000_217fff]  ← 64KB

GPA 空间重叠:
  Dev1 MR: [0x8000_200000 ──────── 0x8000_20ffff]
  Dev2 MR:             [0x8000_208000 ──────── 0x8000_217fff]
                        └── 重叠 32KB! ──┘
                        GPA 0x8000_208000 ~ 0x8000_20ffff
                        同时被两个 MR 覆盖!
```

**根因**: Guest 按 32KB 分配 GPA（因为台账 r->size=32KB），但 QEMU 注册的 MR 是 64KB（因为 mmap 修复成功）。`pci_update_mappings` 不关心 MR 的实际大小——它只是把 MR 挂到 Guest 指定的 GPA 上。GPA 由 Guest 决定，MR 大小由 QEMU 的 mmap 决定，两者独立→不匹配→重叠。



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

### 4.2.1 MR 数据结构层级：ram_device MR 存在哪里？

三层 MR 是**嵌套的父子关系**，每层对应一个数据结构字段：

```
VFIOBAR (hw/vfio/pci.h:50)
├─ MemoryRegion *mr;              ← 第0层: base BAR container (IO 类型)
├─ size_t size;                   ← VFIOBAR.size = 32KB (不改!)
└─ VFIORegion region;             (include/hw/vfio/vfio-common.h:54)
   ├─ MemoryRegion *mem;          ← 第1层: VFIO slow path MR (读写回调)
   ├─ size_t size;                ← VFIORegion.size = 32KB (不改!)
   └─ VFIOMmap *mmaps;            (include/hw/vfio/vfio-common.h:47)
      └─ mmaps[0]
         ├─ MemoryRegion mem;     ← 第2层: ram_device MR (嵌入式结构体, 不是指针!)
         ├─ void *mmap;           ← mmap'd host 指针 (存入 ram_block->host)
         └─ size_t size;          ← VFIOMmap.size = 32KB (不改!)
```

**ram_device MR 是 `bar->region.mmaps[0].mem`**——它是 `VFIOMmap` 结构体里**嵌入的** `MemoryRegion`（不是指针，是结构体的一部分），被持久化存储在堆内存中。

创建位置在 `hw/vfio/helpers.c:469-472`：

```c
memory_region_init_ram_device_ptr(&region->mmaps[i].mem,   // ← ram_device MR
                                  memory_region_owner(region->mem),
                                  name, region->mmaps[i].size,  // ← 初始 32KB
                                  region->mmaps[i].mmap);       // ← mmap 指针存入 ram_block->host
```

`memory_region_init_ram_device_ptr` (`system/memory.c:1703-1720`) 设置：

```c
mr->ram = true;
mr->terminates = true;           // ← 终止节点: FlatView 渲染到这里生成 FlatRange
mr->ram_device = true;           // ← KVM 通过此标志判断是否建 memslot
mr->ram_block = qemu_ram_alloc_from_ptr(size, ptr, mr, ...);
//                              ↑ size=32KB    ↑ ptr=mmap'd 指针
//  ram_block->host = ptr (mmap'd 指针, 后续 KVM 用它取 HVA)
//  ram_block->size = 32KB (不随 mr->size 变化而改变)
```

`MemoryRegion` 结构体关键字段 (`include/exec/memory.h:892-939`)：

```c
struct MemoryRegion {
    ...
    Int128 size;                  // ← 第917行: MR 的大小 (sub_page_bar 会改这个!)
    hwaddr addr;                  // ← 在父地址空间中的偏移
    bool ram;                     // ← true (是 RAM 类型)
    bool terminates;              // ← true (终止节点, FlatView 到此为止)
    bool ram_device;              // ← true (KVM 据此建 memslot)
    RAMBlock *ram_block;          // ← 存储 mmap'd 指针和原始大小
    int32_t priority;             // ← 在父的子链表中的优先级
    QTAILQ_HEAD(, MemoryRegion) subregions;  // ← 子 MR 链表
    ...
};
```

### 4.2.2 memory_region_set_size：直接改 MemoryRegion.size 字段

`memory_region_set_size` (`system/memory.c:2772-2786`) 的实现非常简单——**直接写 `mr->size` 字段**：

```c
void memory_region_set_size(MemoryRegion *mr, uint64_t size)
{
    Int128 s = int128_make64(size);
    if (size == UINT64_MAX) {
        s = int128_2_64();
    }
    if (int128_eq(s, mr->size)) {
        return;                   // 大小没变, 跳过
    }
    memory_region_transaction_begin();
    mr->size = s;                 // ★ 直接写 MemoryRegion.size 字段! 持久化!
    memory_region_update_pending = true;
    memory_region_transaction_commit();
}
```

**是的，扩展到 64KB 的修改会持久化在 `MemoryRegion` 结构体中。** `mr->size` 从 `int128_make64(0x8000)` 变成 `int128_make64(0x10000)`，后续所有读取 `mr->size` 的代码（包括 FlatView 渲染）都会看到 64KB。

### 4.2.3 vfio_sub_page_bar_update_mapping 改了什么、没改什么

`vfio_sub_page_bar_update_mapping` (`hw/vfio/pci.c:1198-1223`) 获取三个 MR 指针并调用 `memory_region_set_size`：

```c
base_mr   = vdev->bars[bar].mr;           // bar->mr (第0层)
region_mr = region->mem;                   // bar->region.mem (第1层)
mmap_mr   = &region->mmaps[0].mem;         // bar->region.mmaps[0].mem (第2层, ram_device)

// 改 MemoryRegion.size (Int128):
if (vdev->bars[bar].size < size)
    memory_region_set_size(base_mr, size);     // bar->mr->size: 32KB → 64KB
memory_region_set_size(region_mr, size);       // region->mem->size: 32KB → 64KB
memory_region_set_size(mmap_mr, size);         // mmaps[0].mem.size: 32KB → 64KB

// 从地址空间删除旧 MR, 以 priority=0 重新加回:
memory_region_del_subregion(r->address_space, base_mr);
memory_region_add_subregion_overlap(r->address_space, bar_addr, base_mr, 0);
```

**改的是 `MemoryRegion.size` 字段（`Int128`），不是指针。** 三个 MR 指针本身不变，指向的 `MemoryRegion` 结构体中的 `.size` 字段被修改。

**完整对比：哪些字段改了、哪些没改**

| 数据结构 | 字段 | 类型 | sub_page_bar 改? | 初始值 | 改后值 | 作用 |
|---|---|---|---|---|---|---|
| `bar->mr` | `.size` | `Int128` | **改** | 32KB | **64KB** | FlatView 渲染用此 size |
| `region->mem` | `.size` | `Int128` | **改** | 32KB | **64KB** | FlatView 渲染用此 size |
| `mmaps[0].mem` | `.size` | `Int128` | **改** | 32KB | **64KB** | FlatView 渲染用此 size (终止节点) |
| `bar->mr` | `.priority` | `int32_t` | **改** | 1 | **0** | QTAILQ 排序用 |
| `bar->mr` | `.addr` | `hwaddr` | 不改 | GPA | GPA | 在父地址空间中的偏移 |
| `mmaps[0].mem` | `.ram_device` | `bool` | 不改 | true | true | KVM 判断是否建 memslot |
| `mmaps[0].mem` | `.ram_block->host` | `void*` | 不改 | mmap指针 | mmap指针 | KVM 取 HVA 用 |
| `mmaps[0].mem` | `.ram_block->size` | `ram_addr_t` | 不改 | 32KB | 32KB | RAMBlock 原始大小 (不随 MR.size 变) |
| `bar->size` | (VFIOBAR.size) | `size_t` | **不改** | 32KB | 32KB | VFIO 层记录的 BAR 大小 |
| `region->size` | (VFIORegion.size) | `size_t` | **不改** | 32KB | 32KB | sub_page_bar 触发条件检查用 |
| `mmaps[0].size` | (VFIOMmap.size) | `size_t` | **不改** | 32KB | 32KB | mmap 信息记录 |
| `r->size` | (PCIIORegion.size) | `pcibus_t` | **不改** | 32KB | 32KB | PCI 台账, Guest 通过 wmask 读到 |

**关键区别**：
- `MemoryRegion.size`（`Int128`）→ **被改**，FlatView 渲染时读这个 → 渲染出 64KB 的 FlatRange
- `VFIOBAR.size` / `VFIORegion.size` / `VFIOMmap.size` / `PCIIORegion.size`（`size_t` / `pcibus_t`）→ **不被改**，仍是 32KB

这就是为什么 sub_page_bar 触发条件 (`pci.c:1343` `vdev->bars[bar].region.size < qemu_real_host_page_size()`) 每次都成立——它检查的是 `VFIORegion.size`（不改），不是 `MemoryRegion.size`（已改）。

### 4.2.4 各 size 变量的关系：它们不是同一个字段

这些 size 分布在 **5 个不同的结构体** 中，类型也不同，只是初始值都来源于 ioctl 返回的 32KB。`memory_region_set_size` 只改 `MemoryRegion.size`，不会反向同步到其他结构体。

**初始赋值链路**（QEMU 启动时，ioctl 返回 32KB 后一次性赋值）：

```
ioctl(VFIO_DEVICE_GET_REGION_INFO) → info.size = 32KB
  │
  │  vfio_region_setup (helpers.c:370)
  ├─→ VFIORegion.size = info.size = 32KB           (size_t,      vfio-common.h:58)
  │     │
  │     │  vfio_bar_prepare (pci.c:1785)
  │     ├─→ VFIOBAR.size = bar->region.size = 32KB  (size_t,      pci.h:53)
  │     │
  │     │  vfio_region_setup (helpers.c:388)
  │     ├─→ VFIOMmap.size = region->size = 32KB     (size_t,      vfio-common.h:51)
  │     │
  │     │  vfio_bar_register (pci.c:1808)
  │     ├─→ memory_region_init_io(bar->mr, ..., bar->size=32KB)
  │     │     → bar->mr->size = 32KB                (Int128,      memory.h:917)  ← 被改!
  │     │
  │     │  vfio_region_setup (helpers.c, region->mem 创建)
  │     ├─→ region->mem->size = 32KB                (Int128,      memory.h:917)  ← 被改!
  │     │
  │     │  vfio_region_mmap → memory_region_init_ram_device_ptr (helpers.c:469)
  │     │     ├─→ mmaps[0].mem.size = mmaps[0].size = 32KB
  │     │     │                                (Int128,      memory.h:917)  ← 被改!
  │     │     │
  │     │     └─→ ram_block = qemu_ram_alloc_from_ptr(size=32KB, ptr)
  │     │           → ram_block->size = 32KB        (ram_addr_t,  RAMBlock)     ← 不改
  │     │
  │     │  pci_register_bar (pci.c:1298)
  │     └─→ PCIIORegion.size = memory_region_size(bar->mr) = 32KB
  │                                    (pcibus_t,   PCIIORegion)               ← 不改
  │
  └─ 以上赋值都是 QEMU 启动时一次性完成, 之后各字段独立存在, 无同步机制
```

**sub_page_bar 触发后**（Guest 写 BAR 寄存器时）：

```
memory_region_set_size(bar->mr,       64KB)  → 只改 MemoryRegion.size  ✓
memory_region_set_size(region->mem,   64KB)  → 只改 MemoryRegion.size  ✓
memory_region_set_size(mmaps[0].mem,  64KB)  → 只改 MemoryRegion.size  ✓

不触及:
  VFIOBAR.size         (size_t)    仍 32KB  ✗
  VFIORegion.size      (size_t)    仍 32KB  ✗
  VFIOMmap.size        (size_t)    仍 32KB  ✗
  PCIIORegion.size     (pcibus_t)  仍 32KB  ✗
  ram_block->size      (ram_addr_t)仍 32KB  ✗
```

**它们不是同一个变量。** 每个结构体有自己的 size 字段，类型也不同（`Int128` vs `size_t` vs `pcibus_t` vs `ram_addr_t`）。`memory_region_set_size` 只写 `MemoryRegion.size`，其他结构体的 size 字段不会被自动同步。

| 结构体 | size 字段 | 类型 | 定义位置 | sub_page_bar 改? | 初始来源 |
|---|---|---|---|---|---|
| `MemoryRegion` (bar->mr) | `.size` | `Int128` | `memory.h:917` | **改 → 64KB** | `memory_region_init_io(..., bar->size)` |
| `MemoryRegion` (region->mem) | `.size` | `Int128` | `memory.h:917` | **改 → 64KB** | region setup 时设 |
| `MemoryRegion` (mmaps[0].mem) | `.size` | `Int128` | `memory.h:917` | **改 → 64KB** | `memory_region_init_ram_device_ptr(..., mmaps[0].size)` |
| `RAMBlock` | `.size` | `ram_addr_t` | `RAMBlock` | 不改 (32KB) | `qemu_ram_alloc_from_ptr(size=32KB)` |
| `VFIOBAR` | `.size` | `size_t` | `pci.h:53` | 不改 (32KB) | `bar->size = bar->region.size` |
| `VFIORegion` | `.size` | `size_t` | `vfio-common.h:58` | 不改 (32KB) | `region->size = info->size` |
| `VFIOMmap` | `.size` | `size_t` | `vfio-common.h:51` | 不改 (32KB) | `mmaps[0].size = region->size` |
| `PCIIORegion` | `.size` | `pcibus_t` | `PCIIORegion` | 不改 (32KB) | `r->size = memory_region_size(bar->mr)` |

**为什么这很重要**：

1. **FlatView 渲染**读的是 `MemoryRegion.size`（已改 64KB）→ 渲染出 64KB 的区间
2. **sub_page_bar 触发条件** (`pci.c:1343`) 读的是 `VFIORegion.size`（不改 32KB）→ `32KB < 64KB` 永远成立
3. **PCI 台账** (`PCIIORegion.size`) 不改 32KB → Guest 通过 BAR wmask 永远看到 32KB → Guest 按 32KB 间隔分配 GPA
4. **ram_block->size** 不改 32KB → KVM 取 HVA 时 `memory_region_get_ram_ptr` 返回的是原始 mmap 指针（实际 mmap 了 64KB，但 ram_block 记录 32KB）

### 4.3 FlatView 渲染机制：为什么高 priority 会截断低 priority

FlatView 由 `render_memory_region` 生成，遍历 MR 子链表，**高 priority 的 MR 先渲染，占据 GPA 空间**，低 priority 的 MR 只能在空隙中填充。

**`system/memory.c:645-649`** — 子链表遍历顺序:

```c
/* Render subregions in priority order. */
QTAILQ_FOREACH(subregion, &mr->subregions, subregions_link) {
    render_memory_region(view, subregion, base, clip, ...);
}
```

QTAILQ 的排序规则（`system/memory.c:2699-2704`）：

```c
QTAILQ_FOREACH(other, &mr->subregions, subregions_link) {
    if (subregion->priority >= other->priority) {
        QTAILQ_INSERT_BEFORE(other, subregion, subregions_link);
        goto done;
    }
}
```

**排序结果**: priority 降序。同 priority 时，**后插入的排前面**——后注册的 MR 优先渲染。

**`system/memory.c:666-693`** — 渲染一个 MR 到 FlatView（"填入空隙"）:

```c
/* Render the region itself into any gaps left by the current view. */
for (i = 0; i < view->nr && remain > 0; ++i) {
    if (int128_ge(base, addrrange_end(view->ranges[i].addr)))
        continue;                           // 跳过已经渲染过的区间

    if (int128_lt(base, view->ranges[i].addr.start)) {
        // ★ 有空洞! 把 MR 的一部分填入这个空洞
        now = int128_min(remain, view->ranges[i].addr.start - base);
        fr.addr = addrrange_make(base, now);
        flatview_insert(view, i, &fr);      // 插入这里
        base += now; remain -= now;         // 消耗掉这部分
    }
    // 重叠区域被消耗, 不插入 (被前面的 MR 占了)
    now = int128_min(base + remain, addrrange_end(view->ranges[i].addr)) - base;
    base += now; remain -= now;
}
// 尾部剩余 → 插入
if (remain > 0) {
    flatview_insert(view, i, &fr);
}
```

**直译**: 遍历已经渲染好的 FlatView 区间。如果在当前区间前面有空洞 → 填入。如果当前区间已经覆盖了要渲染的范围 → 那块不填（"消耗掉"）。所以**先渲染的 MR 占据 GPA，后渲染的 MR 只能填补空隙。**

### 4.4 完整流程模拟：从两个 VF 注册到最终稳定

以 Dev1 BAR2 @ GPA 0x8000_200000、Dev2 BAR2 @ GPA 0x8000_208000 为例。

#### Step 1 — 初始状态

Guest PCI 枚举前，BAR 尚未映射到 GPA。GPEX io_mmio 的子 MR 链表为空。

#### Step 2 — Guest 枚举 Dev1，写 BAR2 = 0x8000_200000

**2a) `pci_default_write_config` → `pci_update_mappings`**（`hw/pci/pci.c:1511`）

```
Dev1 r->addr 从 PCI_BAR_UNMAPPED → GPA 0x8000_200000
memory_region_add_subregion_overlap(GPEX io_mmio, offset=0x200000,
                                     bar->mr, priority=1)
```

QTAILQ 此时:
```
[Dev1: priority=1, offset=0x200000, 32KB, ram_device 64KB]
```

**2b) `vfio_sub_page_bar_update_mapping` 触发**（`hw/vfio/pci.c:1341-1346`）

条件: `old_addr(UNMAPPED) ≠ new_addr(GPA) && region.size(32KB) < PAGE_SIZE(64KB)` → 触发!

```
memory_region_del_subregion(bus, Dev1 base_mr)
memory_region_add_subregion_overlap(bus, offset=0x200000,
                                     base_mr, priority=0, size=64KB)
```

QTAILQ 此时:
```
[Dev1: priority=0, offset=0x200000, 64KB]
```

**2c) FlatView 渲染 + KVM listener**

```
FlatView:
  [0] Dev1 ram_device [0x8000_200000, 0x8000_20ffff] 64KB, mr->ram=true

KVM: kvm_set_phys_mem ADD → section 64KB → ioctl → memslot 创建 ✅
   Dev1 S2 PTE 建立: GPA 0x8000_200000 → HPA
```

#### Step 3 — Guest 枚举 Dev2，写 BAR2 = 0x8000_208000

**3a) `pci_update_mappings`**

```
Dev2 r->addr 从 PCI_BAR_UNMAPPED → GPA 0x8000_208000
memory_region_add_subregion_overlap(GPEX io_mmio, offset=0x208000,
                                     bar->mr, priority=1)
```

QTAILQ 此时（Dev2 priority=1 排在 Dev1 priority=0 前面）:
```
[Dev2: priority=1, offset=0x208000, 32KB, ram_device 64KB]
[Dev1: priority=0, offset=0x200000, 64KB]
```

**3b) FlatView 重建 — 3a 的 `memory_region_add_subregion_overlap` 触发**

```
FlatView 渲染 (Dev2 priority=1 → 先渲染, Dev1 priority=0 → 后渲染):

  1) Dev2 (priority=1, 32KB) 先渲染:
     FlatView: [0x208000, 0x20ffff] Dev2 (IO, 32KB)

  2) Dev1 (priority=0, 64KB) 后渲染 → 填空隙:
     base=0x200000, 空洞 0x200000~0x208000 → 插入 32KB
     0x208000~0x20ffff 已被 Dev2 占 → 消耗掉 → 32KB 没了!

  FlatView 最终:
    [0] Dev1 ram_device [0x200000, 0x208000) 32KB     ← 被截!
    [1] Dev2 (IO)       [0x208000, 0x20ffff] 32KB

KVM listener:
  旧: Dev1 [0x200000, 0x20ffff] 64KB (Step 2c 建的)
  新: Dev1 [0x200000, 0x208000) 32KB (被截!)
  → DEL Dev1 64KB section → kvm_set_phys_mem DEL → Dev1 memslot 删除!
  → ADD Dev1 32KB section → kvm_align_section → 返回0 → SKIP → Dev1 无 memslot!
  (Dev2 是 IO → mr->ram=false → kvm_set_phys_mem 跳过)
```

**3c) `vfio_sub_page_bar_update_mapping` 触发**

条件: `old_addr(UNMAPPED) ≠ new_addr(GPA) && region.size(32KB) < PAGE_SIZE(64KB)` → 触发!

```
memory_region_del_subregion(bus, Dev2 base_mr)
memory_region_add_subregion_overlap(bus, offset=0x208000,
                                     base_mr, priority=0, size=64KB)
```

QTAILQ 此时（两个 priority=0, Dev2 后插入排前面）:
```
[Dev2: priority=0, offset=0x208000, 64KB]  ← 后插入, 排第一!
[Dev1: priority=0, offset=0x200000, 64KB]
```

**3d) FlatView 重建 — 3c 的 del+add 触发**

```
FlatView 渲染 (Dev2 priority=0 → 排前面, Dev1 priority=0 → 后排):

  1) Dev2 (priority=0, 64KB) 先渲染 → FlatView 为空 → 填满:
     [0x208000, 0x218000) Dev2 ram_device 64KB

  2) Dev1 (priority=0, 64KB) 后渲染 → 填空隙:
     base=0x200000, 空洞 0x200000~0x208000 → 插入 32KB ← int128_lt (system/memory.c:671)
     0x208000~0x20ffff 被 Dev2 覆盖 → 消耗掉               ← int128_sub (system/memory.c:682)
     remain=0 → 不走到 flatview_insert (line 689)

  FlatView 最终:
    [0] Dev1 ram_device [0x200000, 0x208000) 32KB
    [1] Dev2 ram_device [0x208000, 0x218000) 64KB

KVM listener:
  旧: Dev1 [0x200000, 0x208000) 32KB (IO, mr->ram=false — 因为 3b 的截断把它从 ram_device 切成了 IO? 不, 仍然是 ram_device)
       Dev2 [0x208000, 0x20ffff] 32KB (IO, mr->ram=false)
  新: Dev1 [0x200000, 0x208000) 32KB (ram_device)
       Dev2 [0x208000, 0x218000) 64KB (ram_device)

  → DEL Dev2 32KB IO section       (无 memslot, 不操作)
  → ADD Dev2 64KB ram_device section → memslot 创建 ✅
  → Dev1 32KB section 不变         (kvm_align → 0 → SKIP)
```

#### 最终稳定状态

```
QTAILQ (不再变化, 因为两个 VF 的 BAR 不会再被 Guest 写入):
  [Dev2: priority=0, offset=0x208000, 64KB]
  [Dev1: priority=0, offset=0x200000, 64KB]

FlatView (每次重建结果相同, 不再变化):
  [0] Dev1 [0x8000_200000, 0x8000_208000) 32KB
  [1] Dev2 [0x8000_208000, 0x8000_218000) 64KB

KVM memslots:
  Dev2: memslot [0x8000_208000, 64KB] → S2 ✅
  Dev1: 无 memslot → S2 ❌

Guest 访问 Dev1 BAR2 → S2 fault → ISV=0 → SEA
```

**为什么不会死循环**: sub_page_bar 只在 `old_addr ≠ r->addr` 时触发（Guest 写 BAR 寄存器）。FlatView 截断改变的是 FlatView section 的大小，不会改变 `r->addr` 的值。两个 VF 的 BAR 各被 Guest 写一次后就稳定了——FlatView 不管重建多少次，QTAILQ 顺序不变，输出结果不变。

### 4.5 FlatView 截断后传给 KVM 的数据结构

**FlatView 渲染时按 64KB 注册**——因为 `vfio_sub_page_bar_update_mapping` 已经把三层 `MemoryRegion.size` 都改成了 64KB。`render_memory_region` (`system/memory.c:645`) 递归遍历子 MR，读到的是改后的 `mr->size = 64KB`。

但渲染时遇到重叠，先渲染的 MR 占据 GPA，后渲染的 MR 只能填空隙 → 被截断。

**截断发生在 FlatView 层面，不是 MR 层面。** MR 本身仍然是 64KB，但 FlatView 输出的 `FlatRange` 被截断为 32KB：

`FlatRange` 结构体 (`system/memory.c:222-231`)：

```c
struct FlatRange {
    MemoryRegion *mr;              // ← 指向 mmaps[0].mem (ram_device MR, 64KB)
    hwaddr offset_in_region;       // ← 在 MR 内的偏移 (0)
    AddrRange addr;                // ← .start = GPA, .size = 被截断的大小!
    ...
};
```

以 Dev1 为例，FlatView 最终输出的 FlatRange：

```
FlatRange {
    .mr   = &Dev1->bar->region.mmaps[0].mem,   // ram_device MR (mr->size=64KB)
    .addr = { .start = 0x8000_200000, .size = 0x8000 }  // ← 32KB! 被 Dev2 截断!
}
```

**MR 是 64KB，但 FlatRange 的 `.addr.size` 是 32KB。** FlatRange 记录的是"这个 MR 在 GPA 空间中实际可用的区间"。

**FlatRange → MemoryRegionSection → kvm_set_phys_mem**

`section_from_flat_range` (`system/memory.c:236-249`) 把 FlatRange 转成 `MemoryRegionSection`：

```c
static inline MemoryRegionSection
section_from_flat_range(FlatRange *fr, FlatView *fv)
{
    return (MemoryRegionSection) {
        .mr = fr->mr,                                    // ram_device MR (64KB)
        .size = fr->addr.size,                           // ← 32KB! (截断后的大小)
        .offset_within_address_space = GPA,              // 0x8000_200000
        .offset_within_region = 0,
        ...
    };
}
```

`MemoryRegionSection` (`include/exec/memory.h:99-121`) 就是**传给 KVM 的数据结构**：

```c
struct MemoryRegionSection {
    Int128 size;                                        // ← 32KB (来自被截断的 FlatRange)
    MemoryRegion *mr;                                   // ← ram_device MR
    hwaddr offset_within_address_space;                 // ← GPA (Guest 物理地址)
    hwaddr offset_within_region;                        // ← 在 MR 内的偏移
    bool readonly;
    ...
};
```

传递路径：

```
FlatView 重建
  → listener 通知 (system/memory.c)
    → kvm_region_add (accel/kvm/kvm-all.c:1584)
      → 拷贝 section 到 KVMMemoryUpdate.section, 入队
    → kvm_region_commit (kvm-all.c:1692)
      → kvm_set_phys_mem(kml, &section, true)           ← section.size = 32KB
```

`kvm_set_phys_mem` (`accel/kvm/kvm-all.c:1338-1471`) 从 section 中提取信息：

```c
static void kvm_set_phys_mem(KVMMemoryListener *kml,
                             MemoryRegionSection *section, bool add)
{
    MemoryRegion *mr = section->mr;                     // ram_device MR

    if (!memory_region_is_ram(mr))                      // mr->ram=true → 不跳过
        return;

    size = kvm_align_section(section, &start_addr);     // ← 32KB section 传进去
    if (!size) {                                        // ← 返回 0 → 跳过!
        return;                                         //   不建 memslot!
    }

    // 正常路径 (64KB section 才走到这里):
    mr_offset = section->offset_within_region + start_addr
                - section->offset_within_address_space;
    ram = memory_region_get_ram_ptr(mr) + mr_offset;   // ← 从 ram_block->host 取 HVA

    // 组装 KVMSlot:
    mem->start_addr = start_addr;                       // GPA
    mem->memory_size = slot_size;                       // 64KB (页对齐后)
    mem->ram = ram;                                     // HVA (mmap'd 指针)
    kvm_set_user_memory_region(kml, mem, true);         // ioctl → KVM 内核建 S2 页表
}
```

正常情况下（64KB section），KVM 组装的 `KVMSlot` (`include/sysemu/kvm_int.h:18-33`)：

```c
typedef struct KVMSlot {
    hwaddr start_addr;            // GPA (Guest 物理地址) → S2 页表的输入
    ram_addr_t memory_size;       // 大小 (页对齐) → S2 页表覆盖范围
    void *ram;                    // HVA (mmap'd host 指针) → S2 页表的输出 (转 HPA)
    int slot;
    int flags;
    ...
};
```

`KVM_SET_USER_MEMORY_REGION` ioctl 把 `(GPA, HVA, size)` 传给 KVM 内核，KVM 据此建立 S2 页表映射：`GPA → HPA`。

**但在 32KB section 的情况下，`kvm_align_section` 返回 0，走不到组装 KVMSlot 这一步。**

### 4.6 根因定位：不是 FlatView 建不了，是 KVM 拒绝 32KB

```
问题: Dev1 的 ram_device MR 在 FlatView 中变成什么样了?

回答: MR 本身仍是 64KB (mr->size=64KB, 被 memory_region_set_size 改了)。
      但 FlatView 输出的 FlatRange 被截断为 32KB (因为 Dev2 的 MR 占了重叠区)。
      FlatRange.mr 仍指向 64KB 的 ram_device MR,
      但 FlatRange.addr.size = 32KB (实际可用区间)。

问题: 传给 KVM 的是什么?

回答: MemoryRegionSection {
          .mr   = ram_device MR (64KB),
          .size = 32KB (来自被截断的 FlatRange),
          .offset_within_address_space = GPA
      }
      通过 kvm_region_add → kvm_region_commit → kvm_set_phys_mem 传递。

问题: 根因是 FlatView 建不了还是 KVM 拒绝?

回答: KVM 拒绝。FlatView 成功建立了 Dev1 的 section (32KB), 成功传递给 KVM listener。
      但 kvm_align_section 把 32KB AND 64KB page mask → 得到 0 → 认为大小为 0 → 跳过。
      不建 memslot → S2 无映射 → Guest 访问 → S2 fault → SEA。
```

数据流全景：

```
MemoryRegion (mr->size = 64KB)         ← sub_page_bar 改了
    ↓ render_memory_region
FlatRange (.mr = MR, .addr.size = 32KB)  ← FlatView 渲染时被截断
    ↓ section_from_flat_range
MemoryRegionSection (.mr = MR, .size = 32KB)  ← 传给 KVM listener
    ↓ kvm_region_add → kvm_region_commit → kvm_set_phys_mem
kvm_align_section(32KB)
    ↓ 0x8000 & qemu_real_host_page_mask() = 0x8000 & 0xFFFF0000 = 0
返回 0 → kvm_set_phys_mem return → 不建 memslot
    ↓
S2 页表: Dev1 BAR2 无映射 → Guest ldp → S2 fault → ISV=0 → SEA
```

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
    memory_region_init_io(bar->mr, ..., bar->size = 32KB)     ← MR.size = 32KB
    vfio_region_mmap → mmap check:
      end = ALIGN(hisi_acc_get_resource_len(), PAGE_SIZE) = 64KB
      → 通过 → mmap 成功
      → memory_region_init_ram_device_ptr(mmaps[0].mem, size=32KB, ptr)
        ← ram_device MR 创建, mr->size = 32KB (不是 64KB!)
        ← mr->ram_block->host = mmap 指针, ram_block->size = 32KB
    pci_register_bar (pci.c:1298):
      r->size = memory_region_size(bar->mr) = 32KB            ← PCI 台账 = 32KB
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
      → memory_region_set_size(bar->mr, 64KB)         ← mr->size: 32KB→64KB
      → memory_region_set_size(region->mem, 64KB)      ← mr->size: 32KB→64KB
      → memory_region_set_size(mmaps[0].mem, 64KB)     ← mr->size: 32KB→64KB
      → 重新注册 priority=0
      注意: VFIOBAR.size/VFIORegion.size/VFIOMmap.size/PCIIORegion.size 不改, 仍 32KB

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
| `hw/vfio/pci.h` | 50-58 | `VFIOBAR` 结构体: `region`, `mr`, `size` |
| `include/hw/vfio/vfio-common.h` | 47-52 | `VFIOMmap`: `mem` (ram_device MR), `mmap`, `size` |
| `include/hw/vfio/vfio-common.h` | 54-63 | `VFIORegion`: `mem`, `size`, `mmaps` |
| `include/exec/memory.h` | 892-939 | `MemoryRegion`: `size`(Int128), `ram_device`, `ram_block`, `priority` |
| `include/exec/memory.h` | 99-121 | `MemoryRegionSection`: `size`, `mr`, `offset_within_address_space` |
| `include/sysemu/kvm_int.h` | 18-33 | `KVMSlot`: `start_addr`(GPA), `ram`(HVA), `memory_size` |
| `hw/vfio/helpers.c` | 388 | `mmaps[0].size = region->size` = 32KB |
| `hw/vfio/helpers.c` | 469-472 | `memory_region_init_ram_device_ptr` 创建 ram_device MR (初始 32KB) |
| `hw/pci/pci.c` | 1323 | `r->size = size` — 台账 32KB 固化 |
| `hw/pci/pci.c` | 1330 | `wmask = ~(size-1)` — Guest 通过它读 BAR 大小 |
| `hw/vfio/pci.c` | 1198-1202 | sub_page_bar 获取三层 MR 指针: `base_mr`, `region_mr`, `mmap_mr` |
| `hw/vfio/pci.c` | 1212-1216 | `memory_region_set_size` 改三层 MR.size → 64KB |
| `hw/vfio/pci.c` | 1217-1221 | del+add priority=0 重新注册 |
| `hw/vfio/pci.c` | 1341-1346 | sub_page_bar 触发条件 (检查 VFIORegion.size, 不改) |
| `hw/pci/pci.c` | 1547 | 原始注册 priority=1 |
| `system/memory.c` | 2772-2786 | `memory_region_set_size` — 直接写 `mr->size` |
| `system/memory.c` | 1703-1720 | `memory_region_init_ram_device_ptr` — 设 `ram_device=true` |
| `system/memory.c` | 222-231 | `FlatRange`: `.mr`, `.addr.size` (被截断后的大小) |
| `system/memory.c` | 236-249 | `section_from_flat_range` — FlatRange → MemoryRegionSection |
| `system/memory.c` | 645-693 | `render_memory_region` — 按 mr->size 渲染 FlatView |
| `accel/kvm/kvm-all.c` | 1584-1606 | `kvm_region_add` — section 入队 |
| `accel/kvm/kvm-all.c` | 1692 | `kvm_region_commit` — 调用 `kvm_set_phys_mem` |
| `accel/kvm/kvm-all.c` | 1338-1471 | `kvm_set_phys_mem` — section → KVMSlot → ioctl |
| `accel/kvm/kvm-all.c` | 266-295 | `kvm_align_section` — 32KB & page_mask = 0 → 拒绝 |
| `accel/kvm/kvm-all.c` | 1394 | `memory_region_get_ram_ptr(mr)` — 从 ram_block->host 取 HVA |
