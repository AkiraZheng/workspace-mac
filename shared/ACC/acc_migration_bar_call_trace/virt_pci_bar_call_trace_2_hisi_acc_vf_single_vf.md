# hisi_acc_vfio_pci 单 VF 直通 SEA 崩溃分析 —— 第2篇

## 1. 问题描述

使用 `hisi_acc_vfio_pci` 绑定加速器 VF 透传给虚拟机（64KB PAGE_SIZE），在 Guest 内 `insmod hisi_zip.ko` 触发 Synchronous External Abort (SEA)，kernel panic。使用通用 `vfio-pci` 驱动绑定时正常。

### 1.1 崩溃日志

```
[Guest] insmod hisi_zip.ko uacce_mode=1 pf_q_num=32
[Host]  qemu-system-aarch64: VFIO_MAP_DMA failed: Bad address

[Guest] Internal error: synchronous external abort: 0000000096000010 [#1] SMP
[Guest] pc : hisi_qm_wait_mb_ready+0x44/0xc8 [hisi_qm]
[Guest] lr : qm_mb_nolock+0x30/0x158 [hisi_qm]

[Guest] Call trace:
[Guest]  hisi_qm_wait_mb_ready  →  qm_mb_nolock  →  hisi_qm_mb_read
[Guest]  → qm_get_vft_v2  →  qm_get_pci_res  →  hisi_qm_pci_init
[Guest]  → hisi_qm_init  →  hisi_zip_probe

[Guest] Kernel panic - not syncing: Fatal exception
```

### 1.2 PCI 枚举差异

| | hisi_acc_vfio_pci (崩溃) | vfio-pci (正常) |
|---|---|---|
| Guest 看到的 BAR2 | **0x8000200000-0x8000207fff (32KB)** | 0x8000200000-0x800020ffff (64KB) |
| Host PAGE_SIZE | 64KB | 64KB |
| 关系 | 32KB < 64KB | 64KB = 64KB |

**关键线索**: 同样的 VF 硬件（物理 BAR2 都是 64KB），`hisi_acc_vfio_pci` 让 Guest 看到 32KB，`vfio-pci` 让 Guest 看到 64KB。只有前者崩溃。

---

## 2. 根因分析

### 2.1 hisi_acc 驱动截断 BAR2 为 32KB

`hisi_acc_vfio_pci` 在 VF_CTRL 迁移模式下，将 BAR2 截半——前 32KB 是功能寄存器（暴露给 Guest），后 32KB 是迁移寄存器（Host 独占）。

**`drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c:1335`**:

```c
static size_t hisi_acc_get_resource_len(struct vfio_pci_core_device *vdev,
                                        unsigned int index)
{
    // ...
    if (hisi_acc_vdev->drv_mode == HW_ACC_MIG_VF_CTRL) {
        ret_len = bar_len >> 1;      // 64KB → 32KB
        return ret_len;
    }
    // ...
}
```

此函数的返回值用于 `VFIO_DEVICE_GET_REGION_INFO` ioctl → QEMU 据此创建 MemoryRegion → Guest PCI 枚举读 wmask 得到 BAR2=32KB。

### 2.2 32KB < 64KB PAGE_SIZE → mmap 失败 → 无 KVM S2

- QEMU 通过 mmap 获取 HVA，mmap 成功后才创建 ram_device MR（`mr->ram=true`），只有这类 MR 才会触发 KVM memslot 注册。

  ```
  QEMU [EL0]:
    // 用 HVA 创建 ram_device MR
    memory_region_init_ram_device_ptr(&mmaps[0].mem, ...,
                                      HVA_0x7fff_xxxx, 64KB);
    // mmaps[0].mem.ram = true
    // mmaps[0].mem.ram_device = true
    // mmaps[0].mem.ram_block->host = HVA_0x7fff_xxxx
  ```

- QEMU 通过 mmap 获取 HVA，目的是让 KVM 能用 `get_user_pages(HVA)` 查到设备 BAR2 的 HPA，进而填入 S2 页表（GPA→HPA），使 Guest 能通过 S2 硬件直达设备。

但是由于 PAGE_SIZE=64KB，acc vfio-pci 驱动返回的 BAR2=32KB，导致 mmap 失败：

```
hisi_acc_get_resource_len → 32KB
  → VFIO_DEVICE_GET_REGION_INFO → size=32KB
  → QEMU mmap(VFIO_fd, 32KB)
    → 内核将 mmap 请求对齐到 PAGE_SIZE=64KB
    → hisi_acc_vfio_pci_mmap() 检查: 0 + 64KB > 32KB → -EINVAL
    → mmap 失败!
  → 无 ram_device MR → KVM 不建 memslot
  → Guest 访问 BAR2 → S2 缺页
```

