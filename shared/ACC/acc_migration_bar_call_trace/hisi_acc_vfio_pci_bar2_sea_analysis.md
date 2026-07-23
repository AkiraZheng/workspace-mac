# hisi_acc_vfio_pci 绑定加速器 VF 后 hisi_zip 加载 SEA 崩溃分析报告

## 1. 问题描述

使用 `hisi_acc_vfio_pci` 驱动绑定加速器 VF 透传给虚拟机后，在虚拟机内 `insmod hisi_zip.ko` 触发 Synchronous External Abort (SEA)，导致 kernel panic。而使用通用 `vfio-pci` 驱动绑定时，驱动可正常加载。

## 2. 现象对比

### 2.1 崩溃场景（hisi_acc_vfio_pci 绑定）

```
root@localhost:/# insmod hisi_zip.ko uacce_mode=1 pf_q_num=32
[   20.945397] No device found currently, suppose queue number is 1024
[   20.946092] hisi_zip 0000:00:01.0: enabling device (0000 -> 0002)
qemu-system-aarch64: VFIO_MAP_DMA failed: Bad address
qemu-system-aarch64: vfio_container_dma_map(0xaaac37156b50, 0x8000000000, 0x200000, 0xfffd31c00000) = -14 (Bad address)
[   20.947036] kernelspace, addr: 0xffff800080ca0300 comm: insmod
[   20.948088] Internal error: synchronous external abort: 0000000096000010 [#1] SMP
[   20.958661] pc : hisi_qm_wait_mb_ready+0x44/0xc8 [hisi_qm]
[   20.959215] lr : qm_mb_nolock+0x30/0x158 [hisi_qm]
...
[   20.967098] Call trace:
[   20.967380]  hisi_qm_wait_mb_ready+0x44/0xc8 [hisi_qm]
[   20.967905]  qm_mb_nolock+0x30/0x158 [hisi_qm]
[   20.968369]  hisi_qm_mb_read+0x6c/0xc8 [hisi_qm]
[   20.968848]  qm_get_vft_v2+0x44/0x98 [hisi_qm]
[   20.969317]  qm_get_pci_res+0x1ac/0x310 [hisi_qm]
[   20.969813]  hisi_qm_pci_init+0x40/0x248 [hisi_qm]
[   20.970309]  hisi_qm_init+0x28/0x170 [hisi_qm]
[   20.970772]  hisi_zip_qm_init+0x98/0x258 [hisi_zip]
[   20.971275]  hisi_zip_probe+0x58/0x3b8 [hisi_zip]
[   20.982512] ---[ end trace 0000000000000000 ]---
[   20.982989] Kernel panic - not syncing: synchronous external abort: Fatal exception
```

PCI 枚举信息（关键行）：
```
pci 0000:00:01.0: reg 0x18: [mem 0x8000200000-0x8000207fff 64bit pref]   ← BAR2 = 32KB
pci 0000:00:01.0: reg 0x20: [mem 0x8000000000-0x80001fffff 64bit pref]   ← BAR4 = 2MB
pci 0000:00:01.0: BAR 4: assigned [mem 0x8000000000-0x80001fffff 64bit pref]
pci 0000:00:01.0: BAR 2: assigned [mem 0x8000200000-0x8000207fff 64bit pref]
```

### 2.2 正常场景（通用 vfio-pci 绑定）

```
root@localhost:/# insmod hisi_zip.ko uacce_mode=1 pf_q_num=32
[  240.852617] No device found currently, suppose queue number is 1024
[  240.853380] hisi_zip 0000:00:01.0: enabling device (0000 -> 0002)
qemu-system-aarch64: VFIO_MAP_DMA failed: Bad address
qemu-system-aarch64: vfio_container_dma_map(...0x8000200000, 0x10000...) = -14 (Bad address)
qemu-system-aarch64: VFIO_MAP_DMA failed: Bad address
qemu-system-aarch64: vfio_container_dma_map(...0x8000000000, 0x200000...) = -14 (Bad address)
[  240.855188] hisi_zip 0000:00:01.0: iommu not support sva!
[  240.855696] hisi_zip 0000:00:01.0: fail to alloc uacce (-22)
```

PCI 枚举信息（关键行）：
```
pci 0000:00:01.0: reg 0x18: [mem 0x8000200000-0x800020ffff 64bit pref]   ← BAR2 = 64KB
pci 0000:00:01.0: reg 0x20: [mem 0x8000000000-0x80001fffff 64bit pref]   ← BAR4 = 2MB
```

### 2.3 关键差异

| 项目 | hisi_acc_vfio_pci | vfio-pci |
|------|-------------------|----------|
| BAR2 报告大小 | **32KB** | **64KB** |
| BAR2 vs HOST PAGE_SIZE | 32KB < 64KB | 64KB = 64KB |
| QEMU mmap BAR2 | **失败** | 成功 |
| KVM stage-2 映射 | **无** | 有 |
| ldp 访问 mailbox | **SEA 崩溃** | 正常 |
| VFIO_MAP_DMA 报错 | 有 | 有 |
| 驱动加载结果 | **kernel panic** | 正常（uacce 报错但不崩溃） |

## 3. VF BAR2 空间分布

### 3.1 BAR2 寄存器布局

根据内核头文件 `include/linux/hisi_acc_qm.h` 和 `drivers/crypto/hisilicon/qm.c` 中的寄存器定义，VF BAR2 的完整空间布局如下：

```
Offset     寄存器                        说明
─────────────────────────────────────────────────────────────────
0x00000    VF 中断寄存器
0x00000    QM_VF_AEQ_INT_SOURCE         AEQ 中断源
0x00004    QM_VF_AEQ_INT_MASK           AEQ 中断屏蔽
0x00008    QM_VF_EQ_INT_SOURCE          EQ 中断源
0x0000C    QM_VF_EQ_INT_MASK            EQ 中断屏蔽

0x00020    PF-VF 通信寄存器
0x00020    QM_IFC_INT_SOURCE_V          IFC 中断源
0x00024    QM_IFC_INT_MASK              IFC 中断屏蔽
0x00028    QM_IFC_INT_STATUS            IFC 中断状态
0x0002C    QM_IFC_INT_SET_V             IFC 中断设置

0x00030    QM_QUE_ISO_CFG_V             队列隔离配置
0x00034    QM_PAGE_SIZE                 页大小配置
0x00060    QM_VF_STATE                  VF 状态寄存器

0x00200    缓存控制
0x00204    QM_CACHE_WB_START            缓存回写启动
0x00208    QM_CACHE_WB_DONE             缓存回写完成

0x00300    Mailbox 寄存器               ← ★ 崩溃点
0x00300    QM_MB_CMD_SEND_BASE          邮箱命令发送 (128-bit)
0x00304    QM_MB_CMD_DATA_ADDR_L        命令数据地址低32位
0x00308    QM_MB_CMD_DATA_ADDR_H        命令数据地址高32位

0x00310    VF2PF 通信
0x00320    QM_VF2PF_VF_W                VF→PF 写
0x00380    QM_PF2VF_VF_R                PF→VF 读

0x00210    QM_SUB_VERSION_ID            子版本号

0x01000    Doorbell 区域 (V2)
0x01000    QM_DOORBELL_SQ_CQ_BASE_V2    SQ/CQ doorbell 基地址
0x02000    QM_DOORBELL_EQ_AEQ_BASE_V2   EQ/AEQ doorbell 基地址

0x08000    EQC/AEQC 上下文
0x08000    QM_EQC_VF_DW0                EQC DW0-DW6
0x08020    QM_AEQC_VF_DW0               AEQC DW0-DW6

0x08040    ──────────────────────────── 功能区域约 32KB

0x08040 ~ 0x0FFFF    保留 / 对齐填充

0x08000 ~ 0x0FFFF    迁移控制寄存器区域 (VF_CTRL 模式)
                      Host 侧独占，不暴露给 Guest
                      包含:
                      - QM 读写寄存器备份
                      - EQC/AEQC DW 寄存器
                      - 设备状态寄存器
                      - 迁移操作控制

0x10000    ──────────────────────────── BAR2 结束 (64KB)
```

### 3.2 BAR4 寄存器布局

```
Offset     寄存器                        说明
─────────────────────────────────────────────────────────────────
0x00000    Doorbell 隔离区域
           QP doorbell 间隔 = QM_QP_DB_INTERVAL (0x10000 = 64KB per QP)

0x200000   ──────────────────────────── BAR4 结束 (2MB)
```

BAR4 仅在 `QM_SUPPORT_DB_ISOLATION` 能力位使能时使用，每个 QP 的 doorbell 占 64KB 间隔。

### 3.3 PF BAR2 中迁移区域布局（PF_CTRL 模式）

```
Offset     说明
─────────────────────────────────────────────────────────────────
0x180000   QM_MIG_REGION_OFFSET         迁移区域起始
           VF0: 0x180000 ~ 0x181FFF     8KB (QM_MIG_REGION_SIZE)
           VF1: 0x182000 ~ 0x183FFF     8KB
           ...
           VFn: 0x180000 + n*0x2000     每个 VF 占 8KB

0x100198   QM_MIG_REGION_SEL            迁移区域选择寄存器
                                       Bit0 = QM_MIG_REGION_EN
```

## 4. 根因分析

### 4.1 直接原因：BAR2 32KB < HOST PAGE_SIZE 64KB

测试环境 Host 和 Guest 的 PAGE_SIZE 均为 64KB (ARM64)。`hisi_acc_vfio_pci` 在 VF_CTRL 模式下将 VF BAR2 截断为原始大小的一半（64KB → 32KB），导致 BAR2 大小小于 HOST PAGE_SIZE，引发一系列连锁故障。

### 4.2 截断机制

`hisi_acc_vfio_pci` 通过以下路径截断 BAR2：

```c
// drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c:1320-1340
static size_t hisi_acc_get_resource_len(struct vfio_pci_core_device *vdev,
                                        unsigned int index)
{
    struct hisi_acc_vf_core_device *hisi_acc_vdev =
            hisi_acc_drvdata(vdev->pdev);

    if (hisi_acc_vdev->drv_mode == HW_ACC_MIG_VF_CTRL)
        return (pci_resource_len(vdev->pdev, index) >> 1);  // 64KB >> 1 = 32KB
    return pci_resource_len(vdev->pdev, index);
}
```

该函数被 `hisi_acc_vfio_pci_ioctl()` 中的 `VFIO_DEVICE_GET_REGION_INFO` 调用，向 QEMU 报告 BAR2 = 32KB：

```c
// hisi_acc_vfio_pci.c:1435-1446
if (info.index == VFIO_PCI_BAR2_REGION_INDEX) {
    info.size = hisi_acc_get_resource_len(vdev, info.index);  // 32KB
    ...
}
```

同时也通过 `hisi_acc_vfio_pci_mmap()` 限制 mmap 范围：

