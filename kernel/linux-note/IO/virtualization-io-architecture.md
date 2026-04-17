# 虚拟化I/O架构

本文档整理Linux虚拟化环境下的I/O体系，涵盖ARM64 SMMU、DMA、Doorbell、VFIO等核心概念。

## 1. SMMU与IOMMU的关系

### 基本概念

**IOMMU（Input/Output Memory Management Unit）** 是通用架构规范，定义了I/O设备如何进行内存地址翻译。它为设备提供类似CPU MMU的地址翻译能力，让设备可以使用虚拟地址访问内存。

**SMMU（System Memory Management Unit）** 是ARM架构对IOMMU的具体硬件实现。在ARM系统中，SMMU就是ARM的IOMMU实现，两者是规范与实现的关系。

这种关系类似于软件设计中的接口与实现类：IOMMU定义了设备应该如何进行地址翻译的接口规范，SMMU是ARM架构对这个接口的具体实现。

### 为什么ARM需要SMMU

没有IOMMU时，设备使用物理地址直接访问内存，这带来两个主要问题：设备只能访问到连续的物理内存（内存碎片化问题），以及无法隔离恶意或故障设备对内存的访问（安全隐患）。

有了SMMU后，设备使用IOVA（I/O Virtual Address）访问内存，SMMU负责翻译到真实物理地址。IOVA可以是连续的，而物理地址可以是非连续的。SMMU可以限制设备只能访问授权的内存区域。

### SMMU与其他架构的对比

x86架构使用VT-d（Intel）或AMD-Vi（AMD）作为IOMMU实现。ARM架构使用SMMUv1/SMMUv2/SMMUv3。RISC-V的IOMMU规范正在发展中。每个架构都遵循通用的IOMMU架构规范，但有各自的硬件实现。

### IOMMU跟SMMU是怎么配合的

SMMU使用Stream Identifier（SID）来识别设备，通过Stream Table Entry（STE）将SID映射到对应的翻译上下文。Context Descriptor（CD）包含页表基址和翻译配置。SMMU遍历页表完成IOVA到PA的翻译。

```
设备请求（带有Stream ID）
    ↓
SMMU查找Stream Table Entry (STE)
    ↓
STE指向Context Descriptor (CD)
    ↓
CD包含Stage 1和/或Stage 2页表指针
    ↓
SMMU遍历页表：IOVA → Intermediate PA → PA
    ↓
最终物理地址访问内存
```

### 设备映射跟内存MMU是怎么配合的

SMMU的页表格式与CPU MMU高度兼容，都支持ARM_64_LPAE_S1/S2、ARM_32_LPAE_S1/S2、ARM_V7S等格式。这确保了CPU和设备对内存视图的一致性。

当CPU更新页表时，需要通过TLB同步机制通知SMMU。通过SMMU命令队列发送TLBI命令，失效相应的TLB条目。io_pgtable层提供统一的页表操作接口，兼容CPU和SMMU。

工作流程如下：CPU侧虚拟地址（VA）经MMU翻译为物理地址（PA），设备侧虚拟地址（IOVA）经SMMU翻译为同一物理地址（PA）。两者共享页表格式，但维护独立的页表结构和TLB。

## 2. SMMU页表与CPU页表

### 相同点

SMMU和CPU MMU使用相同的页表格式规范，都采用四级页表结构（PGD→PUD→PMD→PTE）。PTE格式完全相同，包含物理地址、权限位（Read/Write/Execute）、属性位（Cacheable、Shareable等）。都支持相同的映射粒度：4KB页面、2MB块（PMD）、1GB块（PUD）。

### 关键区别

虽然格式相同，但两者是物理上完全独立的页表结构。CPU使用TTBR0_EL1/TTBR1_EL1作为页表基址寄存器，SMMU使用自己独立的TTBR寄存器。CPU TLB和SMMU TLB是各自独立的缓存，由各自的硬件单元独立遍历和缓存。数据结构不同：CPU使用pgd_t/pmd_t/pte_t结构，SMMU使用struct io_pgtable_ops接口。

### 代码中的证据

在io-pgtable.h中定义的页表格式枚举与ARM64 CPU的页表格式一一对应。io_pgtable_cfg结构中的arm_lpae_s1_cfg包含ttbr、tcr、mair字段，与ARM64的TTBR0_EL1、TCR_EL1、MAIR_EL1寄存器对应。

### 设计原因

