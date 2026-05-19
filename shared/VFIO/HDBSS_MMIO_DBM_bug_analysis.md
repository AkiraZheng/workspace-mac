# HDBSS 错误给 VFIO MMIO BAR 添加 DBM 导致热迁移失败

## 问题现象

带 ACC 设备（hisi_zip）的 VM 进行两次热迁移，**第一次成功，第二次失败**：

```
qemu-system-aarch64: get_pci_config_device: Bad config data: i=0x4a read: 0 device: 8 cmask: ff wmask: 0 w1cmask:0
qemu-system-aarch64: Failed to load PCIDevice:config
qemu-system-aarch64: Failed to load VFIOPCIDevice:pdev
qemu-system-aarch64: 0000:1d:00.1: Failed to load device config space
qemu-system-aarch64: error while loading state for instance 0x0 of device '0000:00:01.0/vfio'
qemu-system-aarch64: load of migration failed: Invalid argument
```

- EVB（真实硅片）正常，FPGA 失败
- 不带 HDBSS 正常，带 HDBSS 失败

## 根本原因

**HDBSS 代码缺少 `!device` 检查，错误地将 DBM（Dirty Bit Management）位设置到了 MMIO BAR 的 stage-2 PTE 上。**

ARM 架构中 DBM 只定义给 Normal memory。对 Device memory（nGnRE 属性）设置 DBM 是**架构未定义行为**。FPGA 上的 HDBSS 硬件严格按规范执行，导致 MMIO 访问异常，设备内部状态不一致，最终在第二次迁移时 config space 校验失败。

---

## VFIO BAR MemoryRegion 层次结构详解

### 什么是 MMIO BAR

PCI 设备的 BAR（Base Address Register）将设备寄存器映射到 CPU 物理地址空间。Guest 通过 `load/store` 指令直接访问这些地址来读写设备寄存器（提交任务、查询状态等）。在 ARM64 平台上称为 MMIO（Memory-Mapped I/O）。

VFIO 直通场景下，QEMU 需要将这些 BAR 映射到 guest 的 IPA 空间。为兼顾性能和安全性，QEMU 将每个 BAR 拆成多层 MemoryRegion：

```
pci_register_bar()
  │
  └── bar->mr                          ← memory_region_init_io()
        │                                  BAR 基 MR，mr->ram = false
        │
        └── region->mem                 ← memory_region_init_io()
              │                             VFIO region MR，mr->ram = false
              │                             .ops = vfio_region_ops
              │
              ├── [unmapped gap]        ← 无 backing，trap 到 QEMU 模拟
              │
              └── mmaps[i].mem          ← memory_region_init_ram_device_ptr()
                                            模拟成 RAM，mr->ram = true
                                            实际 backing = VFIO device fd mmap
                                            → host 侧指向设备 MMIO 物理页
```

### mmap 子区域就是 MMIO 本身

mmap 子区域的 `mr->ram = true` 容易让人误解它是"普通 RAM"，但实际上：

1. **QEMU 侧**：`region->mmaps[i].mmap` 是通过 `mmap(VFIO device fd, ...)` 返回的虚拟地址，直接映射到 host 上 PCI 设备的 MMIO 物理地址
2. **KVM 侧**：因为 `memory_region_is_ram() = true`，KVM 为其创建 memslot，guest 通过 stage-2 页表直接访问，零 VM exit
3. **内核 PFN 侧**：`__gfn_to_pfn_memslot()` 解析出的 PFN 指向设备 MMIO 物理页，`kvm_is_device_pfn()` 返回 true

```
┌──────────────────────────────────────────────────────────────┐
│ 物理层                                                       │
│  PCI 设备: 物理地址 0x1D000000 = 设备寄存器 (MMIO)            │
├──────────────────────────────────────────────────────────────┤
│ QEMU 包装层                                                  │
│  mmaps[i].mmap = mmap(fd, 0x1D000000)                       │
│    → QEMU 进程 VA → 设备 MMIO 物理地址                       │
│                                                              │
│  mmaps[i].mem = memory_region_init_ram_device_ptr(ptr)       │
│    → mr->ram = true   (为 KVM memslot 服务)                  │
│    → backing store  = 设备 MMIO 物理内存 (非普通 RAM)         │
├──────────────────────────────────────────────────────────────┤
│ KVM 层                                                       │
│  memory_region_is_ram(mr) = true                            │
│    → 创建 KVM memslot                                       │
│    → guest 通过 stage-2 直接访问 MMIO 寄存器，零 VM exit      │
│                                                              │
│  __gfn_to_pfn_memslot() → PFN = 设备物理页帧                 │
│    → kvm_is_device_pfn(pfn) = true → device = true           │
└──────────────────────────────────────────────────────────────┘
```