```c
// hisi_acc_vfio_pci.c:1365-1388
static int hisi_acc_vfio_pci_mmap(struct vfio_device *core_vdev,
                                  struct vm_area_struct *vma)
{
    ...
    if (index == VFIO_PCI_BAR2_REGION_INDEX) {
        end = hisi_acc_get_resource_len(vdev, index);  // 32KB
        req_len = vma->vm_end - vma->vm_start;
        // 内核将 mmap 长度向上对齐到 PAGE_SIZE=64KB，故 req_len=64KB
        if (req_start + req_len > end)   // 0 + 64KB > 32KB → true
            return -EINVAL;              // mmap 被拒绝！
    }
    ...
}
```

### 4.3 完整故障链

```
hisi_acc_vfio_pci VF_CTRL 模式截断 BAR2 (64KB → 32KB)
        │
        ▼
QEMU 调用 VFIO_DEVICE_GET_REGION_INFO 获取 BAR2 大小 = 32KB
        │
        ▼
QEMU 调用 vfio_region_mmap() → mmap(NULL, 32768, ...)
        │
        ├─ 内核 do_mmap() 将 32KB 向上对齐到 PAGE_SIZE=64KB
        │
        └─ hisi_acc_vfio_pci_mmap() 拒绝: 0 + 64KB > 32KB → -EINVAL
        │
        ▼
mmap 失败，region->mmaps[0].mmap = NULL
QEMU 仅有 vfio_region_ops (MMIO 陷阱) 覆盖 BAR2，无 ram_device 子区域
        │
        ▼
vfio_sub_page_bar_update_mapping() 检查 mmap != NULL → 跳过，不扩展
        │
        ▼
KVM 无法为 BAR2 创建 stage-2 映射:
  - 无 ram_device MemoryRegion → 不注册 KVM memslot
  - kvm_align_section() 对 32KB 返回 0 (非页对齐)
        │
        ▼
Guest 内 hisi_zip 驱动 ioremap(BAR2) 后访问 mailbox 寄存器 (offset 0x300)
        │
        ▼
CPU 发出 ldp 指令访问 GPA 0x8000200300
        │
        ├─ Stage-1: Guest 虚拟地址 → Guest 物理地址 0x8000200300 ✓
        │
        └─ Stage-2: 无映射 → Data Abort
                │
                ▼
        KVM 处理: ldp 是 128-bit 操作，ISV=0 (无法解码)
                │
                ▼
        QEMU MMIO 仿真: vfio_region_ops max_access_size=8，不支持 128-bit
                │
                ▼
        故障注入回 Guest 为 Synchronous External Abort (DFSC=0x10)
                │
                ▼
        Guest kernel 无 fixup handler → Kernel Panic
```

### 4.4 对比：通用 vfio-pci 为何正常

通用 `vfio-pci` 不截断 BAR2，QEMU 获取 BAR2 = 64KB = PAGE_SIZE：

1. `mmap(NULL, 65536, ...)` → 请求大小 = PAGE_SIZE → mmap 成功
2. `ram_device` 子区域创建成功
3. `kvm_align_section()` 返回 64KB → KVM 创建 stage-2 映射
4. Guest 的 `ldp` 指令通过 stage-2 映射直接访问物理设备 → 无 VM exit，正常工作
5. `VFIO_MAP_DMA: Bad address` 是 IOMMU DMA 映射问题（BAR4 的 MMIO 空间无法作为 DMA 目标），与 guest 访问设备 MMIO 无关，不影响驱动初始化

### 4.5 VFIO_MAP_DMA: Bad address 的含义

两个场景都出现了此错误，这不是 BAR2 问题的原因，而是一个独立的问题：

```
qemu-system-aarch64: VFIO_MAP_DMA failed: Bad address
```

该错误发生在 `vfio_legacy_dma_map()` (`hw/vfio/container.c:257`)，内核 `ioctl(VFIO_IOMMU_MAP_DMA)` 返回 `errno=EFAULT`。

原因：QEMU 尝试将 VF 的 BAR4（doorbell 区域，MMIO 设备寄存器空间）映射到 IOMMU 作为 DMA 目标。但内核 IOMMU 驱动不允许将设备 MMIO 空间映射为 DMA 目标（因为这不是真实内存），返回 EFAULT。

对于 `vfio_listener_region_add()` 中的 RAM device（即 PCI BAR），这个错误是非致命的——打印 `"PCI p2p may not work"` 后继续。这只影响设备间 P2P DMA，不影响 guest 通过 MMIO 访问设备寄存器。

## 5. QEMU MemoryRegion 类型与 KVM stage-2 映射机制

### 5.1 核心规则：MR 类型决定 stage-2 映射

QEMU 对每个 guest 物理地址区间用一个 `MemoryRegion` 描述，**MR 的类型决定了 KVM 是否为该区间创建 stage-2 映射**：

| MemoryRegion 类型 | `mr->ram` | `mr->ram_device` | 创建 stage-2 映射? | 说明 |
|---|---|---|---|---|
| RAM (普通内存) | true | false | ✓ | guest RAM, 大页等 |
| RAM device (mmap) | true | true | ✓ | VF BAR mmap 后的快速路径 |
| IO (MMIO 陷阱) | false | false | ✗ | VF BAR 未 mmap 时的慢路径 |

KVM 的判断在 `kvm_set_phys_mem()` (`accel/kvm/kvm-all.c:1338`)：

```c
if (!memory_region_is_ram(mr)) {   // mr->ram == false ?
    if (writable || !kvm_readonly_mem_allowed) {
        return;   // ← 直接返回，不为该 MR 注册 KVM memslot
    }
    ...
}
```

`memory_region_is_ram()` 就是检查 `mr->ram`。IO 类型 MR（`mr->ram = false`）被跳过，**不会注册 KVM memslot，也就不会创建 stage-2 页表项**。

RAM device 类型（`mr->ram = true`）通过检查，继续执行 `kvm_set_user_memory_region()`，内核在 stage-2 页表中建立映射。

### 5.2 QEMU 为 VF BAR 创建的两层 MemoryRegion

QEMU 为每个 VF BAR 创建两层 MR，mmap 成功时在 IO 层之上叠加 ram_device 层：

```
mmap 成功时:                                  mmap 失败时:

bar->mr (外层容器, IO 类型)                    bar->mr (外层容器, IO 类型)
  └── region.mem (IO 类型, 慢路径)               └── region.mem (IO 类型, 慢路径) ← 仅此一层
        ├── mmaps[0].mem (ram_device 类型) ✓           (无 ram_device 子区域) ✗
        └── mmaps[1].mem (ram_device 类型) ✓
```

创建过程在 `vfio_bar_register()` (`hw/vfio/pci.c:1785`)：

```c
// 第1步: 创建外层容器 (IO 类型, mr->ram = false)
memory_region_init_io(bar->mr, OBJECT(vdev), NULL, NULL, name, bar->size);

// 第2步: 添加内层 region.mem (IO 类型, mr->ram = false)
// region.mem 在 vfio_region_setup() 中通过 memory_region_init_io() 创建
memory_region_add_subregion(bar->mr, 0, bar->region.mem);

// 第3步: 尝试 mmap，成功则叠加 ram_device 子区域
if (vfio_region_mmap(&bar->region)) {
    error_report("Failed to mmap ... Performance may be slow");  // 只打警告
}
```

`vfio_region_mmap()` 内部 (`hw/vfio/helpers.c:414-446`)：

```c
region->mmaps[i].mmap = mmap(NULL, region->mmaps[i].size, ...);
if (region->mmaps[i].mmap == MAP_FAILED) {
    region->mmaps[i].mmap = NULL;    // ← 标记为 NULL
    // 清理之前的 mmap，返回错误
    return ret;
}
// mmap 成功才创建 ram_device 子区域
memory_region_init_ram_device_ptr(&region->mmaps[i].mem, ...);  // mr->ram = true
```

**关键点**：ram_device 子区域只有 mmap 成功才会创建。mmap 失败时，`region->mmaps[i].mmap = NULL`，不会调用 `memory_region_init_ram_device_ptr()`，所以只有 IO 类型的 `region.mem` 存在。

### 5.3 两种路径对 guest 访问的影响

```
mmap 成功 (ram_device 子区域存在):

  Guest 访问 BAR 地址
    → Stage-2 命中 (ram_device 注册了 KVM memslot)
    → 直接访问 host mmap 的物理页，无 VM exit
    → ldp 128-bit 操作正常执行
    → 速度最快

mmap 失败 (只有 IO 类型 region.mem):

  Guest 访问 BAR 地址
    → Stage-2 无映射 (IO 类型不注册 KVM memslot)
    → 触发 Data Abort → VM exit 到 KVM
    → KVM 解析指令:
        - 普通 4/8 字节读写: ISV=1, 可解析
          → KVM 转发到 QEMU → vfio_region_read/write (pread/pwrite) → 正常
        - ldp 128-bit 操作: ISV=0, 无法解析
          → 无法转发到 QEMU 仿真
          → 注入 SEA 回 guest → panic
```

注意：即使 mmap 失败，如果是普通的 4 字节或 8 字节 MMIO 读写，KVM 仍然可以 trap 到 QEMU 通过 `vfio_region_ops` 的 `pread/pwrite` 完成。崩溃的根本原因是 **ldp 是 128-bit 操作**，超出了 KVM 指令解析能力和 QEMU `vfio_region_ops`（`max_access_size=8`）的仿真范围。

### 5.4 KVM 为什么无法仿真 128-bit ldp

当 guest 访问的地址在 stage-2 无映射时，CPU 触发 Data Abort 并退出到 KVM。KVM 通过读取 ESR_EL2（Exception Syndrome Register）中的 ISS（Instruction Specific Syndrome）来解析引起异常的指令信息。

#### 5.4.1 ISV 位：CPU 是否能提供指令解码信息

ESR_EL2.ISS 的 bit[24] 是 **ISV (Instruction Specific Valid)** 位：

```c
// arch/arm64/include/asm/esr.h:135-136
#define ESR_ELx_ISV_SHIFT  (24)
#define ESR_ELx_ISV        (UL(1) << ESR_ELx_ISV_SHIFT)
```

- **ISV=1**：CPU 成功解码了引起 Data Abort 的指令，ISS 中包含了完整的指令信息（访问大小、目标寄存器、符号扩展等）
- **ISV=0**：CPU 无法解码该指令，ISS 中不包含有效指令信息

ARM 架构规范规定，以下情况 ISV=0：
- 引起异常的指令不支持 syndrome 信息解码
- **多寄存器 load/store 指令（如 ldp、stp）—— 128-bit 原子访问**
- 某些原子操作指令
- 对 device 内存属性的访问（某些实现）

#### 5.4.2 KVM 的处理逻辑

`io_mem_abort()` (`arch/arm64/kvm/mmio.c:168`) 是 KVM 处理 MMIO Data Abort 的入口：