分离设计允许CPU和设备有不同的地址空间视图，比如进程A和进程B可以各自有不同的设备映射。支持独立的内存属性控制，设备可以使用与CPU不同的缓存策略。可以在不打扰CPU页表的情况下修改设备映射，比如热插拔设备时。

## 3. Doorbell寄存器

### 概念解析

Doorbell（门铃）寄存器是设备向硬件发送信号的一种机制，本质上是**普通的MMIO写操作**。写doorbell就是往某个地址写数据，设备看到这个特定地址的写入就知道有新任务需要处理。

"门铃"这个名称是类比：想象酒店门口的门铃，按下它（写doorbell）里面的人就知道有访客来了（硬件开始处理任务）。

### 为什么叫Doorbell

设备写入doorbell寄存器通知硬件"有新任务"。硬件感知到这个"敲门"动作后去检查命令队列并处理新命令。CPU不需要等待这个操作完成（fire-and-forget）。

### Doorbell操作的工作流程

以网卡发送命令为例：第一步，驱动把命令写入共享内存队列（内存中）。第二步，驱动写Doorbell寄存器（写入新索引值），通知硬件。第三步，硬件检测到doorbell写入，去队列取命令并执行。

```c
// 伪代码示例
void nic_send_command(struct nic *nic, struct command *cmd)
{
    // 1. 把命令写入共享内存队列
    memcpy(nic->cmdq_base + nic->cmdq_tail * sizeof(cmd), cmd, sizeof(*cmd));

    // 2. 写Doorbell寄存器，通知硬件
    //    写入的值通常是新的tail索引
    writeq(nic->db_base, nic->cmdq_tail);

    // 3. 更新本地tail指针
    nic->cmdq_tail++;
}
```

### Doorbell vs 普通MMIO写入

从CPU和MMU的角度看，doorbell写入和普通内存写入没有本质区别。都是VA→PA翻译，然后总线传输。区别只在于PA指向哪里（RAM还是设备寄存器）以及设备如何解释这个访问。

### MSI Doorbell

MSI（Message Signaled Interrupts）是一种通过内存写触发中断的机制。MSI地址是预先分配好的特殊物理地址，CPU配置MSI地址指向某个寄存器区域。设备写入这个MSI地址就触发对目标CPU的中断。

MSI Doorbell用于中断触发，在SMMU场景下MSI地址通常有特殊处理，可能bypass SMMU翻译以避免循环。

## 4. MLX5网卡的Doorbell BAR空间

### MLX5 UAR结构

MLX5网卡使用UAR（User Access Region）作为doorbell寄存器区域，大小为4KB（MLX5_ADAPTER_PAGE_SIZE）。

```
mlx5 UAR (User Access Region) - 最小4KB
┌─────────────────────────────────────────────┐
│ 0x0000 │ 配置寄存器 (CQ doorbell等)         │
├─────────────────────────────────────────────┤
│ 0x0800 │ BlueField Registers (BF)           │  ← MLX5_BF_OFFSET
│         │ 每个BF占用 64bytes                 │
│         │ BF0, BF1, BF2, BF3                │
├─────────────────────────────────────────────┤
│ 0x1000 │ ... (如果系统页更大)               │
└─────────────────────────────────────────────┘
```

### 关键参数

MLX5_ADAPTER_PAGE_SHIFT = 12，表示4KB单位。MLX5_BF_OFFSET = 0x800，BlueField寄存器偏移。MLX5_BFREGS_PER_UAR = 4，每个UAR有4个BF寄存器。MLX5_NON_FP_BFREGS_PER_UAR = 2，2个非Floor-Planning BF寄存器。

### BAR空间配置

Doorbell BAR大小通过设备能力读取：log_doorbell_bar_size来自固件，bar_size = (2^log_doorbell_bar_size) × 4KB。

实际配置通过pci_request_regions从BAR0分配，BAR0总大小通常为256MB或512MB（取决于具体网卡）。驱动通过pci_iomap()获得BAR的虚拟地址，映射到内核的vmalloc区域。

### 写doorbell就是写BAR空间

```c
// mlx5驱动中
void __iomem *bar = pci_iomap(pdev, 0, 0);  // 映射BAR0
writeq(value, bar + 0x800 + queue_id * stride); // 写doorbell
```

写doorbell = 写BAR空间内特定偏移的地址 = 标准的MMIO写操作 = 对CPU来说就是普通的内存写入。

### BAR地址空间的不固定性

