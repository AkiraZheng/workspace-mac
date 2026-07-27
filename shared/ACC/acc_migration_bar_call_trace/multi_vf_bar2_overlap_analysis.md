# 多 VF 同 PCI Bus BAR2 重叠导致 S2 失效分析报告

## 1. 前提：单 VF 的 Bugfix

hisi_acc_vfio_pci 在 VF_CTRL 模式下将 BAR2 截断为 32KB（`bar_len >> 1`）：

**`drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c:1336`**:
```c
if (hisi_acc_vdev->drv_mode == HW_ACC_MIG_VF_CTRL) {
    ret_len = bar_len >> 1;    // 64KB → 32KB
```

在 64KB PAGE_SIZE 的 Host 上，32KB < PAGE_SIZE → QEMU mmap 被拒绝 → 无 ram_device MR → 无 KVM S2 映射 → Guest ldp → SEA 崩溃。

**已应用的修复**：在 `hisi_acc_vfio_pci_mmap()` 中将 `hisi_acc_get_resource_len` 的返回值 ALIGN 到 PAGE_SIZE，使 mmap 检查通过：

**`drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c:1397` (修复后)**:
```c
end = hisi_acc_get_resource_len(vdev, index);
// 修复: end = ALIGN(end, PAGE_SIZE)   使得 32KB → 64KB
req_len = vma->vm_end - vma->vm_start;  // 64KB (内核对齐)
if (req_start + req_len > end)          // 0+64KB > 64KB → false → pass
    return -EINVAL;
```

修复后单 VF 正常工作：
- mmap 成功 → ram_device MR = 64KB → KVM memslot 注册成功 → S2 映射 OK → Guest 正常访问

**但遗留问题**：`hisi_acc_get_resource_len` 本身仍返回 32KB（用于 `VFIO_DEVICE_GET_REGION_INFO`），Guest 仍然认为 BAR2 = 32KB。

---

## 2. 多 VF 的问题：两个 VF 在同一 PCI Bus 下仍然崩溃

同时直通两个 VF 到同一 PCI Bus（无 PCIe Root Port 隔离）时，即使 mmap 已修复，仍然出现相同的 `hisi_qm_wait_mb_ready` SEA call trace。使用 PCIe Root Port 隔离后问题消失。

---

## 3. 邮局比喻

背景：两个挤在同一间办公室的快递柜。

Host 的页大小是 64KB（一间办公室的面积）。每个 VF 的 BAR2 是快递柜——物理上每个快递柜占 64KB（一间办公室），但 VF_CTRL 模式下只有前 32KB 是功能寄存器（租户可以用的格子），后 32KB 是迁移寄存器（租户不该碰）。

### 第一步：物业登记错了快递柜大小

Host 的 hisi_acc 驱动通过 ioctl 告诉 QEMU："这个快递柜 32KB"（`hisi_acc_get_resource_len` → `bar_len >> 1`）。

QEMU 物业拿这个数在**两个地方**登记：

| 地方 | 代码位置 | 值 | 说明 |
|---|---|---|---|
| PCI 台账 `r->size` | `hw/pci/pci.c:1323` | 32KB | 永久不可改，Guest 通过 BAR wmask 读到 |
| 门禁平面图 MR size | `memory_region_init_io` | 32KB | 可以被 `sub_page_bar` 临时改成 64KB |

**`hw/pci/pci.c:1321-1330`** — 台账固化的代码：
```c
r->size = size;                          // 32KB ← Guest 枚举时读这个
wmask = ~(size - 1);                     // BAR writable mask
// Guest 写 all-1s → 读回 address & wmask → 低位 15 个 0 → 32KB
```

### 第二步：租户按 32KB 分配门牌号，两个柜子挤进同一间办公室

Guest 租户读台账（BAR 寄存器 wmask 由 `r->size=32KB` 决定），看到每个快递柜 32KB。PCI 枚举时分配门牌号：