### 完整场景对照表

| 场景 | `mr->ram` | 有 KVM memslot? | 参与 dirty logging? | 有 DBM 风险? | 作用与用途 |
|------|-----------|----------------|--------------------|-------------|-----------|
| **BAR 基 MR** | false (IO) | 无 | 否 | 否 | 最外层容器。通过 `pci_register_bar()` 注册到 PCI 框架，定义 BAR 在 guest 地址空间中的位置和大小。未被子区域覆盖的偏移由 PCI 核心层的默认 handler 处理 |
| **BAR region 子 MR** | false (IO) | 无 | 否 | 否 | VFIO 定义的 region MR（`vfio_region_ops`）。负责通过 VFIO device fd 的 `read()/write()` 访问真实硬件 config/BAR 空间。当没有 mmap 子区域时，所有 guest 访问经此 MR 的 read/write 回调处理后转发到内核 VFIO 驱动 |
| **mmap 子区域** | **true** (ram_device) | **有** | **是** | **是 (HDBSS)** | 性能关键路径。将 VFIO device fd 中 mmap 出来的设备 MMIO 区域包装为 ram_device，使 guest 通过 stage-2 页表直接访问设备寄存器，**零 VM exit**。是"ram 外壳 + MMIO 内核"的混合体 |
| **mmap 失败 / 被禁用的 BAR** | false (IO) | 无 | 否 | 否 | 当 VFIO region fd 不支持 mmap、或 QEMU 命令行设 `x-no-mmap=on`、或 mmap syscall 失败时，整个 BAR 回退为纯 IO 类型。每个 guest MMIO 访问都 trap 到 QEMU → `vfio_region_ops` → VFIO fd read/write，**每次访问都有 VM exit 开销** |
| **IO Port BAR** | false (IO) | 无 | 否 | 否 | x86 平台的传统 I/O 端口 BAR（`PCI_BASE_ADDRESS_SPACE_IO`），通过 `IN/OUT` 指令访问而非内存映射。VFIO 不会对 IO BAR 做 mmap。ARM64 平台上不存在此类 BAR |
| **包含 MSI-X table 的 BAR** | false (IO) | 无 | 否 | 否 | MSI-X 中断向量表所在的 BAR 区域被 VFIO 显式禁止 mmap（`bar_mmap_supported = false`），因为 MSI-X table 必须由 QEMU trap 和模拟，以确保迁移后中断能正确投递。BAR 的其他部分仍可 mmap（sparse mmap） |

### mmap 子区域是否创建的决定条件链

```
vfio_region_setup()                                    [hw/vfio/region.c:250]
  │
  ├─ 条件1: region->size > 0
  │    └─ region 大小必须非零才能创建 region->mem
  │
  ├─ 条件2: !vbasedev->no_mmap
  │    │  QEMU 参数 "x-no-mmap" (默认 false, 即允许 mmap)
  │    └─ true 时跳过，用作 debug 或应急规避手段
  │
  ├─ 条件3: region->flags & VFIO_REGION_INFO_FLAG_MMAP
  │    │                                        内核 VFIO 驱动决定
  │    │
  │    └─ 内核侧判断: vdev->bar_mmap_supported[bar_index]
  │         [drivers/vfio/pci/vfio_pci_core.c:1051]
  │         │
  │         ├─ true:  PCI resource 存在且可被 mmap
  │         │         (Memory BAR，不在 MSI-X table 范围内)
  │         │
  │         └─ false: 场景包括:
  │              - IO Port BAR (非 Memory BAR)
  │              - BAR size = 0 (未实现)
  │              - MSI-X table 在此 BAR 内 (禁止 mmap)
  │              - host 内核 PCI 资源管理异常
  │
  ├─ 条件4: vfio_setup_region_sparse_mmaps() 成功
  │    │    内核通过 VFIO_DEVICE_GET_REGION_INFO ioctl 返回 sparse mmap
  │    │    信息（region_info.cap_offset 指向 capability 列表），
  │    │    描述 BAR 内哪些偏移范围允许 mmap
  │    │
  │    ├─ -ENODEV: 设备/内核不支持 sparse mmap capability
  │    │           → 降级: 整个 BAR 作为一个 mmap 区间
  │    ├─ 成功:    按 sparse mmap 信息创建多个 mmap 区间
  │    │            (MSI-X table 区域会被自动排除)
  │    └─ 其他错误: 放弃 mmap
  │
  └─ 条件5: vfio_region_mmap() 中的 mmap() 系统调用成功
       [hw/vfio/region.c:409]
       │
       mmap(..., MAP_SHARED | MAP_FIXED, fd,
            region->fd_offset + region->mmaps[i].offset)
       │
       └─ 失败 → region 仍存在，但无 ram_device 子区域
            (降级为纯 IO，每次访问 VM exit)
```