### 2.3 mmap 失败后 BAR2 的建立过程（GPA 去哪了）

mmap 虽然失败，但 **MR 树和 FlatView 仍然有 BAR2 的记录**——只是没有 ram_device 层。QEMU 的 KVMSlot 和 KVM 的 memslot **都不会创建**，但 GPA 仍然存在于台账和 FlatView 中，用于 MMIO 的 GPA→MR 派发。

#### 2.3.1 PCI 台账分配 GPA

Guest PCI 枚举时看到 BAR2=32KB（来自 wmask），分配 GPA `0x8000_200000` 并写入 BAR 寄存器。QEMU 收到写操作后，`pci_update_mappings` 记录 GPA：

**`hw/pci/pci.c:1511-1553`**:

```c
r->addr = 0x8000_200000;   // ← GPA 记录在 PCIIORegion 台账中
memory_region_add_subregion_overlap(
    r->address_space,       // GPEX io_mmio
    0x00200000,             // GPA offset = 0x8000_200000 - base_mmio
    r->memory,              // → bar->mr (容器, 含 region.mem)
    1);
```

#### 2.3.2 MR 树：有 IO 层，没有 ram_device 层

`bar->mr` 挂入 GPEX io_mmio 后，MR 树包含两层：

```
GPEX io_mmio.subregions:
  bar->mr [offset=0x00200000, priority=1, IO, 32KB]
    └── region.mem [IO, ops=vfio_region_ops, ram=false]
         (无 mmaps[0].mem — mmap 失败时不会创建)
```

#### 2.3.3 FlatView：有 IO section，但 mr->ram=false

FlatView 展平后，该 GPA 区间有一个 IO 类型的 section：

```
FlatView.ranges[]:
  Section[S]: GPA [0x8000_200000, 0x8000_207fff], 32KB
              mr = region.mem
              mr->ram = false     ← IO 类型!
              mr->ops = vfio_region_ops
```

#### 2.3.4 KVM memslot 和 QEMU KVMSlot：都不创建

KVM listener 处理 FlatView 变化时，`kvm_set_phys_mem` 对 IO section 直接跳过：

**`accel/kvm/kvm-all.c:1338-1342`**:

```c
if (!memory_region_is_ram(mr)) {   // mr->ram = false → 跳过!
    return;                         // 不创建 QEMU KVMSlot
                                    // 不发出 ioctl
                                    // 不创建 KVM memslot
}
```

**结论**：

| 层 | BAR2 GPA 存在? | 说明 |
|---|---|---|
| PCI 台账 `r->addr` | **是** (0x8000_200000) | Guest 写入后 pci_update_mappings 记录 |
| MR 树 `bar->mr` | **是** (IO 类型) | 挂入 GPEX io_mmio, 含 region.mem |
| FlatView section | **是** (IO, mr->ram=false) | 用于 QEMU MMIO 派发 |
| QEMU KVMSlot | **否** | mr->ram=false → kvm_set_phys_mem 跳过 |
| KVM memslot | **否** | 同上, ioctl 未发出 |
| KVM S2 PTE | **否** | 无 memslot → S2 无映射 |

#### 2.3.5 GPA 在 MMIO 仿真中怎么用

当 Guest 访问 BAR2 → S2 缺页 → VM exit：

```
KVM [EL2]:
  CPU 硬件填写 HPFAR = 故障 IPA = GPA 0x8000_200300
  → ISV=0 → KVM_EXIT_ARM_NISV → GPA 传给 QEMU (arm_nisv.fault_ipa)

  如果 ISV=1 (单寄存器 ldr):
  → KVM_EXIT_MMIO → GPA 填入 kvm_run->mmio.phys_addr

QEMU [EL0]:
  收到 GPA → address_space_rw(GPA) → 查 FlatView
  → 找到 Section: [0x8000_200000, 32KB, mr=region.mem]
  → vfio_region_ops.read() → vfio_region_read()
  → pread(VFIO_fd, ..., fd_offset + 0x300) → 内核读设备
```

**GPA 虽然不在 memslot/S2 中，但存于台账和 FlatView——这是 QEMU MMIO 慢路径派发的关键。**

### 2.4 单寄存器 ldr 的 MMIO 仿真路径 (ISV=1)

在理解 ldp 为什么崩溃之前，先看一个正常工作的 MMIO 仿真路径：假设 Guest 执行的不是 `ldp`，而是普通的 `ldr x0, [x3]`（8 字节单寄存器读），S2 缺页时：