```
Dev1 快递柜 → 0x8000400000（办公室 A 的前半间）
Dev2 快递柜 → 0x8000408000（办公室 A 的后半间）
```

两个 32KB 的快递柜正好挤进同一间 64KB 的办公室。

### 第三步：QEMU 补救机制（sub_page_bar）触发

QEMU 内部有个"补救机制" `vfio_sub_page_bar_update_mapping`：发现快递柜比办公室小（32KB < 64KB PAGE_SIZE），等快递柜分到门牌号时，把门禁平面图上的尺寸临时改成 64KB。

**`hw/vfio/pci.c:1341-1346`** — 触发条件：
```c
if (old_addr[bar] != pdev->io_regions[bar].addr &&      // 门牌号变了才触发
    vdev->bars[bar].region.size > 0 &&
    vdev->bars[bar].region.size < qemu_real_host_page_size()) {  // 32KB < 64KB
    vfio_sub_page_bar_update_mapping(pdev, bar);
}
```

**`hw/vfio/pci.c:1212-1221`** — 补救机制做了什么：
```c
// 只改门禁平面图 MR 的大小
memory_region_set_size(base_mr, PAGE_SIZE);   // bar->mr   → 64KB
memory_region_set_size(region_mr, PAGE_SIZE);  // region.mem → 64KB
memory_region_set_size(mmap_mr, PAGE_SIZE);   // ram_device MR → 64KB

// 从总线删除，再以 priority=0 重新加入（关键！priority 降级！）
memory_region_del_subregion(r->address_space, base_mr);
memory_region_add_subregion_overlap(r->address_space,
                                    bar_addr, base_mr, 0);  // ← priority=0
```

**改了什么、没改什么：**

| 层 | 变量/代码位置 | sub_page_bar 改? | 值 |
|---|---|---|---|
| 台账 | `r->size` (`pci.c:1323`) | 不改 | 32KB |
| 快递柜 | `bar->size` (`vfio/pci.c:1785`) | 不改 | 32KB |
| 平面图 | `bar->mr` size (`pci.c:1213`) | 改 | 64KB |
| 优先级 | MR 覆盖优先级 (`pci.c:1220`) | 降级! | 1 → 0 |

**注意：** 原始 BAR 注册使用 priority=1：

**`hw/pci/pci.c:1547`**:
```c
memory_region_add_subregion_overlap(r->address_space,
                                    r->addr, r->memory, 1);  // priority=1
```

### 第四步：门禁平面图被切成两半

两个 VF 的 BAR2 门牌号紧挨着（间隔 32KB），每个的平面图都被补救机制扩成 64KB → 重叠 32KB。

Dev2 触发补救机制时，两个 BAR2 都是 priority=0，Dev2 后注册：

```
QEMU Flat View 冲突 (同一条 PCI Bus 的 address_space_mem):

  Dev1 (priority=0, 64KB): [0x8000400000 ──────────── 0x800040ffff]
  Dev2 (priority=0, 64KB):             [0x8000408000 ──────────── 0x800040ffff]
                                        └── 重叠 32KB ──┘

同优先级后注册覆盖前注册 → Flat View 最终:
  Section A (Dev1): [0x8000400000, 0x8000407fff] 32KB  ← 被切!
  Section B (Dev2): [0x8000408000, 0x8000417fff] 64KB  ← Dev2 覆盖了重叠部分
```

### 第五步：门禁记录建不上

KVM 门禁系统只按"整间办公室"建 memslot 记录，不认半个办公室。

**`accel/kvm/kvm-all.c:272-280`** — `kvm_align_section`:
```c
/* Pad the start address to next and truncate size to previous page boundary. */
aligned = ROUND_UP(section->offset_within_address_space,
                   qemu_real_host_page_size());     // 对齐到 64KB
delta = aligned - section->offset_within_address_space;
if (delta > size) {
    return 0;       // ← 32KB section → 对齐后返回 0 → 不建 memslot!
}
```