---

## 为什么 `logging_active` 对 MMIO BAR memslot 是 true？

**核心关键**：VFIO BAR 的 mmap 子区域是 `ram_device` 类型（`mr->ram = true`）。这个设计选择使其获得 KVM memslot 和 dirty logging 标记，尽管物理上它指向设备 MMIO。

### 完整链路

```
1. VFIO BAR mmap 子区域创建
   memory_region_init_ram_device_ptr()          [hw/vfio/region.c:427]
     → mr->ram = true                           [system/memory.c:1674]
     → memory_region_is_ram() 返回 true

2. KVM memslot 注册
   kvm_set_phys_mem()                           [accel/kvm/kvm-all.c:1644]
     → memory_region_is_ram(mr) == true         ← 通过检查
     → 创建 KVM memslot

3. 迁移开始，dirty logging 启用
   memory_global_dirty_log_start()
     → kvm_mem_flags(mr)                        [accel/kvm/kvm-all.c:790]
       → memory_region_get_dirty_log_mask(mr) != 0
       → KVM_MEM_LOG_DIRTY_PAGES 设到 memslot
     → 内核为 memslot 分配 dirty_bitmap

4. Guest 首次访问 MMIO BAR，触发 stage-2 fault
   user_mem_abort()                             [arch/arm64/kvm/mmu.c:1476]

   logging_active = memslot_is_logging(memslot) [mmu.c:1491]
     → memslot->dirty_bitmap != NULL            ← 步骤3 分配
     → !(memslot->flags & KVM_MEM_READONLY)     ← ram_device 非只读
     → logging_active = true

   kvm_is_device_pfn(pfn)                       [mmu.c:1613]
     → !pfn_is_map_memory(pfn)                  ← MMIO 物理地址不在 memblock "memory" 中
     → device = true
```

**关键点**：`logging_active` 为 true 并不是 HDBSS 的引入导致的——传统迁移（不带 HDBSS）也一样是 true。区别只在于传统迁移的 `user_mem_abort` 里没有设置 DBM 的代码。HDBSS 加的 DBM 设置代码暴露了这个双重身份的边界情况。

### ram_device 的双重身份

| 视角 | 看到的类型 | 决定因素 | 导致 |
|------|-----------|---------|------|
| QEMU MemoryRegion | `mr->ram = true` | `memory_region_init_ram_device_ptr()` 创建 | 有 KVM memslot → `logging_active = true` |
| 内核 PFN | device PFN | `pfn_is_map_memory()` 返回 false | `device = true` |

HDBSS 的 buggy 代码只看了一眼（`logging_active`），忽略了另一眼（`device`）：

```c
// 只看了 QEMU 侧 → 错误！
if (writable && kvm->arch.enable_hdbss && logging_active)
    prot |= KVM_PGTABLE_PROT_DBM;

// 应该同时看内核侧 → 正确！
if (!device && writable && kvm->arch.enable_hdbss && logging_active)
    prot |= KVM_PGTABLE_PROT_DBM;
```

---

## 传统迁移对 mmap BAR 的脏页跟踪全貌

### 整体架构

```
                         CPU 写入 MMIO BAR
                               │
              ┌────────────────┼────────────────┐
              ▼                                 ▼
     KVM stage-2 MMU 路径               VFIO/IOMMU 路径
  (user_mem_abort fault)       (vfio_listener_log_sync)
              │                                 │
     write-protect + fault            IOMMU dirty bitmap query
     → dirty_bitmap 记录              → physical_memory_set_dirty
              │                                 │
              └────────────┬────────────────────┘
                           ▼
                  QEMU RAMBlock dirty
                           │
                  RAM_MIGRATABLE = false
                  → 迁移流忽略，页面永不发送
```

