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

## 10. 环境信息

| 项目 | 值 |
|------|-----|
| 平台 | ARM64 (aarch64) |
| HOST PAGE_SIZE | 64KB |
| GUEST PAGE_SIZE | 64KB |
| VF 设备 | HiSilicon ZIP VF (PCI ID: 19e5:a251) |
| 内核版本 | 6.6.0 |
| QEMU | aarch64 system emulation |
| VFIO 驱动 | hisi_acc_vfio_pci (VF_CTRL 模式) |

## 11. 涉及的关键源码文件

| 文件 | 路径 | 关键行 |
|------|------|--------|
| QM 驱动主文件 | `drivers/crypto/hisilicon/qm.c` | qm_mb_read:625, hisi_qm_wait_mb_ready:666, qm_get_pci_res:5884 |
| QM 寄存器定义 | `include/linux/hisi_acc_qm.h` | QM_MB_CMD_SEND_BASE:51, QM_MIG_REGION_SEL:103 |
| hisi_acc_vfio_pci 驱动 | `drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.c` | hisi_acc_get_resource_len:1320, hisi_acc_vfio_pci_mmap:1365, hisi_acc_vf_qm_init:1234 |
| hisi_acc_vfio_pci 头文件 | `drivers/vfio/pci/hisilicon/hisi_acc_vfio_pci.h` | QM_MIG_REGION_OFFSET:66, drv_mode:77 |
| QEMU VFIO container | `hw/vfio/container.c` | vfio_legacy_dma_map:220 |
| QEMU VFIO helpers | `hw/vfio/helpers.c` | vfio_region_mmap:402 |
| QEMU VFIO PCI | `hw/vfio/pci.c` | vfio_sub_page_bar_update_mapping:1171, vfio_bar_register:1785 |
| QEMU KVM | `accel/kvm/kvm-all.c` | kvm_align_section:266 |