Dev1 的 section 被切成 32KB：
- `kvm_align_section(32KB)` → 返回 0 → **不建 memslot** ✗
- `kvm_set_phys_mem` SKIP

### 第六步：乒乓效应

Dev1 的 KVM memslot 被删除后，VFIO listener 检测到 Dev1 的 BAR 又是 sub-page 状态，**重新触发补救机制**：

```
Dev1 sub_page_bar
  → 扩展 Dev1 平面图到 64KB, priority=0
  → Flat View 重建
  → Dev1 后注册 → Dev1 覆盖 Dev2 的重叠区
  → Dev2 section 被切回 32KB

Dev2 sub_page_bar（被 VFIO listener 再次触发）
  → 扩展 Dev2 平面图到 64KB, priority=0
  → Flat View 重建
  → Dev2 后注册 → Dev2 覆盖 Dev1 的重叠区
  → Dev1 section 被切回 32KB

循环往复!
```

**这就是为什么即使 mmap 已修复，两个 VF 在同一 PCI Bus 下仍然不稳定的原因。**

### 第七步：Guest 访问 → SEA

等 `insmod hisi_zip.ko`，驱动访问 Dev1 BAR2 的 mailbox 寄存器（如 GPA 0x8000408300）：

```
GVA → GPA (Guest S1 ✓) → GPA → HPA (Host S2 ✗ 无映射!)
  → S2 Translation Fault
  → VM exit → KVM → ISV=0 (ldp 128-bit 无法解码)
  → KVM_EXIT_ARM_NISV → QEMU 注入 SEA
  → Guest kernel panic
```

### 修复：让台账和平面图一开始就一致

彻底修复需要让 `hisi_acc_get_resource_len`（被 `VFIO_DEVICE_GET_REGION_INFO` 使用）返回值与 mmap 允许的值一致：

**`drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c:1336`**:
```c
if (hisi_acc_vdev->drv_mode == HW_ACC_MIG_VF_CTRL) {
    ret_len = bar_len >> 1;
    ret_len = ALIGN(ret_len, PAGE_SIZE);  // 修复: 32KB → 64KB
    return ret_len;
}
```

修复效果：

| | 修复前（仅 mmap） | 修复后（ioctl+mmap 对齐） |
|---|---|---|
| `r->size` (台账) | 32KB | **64KB** |
| Guest BAR enum | 32KB | **64KB** |
| Guest 分配 BAR2 间隔 | 32KB（挤同一办公室） | **≥64KB（不同办公室）** |
| Flat View 重叠 | 是（32KB 重叠） | **否（无重叠）** |
| sub_page_bar 触发 | 是（32KB < 64KB） | **否（64KB = PAGE_SIZE）** |
| KVM memslot | 被切 → 建不上 | **正常建立** |

三层（Guest 台账 / QEMU 平面图 / KVM 门禁记录）从一开始就一致，不依赖补救机制。

---