### 第一步：迁移开始 → write-protect 所有 stage-2 PTE（包括 MMIO BAR）

QEMU 调用 `memory_global_dirty_log_start()`。

mmap BAR 是 `ram_device` → `memory_region_is_ram() = true` → `KVM_MEM_LOG_DIRTY_PAGES` 被设到 KVM memslot。

内核 `kvm_arch_commit_memory_region()` 检测到 `log_dirty_pages = true`（`arch/arm64/kvm/mmu.c:2185`）：

```c
if (log_dirty_pages) {
    ...
    kvm_mmu_wp_memory_region(kvm, new->id);   // write-protect 所有 stage-2 PTE
    kvm_mmu_split_memory_region(kvm, new->id);
}
```

**mmap BAR（MMIO 寄存器）的 stage-2 PTE 被 write-protect 了。** Device nGnRE + writable → Device nGnRE + **read-only**。

### 第二步：Guest 写 MMIO → stage-2 权限 fault → user_mem_abort

```
fault_status       = ESR_ELx_FSC_PERM    ← permission fault（PTE 被 WP 了）
logging_active     = true                ← ram_device memslot 有 dirty_bitmap
kvm_is_device_pfn  = true → device = true ← PFN 指向设备 MMIO 物理页
```

### 第三步：传统迁移的处理

传统迁移中没有 HDBSS/DBM 相关代码，`user_mem_abort` 对 MMIO BAR fault 的处理流程如下：

```c
// 3a. 设置写权限
if (writable)
    prot |= KVM_PGTABLE_PROT_W;         // PTE 恢复可写

// 3b. 设置 Device nGnRE 内存属性
if (device)
    prot |= KVM_PGTABLE_PROT_DEVICE;    // 正确的 MMIO 属性

// 3c. 重新映射为 writable
// fault_status == ESR_ELx_FSC_PERM && vma_pagesize == fault_granule
// → kvm_pgtable_stage2_relax_perms(pgt, fault_ipa, prot)
// PTE: Device nGnRE + writable（从只读恢复为可写）

// 3d. 标记脏页
mark_page_dirty_in_slot(kvm, memslot, gfn);
// → kvm_slot_dirty_track_enabled(memslot) = true
// → set_bit_le(rel_gfn, memslot->dirty_bitmap)
```

**结果**：PTE 恢复 Device nGnRE + writable，MMIO 写成功，dirty_bitmap 中对应位被设 1。

### 第四步：QEMU 收集脏页 → 迁移流忽略

QEMU 周期性调用 `kvm_slot_sync_dirty_pages()`，将内核 dirty_bitmap 同步到 QEMU RAMBlock dirty bitmap。

但 RAM 迁移迭代器（`migration/ram.h`）：

```c
#define RAMBLOCK_FOREACH_NOT_IGNORED(block)
    if (migrate_ram_is_ignored(block)) {} else
```

`migrate_ram_is_ignored()` （`migration/ram.c:227-235`）：

```c
bool migrate_ram_is_ignored(RAMBlock *block)
{
    return !qemu_ram_is_migratable(block) || ...;
}
```

`memory_region_init_ram_device_ptr()` 创建 RAMBlock 时没有 `RAM_MIGRATABLE` 标志 → `qemu_ram_is_migratable()` 返回 false → **mmap BAR 的脏页从未被 RAM 迁移流发送**。

### 第五步：VFIO/IOMMU 侧的并行路径

`vfio_listener_log_sync()` 对 mmap BAR 也不会被跳过：

```c
// vfio_listener_skipped_section(section, true):
return (!memory_region_is_ram(section->mr) &&     // false (是 RAM)
        !memory_region_is_iommu(section->mr)) ||  // false → 不被 skip！
       ...
```

**不被 skip** → `vfio_sync_dirty_bitmap()` → `vfio_container_query_dirty_bitmap()` → 查询 IOMMU 对该 IOVA 范围的脏页。

但设备**不会对自己的 MMIO BAR 做 DMA 写入**。IOMMU 脏页跟踪记录设备通过 SMMU 写 IOVA，而 CPU 写 BAR 走 stage-2 MMU 不经过 IOMMU。所以 IOMMU 对 BAR IOVA 的 dirty bitmap 永远是干净的。