PA（物理地址）由硬件决定，如0x2000000000。VA（虚拟地址）由内核ioremap分配，不固定，每次可能不同。同一台机器上同一个驱动加载，VA通常相同，但这是内核分配的而非固定的。

## 5. SMMU工作原理

### 系统位置

CPU核心发出VA经CPU MMU翻译为PA访问物理内存。设备发出IOVA+SID经SMMU翻译为PA访问物理内存。SMMU位于设备与内存之间，所有设备DMA请求都经过SMMU。

### 核心概念

Stream ID是设备的身份证，设备事务携带SID用于识别来源设备。Stream Table将Stream ID映射到Stream Table Entry（STE），支持LINEAR（一级）和2LVL（两级）两种格式。Context Descriptor（CD）包含TTBR（页表基址）、TCR（翻译控制寄存器）、MAIR（内存属性）。页表实现IOVA到PA的翻译，支持多级遍历。TLB缓存最近使用的翻译结果，加速后续访问。

### 单Stage翻译流程（Stage 1为例）

```
1. 设备发送事务: IOVA + SID
2. SMMU接收事务，提取Stream ID
3. 查Stream Table，获得STE
4. 查Context Descriptor，获得TTBR/TCR
5. Walk页表: IOVA → PA
6. 发送事务到物理内存
```

### 两阶段翻译（嵌套翻译）

Stage 1（S1）实现IOVA到IPA（Intermediate Physical Address）的翻译。Stage 2（S2）实现IPA到PA的翻译，由Hypervisor控制。Nested模式两者结合，提供更灵活的虚拟化支持。

在虚拟化场景中，Guest VM发出IOVA，Hypervisor的SMMU Stage 2将IOVA翻译为IPA，然后Guest的SMMU Stage 1将IPA翻译为最终PA。

### SMMU命令队列

SMMU通过命令队列（CMD Queue）接收软件命令。命令写入内存队列后，写doorbell通知SMMU。SMMU读取命令并执行，更新完成状态。

常用命令包括：TLBI_NH_VA（按VA失效TLB）、TLBI_NH_ASID（按ASID失效）、CFGI_STE（配置STE）、CFGI_CD（配置CD）、ATC_INV（地址翻译缓存失效）、CMD_SYNC（命令同步）。

### TLB同步机制

当CPU修改页表后，需要通知SMMU失效相应的TLB条目。通过SMMU命令队列发送TLBI命令。执行memory barrier确保页表更新可见。等待SMMU完成失效操作。

```c
static void arm_smmu_tlb_inv_context_s1(void *cookie)
{
    struct arm_smmu_domain *smmu_domain = cookie;

    wmb();  // 确保页表更新对SMMU可见

    arm_smmu_cb_write(smmu_domain->smmu, smmu_domain->cfg.cbndx,
              ARM_SMMU_CB_S1_TLBIASID, smmu_domain->cfg.asid);
    arm_smmu_tlb_sync_context(smmu_domain);
}
```

## 6. DMA与CPU的协作

### DMA基本概念

DMA（Direct Memory Access）允许设备直接读写内存，无需CPU介入。CPU配置DMA控制器一次，DMA自动执行大量数据搬运。传输完成后DMA发中断通知CPU。CPU可以同时执行其他任务。

### 为什么需要DMA

CPU亲自读写大量数据会占用CPU资源，影响整体性能。DMA让CPU只做"指挥官"：配置DMA一次，DMA完成搬运，发通知让CPU处理结果。

### CPU读写内存 vs DMA读写内存

CPU读写内存经过CPU缓存层次。DMA读写内存直接通过DMA控制器访问内存控制器。两者访问的是同一块物理内存，但路径独立。

### 环形队列机制

Descriptor Ring（命令队列）存放待执行的命令描述符。每个描述符包含源地址、目标地址、长度等信息。设备DMA读取描述符，根据描述执行数据搬运。

Completion Queue（CQ）记录已完成的任务。设备DMA写入CQE通知任务完成。CQE包含任务状态、WQE ID等信息。CPU读取CQE处理完成事件。

### 完整数据接收流程

外部数据包到达设备。设备DMA将数据写入内存缓冲区。设备DMA写入CQE到Completion Queue。设备发MSI中断到CPU。CPU中断处理函数读取CQE，根据WQE ID找到对应任务。CPU从DMA缓冲区读取数据（如需要）。归还描述符给Ring，写doorbell通知设备继续接收。

### 中断合并优化

每包都中断开销太大，设备支持中断合并（Interrupt Coalescing）。可以按包数量阈值触发（如1000包一次中断），或按时间阈值触发（如10μs后中断）。