```c
int io_mem_abort(struct kvm_vcpu *vcpu, phys_addr_t fault_ipa)
{
    // 检查 ISV 位
    if (!kvm_vcpu_dabt_isvalid(vcpu)) {    // ISV == 0 ?
        // ISV=0: 无法解析指令
        if (test_bit(KVM_ARCH_FLAG_RETURN_NISV_IO_ABORT_TO_USER,
                     &vcpu->kvm->arch.flags)) {
            // 方案A: 返回用户空间 (QEMU) 处理
            run->exit_reason = KVM_EXIT_ARM_NISV;
            run->arm_nisv.esr_iss = kvm_vcpu_dabt_iss_nisv_sanitized(vcpu);
            run->arm_nisv.fault_ipa = fault_ipa;
            return 0;
        }
        // 方案B: 无法处理, 返回错误
        kvm_pr_unimpl("Data abort outside memslots with no valid syndrome info\n");
        return -ENOSYS;
    }

    // ISV=1: 正常解码指令信息
    is_write = kvm_vcpu_dabt_iswrite(vcpu);   // 读写方向
    len = kvm_vcpu_dabt_get_as(vcpu);          // 访问大小
    rt = kvm_vcpu_dabt_get_rd(vcpu);           // 目标寄存器
    ...
}
```

**关键点**：当 ISV=0（如 ldp 128-bit）时，KVM 无法获取访问大小（len）和目标寄存器（rt），无法构造 MMIO 请求转发给 QEMU。

#### 5.4.3 SAS 字段最大支持 8 字节

即使 ISV=1，ESR 中的 **SAS (Synch Abort Size)** 字段也只有 2 bits，最多编码 4 种大小：

```c
// arch/arm64/include/asm/esr.h:137-138
#define ESR_ELx_SAS_SHIFT  (22)
#define ESR_ELx_SAS        (UL(3) << ESR_ELx_SAS_SHIFT)   // 2 bits
```

SAS 编码：

| SAS | 访问大小 |
|-----|---------|
| 00  | 1 字节  |
| 01  | 2 字节  |
| 10  | 4 字节  |
| 11  | 8 字节  |

**没有 16 字节（128-bit）的编码**。KVM 解码访问大小的函数也验证了这一点：

```c
// arch/arm64/include/asm/kvm_emulate.h:400-403
static __always_inline unsigned int kvm_vcpu_dabt_get_as(const struct kvm_vcpu *vcpu)
{
    return 1 << ((kvm_vcpu_get_esr(vcpu) & ESR_ELx_SAS) >> ESR_ELx_SAS_SHIFT);
    // SAS=0→1字节, SAS=1→2字节, SAS=2→4字节, SAS=3→8字节, 无128-bit
}
```

KVM 的 MMIO 读写缓冲区也只支持到 8 字节：

```c
// arch/arm64/kvm/mmio.c:15-44
void kvm_mmio_write_buf(void *buf, unsigned int len, unsigned long data)
{
    switch (len) {
    case 1: ... break;
    case 2: ... break;
    case 4: ... break;
    case 8: ... break;
    // 没有 case 16!
    }
}

// arch/arm64/kvm/mmio.c:47-75
unsigned long kvm_mmio_read_buf(const void *buf, unsigned int len)
{
    switch (len) {
    case 1: ... break;
    case 2: ... break;
    case 4: ... break;
    case 8: ... break;
    // 没有 case 16!
    }
}
```

#### 5.4.4 QEMU 侧的处理：注入 SEA

当 KVM 无法处理 ISV=0 的 Data Abort 时，通过 `KVM_EXIT_ARM_NISV` 退出到 QEMU。QEMU 的处理在 `kvm_arm_handle_dabt_nisv()` (`target/arm/kvm.c:1268`)：

```c
static int kvm_arm_handle_dabt_nisv(CPUState *cs, uint64_t esr_iss,
                                    uint64_t fault_ipa)
{
    ARMCPU *cpu = ARM_CPU(cs);
    CPUARMState *env = &cpu->env;

    if (cap_has_inject_ext_dabt) {
        // 向 guest 注入外部 Data Abort (SEA)
        struct kvm_vcpu_events events = { };
        events.exception.ext_dabt_pending = 1;
        if (!kvm_vcpu_ioctl(cs, KVM_SET_VCPU_EVENTS, &events)) {
            env->ext_dabt_raised = 1;
            return 0;     // 成功注入 SEA, guest 会收到 Synchronous External Abort
        }
    } else {
        // 无法注入, 报错
        error_report("Data abort exception triggered by guest memory access "
                     "at physical address: 0x" TARGET_FMT_lx, fault_ipa);
        error_printf("KVM unable to emulate faulting instruction.\n");
    }
    return -1;
}
```

**QEMU 也无法仿真 128-bit ldp**，只能向 guest 注入一个 SEA。Guest kernel 收到 SEA 后尝试查找 fixup handler，但 `hisi_qm_wait_mb_ready` 中的 `ldp` 没有 fixup，最终触发 kernel panic。

#### 5.4.5 完整的 128-bit 仿真失败路径

```
Guest 执行 ldp x0, x1, [x3]  (x3 = io_base + 0x300, 128-bit 读)
  │
  ▼
Stage-2 无映射 → CPU 触发 Data Abort, 退出到 EL2 (KVM)
  │
  ├─ CPU 填写 ESR_EL2:
  │    ISV = 0  (ldp 128-bit 无法提供指令 syndrome)
  │    DFSC = 0x10 (Translation fault, level 0)  ← 日志中 96000010 的低 6 bits
  │
  ▼
KVM io_mem_abort() 检查 ISV == 0
  │
  ├─ ISV=0 → 无法解析指令信息 (len, rt, is_write 全部未知)
  │
  ▼
KVM 通过 KVM_EXIT_ARM_NISV 退出到 QEMU
  │
  ▼
QEMU kvm_arm_handle_dabt_nisv()
  │
  ├─ cap_has_inject_ext_dabt = true
  │   → KVM_SET_VCPU_EVENTS: ext_dabt_pending = 1
  │   → 向 guest 注入 SEA (Synchronous External Abort)
  │
  ▼
Guest 收到 SEA (DFSC=0x10)
  │
  ├─ hisi_qm_wait_mb_ready() 没有 fixup handler (不在 .fixup 段)
  │
  ▼
Kernel panic: "synchronous external abort: Fatal exception"
```

#### 5.4.6 对比：普通 4/8 字节 MMIO 可以正常仿真

如果是普通 `ldr x0, [x3]`（8 字节读）触发 stage-2 缺页：

```
Guest 执行 ldr x0, [x3]  (8 字节读)
  │
  ▼
Stage-2 无映射 → Data Abort → KVM
  │
  ├─ ESR_EL2: ISV=1 (CPU 可以解码 ldr)
  │   SAS=11 (8 字节), SRT=x0, WNR=0 (读)
  │
  ▼
KVM io_mem_abort() 正常解析:
  len = kvm_vcpu_dabt_get_as() = 8
  rt = kvm_vcpu_dabt_get_rd() = x0
  is_write = false
  │
  ▼
KVM 通过 KVM_EXIT_MMIO 退出到 QEMU
  run->mmio.phys_addr = fault_ipa
  run->mmio.len = 8
  run->mmio.is_write = false
  │
  ▼
QEMU address_space_rw() → vfio_region_read() → pread(VFIO fd, 8)
  │
  ▼
KVM 处理返回值, 写回 x0, 继续执行 guest
```

### 5.5 本场景的完整因果链

```
hisi_acc_vfio_pci VF_CTRL 模式截断 BAR2 (64KB → 32KB)
  → QEMU mmap(32KB) → 内核对齐到 64KB → hisi_acc_vfio_pci_mmap() 拒绝
  → mmap 失败, 打印 "Failed to mmap ... Performance may be slow"
  → 无 ram_device 子区域, 只有 IO 类型 region.mem
  → KVM kvm_set_phys_mem(): mr->ram == false → 跳过, 不建 stage-2
  → guest ldp 访问 BAR2 → stage-2 缺页 → VM exit
  → KVM 无法处理 128-bit ldp (ISV=0)
  → 注入 SEA → panic
```

而通用 `vfio-pci`：

```
通用 vfio-pci 不截断 BAR2 (64KB)
  → QEMU mmap(64KB) → 64KB = PAGE_SIZE → mmap 成功
  → 创建 ram_device 子区域 (mr->ram = true)
  → KVM kvm_set_phys_mem(): mr->ram == true → 注册 KVM memslot → 建 stage-2
  → guest ldp 访问 BAR2 → stage-2 命中 → 直接访问物理设备
  → 无 VM exit, 正常工作
```

## 6. 定位推理过程：如何从日志确定 BAR2 有问题

### 6.1 第1步：从 call trace 定位崩溃访问的是哪个 BAR

call trace 显示崩溃发生在 `hisi_qm_wait_mb_ready` → `qm_mb_read`，该函数访问的地址是：

```c
// drivers/crypto/hisilicon/qm.c:630
const void __iomem *fun_base = qm->io_base + QM_MB_CMD_SEND_BASE; // 0x300
```

`qm->io_base` 来自哪里？追踪 `qm_get_pci_res()` 函数：

```c
// drivers/crypto/hisilicon/qm.c:5896-5897
qm->phys_base = pci_resource_start(pdev, PCI_BAR_2);  // ← BAR2!
qm->io_base = ioremap(qm->phys_base, pci_resource_len(pdev, PCI_BAR_2));
```

同时从崩溃寄存器可以交叉验证：

```
x3 = ffff800080ca0300    // 这是崩溃时的访问地址
```

`ffff800080ca0000` 是 `io_base`（ioremap 返回的虚拟地址），`0x300` 是 `QM_MB_CMD_SEND_BASE` 偏移，所以 `x3 = io_base + 0x300`，与代码完全吻合。

**结论：崩溃时访问的是 BAR2 偏移 0x300 的 mailbox 寄存器。**

### 6.2 第2步：从 PCI 日志计算 BAR2 大小

PCI 配置空间中 BAR 寄存器的偏移是固定的（PCI 规范定义）：

| 配置空间偏移 | BAR 编号 | 说明 |
|---|---|---|
| 0x10 | BAR0 | |
| 0x14 | BAR1 | |
| 0x18 | **BAR2** | ← `reg 0x18` |
| 0x1c | BAR3 | |
| 0x20 | **BAR4** | ← `reg 0x20` |
| 0x24 | BAR5 | |

因此日志中的 `reg 0x18` 就是 BAR2，`reg 0x20` 就是 BAR4。

**崩溃场景 BAR2 大小计算：**

```
reg 0x18: [mem 0x8000200000-0x8000207fff]
BAR2 = end - start + 1
     = 0x8000207fff - 0x8000200000 + 1
     = 0x7fff + 1
     = 0x8000
     = 32768 bytes
     = 32KB
```

**正常场景 BAR2 大小计算：**

```
reg 0x18: [mem 0x8000200000-0x800020ffff]
BAR2 = end - start + 1
     = 0x800020ffff - 0x8000200000 + 1
     = 0xffff + 1
     = 0x10000
     = 65536 bytes
     = 64KB
```

**BAR4 大小计算（两个场景相同）：**

```
reg 0x20: [mem 0x8000000000-0x80001fffff]
BAR4 = end - start + 1
     = 0x80001fffff - 0x8000000000 + 1
     = 0x1fffff + 1
     = 0x200000
     = 2097152 bytes
     = 2MB
```

**对比结果：**

| BAR | 崩溃场景 | 正常场景 | 差异 |
|-----|---------|---------|------|
| BAR2 | 32KB (0x8000) | 64KB (0x10000) | **差 2 倍** |
| BAR4 | 2MB (0x200000) | 2MB (0x200000) | 相同 |