通过 `physical_memory_set_dirty_lebitmap()` 标记的 QEMU 侧 dirty 同样因 `RAM_MIGRATABLE=false` 被忽略。

### 传统 vs HDBSS 完整对比

```
传统迁移 (enable_hdbss=false)          HDBSS Bug (enable_hdbss=true)
─────────────────────────────          ─────────────────────────────
Write-protect PTE                      Write-protect PTE
  │                                      │
Guest写BAR → fault                       Guest写BAR → fault
  │                                      │
user_mem_abort:                         user_mem_abort:
  enable_hdbss=false  ← 不设DBM          enable_hdbss=true
  device=true → DEVICE属性                device=true → DEVICE属性
  writable=true → 恢复写                  writable=true
                                           ↓
  PTE: Device + no DBM = 正确             logging_active=true
                                           ↓
  MMIO写正常                              DBM误设!
                                           ↓
                                         PTE: Device + DBM = UNPREDICTABLE
                                           ↓
                                         FPGA严格实现 → MMIO异常
                                           ↓
                                         设备状态不一致
                                           ↓
                                         第二次迁移config校验失败
```

### 传统迁移下每阶段对正确性的影响

| 阶段 | 做什么 | 是否正确 | 原因 |
|------|--------|---------|------|
| Write-protect PTE | 设只读 | 不影响 | 访问时 fault 恢复，MMIO 写最终成功 |
| Fault 处理 | Device 属性 + writable | 正确 | `device=true`→DEVICE 属性，MMIO 语义正确 |
| dirty_bitmap 标记 | set_bit_le | 不影响 | 仅标记 bitmap，不改变 MMIO 行为 |
| QEMU 收集 | 同步到 RAMBlock | 不影响 | `RAM_MIGRATABLE=false`，迁移流忽略 |
| IOMMU 查询 | 查 IOVA 脏页 | 不影响 | 设备从不 DMA 自己的 BAR，总是干净 |
| PTE 最终状态 | Device nGnRE + writable | 正确 | 与 write-protect 前的 PTE 一致 |

**传统迁移下 mmap BAR 是"无辜的旁观者"**：被卷入 write-protect/fault/dirty-mark 流程，产生无效 dirty bitmap 记录，但从不破坏 MMIO 访问的正确性。HDBSS 加入 DBM 后，旁观者变成了受害者。

### 标脏机制详解

传统热迁移的脏页跟踪基于 **write-protect + stage-2 fault** 机制。对每个开启了 `KVM_MEM_LOG_DIRTY_PAGES` 的 memslot（包括 mmap BAR 所在的 ram_device memslot），整个流程如下：

#### 标脏周期

```
QEMU: KVM_CLEAR_DIRTY_LOG (或 KVM_GET_DIRTY_LOG)
    │
    └── 内核: kvm_mmu_wp_memory_region()
          │  遍历 memslot 所有 stage-2 PTE
          │  → 清除 S2AP[1] (write permission)
          │  → 使 PTE 变为只读
          │
          ▼
    ┌─ Guest 运行 ─────────────────────────────────┐
    │                                              │
    │  Guest 写 MMIO BAR                           │
    │    → stage-2 permission fault (ESR_ELx_FSC_PERM)
    │    → VM exit 到 KVM                          │
    │    → user_mem_abort()                        │
    │      ├─ prot = KVM_PGTABLE_PROT_R | PROT_W   │
    │      ├─ prot |= KVM_PGTABLE_PROT_DEVICE       │  ← device=true
    │      ├─ kvm_pgtable_stage2_relax_perms()      │  ← 恢复 writable
    │      └─ mark_page_dirty_in_slot()             │  ← set_bit_le dirty_bitmap
    │                                              │
    │  Guest 再次写同一 MMIO BAR 页                 │
    │    → PTE 已可写，不 fault，直接通过           │
    │    → 不再记录脏页                            │
    │                                              │
    └──────────────────────────────────────────────┘
    │
    ▼
QEMU: memory_global_dirty_log_sync()
    │
    ├── KVM listener: kvm_slot_sync_dirty_pages()
    │     └─ 读内核 dirty_bitmap → QEMU RAMBlock dirty bitmap
    │
    └── VFIO listener: vfio_listener_log_sync()
          └─ 查 IOMMU dirty bitmap → 标记 QEMU RAMBlock
             (对 BAR 区域：设备不 DMA 自己 BAR，永远干净)
```