## 4. 完整证据链

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 证据链：双 VF 同一 PCI Bus 下 BAR2 重叠 → S2 失效                                    │
│                                                                                     │
│ [A] hisi_acc_get_resource_len 返回 32KB                                              │
│     └─ drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c:1336  ret_len = bar_len >> 1  │
│                                                                                     │
│ [B] VFIO_DEVICE_GET_REGION_INFO 返回 32KB 给 QEMU                                    │
│     └─ hw/vfio/helpers.c:370  region->size = info->size                             │
│        └─ hw/vfio/pci.c:1785  bar->size = bar->region.size  → 32KB                 │
│                                                                                     │
│ [C] PCI 台账固化 32KB，Guest 通过 BAR wmask 看到 32KB                                 │
│     └─ hw/pci/pci.c:1323  r->size = 32KB                                           │
│     └─ hw/pci/pci.c:1330  wmask = ~(size-1) = ~0x7FFF → Guest 枚举得 32KB          │
│                                                                                     │
│ [D] Guest PCI 枚举：两个 BAR2 门牌号紧挨着（间隔 32KB）                                │
│     └─ Dev1 BAR2: GPA 0x8000400000 (32KB aligned)                                  │
│     └─ Dev2 BAR2: GPA 0x8000408000 (32KB aligned)                                  │
│     └─ 两者在同一 64KB 物理页内！                                                      │
│                                                                                     │
│ [E] QEMU 补救机制 sub_page_bar 触发                                                  │
│     └─ hw/vfio/pci.c:1341-1346  条件: old_addr≠new_addr && size<PAGE_SIZE          │
│     └─ hw/vfio/pci.c:1212-1216  扩展 MR size 到 64KB                                │
│     └─ hw/vfio/pci.c:1217-1221  删除+重新加回, priority 降级 1→0                    │
│                                                                                     │
│ [F] Flat View 重叠 → section 被截断                                                  │
│     └─ 两个 priority=0 的 64KB MR 在 GPA 上重叠 32KB                                │
│     └─ 同优先级后注册覆盖前注册 → 被覆盖的 BAR2 在 Flat View 中截断为 32KB            │
│                                                                                     │
│ [G] KVM 不认 32KB section → 不建 memslot                                            │
│     └─ accel/kvm/kvm-all.c:272-280  kvm_align_section:                              │
│         if (delta > size) return 0  → 32KB section → 返回0 → SKIP                  │
│                                                                                     │
│ [H] VFIO listener 检测到截断 → 触发新一轮 sub_page_bar → 乒乓                         │
│     └─ Flat View 变化 → listener 通知 → sub_page_bar 再次触发                        │
│     └─ Dev1→Dev2→Dev1→... 循环往复                                                  │
│                                                                                     │
│ [I] Guest 访问 BAR2 → S2 无映射 → SEA                                                │
│     └─ S2 Translation Fault → ldp ISV=0 → KVM_EXIT_ARM_NISV → SEA                  │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. 根因一句话

修复了 mmap 检查（ram_device MR 可以建），但台账（BAR wmask）仍告诉 Guest BAR2=32KB，Guest 把两个 VF 的 BAR2 分到同一 64KB 页内。QEMU 的 sub_page_bar 机制将 MR 扩到 64KB 但降 priority，两个 priority=0 的 MR 在 Flat View 中交替覆盖，被截断的那个 KVM 建不上 memslot，S2 页表为空，Guest 访问触发 SEA。

---

## 6. 涉及文件

| 文件 | 行号 | 内容 |
|---|---|---|
| `drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c` | 1336 | `ret_len = bar_len >> 1` (32KB) |
| `drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c` | 1397 | mmap 检查 (已修复为 ALIGN) |
| `hw/pci/pci.c` | 1323 | `r->size = size` (台账固化) |
| `hw/pci/pci.c` | 1330 | `wmask = ~(size - 1)` (Guest 读 BAR 大小) |
| `hw/pci/pci.c` | 1547 | `priority=1` (原始 BAR 注册) |
| `hw/vfio/helpers.c` | 370 | `region->size = info->size` (来自 ioctl) |
| `hw/vfio/pci.c` | 1785 | `bar->size = bar->region.size` |
| `hw/vfio/pci.c` | 1171-1224 | `vfio_sub_page_bar_update_mapping` (补救机制) |
| `hw/vfio/pci.c` | 1213-1216 | `memory_region_set_size` (只改 MR, 不改台账) |
| `hw/vfio/pci.c` | 1220 | `priority=0` (降级) |
| `hw/vfio/pci.c` | 1341-1346 | sub_page_bar 触发条件 (old_addr ≠ new_addr) |
| `accel/kvm/kvm-all.c` | 272-280 | `kvm_align_section` (32KB → 返回 0) |