两个场景唯一的硬件可见差异就是 BAR2：32KB vs 64KB。

### 6.3 第3步：从代码找到 BAR2 被截断的原因

BAR2 大小差 2 倍（32KB vs 64KB），直接联想到 `hisi_acc_vfio_pci` 的截断逻辑：

```c
// drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c:1332
if (hisi_acc_vdev->drv_mode == HW_ACC_MIG_VF_CTRL)
    return (pci_resource_len(vdev->pdev, index) >> 1);  // 右移1位 = 除以2
```

计算验证：

```
pci_resource_len(BAR2) = 64KB (物理 BAR2 大小)
64KB >> 1 = 32KB                          ← 与崩溃场景日志中的 32KB 完全吻合！
```

而通用 `vfio-pci` 驱动没有这个截断逻辑，直接返回 `pci_resource_len()` 的原始值 64KB。

### 6.4 第4步：32KB 为什么致命 —— 与 PAGE_SIZE 的关系

测试环境为 ARM64，HOST PAGE_SIZE = 64KB。关键不等式：

```
BAR2 报告大小 = 32KB < HOST PAGE_SIZE = 64KB
```

这导致 QEMU mmap BAR2 时失败，推导如下：

1. QEMU 调用 `mmap(NULL, 32768, ...)` 请求映射 32KB 的 BAR2
2. 内核 `do_mmap()` 将请求长度向上对齐到 PAGE_SIZE = 64KB，实际 VMA 大小 = 64KB
3. `hisi_acc_vfio_pci_mmap()` 校验：
   ```
   end = 32KB (hisi_acc_get_resource_len 返回值)
   req_len = 64KB (VMA 实际大小)
   req_start + req_len > end  →  0 + 64KB > 32KB  →  true  →  return -EINVAL
   ```
4. mmap 失败 → 无 ram_device 子区域 → KVM 不创建 stage-2 映射
5. Guest 的 `ldp` 指令访问 `io_base + 0x300` → stage-2 缺页 → SEA

而在正常场景（BAR2 = 64KB = PAGE_SIZE）：

```
mmap(NULL, 65536, ...) → 请求大小 = PAGE_SIZE → VMA = 64KB
req_start + req_len > end  →  0 + 64KB > 64KB  →  false  →  mmap 成功
```

### 6.5 推理链总结

```
call trace: pc = hisi_qm_wait_mb_ready+0x44
    │
    ├─ 崩溃函数访问 qm->io_base + 0x300 (QM_MB_CMD_SEND_BASE)
    │
    └─ qm->io_base = ioremap(pci_resource_start(pdev, BAR2))
    │                                                ↑
    │                                    崩溃位置在 BAR2 内
    │
    ▼
PCI 日志: reg 0x18 = BAR2
    │
    ├─ 崩溃场景: 0x8000207fff - 0x8000200000 + 1 = 0x8000 = 32KB
    ├─ 正常场景: 0x800020ffff - 0x8000200000 + 1 = 0x10000 = 64KB
    │
    └─ BAR2 大小差 2 倍，BAR4 完全相同 → 问题锁定在 BAR2
    │
    ▼
代码: hisi_acc_get_resource_len() 中 >> 1 截断
    │
    ├─ 64KB >> 1 = 32KB，与崩溃场景日志完全吻合
    │
    └─ 通用 vfio-pci 无此截断，BAR2 保持 64KB
    │
    ▼
根因: 32KB < PAGE_SIZE(64KB) → mmap 失败 → KVM stage-2 无映射 → SEA
```

## 7. 关键代码路径分析

### 7.1 崩溃路径

```
hisi_zip_probe()                              // drivers/crypto/hisilicon/zip/zip_main.c
  → hisi_zip_qm_init()                        // 初始化 QM
    → hisi_qm_init()                          // qm.c
      → hisi_qm_pci_init()                    // qm.c
        → qm_get_pci_res()                    // qm.c:5884
          → ioremap(BAR2)                     // 映射 BAR2 0x8000200000-0x8000207fff (32KB)
          → qm_get_qp_num()                   // 获取队列对数量
            → qm_get_vft_v2()                 // qm.c:1519
              → hisi_qm_mb_read()             // qm.c:753 - 读取 VFT
                → qm_mb_nolock()              // qm.c:704
                  → hisi_qm_wait_mb_ready()   // qm.c:666
                    → qm_mb_read()            // qm.c:625 - 读取 mailbox 状态
                      → ldp x0,x1,[x3]        // x3=io_base+0x300, 128-bit atomic read
                                               // → 触发 SEA!
```

### 7.2 qm_mb_read() 实现

```c
// drivers/crypto/hisilicon/qm.c:625-643
static struct qm_mailbox qm_mb_read(struct hisi_qm *qm)
{
    struct qm_mailbox mailbox = {0};
    const void __iomem *fun_base = qm->io_base + QM_MB_CMD_SEND_BASE; // 0x300
    unsigned long tmp0, tmp1;

    asm volatile("ldp %0, %1, %3\n"     // 128-bit 原子读
                 "stp %0, %1, %2\n"
                 : "=&r" (tmp0), "=&r" (tmp1),
                   "+Q" (mailbox)
                 : "Q" (*((char __iomem *)fun_base))
                 : "memory");
    return mailbox;
}
```

该函数使用 ARM64 `ldp` 指令对 MMIO 做 128-bit 原子读取。当 KVM stage-2 无映射时：
- 触发 Data Abort 退出到 KVM
- `ldp` 是 128-bit 操作，KVM 无法解码（ISV=0），无法在 QEMU 中模拟
- 故障被注入回 Guest 为 SEA

### 7.3 hisi_acc_vfio_pci 的两种模式

```c
// drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c:1242-1246
val = readl(pf_qm->io_base + QM_MIG_REGION_SEL);
if (pf_qm->ver > QM_HW_V3 && (val & QM_MIG_REGION_EN))
    hisi_acc_vdev->drv_mode = HW_ACC_MIG_PF_CTRL;  // PF_CTRL: 迁移在 PF BAR2
else
    hisi_acc_vdev->drv_mode = HW_ACC_MIG_VF_CTRL;  // VF_CTRL: 迁移在 VF BAR2 后半
```

| 模式 | 迁移寄存器位置 | VF BAR2 给 Guest 的大小 | 是否截断 |
|------|---------------|------------------------|---------|
| HW_ACC_MIG_VF_CTRL | VF BAR2 后 32KB | 32KB (前半) | **是** |
| HW_ACC_MIG_PF_CTRL | PF BAR2 迁移区域 | 64KB (全部) | 否 |

VF_CTRL 模式是默认模式（当硬件版本 ≤ QM_HW_V3 或 `QM_MIG_REGION_EN` 未设置时）。在此模式下，BAR2 的后 32KB 用于迁移控制，Host 侧 `hisi_acc_vfio_pci` 需要独占访问，因此只将前 32KB 暴露给 Guest。

## 8. 解决方案

### 方案1（推荐）：使用 PF_CTRL 模式

如果硬件版本 ≥ QM_HW_V4 (0x50)，在 PF 驱动中设置 `QM_MIG_REGION_SEL` 寄存器使能 `QM_MIG_REGION_EN`，使驱动进入 PF_CTRL 模式：

- 迁移控制寄存器移到 PF BAR2 的 `QM_MIG_REGION_OFFSET` (0x180000) 开始
- 每个 VF 占 8KB (`QM_MIG_REGION_SIZE` = 0x2000)
- VF BAR2 完整 64KB 全部暴露给 Guest
- 无截断，无 mmap 问题

### 方案2：修改 `hisi_acc_vfio_pci` 在 64KB 页面系统上不截断 BAR2

在 `hisi_acc_get_resource_len()` 中加入 PAGE_SIZE 检查：

```c
static size_t hisi_acc_get_resource_len(struct vfio_pci_core_device *vdev,
                                        unsigned int index)
{
    struct hisi_acc_vf_core_device *hisi_acc_vdev =
            hisi_acc_drvdata(vdev->pdev);

    if (hisi_acc_vdev->drv_mode == HW_ACC_MIG_VF_CTRL) {
        size_t len = pci_resource_len(vdev->pdev, index) >> 1;
        if (len < PAGE_SIZE)
            return pci_resource_len(vdev->pdev, index);
        return len;
    }
    return pci_resource_len(vdev->pdev, index);
}
```

**注意事项**：此方案让 Guest 看到 64KB BAR2（包括迁移控制区域），可能影响迁移安全性。需要配合 QEMU 侧或 `hisi_acc_vfio_pci` 的 read/write/mmap 拦截来保护迁移区域，防止 Guest 直接操作迁移寄存器干扰 Host 侧迁移流程。

### 方案3：修改 `hisi_acc_vfio_pci_mmap()` 支持 sub-page mmap

在 `hisi_acc_vfio_pci_mmap()` 中，当截断后 BAR2 小于 PAGE_SIZE 时，允许 mmap 覆盖完整 PAGE_SIZE 的物理页（因为 VF BAR2 在物理上始终是 64KB 对齐的，第一个 64KB 页包含前 32KB 功能区域和后 32KB 迁移区域）：

```c
static int hisi_acc_vfio_pci_mmap(struct vfio_device *core_vdev,
                                  struct vm_area_struct *vma)
{
    ...
    if (index == VFIO_PCI_BAR2_REGION_INDEX) {
        resource_size_t bar_len = pci_resource_len(vdev->pdev, index);
        end = hisi_acc_get_resource_len(vdev, index);
        req_len = vma->vm_end - vma->vm_start;
        req_start = pgoff << PAGE_SHIFT;

        if (req_start + req_len > end) {
            if (end < PAGE_SIZE && req_start == 0 && req_len == PAGE_SIZE
                && bar_len >= PAGE_SIZE)
                ; /* 允许: sub-page BAR mmap 需要完整页面 */
            else
                return -EINVAL;
        }
    }
    ...
}
```

同样需要注意：mmap 的 64KB 页面中后 32KB 是迁移控制区域，Guest 通过 mmap 可直接读写。需要依赖 `hisi_acc_vfio_pci` 的 read/write 拦截来保护（但 mmap 绕过了 read/write 拦截），因此此方案需要额外的页表保护机制。

### 方案4：修改 QEMU 的 sub-page BAR 扩展逻辑（不可行）

修改 `vfio_sub_page_bar_update_mapping()` (`hw/vfio/pci.c:1171`)，在 mmap 失败时也执行 BAR 大小扩展到 PAGE_SIZE。

**此方案不可行**，原因如下：

1. **扩展 MR 大小不改变 MR 类型，不解决 stage-2 映射问题**：

   mmap 已经失败，ram_device 子区域未创建。剩下的是 `region.mem`（IO 类型，`mr->ram = false`）。把它的 size 从 32KB 改成 64KB，`mr->ram` 仍然是 false，KVM 的判断逻辑不变：

   ```c
   // kvm_set_phys_mem():
   if (!memory_region_is_ram(mr))   // mr->ram == false，没变
       return;                       // 照样跳过，不建 stage-2
   ```

   这好比一扇门，把门框加宽了，但门还是锁着的——key 是 ram_device 类型（`mr->ram = true`），而 ram_device 子区域只有 mmap 成功才会创建。扩展 IO 类型 MR 的大小无法解决 stage-2 缺映射的问题。