**关键细节**：每次 dirty log 收集后，QEMU 调用 `KVM_CLEAR_DIRTY_LOG` ioctl，内核会**再次 write-protect 已清除的页面**。这意味着 MMIO BAR 的每个页面在每个 dirty log 周期内，第一次 CPU 写都会触发一次 stage-2 permission fault。

#### QEMU 侧代码链：dirty log 如何开启

**(1) 迁移启动 → 全局 dirty logging 开始**

`migration/migration.c` → `memory_global_dirty_log_start(GLOBAL_DIRTY_MIGRATION)`（`system/memory.c:2888`）：

```c
bool memory_global_dirty_log_start(unsigned int flags, Error **errp)
{
    ...
    if (!old_flags) {
        memory_global_dirty_log_do_start(errp);  // 通知所有 listener
        memory_region_transaction_begin();
        memory_region_update_pending = true;       // 触发全局 topology update
        memory_region_transaction_commit();
    }
    return true;
}
```

`memory_global_dirty_log_do_start()` 遍历所有 `MemoryListener`，调用其 `log_global_start` 回调。VFIO listener 在此启动设备 DMA logging（`vfio_listener_log_global_start`）。KVM listener 没有 `log_global_start` 回调。

**(2) KVM memslot 获得 `KVM_MEM_LOG_DIRTY_PAGES`**

`memory_region_transaction_commit()` 触发 `kvm_region_add()` → `kvm_region_commit()` → `kvm_set_phys_mem()`。在 `kvm_set_phys_mem()` 中调用 `kvm_mem_flags(mr)`：

```c
static int kvm_mem_flags(MemoryRegion *mr)
{
    int flags = 0;
    if (memory_region_get_dirty_log_mask(mr) != 0) {
        flags |= KVM_MEM_LOG_DIRTY_PAGES;  // ← ram_device MR 的 mask 非零
    }
    ...
}
```

mmap BAR 的 ram_device MR 在 `memory_global_dirty_log_start()` 期间被设置了 `dirty_log_mask`，因此此 memslot 获得 `KVM_MEM_LOG_DIRTY_PAGES` 标志。

**(3) 内核处理 `KVM_MEM_LOG_DIRTY_PAGES`**

内核 `kvm_arch_commit_memory_region()`（`arch/arm64/kvm/mmu.c:2180`）：

```c
if (log_dirty_pages) {
    if (kvm_dirty_log_manual_protect_and_init_set(kvm))
        return;
    kvm_mmu_wp_memory_region(kvm, new->id);    // write-protect 所有 PTE
    kvm_mmu_split_memory_region(kvm, new->id);  // 拆分 huge page
}
```

**从此开始，mmap BAR 的所有 stage-2 PTE 变为只读，进入标脏周期。**

#### 迁移完整流程

```
+──────────────────────────────────────────────────────────────────+
│                        迁移生命周期                              │
+──────────────────────────────────────────────────────────────────+

1. 迁移启动
   memory_global_dirty_log_start()
     ├─ VFIO: vfio_listener_log_global_start()    ← 启动设备 DMA logging
     ├─ KVM: 所有 RAM memslot 设 KVM_MEM_LOG_DIRTY_PAGES
     └─ 内核: kvm_mmu_wp_memory_region()
               ← 包括 mmap BAR 在内，所有 PTE write-protect

2. 迭代脏页同步（反复执行）
   ┌─ 循环 ──────────────────────────────────────┐
   │                                              │
   │  memory_global_dirty_log_sync()              │
   │    │                                         │
   │    ├─ KVM: kvm_slot_sync_dirty_pages()       │
   │    │    └─ 读内核 dirty_bitmap               │
   │    │    └─ physical_memory_set_dirty_lebitmap │
   │    │       → 标记 QEMU RAMBlock dirty         │
   │    │                                          │
   │    └─ VFIO: vfio_listener_log_sync()         │
   │         └─ vfio_sync_dirty_bitmap()           │
   │           └─ vfio_container_query_dirty_bitmap │
   │             → 查 IOMMU IOVA 脏页              │
   │             → 标记 QEMU RAMBlock              │
   │                                              │
   │  migration_bitmap_sync_pre_copy()            │
   │    │                                         │
   │    └─ RAMBLOCK_FOREACH_NOT_IGNORED(block)    │
   │         └─ migrate_ram_is_ignored(block):     │
   │              ram_device MR → true → 跳过!    │
   │              (mmap BAR 的 dirty bitmap 被忽略) │
   │                                              │
   │  KVM_CLEAR_DIRTY_LOG ioctl                   │
   │    └─ 内核: 清除 dirty_bitmap，再次 WP 这些页 │
   │                                              │
   └──────────────────────────────────────────────┘

3. 迁移完成
   memory_global_dirty_log_stop()
     ├─ VFIO: vfio_listener_log_global_stop()     ← 停止 DMA logging
     └─ KVM: 清除 KVM_MEM_LOG_DIRTY_PAGES
        └─ 内核: kvm_mmu_wp_memory_region() 不再调用
```