### DMA与中断的关系

DMA执行类似"软中断/后台任务"。CPU发起DMA后去干别的事。DMA独立执行，不占用CPU。完成后触发MSI"硬中断"通知CPU。

```
┌─────────────────────────────────────────────────────────────┐
│  DMA = 后台任务执行（软操作，不打断CPU）                    │
│  MSI = 任务完成通知（硬中断，打断CPU）                      │
│  CPU = 处理收尾工作                                         │
└─────────────────────────────────────────────────────────────┘
```

## 7. MSI中断机制

### 传统中断 vs MSI

传统INTx中断需要设备通过专门的INTx引脚连接中断控制器。MSI（Message Signaled Interrupt）通过Memory Write TLP触发中断，可携带数据（如向量号），支持更多中断，延迟更低。

### MSI地址

MSI地址是预先分配的物理地址。当设备写这个地址时，触发中断。CPU在启动时配置MSI地址分配。

### MSI写入流程

设备构造Memory Write TLP，目标地址为MSI地址。写入数据包含中断向量信息。PCIe路由这个TLP到中断控制器或CPU本地APIC。中断控制器/本地APIC产生中断信号给CPU。

### MSI Doorbell在SMMU场景

MSI地址需要特殊处理，避免被SMMU错误翻译。通常配置为bypass SMMU或使用固定映射。

## 8. VFIO框架

### 位置

VFIO（Virtual Function I/O）是运行在**宿主机Linux内核**的I/O虚拟化框架。让用户空间程序（QEMU）能够安全地直接访问硬件。配合SMMU实现设备隔离和地址翻译。

### 核心功能

DMA映射建立用户内存与设备IOVA的映射。通过IOMMU实现地址翻译和隔离。用户空间通过ioctl配置DMA映射。

中断转发将设备MSI中断绑定到用户空间eventfd。QEMU在用户空间接收中断并处理。VFIO只是路由，不做复杂处理。

BAR映射通过mmap将设备寄存器映射到用户空间。用户可以直接读写设备寄存器。绕过内核，直接操作硬件。

配置空间访问允许用户直接访问PCI配置空间。QEMU可以模拟设备的PCI配置。

### VFIO vs 传统Virtio

Virtio方式中，VM数据经过Guest驱动到Host virtio模块，再到QEMU，然后经过协议栈，最后到硬件。需要2-3次内存拷贝，中断经过复杂内核路径，延迟较高。

VFIO透传方式中，VM数据经过VFIO直接到硬件DMA，零拷贝，中断路径最短化，延迟极低。

### VFIO透传的数据流

```
QEMU (用户空间)
    │
    │ 打开 /dev/vfio/vfio
    │ 通过ioctl配置VFIO
    │ mmap BAR空间
    │
    ▼
VFIO内核驱动
    │
    │ 建立IOMMU映射 (VM内存 ↔ 设备IOVA)
    │ 配置MSI中断路由 (设备 → eventfd → QEMU)
    │
    ▼
SMMU/IOMMU (硬件)
    │
    │ IOVA → PA翻译
    │ 设备隔离
    │
    ▼
硬件设备
```

### VFIO快在哪里

零拷贝是最大的性能来源。数据直接在VM内存和硬件之间传输，不经过宿主机内核。不需要任何内存拷贝操作。

中断路径大幅缩短。传统方式需要5步以上，VFIO只需3步。VFIO几乎不做处理，只是转发。

绕过宿主机协议栈。硬件直接和VM通信，宿主机只做必要的配置和路由。

IOMMU保护仍然存在。不是"裸机透传"（危险），而是有IOMMU保护的透传。即使VM被攻击，也只能访问IOMMU授权的内存。

## 9. 内存映射的本质

### VFIO映射的不是"两块共享内存"

VFIO映射的内存并非两块不同的内存"共享"。而是**同一块物理内存被多个视角同时访问**。

QEMU分配给VM的内存同时是Host的进程内存，同时是设备的DMA目标。IOMMU建立映射：设备使用IOVA，翻译到同一块物理内存。

### 内存归属视角

Guest视角认为这是我的物理内存。Host视角认为这是QEMU的进程内存。设备视角通过IOVA访问这块内存。物理实际是同一块RAM。

### IOMMU的保护作用

VFIO透传不是"裸机透传"（危险）。有IOMMU保护的透传提供接近原生硬件的性能。保持虚拟化的安全隔离，即使VM被攻击也只访问授权内存。