2. **不会暴露迁移配置区域**：guest 访问走 MMIO trap → `vfio_region_read/vfio_region_write` → `pread/pwrite(VFIO fd)`，内核侧 `hisi_acc_vfio_pci` 的 read/write 拦截会阻止访问迁移区域（offset >= 32KB 时返回错误）。但这一点意义不大，因为 stage-2 映射问题使该方案根本无法工作。

## 9. Debug Patch 说明

为验证 4KB/64KB PAGE_SIZE 下 BAR2 mmap 结果差异，分别在 kernel 和 QEMU 侧添加了 debug 信息。

### 9.1 Kernel 侧打桩点（3处）

| 位置 | 打印信息 |
|------|---------|
| `hisi_acc_vf_qm_init()` | `drv_mode`、`pf_ver`、`mig_region_sel`、`PAGE_SIZE` |
| `hisi_acc_get_resource_len()` | `bar_len`、截断后 `ret_len`、`ret_len < PAGE_SIZE` |
| `hisi_acc_vfio_pci_mmap()` | `end`、`req_start`、`req_len`、`req_start+req_len > end` |

### 9.2 QEMU 侧打桩点（4处）

| 位置 | 打印信息 |
|------|---------|
| `vfio_region_mmap()` | mmap 前：请求大小、PAGE_SIZE；mmap 后：成功/失败、ptr |
| `vfio_bar_register()` | BAR size、PAGE_SIZE、mmap 结果→ram_device or IO |
| `vfio_sub_page_bar_update_mapping()` | `mmaps[0].mmap` 是否 NULL、是否跳过扩展 |
| `kvm_set_phys_mem()` | `mr->ram`、`mr->ram_device`、SKIP/REGISTER |

### 9.3 预期日志：64KB PAGE_SIZE（BAR2 mmap 失败）

```
kernel: DEBUG: hisi_acc_vf_qm_init drv_mode=VF_CTRL(0) PAGE_SIZE=0x10000
kernel: DEBUG: hisi_acc_get_resource_len bar_len=0x10000 ret_len=0x8000 ret_len<PAGE_SIZE=1
kernel: DEBUG: hisi_acc_vfio_pci_mmap req_len=0x10000 > end=0x8000 → -EINVAL
qemu:  DEBUG: vfio_region_mmap FAILED mmap_size=0x8000 errno=22(EINVAL)
qemu:  DEBUG: vfio_bar_register BAR2 mmap FAILED -> IO type, no stage-2
qemu:  DEBUG: vfio_sub_page_bar_update_mapping SKIPPED: mmap=NULL
qemu:  DEBUG: kvm_set_phys_mem SKIP non-RAM mr->ram=0 -> no stage-2
```

日志解读：

1. **`hisi_acc_vf_qm_init`**：`drv_mode=VF_CTRL`，迁移寄存器在 VF BAR2 后半，BAR2 需要截断
2. **`hisi_acc_get_resource_len`**：`bar_len=0x10000(64KB)` 截断为 `ret_len=0x8000(32KB)`，且 `ret_len < PAGE_SIZE=1`，问题已埋下
3. **`hisi_acc_vfio_pci_mmap`**：内核 `do_mmap()` 将 32KB 对齐到 `PAGE_SIZE=0x10000(64KB)`，所以 `req_len=0x10000 > end=0x8000`，mmap 被拒绝返回 `-EINVAL`
4. **`vfio_region_mmap`**：QEMU 收到 mmap 失败，`errno=22(EINVAL)`
5. **`vfio_bar_register`**：mmap 失败 → 无 ram_device 子区域 → BAR 为 IO 类型 → 无 stage-2 映射
6. **`vfio_sub_page_bar_update_mapping`**：因 `mmap=NULL`，前置检查不通过，跳过 sub-page 扩展
7. **`kvm_set_phys_mem`**：`mr->ram=0` → 跳过，不注册 KVM memslot → 不建 stage-2 → guest ldp 触发 SEA

### 9.4 预期日志：4KB PAGE_SIZE（BAR2 mmap 成功）

```
kernel: DEBUG: hisi_acc_vf_qm_init drv_mode=VF_CTRL(0) PAGE_SIZE=0x1000
kernel: DEBUG: hisi_acc_get_resource_len bar_len=0x10000 ret_len=0x8000 ret_len<PAGE_SIZE=0
kernel: DEBUG: hisi_acc_vfio_pci_mmap req_len=0x8000 > end=0x8000 → false → 成功
qemu:  DEBUG: vfio_region_mmap SUCCESS → ram_device created
qemu:  DEBUG: vfio_bar_register BAR2 mmap SUCCESS → stage-2 enabled
qemu:  DEBUG: kvm_set_phys_mem REGISTER mr->ram=1 mr->ram_device=1 → stage-2 mapping
```

日志解读：

1. **`hisi_acc_vf_qm_init`**：同样是 `VF_CTRL` 模式，BAR2 同样截断为 32KB
2. **`hisi_acc_get_resource_len`**：`ret_len=0x8000(32KB)` 但 `ret_len < PAGE_SIZE=0`，32KB > 4KB，不触发问题
3. **`hisi_acc_vfio_pci_mmap`**：内核对齐后 `req_len=0x8000(32KB) = end`，`req_start+req_len > end` 为 false → mmap 成功
4. **`vfio_region_mmap`**：mmap 成功，创建 ram_device 子区域
5. **`vfio_bar_register`**：mmap 成功 → BAR 有 ram_device 子区域 → stage-2 映射可用
6. **`kvm_set_phys_mem`**：`mr->ram=1, mr->ram_device=1` → 注册 KVM memslot → 创建 stage-2 映射 → guest ldp 直接访问物理设备

### 9.5 关键差异对比

| 步骤 | 64KB PAGE_SIZE | 4KB PAGE_SIZE |
|------|---------------|---------------|
| BAR2 截断后大小 | 32KB | 32KB |
| `req_len`（对齐后） | **64KB**（32KB 对齐到 PAGE_SIZE） | 32KB（32KB 已是 PAGE_SIZE 整数倍） |
| `req_len > end(32KB)` | **true** → mmap 失败 | **false** → mmap 成功 |
| MR 类型 | IO（`mr->ram=0`） | ram_device（`mr->ram=1`） |
| KVM stage-2 | 无映射 | 有映射 |
| guest ldp 访问 | SEA 崩溃 | 正常 |

### 9.6 Patch 文件

- **kernel-DEBUG-add-debug-info-for-hisi_acc_vfio_pci-BAR2-mmap.patch** — Kernel 侧 3 处打桩
- **qemu-DEBUG-add-debug-info-for-VFIO-BAR-mmap-and-KVM-stage-2-mapping.patch** — QEMU 侧 4 处打桩
- **kernel-DEBUG-KVM-ISV0-128bit-emulation-failure-path.patch** — Kernel KVM `io_mem_abort()` ISV=0 分支打桩
- **qemu-DEBUG-SEA-injection-on-NISV-exit.patch** — QEMU `kvm_arm_handle_dabt_nisv()` SEA 注入打桩
- **qemu-DEBUG-VFIO-region-pread-pwrite-slow-path.patch** — QEMU `vfio_region_read`/`vfio_region_write` pread/pwrite 慢路径打桩，验证 ldr 单寄存器操作在 S2 无映射时是否能走 QEMU 仿真

## 11. 三份页表、VHE 模式、Host S1 映射与 MMIO 仿真机制

### 11.1 ARM64 VHE 模式与三套独立 TTBR 寄存器

ARM64 VHE (Virtualization Host Extensions) 模式下，Host Kernel 运行在 EL2，Guest 运行在 EL1。为让 Host Kernel 在 EL2 复用 EL1 的指令编码，ARM 硬件对 TTBR 寄存器做了别名映射：

```
VHE 模式 (HCR_EL2.E2H=1, TGE=1):

Host 在 EL2 运行时:
  代码写 TTBR0_EL1 ──→ 硬件自动路由到 TTBR0_EL2  (Host 用户空间映射)
  代码写 TTBR1_EL1 ──→ 硬件自动路由到 TTBR1_EL2  (Host 内核空间映射)
  代码写 TCR_EL1   ──→ 硬件自动路由到 TCR_EL2

Guest 在 EL1 运行时:
  代码写 TTBR0_EL1 ──→ 真正的 TTBR0_EL1          (Guest 用户空间映射)
  代码写 TTBR1_EL1 ──→ 真正的 TTBR1_EL1          (Guest 内核空间映射)
```

**Host 和 Guest 不共用任何 TTBR 寄存器。** 物理上存在六套独立寄存器：

```
┌──────────────────────────────────────────────────────────────┐
│ 物理寄存器 (各自独立)                                         │
│                                                              │
│ Host S1 (EL2, VHE alias):                                    │
│   TTBR0_EL2 → Host 用户空间页表 (QEMU HVA → HPA)            │
│   TTBR1_EL2 → Host 内核空间页表 (KVA → HPA)                 │
│                                                              │
│ Guest S1 (EL1, 真实 EL1 寄存器):                             │
│   TTBR0_EL1 → Guest 用户空间页表 (GVA → GPA)                │
│   TTBR1_EL1 → Guest 内核空间页表 (GVA → GPA)                │
│                                                              │
│ Host S2:                                                     │
│   VTTBR_EL2 → Stage-2 页表 (GPA → HPA)                      │
│                                                              │
│ VM entry/exit 时硬件自动切换:                                  │
│   VM entry: TTBR0_EL2→保存, TTBR0_EL1→恢复Guest值           │
│   VM exit:  TTBR0_EL1→保存, TTBR0_EL2→恢复Host值            │
└──────────────────────────────────────────────────────────────┘
```

### 11.1.1 三份页表同时驻留内存

正常 VM 运行时，内存中同时存在三份完整的页表：

| 页表 | 基址寄存器 | 翻译关系 | 管理者 | 覆盖范围 |
|---|---|---|---|---|
| Host S1 (用户) | TTBR0_EL2 (VHE alias) | HVA → HPA | Host 内核 (QEMU 进程的 mm_struct) | QEMU 等进程的地址空间 |
| Host S1 (内核) | TTBR1_EL2 (VHE alias) | KVA → HPA | Host 内核 | 内核虚拟地址空间 |
| Guest S1 (用户) | TTBR0_EL1 | GVA → GPA | Guest OS | Guest 用户进程地址空间 |
| Guest S1 (内核) | TTBR1_EL1 | GVA → GPA | Guest OS | Guest 内核地址空间 |
| Host S2 | VTTBR_EL2 | GPA → HPA | KVM | Guest 物理地址空间 |