#### 脏页标记的实际效果

对 mmap BAR 来说，脏页标记经历了完整链路，但在每一层都被无害化处理：

```
Guest 写 MMIO BAR
  │
  ▼
Stage-2 fault → user_mem_abort()
  │
  ├─ PTE 处理:       Device nGnRE + writable  ← 正确，MMIO 语义不变
  │
  └─ set_bit_le(gfn, memslot->dirty_bitmap)    ← 内核 dirty_bitmap[D]=1
       │
       ▼
     kvm_slot_sync_dirty_pages()
       │
       └─ physical_memory_set_dirty_lebitmap()  ← QEMU RAMBlock dirty[D]=1
            │
            ▼
          migration_bitmap_sync_pre_copy()
            │
            └─ migrate_ram_is_ignored(block) = true
               → 跳过，页面 D 永不进入迁移流
```

**结论**：mmap BAR 在传统热迁移中完整参与了 dirty logging 流程——PTE 被 write-protect、写操作触发 fault、dirty bitmap 被标记、QEMU 周期性收集——但最终因 `RAM_MIGRATABLE=false` 被 RAM 迁移流忽略。整个过程对 MMIO 正确性无影响。

---

## Bug 触发条件

在 `user_mem_abort()` 中，四个条件同时为 true：

```
writable       = true   ← MMIO BAR 可写
enable_hdbss   = true   ← HDBSS 已全局启用 (kvm->arch.enable_hdbss = true)
logging_active = true   ← ram_device memslot 有 dirty_bitmap
device         = true   ← kvm_is_device_pfn 检测到 MMIO PFN
```

HDBSS v3 的 buggy 代码（`arch/arm64/kvm/mmu.c`）：

```c
// Bug: 缺少 !device 检查
if (writable && kvm->arch.enable_hdbss && logging_active)
    prot |= KVM_PGTABLE_PROT_DBM;    // DBM (PTE bit 51) 被设为 Device nGnRE PTE 上!
```

几行之后：

```c
if (device)
    prot |= KVM_PGTABLE_PROT_DEVICE;  // 同一个 PTE 获得 Device nGnRE 内存属性
```

**同一个 stage-2 PTE 同时携带 DBM 位和 Device nGnRE 属性 → ARM 架构未定义行为。**

### 引入问题的 commit

```
a80960316b53 ("KVM: arm64: Add HDBSS v3 support")
```

在 `user_mem_abort()` 中添加：

```c
+	if (writable && kvm->arch.enable_hdbss && logging_active)
+		prot |= KVM_PGTABLE_PROT_DBM;
```

### DBM on Device memory 的后果

ARM 架构规范中 DBM 只对 Normal memory 定义。当 DBM 设置在 Device memory PTE 上：

1. **HDBSS 硬件尝试对 Device memory 做 dirty tracking**
2. **Device memory 访问语义被破坏**：写操作可能被重排、合并、丢弃或重复
3. **MMIO 寄存器访问异常**：guest 通过 MMIO 提交的任务/查询的状态可能出现错误
4. **设备内部状态不一致**：QEMU 缓存的 config space 值与设备硬件真实状态产生偏差

### 为什么第一次迁移成功，第二次失败？

**第一次迁移 A→B**：
- 源端 A：设备处于 quiesced 状态，`config[0x4a] = 0`
- QEMU 保存 config space 到迁移流（直接使用缓存，不重新读硬件）
- 目的端 B：恢复成功，设备初始化

**目的端 B 运行 workload**：
- Guest 通过 MMIO 使用 hisi_zip 进行压缩任务
- DBM on MMIO 干扰设备 MMIO 访问
- 设备硬件内部状态变化，`config[0x4a]` 硬件值从 0 变为 8

**第二次迁移 B→A（失败）**：