## 10. PCIe总线基础

### TLP（Transaction Layer Packet）

所有设备通信的基础协议包。Memory Write TLP用于DMA数据写入和CQ更新。Memory Read TLP用于设备读取内存。Configuration Read/Write用于PCI枚举和配置。Completion用于响应读请求。MSI Interrupt也是一种Write TLP。

### 路由方式

Memory事务基于地址路由（目标内存PA）。Configuration事务基于总线/设备/功能号路由（BDF）。Interrupt消息基于MSI地址路由。

### PCIe空间划分

```
物理地址空间
┌─────────────────────────────────────┐
│         DRAM                        │  ← 系统内存
├─────────────────────────────────────┤
│     PCIe BAR 0 (设备A)             │
│   ┌───────────────────────────┐    │
│   │ 配置寄存器 │  门铃寄存器   │    │
│   └───────────────────────────┘    │
├─────────────────────────────────────┤
│     PCIe BAR 0 (设备B)             │
│   ┌───────────────────────────┐    │
│   │ 配置寄存器 │  门铃寄存器   │    │
│   └───────────────────────────┘    │
├─────────────────────────────────────┤
│     SMMU MMIO                     │
│   ┌───────────────────────────┐    │
│   │ Stream Table │ CMDQ │ ... │    │
│   └───────────────────────────┘    │
└─────────────────────────────────────┘
```

每个设备有独立的MMIO区域，包含配置寄存器和doorbell寄存器。不是所有设备共享一个doorbell页，而是每个设备有自己独立的doorbell区域。

## 11. 概念关系总览

### 数据流全景图

```
┌─────────────────────────────────────────────────────────────────────────┐
│  应用层                                                                  │
│    │                                                                     │
│    ▼                                                                     │
│  虚拟机 (Guest VM)                                                       │
│    │                                                                     │
│    ▼                                                                     │
│  VFIO / Virtio (用户空间)                                                │
│    │                        │                                           │
│    │                        │ ← 两种设备模型分叉                         │
│    │                        │                                           │
│    ▼                        ▼                                           │
│  Virtio Backend      VFIO Device                                       │
│  (模拟设备)           (透传设备)                                        │
│    │                        │                                           │
│    └────────────────────────┘                                           │
│              │                                                           │
│              ▼                                                           │
│  VFIO Framework (内核)                                                  │
│    │                        │                                           │
│    │                        │                                           │
│    ▼                        ▼                                           │
│  IOMMU / SMMU              ────────────────────────────────────────    │
│  (地址翻译 + 隔离)                    │                              │
│              │                        │                              │
│              ▼                        ▼                              │
│  PCIe / AMBA Bus                硬件设备                              │
│              │                        │                              │
│              └────────────────────────┘                              │
│                           │                                            │
│                           ▼                                            │
│                        内存 (DRAM)                                     │
└─────────────────────────────────────────────────────────────────────────┘
```

### 核心概念对比

| 概念 | 类比 | 实际角色 |
|------|------|----------|
| DMA | 软中断/后台任务 | 执行者，真正干活 |
| MSI中断 | 硬中断 | 通知者，告诉CPU干完了 |
| Doorbell | 任务队列通知 | 调度者，告诉DMA有新任务 |
| CQ | 进度表 | 让CPU知道进展 |
| IOMMU/SMMU | 交警 | 地址翻译和隔离 |
| VFIO | 桥梁 | 连接用户空间和硬件 |

### 优化思想

```
让擅长搬运的（DMA）专心搬运
让擅长计算的（CPU）只做计算
中间协调用最小最轻量的方式进行
    - SMMU地址翻译（硬件级，快）
    - VFIO用户空间路由（内核只转发，不处理）
    - MSI最小中断（只是敲门，不带大数据）
```

### 性能对比

| 指标 | Virtio | VFIO透传 | 提升 |
|------|--------|----------|------|
| 数据拷贝次数 | 2-3次 | 0次 | 零拷贝 |
| 中断路径 | 5+步 | 3步 | 大幅缩短 |
| 协议栈参与 | 是 | 否 | 绕过 |
| 延迟 | 10-50μs | 1-5μs | 10x |
| CPU开销 | 高 | 低 | 大量节省 |

### 适合VFIO的场景

VFIO适合高带宽场景（网络加速器、GPU、NVMe）和低延迟场景（金融交易、实时处理）。也适合大数据量场景（数据分析）。不适合小数据量高频场景（可能被IOMMU开销抵消）。