```
三份页表的内容示例 (同一块物理内存):

Host S1:  HVA 0x7fff_0000_0000 ─→ HPA 0x8000_0000  (QEMU malloc 分配)
Guest S1: GVA 0xffff_8000_0000 ─→ GPA 0x4000_0000  (Guest ioremap)
Host S2:  GPA 0x4000_0000     ─→ HPA 0x8000_0000  (KVM memslot)

注意: S2 的 GPA 和 Host S1 的 HVA 完全不同，
      但它们最终指向同一个 HPA
```

**S2 不是 Host S1 的副本。** S2 是 KVM 独立维护的页表，格式与 S1 不同：
- S1 是 VA→PA 的多层映射（支持权限、属性等丰富控制）
- S2 是 IPA→HPA 的单层映射（只做地址翻译+权限控制）

S2 的 HPA 来源是 Host S1 的解析结果：KVM 注册 memslot 时通过 `get_user_pages()` 查 Host S1 得到 HPA，然后填入 S2。

### 11.1.2 Host S1 对 Guest 执行是透明的

Guest 运行时（VM entry 后，HCR_EL2.VM=1），CPU 硬件页表遍历器只查 Guest S1 + Host S2，**不查 Host S1**：

```
Guest 运行时 CPU 页表遍历 (硬件自动完成):

  GVA
   ↓ Guest S1: 查 TTBR0_EL1 / TTBR1_EL1 (Guest 真实 EL1 寄存器)
  GPA
   ↓ Host S2: 查 VTTBR_EL2
  HPA

  Host S1 (TTBR0_EL2 / TTBR1_EL2) ── 完全不参与！

Host 运行时 (VM exit 后):

  HVA
   ↓ Host S1: 查 TTBR0_EL2 / TTBR1_EL2 (EL2 VHE alias)
  HPA

  Guest S1 和 S2 ── 硬件不使用这些页表
```

Host S1 存在是因为 QEMU 进程需要操作这些内存（建 S2、设备模拟等），但 Guest 运行时 CPU 硬件根本不查 Host S1。Host S1 是建 S2 的"脚手架"。

### 11.1.3 VFIO BAR 场景中的两个 Host S1 映射

在 VFIO BAR 场景中，Host 上存在两个独立的 Host S1 映射，分别使用不同的 TTBR：

| | 映射1：内核 ioremap | 映射2：QEMU mmap(VFIO_fd) |
|---|---|---|
| 使用的 TTBR | **TTBR1_EL2** (VHE alias, Host 内核空间页表) | **TTBR0_EL2** (VHE alias, Host 用户空间页表) |
| 虚拟地址范围 | KVA `0xffff_8000_xxxx` | QEMU HVA `0x0000_7fff_xxxx` |
| 建立方式 | `pci_iomap()` / `ioremap()` | `mmap(VFIO_fd, bar_offset)` |
| 建立时机 | QEMU 首次 pread/pwrite 时延迟创建 | QEMU `vfio_region_mmap()` 时 |
| 页表创建者 | 内核直接操作内核页表 | 内核在 syscall 上下文中操作 QEMU 用户页表 |
| 64KB PAGE_SIZE 下 | **成功**（内核内部，不受 PAGE_SIZE 限制） | **失败**（32KB < 64KB） |
| 用途 | pread/pwrite 慢路径 | ram_device + KVM stage-2 快路径 |
| 谁使用 | 内核 VFIO 驱动 | QEMU 进程 + KVM |

```
映射1 (ioremap, TTBR1_EL2 内核空间):    映射2 (mmap, TTBR0_EL2 用户空间):
  内核虚拟地址 (KVA)                        QEMU 进程虚拟地址 (HVA)
  ↓ pci_iomap()                             ↓ mmap(VFIO_fd)
  VF BAR2 HPA                               VF BAR2 HPA

用途:                                      用途:
  QEMU pread/pwrite 时                     QEMU 创建 ram_device MR 时
  内核 VFIO 驱动通过这个地址读设备           KVM 需要这个 HVA 来注册 memslot
  慢路径，每次都陷入内核                    快路径，guest 直接通过 S2 访问
```

### 11.1.4 mmap 建立用户空间 Host S1 映射的机制

`hisi_acc_vfio_pci_mmap()` 是**内核驱动代码**，但它建立的是 **QEMU 进程的用户空间 S1 映射**。这不矛盾——Linux mmap 的标准机制就是用户进程发起 syscall，内核代替用户进程在其用户页表中建立映射：

```
QEMU (用户态 EL0)                    内核 (EL2, VHE 模式)
     │                                  │
     │  mmap(VFIO_fd, 32KB, ...)        │
     │ ─────── syscall ─────────────►  │
     │                                  │ VFS 层: 找到 file->f_op->mmap
     │                                  │ 调用 hisi_acc_vfio_pci_mmap()
     │                                  │   → 检查 BAR2 范围 (32KB vs 64KB)
     │                                  │   → 4KB PAGE_SIZE: 检查通过
     │                                  │   → 64KB PAGE_SIZE: 返回 -EINVAL
     │                                  │
     │                                  │ 检查通过时:
     │                                  │   → vfio_pci_core_mmap()
     │                                  │     设置 vma->vm_pgoff = BAR2 HPA 页帧号
     │                                  │     设置 vma->vm_ops = vfio_pci_mmap_ops
     │                                  │     设置 VM_PFNMAP | VM_IO 等标志
     │                                  │     注意: 此时并未建页表！
     │                                  │
     │  ◄──── 返回 HVA ──────────────  │
     │                                  │
     │  QEMU 访问 HVA                   │
     │ ─────── page fault ──────────►  │
     │                                  │ vfio_pci_mmap_fault()
     │                                  │   → io_remap_pfn_range()
     │                                  │     在 QEMU 的用户页表 (TTBR0_EL2, VHE alias) 中:
     │                                  │     HVA → BAR2 HPA (Device 属性)
     │  ◄─── page fault resolved ────  │
```

关键点：
- `vfio_pci_core_mmap()` 只设置 VMA 元数据，**不立即建页表**
- Host S1 用户页表在 QEMU 首次访问 HVA 触发 page fault 时，由 `vfio_pci_mmap_fault()` → `io_remap_pfn_range()` 建立
- `io_remap_pfn_range()` 通过 `vma->vm_mm` 操作 QEMU 进程的 `mm_struct`，在 QEMU 的 TTBR0_EL2 页表（VHE alias，代码写 TTBR0_EL1 但硬件路由到 TTBR0_EL2）中插入映射
- 这跟普通文件 mmap 完全一样，区别只是映射目标是设备寄存器物理地址而非内存页

### 11.2 内核 ioremap 的创建时机

**不是绑定时创建的，是延迟创建的**——QEMU 首次通过 pread/pwrite 访问 BAR 时才创建：

```c
// drivers/vfio/pci/vfio_pci_rdwr.c:287
ssize_t vfio_pci_bar_rw(struct vfio_pci_core_device *vdev, ...)
{
    ...
    int ret = vfio_pci_setup_barmap(vdev, bar);  // 首次调用时才 ioremap
    io = vdev->barmap[bar];
    done = do_io_rw(vdev, ..., io, buf, pos, count, ...);
    ...
}

// drivers/vfio/pci/vfio_pci_rdwr.c:263
static int vfio_pci_setup_barmap(struct vfio_pci_core_device *vdev, int bar)
{
    if (vdev->barmap[bar])    // 已缓存？直接返回
        return 0;

    pci_request_selected_regions(pdev, 1 << bar, "vfio");
    io = pci_iomap(pdev, bar, 0);         // ← ioremap 完整 BAR (64KB)
    vdev->barmap[bar] = io;               // 缓存，后续复用
    return 0;
}
```

ioremap 一定成功，因为：
- 内核内部映射，不涉及用户空间 PAGE_SIZE 对齐
- `pci_iomap()` 映射完整 BAR 大小（64KB），不做截断
- 只有内核自己用，不暴露给用户空间

### 11.3 Guest 访问 RAM 时需要 Host S1 页表吗？

**不需要。** 正常 VM 运行时，Guest 访问 RAM 只经过两级页表翻译：

```
Guest 访问 RAM:
  GVA → GPA (Guest S1, Guest OS 管理, TTBR0_EL1 / TTBR1_EL1)
  GPA → HPA (Host S2, KVM 管理, VTTBR_EL2)
  → 直接到达物理内存

Host S1 页表完全不参与！
```

CPU 硬件页表遍历器在 VM 运行时（HCR_EL2.VM=1）只查 Guest S1 + Host S2，不查 Host S1：

```
┌──────────────────────────────────────────────────────────────┐
│ VM 运行时 CPU 页表遍历 (硬件自动完成)                          │
│                                                              │
│   GVA                                                        │
│    ↓ Guest S1 (TTBR0_EL1 / TTBR1_EL1, Guest 真实 EL1 寄存器) │
│   GPA                                                        │
│    ↓ Host S2 (VTTBR_EL2)                                     │
│   HPA ──→ 物理内存                                            │
│                                                              │
│   Host S1 (TTBR0_EL2 / TTBR1_EL2, VHE alias) ── 完全不参与！  │
└──────────────────────────────────────────────────────────────┘
```

Host S1 映射虽然存在，但它只在以下场景被使用：

| 场景 | 使用的 Host S1 | 说明 |
|---|---|---|
| Guest 访问 RAM | **不使用** | Guest S1 + Host S2 直达 HPA |
| Guest 访问 VFIO BAR（S2 有映射） | **不使用** | Guest S1 + Host S2 直达 HPA |
| QEMU 用户态访问 guest 内存 | TTBR0_EL2 (VHE alias) | QEMU 模拟设备 DMA 时需要读/写 guest 内存 |
| QEMU pread/pwrite 访问 VFIO BAR | TTBR1_EL2 (VHE alias) | 内核通过 ioremap 读设备 |
| KVM 建 S2 页表 | TTBR0_EL2 (VHE alias) | KVM 通过 QEMU 提供的 HVA → `get_user_pages()` → HPA → 填 S2 |

关键洞察：**Host S1 对 Guest 执行是透明的。** Host S1 存在是因为 QEMU 进程需要操作这些内存（建 S2、设备模拟等），但 Guest 运行时 CPU 硬件根本不查 Host S1。

这也解释了为什么 mmap 对 KVM stage-2 如此重要：KVM 注册 memslot 时需要 QEMU 的 HVA（Host S1 用户映射），通过 `get_user_pages()` 解析出 HPA 来填 S2。**mmap 失败 → 没有 HVA → 无法建 S2 → Guest 运行时找不到 HPA。**

### 11.3.1 S2 页表的建立过程：Host S1 是"脚手架"

S2 页表不是凭空产生的，KVM 必须通过 Host S1 用户页表来获取 HPA。完整流程：

```
1. QEMU 分配 guest RAM 后端内存:
   QEMU: mmap(MAP_ANONYMOUS) → 拿到 HVA = 0x7fff_0000_0000
   此时 Host S1 (TTBR0_EL2) 中已有: HVA 0x7fff_0000_0000 → HPA (延迟建页表)

2. QEMU 注册 KVM memslot:
   QEMU: ioctl(KVM_SET_USER_MEMORY_REGION,
               GPA=0x4000_0000, userspace_addr=HVA=0x7fff_0000_0000, size=1GB)

3. KVM 内核模块建立 S2 映射:
   KVM: get_user_pages(HVA=0x7fff_0000_0000)
        → 查 Host S1 (TTBR0_EL2) 页表  ← 依赖 Host S1!
        → 得到 HPA = 0x0000_8000_0000

   KVM: 在 S2 页表 (VTTBR_EL2) 中填入:
        GPA 0x4000_0000 → HPA 0x0000_8000_0000

4. 之后 Guest 运行时:
   Guest 访问 GPA 0x4000_0000 → S2 直接命中 → HPA 0x8000_0000
   Host S1 不再参与!
```