```
Guest [EL1]: ldr x0, [x3]  (x3 = io_base + 0x300)
  → GVA → GPA (Guest S1 ✓) → S2 缺页 → VM exit

KVM [EL2]: io_mem_abort()
  → ISV=1 → 解码 ESR_EL2:
      is_write=false, len=8, rt=x0
  → kvm_io_bus_read 失败 (VFIO 设备不在 KVM_MMIO_BUS 上)
  → 构造 KVM_EXIT_MMIO: {GPA=0x8000_200300, len=8, is_read}
  → 返回 QEMU

QEMU [EL0]:
  → address_space_rw(GPA) → 查 FlatView → 找到 region.mem
  → vfio_region_ops.read() → vfio_region_read()
  → pread(VFIO_fd, buf, 8, fd_offset+0x300) //关键就是要找到这个GPA对应的VFIO的fd传给host内核
    → syscall → Host 内核 VFIO 驱动 → ioremap 读设备 → 返回数据
```

**QEMU 侧的 ops 注册**（`hw/vfio/helpers.c:260`）:

```c
const MemoryRegionOps vfio_region_ops = {
    .read = vfio_region_read,
    .write = vfio_region_write,
    .valid = {
        .min_access_size = 1,
        .max_access_size = 8,     // ← 最大只支持 8 字节!
    },
};
```

**`vfio_region_read`**（`hw/vfio/helpers.c:210`）:

```c
uint64_t vfio_region_read(void *opaque, hwaddr addr, unsigned size)
{
    VFIORegion *region = opaque;
    union { uint8_t byte; uint16_t word; uint32_t dword; uint64_t qword; } buf;

    if (pread(vbasedev->fd, &buf, size, region->fd_offset + addr) != size)
        return (uint64_t)-1;

    switch (size) {
    case 8:  return le64_to_cpu(buf.qword);    // 8 字节 ✅
    // ...
    default: hw_error("unsupported read size"); // >8 字节 ❌
    }
}
```

**关键限制**: `max_access_size = 8` → VFIO 慢路径只支持 1~8 字节。ldr (8 字节) 可通过 pread 完成。ldp (16 字节) 在进入 QEMU 之前就被 KVM 拦截（ISV=0），根本走不到这里。

KVM [EL2]: kvm_handle_mmio_return()
  → vcpu_set_reg(vcpu, x0, data)   ← 写回 Guest x0
  → kvm_incr_pc(vcpu)              ← 跳过已仿真的 ldr
  → Guest 继续执行 ✅
```

**关键**: ISV=1 意味着 KVM 能从 ESR_EL2 解码出完整的指令信息（方向、大小、目标寄存器），从而构造有效的 MMIO 请求交给 QEMU。QEMU 通过 pread/pwrite 慢路径完成设备访问，再把结果写回 Guest 寄存器。

### 2.5 ldp 128-bit 指令 ISV=0 → 无法 MMIO 仿真 → SEA

崩溃发生在 `qm_mb_read` 读取 mailbox 寄存器时。该函数使用 ARM64 inline asm `ldp` 做 128-bit 原子读：

**`drivers/crypto/hisilicon/qm.c:633`**:

```c
asm volatile("ldp %0, %1, %3\n"
             "stp %0, %1, %2\n"
             : "=&r" (tmp0), "=&r" (tmp1), "+Q" (mailbox)
             : "Q" (*((char __iomem *)fun_base))
             : "memory");
```

`ldp` 是双寄存器加载指令，一次读 16 字节（128-bit）。对于 S2 缺页触发的 Data Abort：

- CPU 写入 ESR_EL2 的 ISV=0 —— ARM 规范下 ldp/stp 等多寄存器操作的 syndrome 格式无法完整描述两个目标寄存器
- KVM 无法解码指令 → 不知道是读还是写、多大、哪个寄存器
- 无法构造 MMIO 请求 → 只能返回 KVM_EXIT_ARM_NISV
- QEMU 收到 NISV → 注入 SEA → Guest panic

**对比 2.4 的 ldr 路径**: ldr 的 ISV=1 让整个 MMIO 仿真链路畅通。ldp 的 ISV=0 在第一关 KVM 就被拦截——连 MMIO 请求都构造不出来，更不可能走到 QEMU 的 pread/pwrite 慢路径。hisi_qm 驱动固定用 `ldp` 做 128-bit 原子读，无法改成单寄存器操作。

### 2.6 完整故障链

```
hisi_acc_get_resource_len: bar_len>>1 = 32KB
  → Guest 看到 BAR2=32KB (wmask)
  → QEMU mmap 失败 (32KB < 64KB PAGE_SIZE)
  → 无 ram_device MR → KVM 不建 memslot → S2 无映射
  → Guest ldp 访问 mailbox → S2 Translation Fault
  → ISV=0 → KVM_EXIT_ARM_NISV → QEMU 注入 SEA
  → Guest kernel panic
