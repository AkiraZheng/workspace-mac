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

### 4.4 截断的逐步演示

以 Dev1 BAR2 @ GPA 0x8000_200000 和 Dev2 BAR2 @ GPA 0x8000_208000 为例。

**初始状态** — 两个 BAR 都刚通过 `pci_update_mappings` 注册（priority=1，32KB）：

```
GPEX io_mmio.subregions (QTAILQ):
  Dev1: priority=1, offset=0x200000, size=32KB
  Dev2: priority=1, offset=0x208000, size=32KB

FlatView 渲染 (两者同 priority, Dev1 offset 小→先渲染):
  [0x8000_200000, 0x8000_207fff] → Dev1 BAR2 (IO, 32KB)
  [0x8000_208000, 0x8000_20ffff] → Dev2 BAR2 (IO, 32KB)
```

**Round 1: Dev1 触发 sub_page_bar** → Dev1 priority=0, size=64KB, 插入到 Dev2 前面：

```
QTAILQ:
  Dev1: priority=0, offset=0x200000, 64KB  ← 后插入, 排前面!
  Dev2: priority=1, offset=0x208000, 32KB

FlatView 渲染:
  1) Dev1 (priority=0, 64KB) 先渲染 → 因为 FlatView 为空 → 填满64KB
     FlatView: [0x8000_200000, 0x8000_20ffff] Dev1
  2) Dev2 (priority=1, 32KB) 后渲染 → 因为 Dev1 已占满 0x200000~0x20ffff
     → Dev2 的 [0x208000, 0x20ffff] 完全被覆盖 → 只能等待空隙
     → 但在 0x8000_208000 处没有空隙 → Dev2 什么也插入不了!

  FlatView 最终:
    [0x8000_200000, 0x8000_20ffff] Dev1 BAR2 (64KB)
    (Dev2 BAR2 被完全覆盖, 不出现!)                               ← 不是截断, 是完全消失!
```

**Round 2: Dev2 触发 sub_page_bar** → Dev2 priority=0, size=64KB, 插入到 Dev1 前面：

```
QTAILQ:
  Dev2: priority=0, offset=0x208000, 64KB  ← 后插入, 排前面!
  Dev1: priority=0, offset=0x200000, 64KB
```

**`render_memory_region` 逐步模拟**（内核地址用 pcie-mmio alias 前的 offset, base_mmio=0x8000_000000）:

```
初始 FlatView: 空 (view->nr=0)

Step A — 渲染 Dev2 (priority=0, offset=0x208000, size=0x10000=64KB):
────────────────────────────────────────────────────────
  base = 0x208000, remain = 0x10000
  view->nr=0 → for 循环跳过
  remain>0 → flatview_insert(view, 0, Dev2_fr):
    view->ranges[0] = {start=0x208000, size=0x10000, mr=Dev2}
  FlatView 暂态: [0] Dev2 [0x208000 ── 0x218000) 64KB

Step B — 渲染 Dev1 (priority=0, offset=0x200000, size=0x10000=64KB):
────────────────────────────────────────────────────────
  base = 0x200000, remain = 0x10000
  i=0 → view->ranges[0] = {start=0x208000, end=0x218000}

  ★ 空洞判定 (line 671):
    int128_lt(0x200000, 0x208000)? → Yes! 0x200000 在 0x208000 前面 → 有空洞!
    now = min(0x10000, 0x208000 - 0x200000) = min(0x10000, 0x8000) = 0x8000 (32KB)

    flatview_insert(view, 0, Dev1_hole_fr):
      → memmove → 原 ranges[0](Dev2) 右移一格
      → view->ranges[0] = {start=0x200000, size=0x8000, mr=Dev1}  ← 空洞部分插入!

    base   = 0x200000 + 0x8000 = 0x208000   (推进到空洞末尾)
    remain = 0x10000 - 0x8000 = 0x8000      (还剩 32KB)
    ++i → i=1

  FlatView 暂态: [0] Dev1 hole [0x200000 ── 0x208000) 32KB
                 [1] Dev2      [0x208000 ── 0x218000) 64KB

  i=1 → view->ranges[1] = {start=0x208000, end=0x218000}
    没有空洞需要插入。
    ★ 覆盖消耗 (line 682-687):
    now = min(0x208000+0x8000=0x210000, 0x218000) - 0x208000
        = 0x210000 - 0x208000 = 0x8000 (32KB)
    base   = 0x208000 + 0x8000 = 0x210000   (跳过被 Dev2 覆盖的区域)
    remain = 0x8000 - 0x8000 = 0            (刚好消耗完!)
    ++i → i=2 → 循环结束

  remain==0 → 不插入 (line 689)

最终 FlatView:
  [0] Dev1 [0x200000, 0x208000) 32KB!!   ← 只有空洞部分留下了, 被截断!
  [1] Dev2 [0x208000, 0x218000) 64KB     ← 后注册, 占满 64KB
```

Dev1 的 64KB MR 在渲染时，前 32KB（0x200000~0x208000）插入为空洞，后 32KB（0x208000~0x20ffff）被 Dev2 的已渲染区间覆盖 → 消耗掉不插入 → **Dev1 在 FlatView 中只剩 32KB。这就是截断发生的精确机制。**

**Round 3: Dev1 被截断为 32KB** → VFIO listener 再次触发 sub_page_bar → 循环往复。

### 4.5 截断的本质

FlatView 的 `render_memory_region` 逻辑保证了 "高 priority 先占，同 priority 后注册先占，低 priority / 先注册者只能填空隙"。sub_page_bar 把 priority 降到 0 后，两个 64KB BAR 在同一 GPA 区域竞争——后渲染的那个填满 64KB，先渲染的那个被截断为 32KB。被截断的又触发新一轮 sub_page_bar → 乒乓。

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