关键依赖链：
```
mmap 成功 → QEMU 有 HVA → get_user_pages() 能查到 HPA → S2 能建立 → Guest 正常运行
mmap 失败 → QEMU 无 HVA → 无法建 S2                → Guest 运行时 S2 缺页 → 崩溃
```

这就是为什么 VFIO BAR mmap 失败是致命的——它不是 QEMU 自己访问不了设备的问题，而是 **S2 页表无法建立**，导致 Guest 运行时所有对该 BAR 的访问都会触发 S2 Translation Fault。

### 11.3.2 QEMU MemoryRegion 类型与 Host S1 映射的关系

不是所有 MemoryRegion 都有 QEMU 侧的 Host S1 映射。核心规则：**`mr->ram == true` 的 MR 才有 Host S1 映射，`mr->ram == false` 的没有。**

| MemoryRegion 类型 | `mr->ram` | QEMU 侧 Host S1 (TTBR0_EL2) | 创建方式 | KVM S2 | 说明 |
|---|---|---|---|---|---|
| RAM (普通 guest 内存) | true | ✓ 有 | `mmap(MAP_ANONYMOUS)` | ✓ | guest RAM, 大页等 |
| RAM device (VFIO BAR mmap 成功) | true | ✓ 有 | `mmap(VFIO_fd)` | ✓ | VF BAR 快路径 |
| IO (VFIO BAR mmap 失败) | false | ✗ 无 | 不需要 | ✗ | 走 pread/pwrite 慢路径 |
| IO (virtio 等纯软件设备) | false | ✗ 无 | 不需要 | ✗ | 纯软件仿真 |
| ROM / ROM device | true | ✓ 有 | `mmap(MAP_ANONYMOUS)` | ✓ | 固件等 |

各类型的 Host S1 映射建立过程：

```
1. RAM (普通 guest 内存):
   QEMU: qemu_anon_ram_alloc() → mmap(MAP_ANONYMOUS, 4GB)
   Host S1 (TTBR0_EL2): HVA 0x7fff_0000_0000 → HPA (普通内存页)
   KVM: get_user_pages(HVA) → HPA → 填 S2 (GPA → HPA)
   → Guest 访问该 GPA 时，S2 命中，直接到物理内存

2. RAM device (VFIO BAR, mmap 成功):
   QEMU: mmap(VFIO_fd, 64KB) → 拿到 HVA
   Host S1 (TTBR0_EL2): HVA 0x7fff_4000_0000 → HPA (设备寄存器物理地址)
   KVM: get_user_pages(HVA) → HPA → 填 S2 (GPA → HPA)
   → Guest 访问该 GPA 时，S2 命中，直接到设备寄存器

3. IO (VFIO BAR, mmap 失败):
   QEMU: 没有 HVA，只有 vfio_region_ops (pread/pwrite)
   Host S1 (TTBR0_EL2): 无映射
   KVM: 无法建 S2 → Guest 访问触发 S2 缺页 → MMIO 仿真
   → 但内核侧 Host S1 (TTBR1_EL2) 有 ioremap 映射，慢路径可走 pread/pwrite

4. IO (virtio 设备寄存器等):
   QEMU: 纯软件模拟，不需要真实内存后端
   Host S1 (TTBR0_EL2): 无映射
   KVM: 无法建 S2 → Guest 访问走 MMIO trap → QEMU 软件仿真
```

### 11.3.3 慢路径用的不是 QEMU 侧 Host S1，而是内核侧 ioremap

IO 类型 MR 没有 QEMU 侧的 Host S1 映射，但慢路径仍然能工作——因为它使用的是**内核侧** Host S1 (ioremap)，完全不依赖 QEMU 侧映射：

```
IO MR 的两条路径对比:

快路径 (S2 直接访问, 需要 QEMU 侧 Host S1):
  QEMU mmap(VFIO_fd) → TTBR0_EL2 用户页表 → HVA→HPA
  KVM 用 HVA 建 S2 → Guest 直接访问
  → mmap 失败时: 这条路不存在

慢路径 (MMIO 仿真, 用内核侧 Host S1):
  QEMU pread(VFIO_fd) → syscall → 内核 ioremap → TTBR1_EL2 内核页表 → KVA→HPA
  → 这条路不需要 QEMU 有 HVA, 也不需要 S2
```

两种 Host S1 映射在 IO MR 场景中的使用对比：

| | QEMU 侧 Host S1 (TTBR0_EL2) | 内核侧 Host S1 (TTBR1_EL2) | KVM S2 |
|---|---|---|---|
| RAM | ✓ mmap(ANONYMOUS) | 不需要 | ✓ 通过 TTBR0_EL2 建立 |
| RAM device | ✓ mmap(VFIO_fd) | 不需要 | ✓ 通过 TTBR0_EL2 建立 |
| IO (mmap 失败) | ✗ 无 | ✓ ioremap (首次 pread 时) | ✗ 无法建立 |

**关键洞察：慢路径能走通，恰恰是因为它绕过了 QEMU 侧的 Host S1，直接用内核 ioremap。** 但这也意味着 S2 无法建立——KVM 建不了"脚手架"，Guest 运行时只能靠 VM exit + QEMU 仿真。

这也回答了 ldr 是否能走慢路径的问题：ldr 理论上能走慢路径，是因为 pread → ioremap 这条路是通的。问题是 ldp ISV=0 根本走不到 QEMU 这一步（无法构造 KVM_EXIT_MMIO 退出），在 KVM 就被拦截并注入 SEA。

### 11.4 KVM 为什么不能用 ioremap 映射建 S2

KVM 注册 memslot 需要的是 **QEMU 用户空间的 HVA**：

```c
// accel/kvm/kvm-all.c
ram = memory_region_get_ram_ptr(mr) + mr_offset;  // 需要 QEMU 的 HVA
kvm_set_user_memory_region(kml, mem, true);         // 传给内核建 S2
```

内核通过 `get_user_pages()` 把 HVA 转成 HPA 来填 S2 页表。ioremap 产生的是**内核虚拟地址**，不在 QEMU 用户空间地址空间里，`get_user_pages()` 无法使用。所以 KVM 注册 memslot 只能依赖映射2（QEMU mmap），映射2 失败则 S2 无法建立。

### 11.5 QEMU MMIO 仿真的完整路径

QEMU 不是通过 GPA → HPA 的 S2 翻译来访问设备的，它走的是完全独立的 pread/pwrite 路径。注意慢路径使用的是**内核侧 Host S1 (ioremap, TTBR1_EL2)**，不是 QEMU 侧 Host S1：

```
路径A: Guest 直接访问 (需要 S2 映射)          路径B: QEMU 仿真访问 (不需要 S2)
  Guest ldr x0, [x3]                           QEMU 收到 KVM_EXIT_MMIO
    → GVA → GPA (S1) ✓                           → pread(VFIO_fd, buf, 8, offset)
    → GPA → HPA (S2) ✗                            → 内核 VFIO 驱动通过 ioremap 读设备
    → 失败                                        → 返回数据给 QEMU
                                                   → QEMU 写入 kvm_run.mmio.data
                                                   → KVM 写回 guest x0 寄存器

  使用的 Host S1:                                使用的 Host S1:
    QEMU 侧 TTBR0_EL2 (mmap)                     内核侧 TTBR1_EL2 (ioremap)
    用于建 S2 "脚手架"                             用于 pread/pwrite 实际读设备
    mmap 失败 → S2 无法建                          ioremap 总是成功，不依赖 mmap
```

### 11.6 单寄存器 ldr 的完整仿真流程

以 `ldr x0, [x3]`（8 字节读，x3 = io_base + 0x300）为例，当 S2 无映射时：

```
Step 1: 硬件产生 Data Abort
─────────────────────────────
Guest 执行: ldr x0, [x3]
  → S1 成功 → S2 无映射 → Data Abort
  → CPU 硬件填写 ESR_EL2:
      ISV  = 1       (有效 syndrome，单寄存器可以解码)
      SAS  = 11      (8 字节)
      SRT  = 00000   (目标寄存器 x0)
      WNR  = 0       (读)
      SF   = 1       (64-bit)
      DFSC = 0x10    (Translation fault, level 0)
  → CPU 跳转到 EL2 (KVM)

Step 2: KVM 解码 ESR，构造 MMIO 请求
──────────────────────────────────────
io_mem_abort() (arch/arm64/kvm/mmio.c:168)
  ISV=1 → 解码成功:
    is_write = false    (ESR.WNR=0)
    len      = 8        (ESR.SAS=11)
    rt       = x0       (ESR.SRT=0)
  → KVM 现在知道了: 这是一次 8 字节读，结果要写回 x0

Step 3: KVM 退出到 QEMU
────────────────────────
kvm_io_bus_read() 失败 → VFIO 设备没注册在 KVM_MMIO_BUS 上
  → 准备 kvm_run:
      run->mmio.is_write   = false
      run->mmio.phys_addr  = 0x8000200300
      run->mmio.len        = 8
      run->exit_reason     = KVM_EXIT_MMIO
  → 返回 QEMU

Step 4: QEMU 执行实际 MMIO 操作
─────────────────────────────────
kvm_cpu_exec() (accel/kvm/kvm-all.c:3124)
  case KVM_EXIT_MMIO:
    address_space_rw(&address_space_memory,
                     phys_addr = 0x8000200300, len=8, is_read)
      → 找到该 GPA 属于 VFIO BAR2 MemoryRegion
      → 计算 BAR2 内偏移 = 0x8000200300 - BAR2_base = 0x300
      → vfio_region_read(region, offset=0x300, size=8)
        → pread(VFIO_fd, buf, 8, bar2_fd_offset + 0x300)

Step 5: 内核 VFIO 驱动读设备
──────────────────────────────
vfio_pci_bar_rw() (drivers/vfio/pci/vfio_pci_rdwr.c:287)
  → vfio_pci_setup_barmap() → pci_iomap(BAR2) → ioremap 成功 (映射1)
  → do_io_rw():
      vfio_pci_ioread32(vdev, &val, io + 0x300)   // 读前 4 字节
      vfio_pci_ioread32(vdev, &val, io + 0x304)   // 读后 4 字节
  → 返回 8 字节数据

Step 6: QEMU 返回后，KVM 写回 guest 寄存器
─────────────────────────────────────────────
kvm_handle_mmio_return() (arch/arm64/kvm/mmio.c:108)
  data = kvm_mmio_read_buf(run->mmio.data, 8)     // 从缓冲区读 8 字节
  vcpu_set_reg(vcpu, kvm_vcpu_dabt_get_rd(vcpu), data)
  //                   rt=x0                        ← 写回 x0
  kvm_incr_pc(vcpu)    // 跳过已仿真的 ldr，继续执行下一条指令

结果: Guest x0 有正确数据，继续执行，不会崩溃
```