```
源端 B save:
  QEMU 缓存 config[0x4a] = 0           ← QEMU 保存时不重新读硬件，直接用缓存值
  → 写入迁移流

目的端 A load:
  从迁移流读取 config[0x4a] = 0        ← "read: 0"
  目标端设备硬件真实值 = 8              ← "device: 8"（VFIO init 时从硬件读取）
  cmask[0x4a] = 0xff                   ← 检查所有位（包括硬件只读位）

  get_pci_config_device() 校验逻辑:
  (0 ^ 8) & 0xff & ~0 & ~0 = 8        ← 非零 → 报错！
```

这里暴露了 QEMU 侧的第二个缺陷：VFIO 传统热迁移缺少 `cmask` 限制机制。对于 `wmask=0` 的硬件只读寄存器，校验时不应该检查所有位。CPR 迁移模式有 `cpr_pre_load()` 回调限制 cmask，但传统迁移没有。

### 为什么 EVB 正常，FPGA 失败？

| | EVB（真实 ARM 硅片） | FPGA |
|---|---|---|
| DBM on Device memory | 硬件 MMU 容错，静默忽略 | 严格按架构规范，产生未定义行为 |
| MMIO 访问正确性 | 不受 DBM 影响 | 被 DBM 干扰 |
| 设备状态稳定性 | 正确 | 异常 |

代码在两个平台上都错误地设置了 DBM。区别在于真实硅片的硬件实现在遇到非法组合时做了容错，而 FPGA 上的 HDBSS 硬件严格按规范执行。

---

## 修复方案

### Kernel Bug Fix（治本）

**文件**：`arch/arm64/kvm/mmu.c`

```c
// 修复前 (Buggy)
if (writable && kvm->arch.enable_hdbss && logging_active)
    prot |= KVM_PGTABLE_PROT_DBM;

// 修复后
if (!device && writable && kvm->arch.enable_hdbss && logging_active)
    prot |= KVM_PGTABLE_PROT_DBM;
```

**原理**：DBM 只应用于普通 RAM（Normal memory），绝不应用于 Device/MMIO 内存。`kvm_is_device_pfn()` 已经正确检测了 device PFN，只需要在 DBM 决策时利用这个信息。

### Kernel Debug Patch（辅助验证）

添加诊断日志，当 DBM 将被错误添加到 MMIO 时打印警告：

```c
if (device && writable && kvm->arch.enable_hdbss && logging_active) {
    pr_info_ratelimited("KVM_HDBSS_DBG: BUG detected! "
        "DBM would be added to MMIO ipa=0x%llx dev=%d en=%d log=%d\n",
        fault_ipa, device, kvm->arch.enable_hdbss, logging_active);
}
```

### QEMU Bug Fix（兜底）

**文件**：`hw/vfio/pci.c`

为 VFIO 传统热迁移添加 `pre_load` 回调，限制 cmask 只校验 QEMU 模拟的位：

```c
static int vfio_pci_config_pre_load(void *opaque)
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
    ...
    .pre_load = vfio_pci_config_pre_load,  // 添加此行
    ...
};
```

**原理**：`cmask` 控制 config space 迁移时哪些位需要校验。硬件只读位（`wmask=0`）在源端和目标端之间必然不同（不同物理设备），不应参与校验。限制 `cmask` 只检查 QEMU 模拟的位。

---

## 三层防御总结

```
┌─────────────────────────────────────────────────────────────────┐
│ 第一层防御 (Kernel)                                              │
│ !device → 不设 DBM                                              │
│ 防止: HDBSS 硬件错误地对 MMIO 做 dirty tracking                  │
│ 类型: 治本（根因修复）                                           │
├─────────────────────────────────────────────────────────────────┤
│ 第二层防御 (QEMU)                                                │
│ cmask &= emulated_config_bits → 只校验 QEMU 模拟的 config 位     │
│ 防止: 硬件只读位不一致导致迁移验证失败                            │
│ 类型: 兜底（即使 kernel 侧有未知问题，也不影响迁移正确性）         │
├─────────────────────────────────────────────────────────────────┤
│ 第三层防御 (应急规避)                                             │
│ QEMU: x-no-mmap=on → 强制 BAR 为纯 IO 类型，禁用 mmap            │
│ 防止: 整个 ram_device 路径被绕过                                 │
│ 类型: 测试/应急（性能会下降，但可快速验证是否是 mmap 路径问题）    │
└─────────────────────────────────────────────────────────────────┘
```