```

### 2.7 为什么 vfio-pci 正常

通用 vfio-pci 不截断 BAR2 → `VFIO_DEVICE_GET_REGION_INFO` 返回 64KB → QEMU mmap 64KB = PAGE_SIZE → 成功 → ram_device MR → KVM memslot → S2 映射 → ldp 通过 S2 直达硬件。

---

## 3. 三条 MMIO 访问路径对比

Guest 对 BAR2 的访问有三种可能路径，取决于 S2 映射状态和指令类型：

| | 路径1: S2 直达 | 路径2: QEMU 慢路径仿真 | 路径3: ISV=0 失败 |
|---|---|---|---|
| 条件 | S2 有映射 (ram_device) | S2 无映射 + ISV=1 | S2 无映射 + ISV=0 |
| VM exit? | 无（硬件直达） | 有 | 有 |
| QEMU 参与? | 无 | 有 (pread/pwrite) | 无法参与 |
| 指令要求 | 任意 | 单寄存器 (≤8B) | ldp/stp 等 |
| 性能 | 最快 | 慢 (EL2→EL0→EL2) | 崩溃 |
| 本场景 | vfio-pci | — | hisi_acc (ldp) |

**hisi_acc 场景走了路径3**: S2 无映射 + ldp ISV=0 → 无法仿真 → SEA。

---

## 4. 修复方案

### 4.1 推荐方案：修改 hisi_acc_vfio_pci_mmap 检查

在 mmap 检查中将 `hisi_acc_get_resource_len` 返回值 ALIGN 到 PAGE_SIZE：

**`drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c:1382`**:

```c
if (index == VFIO_PCI_BAR2_REGION_INDEX) {
    end = hisi_acc_get_resource_len(vdev, index);
    end = ALIGN(end, PAGE_SIZE);          // 修复: 32KB → 64KB
    req_len = vma->vm_end - vma->vm_start;  // = 64KB (内核 PAGE_SIZE 对齐)
    if (req_start + req_len > end)         // 0 + 64KB > 64KB → false
        return -EINVAL;
}
```

**修复效果**：

```
修复前: end=32KB, req_len=64KB → 64KB > 32KB → mmap 拒绝
修复后: end=64KB, req_len=64KB → 64KB = 64KB → mmap 通过
  → ram_device MR 创建 → KVM memslot → S2 建立
  → Guest ldp 直接 S2 访问 → 正常
```

**注意**: 此修复只解决了 mmap 检查——让 ram_device MR 和 S2 能建立。但 Guest 仍然从 BAR wmask 读到的 BAR2=32KB（因为 `hisi_acc_get_resource_len` 本身仍返回 32KB）。单 VF 场景无影响——BAR2 独占一个 64KB 页，不会与其他 BAR 重叠。多 VF 场景则需要额外处理（见第3篇）。

### 4.2 替代方案

**方案A**: 修改 `hisi_acc_get_resource_len` 本身 `ALIGN` 返回值（同时影响 VFIO_DEVICE_GET_REGION_INFO → Guest 看到 64KB）

**方案B**: 使用 PF_CTRL 迁移模式（迁移寄存器移到 PF BAR2）→ 无需截断 VF BAR2

---

## 5. 涉及的关键源码

| 文件 | 行号 | 内容 |
|------|------|------|
| `drivers/crypto/hisilicon/qm.c` | 633 | `qm_mb_read` — `ldp` inline asm 128-bit 读 |
| `drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c` | 1335 | `hisi_acc_get_resource_len` — `bar_len>>1` 截断 |
| `drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c` | 1382 | `hisi_acc_vfio_pci_mmap` — mmap 范围检查 |
| `arch/arm64/kvm/mmio.c` | 182 | `io_mem_abort` — ISV=0 分支 → NISV |
| `hw/vfio/pci.c` | 1785 | `vfio_bar_register` — MR 创建 + mmap |
| `hw/vfio/helpers.c` | 258 | `vfio_region_ops.valid.max_access_size = 8` |
| `accel/kvm/kvm-all.c` | 266 | `kvm_align_section` — 32KB 返回 0, 不建 memslot |