### 11.7 为什么 ldp 无法仿真

`ldp x0, x1, [x3]` 在 Step 1 就失败了：

```
CPU 填写 ESR_EL2:
  ISV = 0    (多寄存器操作，syndrome 格式放不下)
  → SAS/SRT/WNR 全部无效

io_mem_abort():
  ISV=0 → 无法知道读/写/大小/寄存器
  → 无法构造 MMIO 请求
  → 返回 KVM_EXIT_ARM_NISV
  → QEMU 无法仿真
  → 注入 SEA → Guest panic
```

### 11.8 ISV 填充原则（修正）

ARM 架构规范对 ISV 的填充原则：

**ISV = 1 的条件（有效 Syndrome）：**

触发异常的 Data Abort 由单寄存器或通用寄存器 pair 操作引起，包括 LDR、STR、**LDP**、**STP**、LDUR、STUR 等。CPU 能解码指令并填充 SAS/SSE/SRT/SF/WNR/AR。

**ISV = 0 的情况（无效 Syndrome）：**

- 多寄存器指令（LDM、STM、LDRD、STRD）
- SIMD/FP 寄存器操作（如 LDR Q0, [X0]）
- 独占访问指令（LDXR、STXR）某些实现不提供 syndrome
- 预取指令（PRFM）
- CPU 无法解码该指令

**注意**：LDP/STP 属于通用寄存器 pair 操作，ARM 规范允许 ISV=1。但 ISV=1 时 syndrome 只描述**第一个寄存器**，第二个寄存器的信息丢失。

### 11.9 LDP 在 ISV=1 时的仿真问题

即使 `ldp x0, x1, [x3]` 的 ISV=1，KVM 也无法正确仿真：

```
ESR_EL2 (ISV=1):
  SAS = 11     (8 字节 — 每个 register 的大小，不是总和)
  SRT = 00000  (x0 — 第一个寄存器)
  WNR = 0      (读)
```

但 LDP 一次指令做两次 8 字节访问，syndrome 只描述了第一个（x0）：

```
ldp x0, x1, [x3] 实际执行:
  访问1: 从 [x3]     读 8 字节 → x0    ← syndrome 只描述了这个
  访问2: 从 [x3+0x8] 读 8 字节 → x1    ← 这个信息丢失了
```

KVM 只能仿真一次 MMIO 请求：

```
KVM 仿真:
  pread(VFIO_fd, buf, 8, offset+0x300)  → 读 8 字节
  vcpu_set_reg(vcpu, x0, data)           → x0 有数据
  kvm_incr_pc()                          → 跳过 ldp

问题:
  x1 没有被写入！第二次 8 字节访问被完全跳过！
  x1 中是垃圾值 → 后续使用 x1 的代码行为不可预测
```

### 11.10 本场景中 ISV 的实际值

崩溃日志中 guest 看到的 ESR：

```
Internal error: synchronous external abort: 0000000096000010
```

ESR = `0x96000010`，bit[24] = 0 → ISV=0。但这是 **KVM 注入 SEA 后 guest 看到的 ESR**，不是 CPU 产生 S2 fault 时的原始 ESR_EL2。

原始 ESR_EL2 是否 ISV=1，取决于具体 CPU 实现：
- ARM 规范允许某些实现对 pair 指令不提供 syndrome（ISV=0）
- 也有些实现提供 ISV=1

需要通过 debug patch 在 `io_mem_abort()` 打印原始 ESR 来确认。

### 11.11 LDP 无论 ISV 值如何都无法正确仿真

| | ISV=0 (某些 CPU 实现) | ISV=1 (某些 CPU 实现) |
|---|---|---|
| KVM 能否解码 | 不能 | 能（但只描述第一个寄存器） |
| 仿真结果 | 直接注入 SEA → panic | 部分仿真：x0 有数据，x1 丢失 |
| 后果 | 崩溃 | x1 垃圾值，后续行为不可预测 |
| 能否正常工作 | 不能 | 不能（仿真不完整） |

**无论 ISV 是 0 还是 1，ldp 的 MMIO 仿真都无法正确完成。** 根本解法还是让 mmap 成功，让 ldp 走 S2 直接访问。

### 11.12 ldr 单寄存器操作能否走 pread/pwrite 慢路径（待验证）

基于代码推理，`ldr` 单寄存器读在 S2 无映射时应该能走 QEMU pread/pwrite 慢路径：

```
mmap 失败后的 MemoryRegion 层次:
  bar->mr (外层容器, NULL ops, size=32KB)
    └── region.mem (IO 类型, vfio_region_ops) at offset 0
         → .read = vfio_region_read  → pread(VFIO_fd)
         → .write = vfio_region_write → pwrite(VFIO_fd)
```

当 KVM_EXIT_MMIO 到达 QEMU 时：

```
QEMU: address_space_rw(GPA=0x8000200300, len=8, read)
  → 找到 GPA 属于 VFIO BAR2 region.mem
  → 计算 region 内偏移 = 0x300
  → vfio_region_read(region, addr=0x300, size=8)
  → pread(VFIO_fd, buf, 8, region->fd_offset + 0x300)
  → 内核 VFIO 驱动通过 ioremap 读设备 → 返回数据
```

**但这是代码推理，有以下不确定性：**

1. **GPA 到 MemoryRegion 的映射**：`hisi_acc_vfio_pci_ioctl` 把 BAR2 大小改成 32KB，QEMU 注册的 MR 也是 32KB。0x300 < 32KB，应该能找到。但未实测。

2. **hisi_acc_vfio_pci_read 拦截**：`hisi_acc_vfio_pci` 覆盖了 read 回调，对 BAR2 做范围检查（offset >= 32KB 返回 -EINVAL）。0x300 < 32KB 不会被拦截。但未实测。

3. **vfio_region_ops.max_access_size=8**：`ldr` 是 8 字节，在范围内。但未实测 QEMU 内存系统是否会拆分成更小的访问。

**为验证这一点，已在 `vfio_region_read`/`vfio_region_write` 中添加了 debug 打印**（见 `qemu-DEBUG-VFIO-region-pread-pwrite-slow-path.patch`），确认 pread/pwrite 是否被调用。

### 11.13 三层映射与三条路径总结

```
Guest 访问 BAR2 的三条路径:

路径1: S2 直接访问 (最快，无 VM exit)
  GVA → GPA (Guest S1, TTBR0_EL1/TTBR1_EL1, Guest ioremap 建立)
  GPA → HPA (Host S2, VTTBR_EL2, KVM memslot 建立，依赖 QEMU mmap 成功)
  → 直接访问设备寄存器
  → 前提: QEMU mmap 成功 → ram_device → KVM memslot
  → 64KB PAGE_SIZE 下: mmap 失败 → 不可用
  → 4KB PAGE_SIZE 下: mmap 成功 → 可用

路径2: KVM + QEMU MMIO 仿真 (慢，需 VM exit + QEMU 介入)
  GVA → GPA (Guest S1, TTBR0_EL1/TTBR1_EL1)
  GPA → Host S2 缺页 (VTTBR_EL2) → VM exit → KVM (EL2)
  KVM 解码 ESR (需要 ISV=1)
  KVM → QEMU (KVM_EXIT_MMIO)
  QEMU pread(VFIO_fd) → 内核 ioremap (TTBR1_EL2) → 读设备
  QEMU → KVM → 写回 guest 寄存器
  → 前提: ISV=1 且单寄存器操作
  → ldr: ISV=1 → 可用（代码推理可行，待实测验证）
  → ldp: ISV=1 → 不完整（只仿真第一个寄存器，第二个丢失）
  → ldp: ISV=0 → 不可用

路径3: S2 缺页 + ISV=0 (失败，只能注入 SEA)
  GVA → GPA (Guest S1, TTBR0_EL1/TTBR1_EL1)
  GPA → Host S2 缺页 (VTTBR_EL2) → VM exit → KVM (EL2)
  KVM 解码 ESR: ISV=0 → 无法处理
  KVM → QEMU (KVM_EXIT_ARM_NISV)
  QEMU 注入 SEA → Guest panic
  → ldp 在某些 CPU 实现上 ISV=0 时走这条路
```

## 12. 环境信息

| 项目 | 值 |
|------|-----|
| 平台 | ARM64 (aarch64) |
| HOST PAGE_SIZE | 64KB |
| GUEST PAGE_SIZE | 64KB |
| VF 设备 | HiSilicon ZIP VF (PCI ID: 19e5:a251) |
| 内核版本 | 6.6.0 |
| QEMU | aarch64 system emulation |
| VFIO 驱动 | hisi_acc_vfio_pci (VF_CTRL 模式) |

## 13. 涉及的关键源码文件

| 文件 | 路径 | 关键行 |
|------|------|--------|
| QM 驱动主文件 | `drivers/crypto/hisilicon/qm.c` | qm_mb_read:625, hisi_qm_wait_mb_ready:666, qm_get_pci_res:5884 |
| QM 寄存器定义 | `include/linux/hisi_acc_qm.h` | QM_MB_CMD_SEND_BASE:51, QM_MIG_REGION_SEL:103 |
| ESR 寄存器定义 | `arch/arm64/include/asm/esr.h` | ESR_ELx_ISV:136, ESR_ELx_SAS:138, ESR_ELx_SRT:142 |
| KVM MMIO 仿真 | `arch/arm64/kvm/mmio.c` | io_mem_abort:168, kvm_handle_mmio_return:108, kvm_mmio_write_buf:15, kvm_mmio_read_buf:47 |
| KVM ESR 解码 | `arch/arm64/include/asm/kvm_emulate.h` | kvm_vcpu_dabt_isvalid:359, kvm_vcpu_dabt_get_as:400 |
| VFIO PCI BAR 读写 | `drivers/vfio/pci/vfio_pci_rdwr.c` | vfio_pci_setup_barmap:263, vfio_pci_bar_rw:287, do_io_rw:157 |
| hisi_acc_vfio_pci 驱动 | `drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c` | hisi_acc_get_resource_len:1320, hisi_acc_vfio_pci_mmap:1365, hisi_acc_vf_qm_init:1234 |
| hisi_acc_vfio_pci 头文件 | `drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.h` | QM_MIG_REGION_OFFSET:66, drv_mode:77 |
| QEMU VFIO container | `hw/vfio/container.c` | vfio_legacy_dma_map:220 |
| QEMU VFIO helpers | `hw/vfio/helpers.c` | vfio_region_mmap:402 |
| QEMU VFIO PCI | `hw/vfio/pci.c` | vfio_sub_page_bar_update_mapping:1171, vfio_bar_register:1785 |
| QEMU KVM ARM | `target/arm/kvm.c` | kvm_arm_handle_dabt_nisv:1268 |
| QEMU KVM | `accel/kvm/kvm-all.c` | kvm_set_phys_mem:1327, kvm_align_section:266 |
| KVM UAPI | `include/uapi/linux/kvm.h` | kvm_run.mmio.data[8]:354 |
