# HACDBS (Hardware Accelerated Dirty-page Cleaning) 实现文档

## 基本信息

- **Patchset**: [PATCH v2 0/13] KVM Dirty-bit cleaning hw accelerator (HACDBS)
- **作者**: Leonardo Bras <leo.bras@arm.com>
- **日期**: 2026-06-29
- **Base**: Linux 7.2-rc1 (dc59e4fea9d8)
- **Link**: lore.kernel.org patchset
- **依赖**: FEAT_HDBSS (上游未合入), ACPI HACDBSIRQ 表项 (EDK2 spec 未合入)

## 概述

HACDBS 是 ARM64 架构的一项硬件特性 (FEAT_HACDBS)，其核心功能是将 KVM 虚拟化场景中**脏页跟踪 (dirty-page tracking)** 的清理工作从纯软件路径卸载到硬件执行。

KVM 中有两种脏页跟踪机制：
1. **Dirty-bitmap**：通过 bitmap 标记脏页，用于传统热迁移 (live migration)
2. **Dirty-ring**：通过环形缓冲区记录脏页 GFN，效率更高

HACDBS 对两种机制均提供硬件加速支持。硬件通过 HDBSS (Hardware Dirty State tracking Structure) 表项中指定的 IPA 列表，直接遍历 Stage-2 页表，将 `writable-dirty (S2AP[1]=0)` 的页表项改为 `writable-clean (S2AP[1]=1)`，完成脏页清理。

### 性能数据

测试基于 `dirty_log_perf_test`，在仿真器上的结果：

| 测试场景 | 1GB 内存 | 3GB 内存 |
|----------|----------|----------|
| dirty-bitmap (GET_DIRTY_LOG) | **82.19%** | **82.45%** |
| dirty-bitmap (CLEAR_DIRTY_LOG) | **81.74%** | **82.40%** |
| dirty-ring (RESET_DIRTY_RINGS) | **70.90%** | **70.92%** |

---

## 整体架构

```
用户态 (QEMU)
  │
  ├── ioctl(KVM_GET_DIRTY_LOG / KVM_CLEAR_DIRTY_LOG)
  │     ↓
  │   kvm_get_dirty_log_protect() / kvm_clear_dirty_log_protect()
  │     ↓
  │   kvm_arch_dirty_log_clear() ── arch hook ──┐
  │                                              │
  ├── ioctl(KVM_RESET_DIRTY_RINGS)               │
  │     ↓                                        │
  │   kvm_dirty_ring_reset()                     │
  │     ↓                                        │
  │   kvm_arch_dirty_ring_clear() ── arch hook ──┤
  │                                              │
  │                    ┌─────────────────────────┘
  │                    ↓
  │              arm64 实现
  │     ┌────────────────────────────┐
  │     │ kvm_arch_dirty_log_clear() │  kvm_arch_dirty_ring_clear()
  │     │  (条件检查: HACDBS IDLE    │  (条件检查: HACDBS IDLE
  │     │   + S2 DBM 支持)           │   + S2 DBM 支持)
  │     └────────────────────────────┘
  │                    ↓
  │          __kvm_arch_dirty_*_clear()
  │                    ↓
  │            dirty_bit_clear()
  │     ┌────────────────────────────┐
  │     │ 1. preempt_disable()       │
  │     │ 2. 临时开启 HCR_EL2.VM     │
  │     │ 3. __load_stage2(&mmu)     │
  │     │ 4. hacdbs_start(entries)   │  ← 配置 HACDBSBR_EL2
  │     │ 5. wfi() 循环等待          │  ← 等待 HACDBSIRQ 中断
  │     │ 6. hacdbs_stop()           │  ← 读 HACDBSCONS_EL2 获取结果
  │     │ 7. 恢复 HCR_EL2            │
  │     │ 8. preempt_enable()        │
  │     └────────────────────────────┘
  │                    ↓
  │         ┌── 成功: 返回已清理条目数
  │         └── 失败: 返回 -EAGAIN / -EFAULT → 走软件 fallback
```

---

## 13 个 Patch 详解

### 整体分层

| 层次 | Patch | 职责 |
|------|-------|------|
| 依赖预置 | Patch 1-2 | HDBSS cpufeature 检测、大页预拆分 |
| 硬件基础设施 | Patch 3-5 | HACDBS cpufeature 检测、sysreg 定义、ACPI 中断发现 |
| 核心引擎 | Patch 6 | HACDBS start/wait/stop 三段式硬件交互 |
| 通用层接口 | Patch 7, 11 | arch hook 插入 KVM dirty-bitmap / dirty-ring 路径 |
| arm64 后端 | Patch 8-9, 12 | dirty-bitmap 加速实现、dirty-ring 加速实现、大页拆分优化 |
| 辅助重构 | Patch 10 | dirty-ring 辅助函数提取以供 arch 层复用 |
| 总开关 | Patch 13 | 启用 CONFIG_HAVE_KVM_HW_DIRTY_BIT |

---

### Patch 1: KVM: arm64: HDBSS bits

**Commit**: `93ba64c74f25`

**作用**：预置 HDBSS cpufeature 基础设施，使后续 patch 可编译运行。

HDBSS (Hardware Dirty State tracking Structure) 是 HACDBS 的前置特性，其 CPUID 字段在 `ID_AA64MMFR1_EL1.HAFDBS` (bits 55-52)。本 patch 引入：

**修改文件**：

```
arch/arm64/include/asm/cpufeature.h    | 5 +++++
arch/arm64/include/asm/kvm_dirty_bit.h | 12 ++++++++++++  (新建)
arch/arm64/include/asm/kvm_pgtable.h   | 3 +++
arch/arm64/kernel/cpufeature.c         | 12 ++++++++++++
arch/arm64/kvm/Makefile                | 2 +-
arch/arm64/kvm/dirty_bit.c             | 16 ++++++++++++++++  (新建)
arch/arm64/kvm/hyp/pgtable.c           | 15 +++++++++++++--
arch/arm64/tools/cpucaps               | 1 +
```

**关键代码**：

1. **cpufeature 检测** (`arch/arm64/kernel/cpufeature.c`):

```c
static bool has_vhe_hdbss(const struct arm64_cpu_capabilities *entry, int cope)
{
    return is_kernel_in_hyp_mode() && has_cpuid_feature(entry, cope);
}

// 在 arm64_features[] 数组中注册:
{
    .desc = "Hardware Dirty state tracking structure (HDBSS)",
    .type = ARM64_CPUCAP_SYSTEM_FEATURE,
    .capability = ARM64_HAS_HDBSS,
    .matches = has_vhe_hdbss,
    ARM64_CPUID_FIELDS(ID_AA64MMFR1_EL1, HAFDBS, HDBSS)
},
```

> `has_vhe_hdbss` 确保只在 VHE (Virtualization Host Extensions, Linux 运行在 EL2) 模式下才使能 HDBSS，这是 HACDBS 正常工作的前提。

2. **查询函数** (`arch/arm64/include/asm/cpufeature.h`):

```c
static inline bool system_supports_hdbss(void)
{
    return cpus_have_final_cap(ARM64_HAS_HDBSS);
}
```

3. **S2 DBM 标志位** (`arch/arm64/include/asm/kvm_pgtable.h`):

```c
#define KVM_PTE_LEAF_ATTR_HI_S2_DBM    BIT(51)
```

Stage-2 页表项 bit[51] 是 DBM (Dirty Bit Management) 位。当硬件支持 DBM 时，写操作不会触发 Stage-2 fault，而是由硬件将 S2AP[1] 清零（标记为 dirty），HACDBS 负责将其恢复（clean）。

4. **Stub 文件** (`arch/arm64/kvm/dirty_bit.c`):
   创建空的 dirty_bit.c，仅包含 SPDX 和版权声明。

> **注意**：此 patch 标记为 "should not be merged upstream"，其内容应来自独立的 HDBSS patchset。作者在此处暂时包含了必要 bit 以满足编译依赖。

---

### Patch 2: KVM: arm64: Enable eager hugepage splitting if HDBSS is available

**Commit**: `d61344513a02`

**作用**：当系统支持 HDBSS 时，在 Stage-2 初始化时启用激进的大页预拆分 (eager hugepage splitting)。

**问题背景**：HDBSS 在硬件层面绕过传统内存缺页 (page fault) 路径，直接在跟踪结构体中写入脏页信息。这意味着对于 hugepages / THP 的**按需拆分 (on-demand splitting)** 机制将失效——不存在 page fault 可以触发拆分。

**解决方案**：在 Stage-2 MMU 初始化时，如果系统支持 HDBSS，直接开启 eager hugepage splitting，chunk 设为 `256 * 1024 * PAGE_SIZE`。

**修改文件**: `arch/arm64/kvm/mmu.c`

**关键代码**：

```c
int kvm_init_stage2_mmu(struct kvm *kvm, struct kvm_s2_mmu *mmu, unsigned long type)
{
    // ...
    for_each_possible_cpu(cpu)
        *per_cpu_ptr(mmu->last_vcpu_ran, cpu) = -1;

    /* The eager page splitting is disabled by default if system has no HDBSS */
    if (system_supports_hdbss())
        mmu->split_page_chunk_size = 256 * 1024 * PAGE_SIZE;
    else
        mmu->split_page_chunk_size = KVM_ARM_EAGER_SPLIT_CHUNK_SIZE_DEFAULT;

    mmu->split_page_cache.gfp_zero = __GFP_ZERO;
    // ...
}
```

**设计考量**：chunk = 256K * PAGE_SIZE，每次拆分以 256 个页为单位，在需要 reschedule 时主动让出 CPU，确保大页拆分不会长时间阻塞调度。

---

### Patch 3: arm64/cpufeature: Add system-wide FEAT_HACDBS detection

**Commit**: `d0f586286b3c`

**作用**：在 cpufeature 框架中注册 FEAT_HACDBS 的检测能力。

FEAT_HACDBS 的 CPUID 字段位于 `ID_AA64MMFR4_EL1[3:0]`，值为 `0b0001` 表示实现 (IMP)。

**修改文件**：

```
arch/arm64/include/asm/cpufeature.h | 5 +++++
arch/arm64/kernel/cpufeature.c      | 8 ++++++++
arch/arm64/tools/cpucaps            | 1 +
```

**关键代码**：

1. **ftr 字段注册** (`arch/arm64/kernel/cpufeature.c`):

```c
static const struct arm64_ftr_bits ftr_id_aa64mmfr4[] = {
    S_ARM64_FTR_BITS(FTR_HIDDEN, FTR_STRICT, FTR_LOWER_SAFE,
                     ID_AA64MMFR4_EL1_E2H0_SHIFT, 4, 0),
    ARM64_FTR_BITS(FTR_HIDDEN, FTR_STRICT, FTR_LOWER_SAFE,
                   ID_AA64MMFR4_EL1_NV_frac_SHIFT, 4, 0),
    ARM64_FTR_BITS(FTR_HIDDEN, FTR_STRICT, FTR_LOWER_SAFE,
                   ID_AA64MMFR4_EL1_HACDBS_SHIFT, 4, 0),  // NEW
    ARM64_FTR_END,
};
```

2. **system-wide capability 注册**：

```c
static const struct arm64_cpu_capabilities arm64_features[] = {
    // ...
    {
        .desc = "Hardware dirty bit Cleaning",
        .type = ARM64_CPUCAP_SYSTEM_FEATURE,
        .capability = ARM64_HACDBS,
        .matches = has_cpuid_feature,
        ARM64_CPUID_FIELDS(ID_AA64MMFR4_EL1, HACDBS, IMP)
    },
    // ...
};
```

- `ARM64_CPUCAP_SYSTEM_FEATURE`：要求所有 CPU 均具备此特性
- `.matches = has_cpuid_feature`：直接根据 CPUID 字段匹配 (IMP = 0b0001)

3. **查询函数** (`arch/arm64/include/asm/cpufeature.h`):

```c
static inline bool system_supports_hacdbs(void)
{
    return cpus_have_final_cap(ARM64_HACDBS);
}
```

---

### Patch 4: arm64/sysreg: Add HACDBS consumer and base registers

**Commit**: `a6e29c8b3710`

**作用**：在 arm64 sysreg 工具文件中定义 HACDBS 的两个 EL2 系统寄存器。

**修改文件**: `arch/arm64/tools/sysreg`

**关键代码**：

```asn
Sysreg  HACDBSBR_EL2       3   4   2   3   4
Res0    63:56
Field   55:12   BADDR               // 缓冲区物理基地址
Field   11      EN                  // 使能位
Res0    10:4
UnsignedEnum    3:0     SZ          // 缓冲区大小
    0b0000  4K
    0b0001  8K
    0b0010  16K
    0b0011  32K
    0b0100  64K
    0b0101  128K
    0b0110  256K
    0b0111  512K
    0b1000  1M
    0b1001  2M
EndEnum
EndSysreg

Sysreg  HACDBSCONS_EL2     3   4   2   3   5
UnsignedEnum    63:62   ERR_REASON      // 错误原因
    0b00    NOF             // No Fault — 处理完成
    0b01    STRUCTF         // Structure Fault — HDBSS 表项结构错误
    0b10    IPAF            // IPA Fault — 页表遍历错误
    0b11    IPAHACF         // IPA HAC Fault — 条目超出缓冲区范围
EndEnum
Res0    61:19
Field   18:0    INDEX                   // 故障条目索引 (出错时有效)
EndSysreg
```

**寄存器语义**：

| 寄存器 | 作用 |
|--------|------|
| `HACDBSBR_EL2` | 指定 HDBSS 条目数组的物理地址、大小和启动标志 |
| `HACDBSCONS_EL2` | 硬件回写：完成状态 (NOF) 或错误类型 + 出错条目索引 |

**使用流程**：
1. 软件在内存中构造 HDBSS 条目数组（每个 8 bytes）
2. 写 `HACDBSBR_EL2` 启动硬件遍历
3. 硬件遍历完成后产生 HACDBSIRQ 中断
4. 软件读 `HACDBSCONS_EL2` 获取结果

---

### Patch 5: KVM: arm64: Detect (via ACPI) and initialize HACDBSIRQ

**Commit**: `6a9f3446b706`

**作用**：通过 ACPI 发现并注册 HACDBSIRQ per-CPU 中断，引入 per-CPU 状态机管理。

**修改文件**：

```
arch/arm64/include/asm/acpi.h          |  3 ++
arch/arm64/include/asm/kvm_dirty_bit.h | 18 +++++++
arch/arm64/kvm/arm.c                   |  5 ++
arch/arm64/kvm/dirty_bit.c             | 97 +++++++++++++++++++++++++++
include/acpi/actbl2.h                  |  1 +
```

**关键代码**：

1. **Per-CPU 状态机** (`arch/arm64/include/asm/kvm_dirty_bit.h`):

```c
enum hacdbs_status {
    HACDBS_OFF,       // HACDBS 未初始化/CPU offline
    HACDBS_IDLE,      // 空闲，可接受新任务
    HACDBS_RUNNING,   // 正在执行硬件脏页清理
    HACDBS_ERROR      // 硬件报告错误
};

struct hacdbs {
    enum hacdbs_status status;
    int size;         // 预期处理的条目数
};

DECLARE_PER_CPU(struct hacdbs, hacdbs_pcp);
```

状态转移：
```
OFF ──(cpu_up)──→ IDLE ──(hacdbs_start)──→ RUNNING
                     ↑                          │
                     │              ┌───────────┤
                     │              ↓           ↓
                     └──(cpu_up)── IDLE    ERROR ──(cpu_up)──→ IDLE
                                    ↑
                              (cpu_down)
                                    │
                                    ↓
                                   OFF
```

2. **中断注册与处理** (`arch/arm64/kvm/dirty_bit.c`):

```c
void __init kvm_hacdbs_init(void)
{
    int irq;

    // 仅在系统支持 HACDBS 且运行在 VHE/EL2 模式时初始化
    if (!system_supports_hacdbs() || !is_kernel_in_hyp_mode())
        return;

    // 通过 ACPI 获取 HACDBSIRQ
    irq = hacdbs_acpi_get_irq();
    if (irq < 0)
        return;

    // 注册 per-CPU 中断
    if (request_percpu_irq(irq, hacdbsirq_handler, "HACDBSIRQ", &hacdbs_pcp) < 0)
        return;

    hacdbsirq = irq;
}
```

3. **ACPI 中断发现** (`arch/arm64/kvm/dirty_bit.c`):

```c
static int __init hacdbs_acpi_get_irq(void)
{
    struct acpi_madt_generic_interrupt *gicc;
    u32 gsi;
    int irq;

    gicc = acpi_cpu_get_madt_gicc(smp_processor_id());
    if (gicc->header.length < ACPI_MADT_GICC_HACDBSIRQ)
        return -ENXIO;

    gsi = gicc->hacdbsirq_gsi;

    irq = acpi_register_gsi(NULL, gsi, ACPI_LEVEL_SENSITIVE, ACPI_ACTIVE_HIGH);
    if (irq < 0) {
        pr_warn("ACPI: Unable to register HACDBS interrupt: %d\n", gsi);
        return -ENXIO;
    }

    return irq;
}
```

在 `include/acpi/actbl2.h` 中定义了 MADT GICC 结构的新字段：

```c
#define ACPI_MADT_GICC_HACDBSIRQ    (offsetof(struct acpi_madt_generic_interrupt, hacdbsirq_gsi) + 4)
```

4. **CPU 热插拔管理** (`arch/arm64/kvm/arm.c`):

```c
// CPU 上线时
kvm_hacdbs_cpu_up();    // enable_percpu_irq + 设置状态为 IDLE
// CPU 下线时
kvm_hacdbs_cpu_down();  // disable_percpu_irq + 设置状态为 OFF
```

---

### Patch 6: KVM: arm64: dirty_bit: Add base FEAT_HACDBS cleaning routine

**Commit**: `258107f1147f`

**作用**：实现 HACDBS 核心引擎 — start / wait / stop 三段式硬件交互循环。

**修改文件**: `arch/arm64/kvm/dirty_bit.c`

**关键代码**：

1. **HDBSS 条目格式定义**：

```c
#define HDBSS_ENTRY_VALID          BIT(0)        // bit[0]: 条目有效
#define HDBSS_ENTRY_TTWL_SHIFT     (1)
#define HDBSS_ENTRY_TTWL_MASK      (GENMASK(3, 1))
#define HDBSS_ENTRY_TTWL(x)        (((x) << 1) & GENMASK(3, 1))  // bits[3:1]: Table Table Walk Level
#define HDBSS_ENTRY_TTWL_RESV      HDBSS_ENTRY_TTWL(-4)   // reserved value, 用于停止标记
#define HDBSS_ENTRY_IPA            GENMASK_ULL(55, 12)    // bits[55:12]: Intermediate Physical Address
```

HDBSS 条目布局 (64-bit)：
```
+-----------+----------------+----------+---+---------+
| 63:56 RSV |  55:12  IPA     | 11:4 RSV |3:1|0 VALID |
|           |                 |          |TTWL|        |
+-----------+----------------+----------+---+---------+
```

2. **硬件启动 — `hacdbs_start()`**：

```c
static void hacdbs_start(u64 *hw_entries, int size)
{
    u64 br;
    int size_b = size * sizeof(hw_entries[0]);
    int size_p2 = max(roundup_pow_of_two(size_b), PAGE_SIZE);

    // 如果未填满缓冲区大小的幂，末尾放置停止标记
    if (size_b < size_p2)
        hw_entries[size] = HDBSS_ENTRY_VALID | HDBSS_ENTRY_TTWL_RESV;

    // 清零 consumer 寄存器的错误/索引字段
    sysreg_clear_set_s(SYS_HACDBSCONS_EL2,
                       HACDBSCONS_EL2_ERR_REASON | HACDBSCONS_EL2_INDEX, 0);

    // 构造 base register 值：物理地址 | 大小 | 使能
    br = (virt_to_phys(hw_entries) & HACDBSBR_EL2_BADDR_MASK) |
         FIELD_PREP(HACDBSBR_EL2_SZ, ilog2(size_p2) - 12) |
         FIELD_PREP(HACDBSBR_EL2_EN, 1);

    this_cpu_write(hacdbs_pcp.status, HACDBS_RUNNING);
    this_cpu_write(hacdbs_pcp.size, size);
    write_sysreg_s(br, SYS_HACDBSBR_EL2);
    isb();  // 保证写入对硬件可见
}
```

**关键细节**：
- `size_p2` 向上取整为 ≥ `size_b` 的 2 的幂（最小 PAGE_SIZE=4K）
- 参数 `size_p2 - 12` 输入给 `SZ` 字段是因为硬件按 `2^(SZ+12)` 字节解释
- 当 `size_b < size_p2` 时在末尾放一个 TTWL_RESV 标记位，硬件遇到后停止
- `isb()` 确保写入在硬件遍历开始前生效

3. **硬件停止 — `hacdbs_stop()`**：

```c
static int hacdbs_stop(void)
{
    write_sysreg_s(0, SYS_HACDBSBR_EL2);  // 清零使能位
    isb();

    if (this_cpu_read(hacdbs_pcp.status) == HACDBS_ERROR) {
        u64 cons = read_sysreg_s(SYS_HACDBSCONS_EL2);
        int idx = FIELD_GET(HACDBSCONS_EL2_INDEX, cons);
        this_cpu_write(hacdbs_pcp.status, HACDBS_IDLE);
        return idx;   // 返回故障条目索引
    }

    return this_cpu_read(hacdbs_pcp.size);  // 返回全部成功条目数
}
```

4. **核心循环 — `dirty_bit_clear()`**：

```c
static int dirty_bit_clear(struct kvm *kvm, u64 *hw_entries, int size)
{
    u64 hcr_el2;
    int ret;

    preempt_disable();

    // 临时开启 Stage-2 翻译，加载目标 VM 的页表
    hcr_el2 = read_sysreg(HCR_EL2);
    write_sysreg(hcr_el2 | HCR_EL2_VM, HCR_EL2);
    __load_stage2(&kvm->arch.mmu);

    hacdbs_start(hw_entries, size);

    // WFI 等待，hacdbsirq_handler 中断后将状态从 RUNNING 改为 IDLE/ERROR
    do {
        wfi();
    } while (this_cpu_read(hacdbs_pcp.status) == HACDBS_RUNNING);

    ret = hacdbs_stop();

    // 恢复 HCR_EL2
    write_sysreg(hcr_el2, HCR_EL2);
    isb();

    preempt_enable();
    return ret;
}
```

**为什么必须关抢占？**
- 在 `__load_stage2()` 到 HACDBS 完成之间，不能发生进程调度
- 调度到另一个 vCPU 会切换 Stage-2 页表，导致 HACDBS 访问错误的页表，可能损坏目标 VM 的脏页跟踪和调度到的 VM 的 S2 页表

---

### Patch 7: kvm: Add arch-generic interface for hw-accelerated dirty-bitmap cleaning

**Commit**: `cc3ee309608b`

**作用**：在 KVM 通用层 dirty-bitmap 清理路径中插入 arch hook。

**修改文件**：

```
include/linux/kvm_dirty_bit.h | 27 +++++++++++++++  (新建)
virt/kvm/Kconfig              |  3 +++
virt/kvm/kvm_main.c           | 13 +++++++-
```

**关键代码**：

1. **条件编译框架** (`include/linux/kvm_dirty_bit.h`):

```c
#ifndef CONFIG_HAVE_KVM_HW_DIRTY_BIT

// 架构未实现时：提供返回 -ENXIO 的 stub，编译器会优化掉整个调用
static inline int kvm_arch_dirty_log_clear(struct kvm *kvm, ...)
{
    return -ENXIO;
}

static inline int kvm_arch_dirty_ring_clear(struct kvm *kvm, ...)
{
    return -ENXIO;
}

#else /* CONFIG_HAVE_KVM_HW_DIRTY_BIT */

#include <asm/kvm_dirty_bit.h>  // 引入架构实现

#endif
```

2. **插入到 `kvm_get_dirty_log_protect()`** (`virt/kvm/kvm_main.c`):

```c
static int kvm_get_dirty_log_protect(struct kvm *kvm, struct kvm_dirty_log *log)
{
    // ...
    dirty_bitmap_buffer = kvm_second_dirty_bitmap(memslot);
    memset(dirty_bitmap_buffer, 0, n);

    // 优先尝试硬件加速
    if (kvm_arch_dirty_log_clear(kvm, memslot, NULL,
                                  dirty_bitmap_buffer, &flush) >= 0)
        goto out;    // 成功 → 跳过软件清理

    // 软件 fallback
    KVM_MMU_LOCK(kvm);
    for (i = 0; i < n / sizeof(long); i++) {
        // ... write-protect 脏页 ...
    }
    KVM_MMU_UNLOCK(kvm);

out:
    if (flush)
        kvm_flush_remote_tlbs_memslot(kvm, memslot);
    // ...
}
```

3. **插入到 `kvm_clear_dirty_log_protect()`**：

```c
static int kvm_clear_dirty_log_protect(struct kvm *kvm, ...)
{
    // ...
    if (copy_from_user(dirty_bitmap_buffer, log->dirty_bitmap, n))
        return -EFAULT;

    // 优先尝试硬件加速
    if (kvm_arch_dirty_log_clear(kvm, memslot, log, dirty_bitmap_buffer,
                                  &flush) >= 0)
        goto out;

    // 软件 fallback
    KVM_MMU_LOCK(kvm);
    for (...) {
        // ... write-protect 脏页 ...
    }
    KVM_MMU_UNLOCK(kvm);
out:
    // ...
}
```

**设计亮点**：通用层代码零侵入 — 架构未启用 `CONFIG_HAVE_KVM_HW_DIRTY_BIT` 时完全不改变运行时行为。

---

### Patch 8: KVM: arm64: Add hardware-accelerated dirty-bitmap cleaning routine

**Commit**: `6fb5c6f5b195`

**作用**：实现 arm64 侧 bitmap 脏页清理的硬件加速完整流程。这是整个 patchset 中最核心、代码量最大的 patch (~175 行新增)。

**修改文件**：

```
arch/arm64/include/asm/kvm_dirty_bit.h |  24 ++++++
arch/arm64/kvm/dirty_bit.c             | 146 +++++++++++++++++++++++++
arch/arm64/kvm/mmu.c                   |   4 +-
include/linux/kvm_host.h               |   3 +
```

**入口条件检查** (`arch/arm64/include/asm/kvm_dirty_bit.h`):

```c
static inline bool kvm_arch_dirty_clear_enabled(struct kvm *kvm)
{
    return this_cpu_read(hacdbs_pcp.status) == HACDBS_IDLE &&   // HACDBS 空闲
           (kvm->arch.mmu.pgt->flags & KVM_PGTABLE_S2_DBM);     // S2 支持 DBM
}

static inline int kvm_arch_dirty_log_clear(struct kvm *kvm,
                                            struct kvm_memory_slot *memslot,
                                            struct kvm_clear_dirty_log *log,
                                            unsigned long *bitmap,
                                            bool *flush)
{
    if (!kvm_arch_dirty_clear_enabled(kvm))
        return -EPERM;    // 不满足条件 → 走软件

    return __kvm_arch_dirty_log_clear(kvm, memslot, log, bitmap, flush);
}
```

**Bitmap → HDBSS 转换辅助函数** (`arch/arm64/kvm/dirty_bit.c`):

```c
// 将 bitmask 中的 set bits 转换为 HDBSS 条目
static inline int mask_to_hdbss(unsigned long *mask, u64 *hw_entries,
                                const gfn_t offset, u64 ttwl,
                                int idx, int entries_sz)
{
    while (idx < entries_sz) {
        int j = __ffs(*mask);                            // 找到第一个 set bit
        u64 a = gfn_to_gpa(offset + j);                  // GFN → GPA

        hw_entries[idx++] = (a & HDBSS_ENTRY_IPA) |      // IPA bits
                             ttwl |                       // Table walk level
                             HDBSS_ENTRY_VALID;           // Valid

        *mask &= ~BIT(j);                                 // 清除已转换的 bit
        if (!*mask)
            break;
    }
    return idx;
}

// 将 HDBSS 条目回写到 dirty-bitmap (错误恢复用)
static inline void hdbss_to_bitmap(u64 *hdbss_array, int start, int end,
                                    unsigned long *dirty_bitmap,
                                    unsigned long long offset)
{
    u64 w = (gpa_to_gfn(hdbss_array[start]) - offset) / BITS_PER_LONG;
    u64 mask = 0;
    int idx = start;

    do {
        u64 entry = (gpa_to_gfn(hdbss_array[idx]) - offset);
        if (entry / BITS_PER_LONG == w) {
            mask |= BIT(entry % BITS_PER_LONG);
        } else {
            atomic_long_or(mask, (atomic_long_t *)&dirty_bitmap[w]);
            w = entry / BITS_PER_LONG;
            mask = BIT(entry % BITS_PER_LONG);
        }
    } while (++idx < end);
    atomic_long_or(mask, (atomic_long_t *)&dirty_bitmap[w]);
}
```

**主清理函数 — `__kvm_arch_dirty_log_clear()`**:

```c
int __kvm_arch_dirty_log_clear(struct kvm *kvm,
                                struct kvm_memory_slot *memslot,
                                struct kvm_clear_dirty_log *log,
                                unsigned long *bitmap,
                                bool *flush)
{
    int ret = 0, idx = 0;
    unsigned long *dirty_bitmap = memslot->dirty_bitmap;
    u64 *hw_entries;
    const int entries_sz = PAGE_SIZE / sizeof(*hw_entries);  // 512 条目/页
    u64 ttwl = HDBSS_ENTRY_TTWL(KVM_PGTABLE_LAST_LEVEL);
    u64 start, end;
    gfn_t base_gfn;
    gpa_t split_end = 0;

    hw_entries = kmalloc_objs(u64, entries_sz, GFP_KERNEL);
    if (!hw_entries)
        return -ENOMEM;

    // 计算遍历范围
    if (log) {
        start = log->first_page / BITS_PER_LONG;
        end = start + DIV_ROUND_UP(log->num_pages, BITS_PER_LONG);
        base_gfn = memslot->base_gfn + log->first_page % BITS_PER_LONG;
    } else {
        start = 0;
        end = kvm_dirty_bitmap_bytes(memslot) / sizeof(long);
        base_gfn = memslot->base_gfn;
    }

    write_lock(&kvm->mmu_lock);

    for (unsigned long i = start; i < end; i++) {
        unsigned long mask;
        gfn_t offset;
        atomic_long_t *p;

        // 原子地读取并清理 dirty-bitmap
        if (log) {
            mask = bitmap[i];
            if (!mask) continue;
            p = (atomic_long_t *)&dirty_bitmap[i];
            mask &= atomic_long_fetch_andnot(mask, p);  // clear and fetch
        } else {
            if (!dirty_bitmap[i]) continue;
            mask = xchg(&dirty_bitmap[i], 0);           // atomic swap
            bitmap[i] = mask;
        }

        if (!mask) continue;

        offset = base_gfn + i * BITS_PER_LONG;

        // manual_protect 模式下拆分大页 (优化在 Patch 9)
        if (kvm_dirty_log_manual_protect_and_init_set(kvm) &&
            (offset + BITS_PER_LONG > split_end)) {
            gpa_t start = gfn_to_gpa(offset + __ffs(mask));
            gpa_t end = gfn_to_gpa(offset + __fls(mask) + 1);
            kvm_mmu_split_huge_pages(kvm, start, end);
            split_end = gpa_to_gfn(ALIGN_DOWN(end, PMD_SIZE) + PMD_SIZE - 1);
        }

        // 逐 bit 转换为 HDBSS 条目，满一页提交一次
        do {
            idx = mask_to_hdbss(&mask, hw_entries, offset, ttwl,
                                idx, entries_sz);
            if (idx >= entries_sz) {
                ret = dirty_bit_clear(kvm, hw_entries, idx);
                *flush = *flush || ret > 0;
                if (ret != idx) {
                    atomic_long_or(mask, (atomic_long_t *)&dirty_bitmap[i]);
                    goto out_err;
                }
                idx = 0;
            }
        } while (mask);
    }

    // 提交最后一批未满的条目
    if (idx != 0) {
        ret = dirty_bit_clear(kvm, hw_entries, idx);
        *flush = *flush || ret > 0;
    }

out_err:
    if (unlikely(ret != idx)) {
        // 错误恢复：未处理的条目回写 bitmap → 软件 fallback
        if (ret < idx)
            hdbss_to_bitmap(hw_entries, ret, idx, dirty_bitmap,
                            memslot->base_gfn);
        ret = -EAGAIN;
    }

    write_unlock(&kvm->mmu_lock);
    kfree(hw_entries);
    return ret;
}
```

**流程总结**：
```
遍历 bitmap → mask_to_hdbss(条目转换) → 填满 PAGE_SIZE batch
    → dirty_bit_clear(HACDBS 硬件清理) → 成功: 继续; 失败: 回写 + 软件 fallback
```

对于 `kvm_mmu_split_huge_pages()`，去除了 static 限定并暴露到 `include/linux/kvm_host.h`，使其可被 dirty_bit.c 调用。

---

### Patch 9: KVM: arm64: Dirty-bitmap: avoid splitting previously split blocks

**Commit**: `d441445db658`

**作用**：优化 Patch 8 中的大页拆分逻辑，避免对已被前一轮 `kvm_mmu_split_huge_pages()` 拆分过的区域重复调用。

**修改文件**: `arch/arm64/kvm/dirty_bit.c`

**变更前**：
```c
if (kvm_dirty_log_manual_protect_and_init_set(kvm))
    kvm_mmu_split_huge_pages(kvm,
                             gfn_to_gpa(offset + __ffs(mask)),
                             gfn_to_gpa(offset + __fls(mask) + 1));
```
每轮 bitmap 迭代都调用拆分。

**变更后**：
```c
// 新变量
gpa_t split_end = 0;

// 在循环中：
if (kvm_dirty_log_manual_protect_and_init_set(kvm) &&
    (offset + BITS_PER_LONG > split_end)) {
    gpa_t start = gfn_to_gpa(offset + __ffs(mask));
    gpa_t end = gfn_to_gpa(offset + __fls(mask) + 1);

    kvm_mmu_split_huge_pages(kvm, start, end);
    split_end = gpa_to_gfn(ALIGN_DOWN(end, PMD_SIZE) + PMD_SIZE - 1);
}
```

**机制**：引入 `split_end` 追踪上一个已拆分区间的末端 GFN：
```
         PMD_SIZE (2M)              PMD_SIZE (2M)
    ├─────────────────────┼─────────────────────┤
    │ 已拆分               │                     │
    │                      │   offset 落在此区间  │
    │ split_end ──────────┤  时需要再次拆分      │
    └──────────────────────┴─────────────────────┘
```

只有当 `offset + BITS_PER_LONG > split_end`（即当前 bitmask 跨越了上次拆分的边界）时才触发新的拆分调用。`ALIGN_DOWN(end, PMD_SIZE) + PMD_SIZE - 1` 将 `split_end` 对齐到下一个 PMD_SIZE 边界。

---

### Patch 10: kvm/dirty_ring: Introduce get_memslot and move helpers to header

**Commit**: `a257f6291f96`

**作用**：重构 dirty-ring 辅助函数，为后续 arch 层实现提供必要的基础设施。

**修改文件**：

```
include/linux/kvm_dirty_ring.h | 12 ++++++++++++
virt/kvm/dirty_ring.c          | 30 ++++++++++++++++--------------
```

**关键变更**：

1. **抽取 `kvm_dirty_ring_get_memslot()`** 为公开接口：

```c
// virt/kvm/dirty_ring.c
struct kvm_memory_slot *kvm_dirty_ring_get_memslot(struct kvm *kvm, u32 slot)
{
    int as_id = slot >> 16;
    int id = (u16)slot;

    if (as_id >= kvm_arch_nr_memslot_as_ids(kvm) ||
        id >= KVM_USER_MEM_SLOTS)
        return NULL;

    return id_to_memslot(__kvm_memslots(kvm, as_id), id);
}
```

同时在头文件中声明。

2. **提取 inline 辅助函数到 header** (`include/linux/kvm_dirty_ring.h`):

```c
static inline bool kvm_dirty_gfn_harvested(struct kvm_dirty_gfn *gfn)
{
    return smp_load_acquire(&gfn->flags) & KVM_DIRTY_GFN_F_RESET;
}

static inline void kvm_dirty_gfn_set_invalid(struct kvm_dirty_gfn *gfn)
{
    smp_store_release(&gfn->flags, 0);
}
```

这些函数原本是 `static` 在 `virt/kvm/dirty_ring.c` 中，移到 header 后 arch 层（`arch/arm64/kvm/dirty_bit.c`）可以直接使用。

---

### Patch 11: kvm/dirty_ring: Add arch-generic interface for hw-accelerated dirty-ring cleaning

**Commit**: `11c67b125158`

**作用**：与 Patch 7 对称，在 dirty-ring 重置路径中插入 arch hook。

**修改文件**：

```
include/linux/kvm_dirty_bit.h | 7 +++++++
virt/kvm/dirty_ring.c         | 4 ++++
```

**关键代码** (`virt/kvm/dirty_ring.c`):

```c
int kvm_dirty_ring_reset(struct kvm *kvm, struct kvm_dirty_ring *ring,
                          int *nr_entries_reset)
{
    lockdep_assert_held(&kvm->slots_lock);

    // 优先尝试硬件加速
    if (kvm_arch_dirty_ring_clear(kvm, ring, nr_entries_reset) >= 0)
        return 0;    // 成功 → 跳过软件清理

    // 软件 fallback：逐项 kvm_reset_dirty_gfn()
    while (likely((*nr_entries_reset) < INT_MAX)) {
        if (signal_pending(current))
            return -EINTR;
        // ...
    }
}
```

---

### Patch 12: KVM: arm64: Add hardware-accelerated dirty-ring cleaning routine

**Commit**: `097b2939b738`

**作用**：实现 arm64 侧 dirty-ring 脏页清理的硬件加速。

**修改文件**：

```
arch/arm64/include/asm/kvm_dirty_bit.h | 13 +++++++
arch/arm64/kvm/dirty_bit.c             | 66 ++++++++++++++++++++++
```

**入口** (`arch/arm64/include/asm/kvm_dirty_bit.h`):

```c
static inline int kvm_arch_dirty_ring_clear(struct kvm *kvm,
                                             struct kvm_dirty_ring *ring,
                                             int *nr_entries_reset)
{
    if (!kvm_arch_dirty_clear_enabled(kvm))
        return -EPERM;

    return __kvm_arch_dirty_ring_clear(kvm, ring, nr_entries_reset);
}
```

**主清理函数 — `__kvm_arch_dirty_ring_clear()`** (`arch/arm64/kvm/dirty_bit.c`):

```c
int __kvm_arch_dirty_ring_clear(struct kvm *kvm, struct kvm_dirty_ring *ring,
                                 int *nr_entries_reset)
{
    u64 *hw_entries;
    u64 slot_offset = 0;
    u64 ttwl = HDBSS_ENTRY_TTWL(KVM_PGTABLE_LAST_LEVEL);
    int i, ret;
    u32 slot = -1;

    if (signal_pending(current))
        return -EINTR;

    // 分配足够容纳 ring 全部条目的缓冲区
    hw_entries = kmalloc(max(ring->size * sizeof(u64), PAGE_SIZE), GFP_KERNEL);
    if (!hw_entries)
        return -ENOMEM;

    // 遍历 dirty-ring，将 harvested entries 转为 HDBSS 条目
    for (i = 0; i < ring->size; i++) {
        struct kvm_dirty_gfn *entry;
        gfn_t gfn;

        entry = &ring->dirty_gfns[(ring->reset_index + i) &
                                   (ring->size - 1)];

        if (!kvm_dirty_gfn_harvested(entry))
            break;    // 遇到非 harvested entry → 停止

        // 跨 slot 时更新 slot_offset
        if (entry->slot != slot) {
            struct kvm_memory_slot *memslot;
            memslot = kvm_dirty_ring_get_memslot(kvm, entry->slot);
            slot = entry->slot;
            slot_offset = memslot->base_gfn;
        }

        gfn = slot_offset + entry->offset;

        // 构造 HDBSS 条目
        hw_entries[i] = (gfn_to_gpa(gfn) & HDBSS_ENTRY_IPA) |
                         ttwl | HDBSS_ENTRY_VALID;
    }

    // 一次提交给 HACDBS 硬件处理
    ret = dirty_bit_clear(kvm, hw_entries, i);

    // 只将成功清理的条目标记为 invalid
    for (int j = 0; j < ret; j++) {
        struct kvm_dirty_gfn *entry;
        entry = &ring->dirty_gfns[(ring->reset_index + j) &
                                   (ring->size - 1)];
        kvm_dirty_gfn_set_invalid(entry);    // flags = 0
    }

    // 更新 reset_index：跳转到第一个未处理的条目
    ring->reset_index += ret;
    *nr_entries_reset += ret;

    kfree(hw_entries);

    if (ret < i)
        return -EFAULT;    // 部分失败 → 软件 fallback 从未处理条目继续

    return ret;
}
```

**与 bitmap 版本的关键差异**：

| 维度 | Dirty-bitmap (Patch 8) | Dirty-ring (Patch 12) |
|------|----------------------|----------------------|
| 数据来源 | `memslot->dirty_bitmap[]` | `ring->dirty_gfns[]` |
| 条目格式 | bitmap bit → GPA | entry.offset + slot.base_gfn → GPA |
| 批次大小 | PAGE_SIZE (512 条目) | 整个 ring (size 条) 一次提交 |
| 错误恢复 | 回写 bitmap → 软件重试 | reset_index 前移 → 软件从未处理条目继续 |
| 并发安全 | `write_lock(&kvm->mmu_lock)` | 由 `slots_lock` 保护 |

---

### Patch 13: KVM: arm64: Enable KVM_HW_DIRTY_BIT

**Commit**: `d37a1136928c`

**作用**：总开关 — 在 Kconfig 中启用 `HAVE_KVM_HW_DIRTY_BIT`。

**修改文件**: `arch/arm64/kvm/Kconfig`

```diff
 menuconfig KVM
     select HAVE_KVM_IRQ_BYPASS
     select HAVE_KVM_READONLY_MEM
     select HAVE_KVM_VCPU_RUN_PID_CHANGE
+    select HAVE_KVM_HW_DIRTY_BIT if ACPI
     select SCHED_INFO
     select GUEST_PERF_EVENTS if PERF_EVENTS
     select KVM_GUEST_MEMFD
```

**条件**：仅在 `ACPI` 使能时选中（因为 HACDBSIRQ 依赖 ACPI 发现）。这使 `CONFIG_HAVE_KVM_HW_DIRTY_BIT=y`，从而：
- `include/linux/kvm_dirty_bit.h` 中的 arch hook stub 被替换为真实的 arm64 实现
- `virt/kvm/kvm_main.c` 和 `virt/kvm/dirty_ring.c` 中的 `kvm_arch_dirty_*_clear()` 调用不再编译为 `return -ENXIO`

---

## 中断处理流程

```c
static irqreturn_t hacdbsirq_handler(int irq, void *pcpu)
{
    u64 cons = read_sysreg_s(SYS_HACDBSCONS_EL2);
    unsigned long err = FIELD_GET(HACDBSCONS_EL2_ERR_REASON, cons);

    switch (err) {
    case HACDBSCONS_EL2_ERR_REASON_NOF:
        // NO Fault: 成功完成
        this_cpu_write(hacdbs_pcp.status, HACDBS_IDLE);
        break;

    case HACDBSCONS_EL2_ERR_REASON_IPAHACF:
        // IPA HAC Fault: 条目索引超出缓冲区
        // 检查是否是真的错误 vs 停止标记 (TTWL_RESV) 被触发
        int index = FIELD_GET(HACDBSCONS_EL2_INDEX, cons);
        if (index >= this_cpu_read(hacdbs_pcp.size)) {
            // 索引 >= 实际条目数 → 停止标记被到达 → 正常完成
            this_cpu_write(hacdbs_pcp.status, HACDBS_IDLE);
            break;
        }
        fallthrough;

    case HACDBSCONS_EL2_ERR_REASON_STRUCTF:
        // Structure Fault: HDBSS 条目结构无效
    case HACDBSCONS_EL2_ERR_REASON_IPAF:
        // IPA Fault: 页表遍历失败
        this_cpu_write(hacdbs_pcp.status, HACDBS_ERROR);
        break;
    }

    return IRQ_HANDLED;
}
```

**关键逻辑**：`IPAHACF` 有两种含义：
1. 真正的 HACDBS 处理错误 (索引 < size) → 标记 ERROR
2. 遇到 TTWL_RESV 停止标记 (索引 >= size) → 标记 IDLE (正常完成)

这是硬件利用 TTWL_RESV 条目的自然行为。

---

## 文件修改汇总

```
新文件 (3):
  arch/arm64/include/asm/kvm_dirty_bit.h  — arm64 HACDBS 接口定义
  include/linux/kvm_dirty_bit.h           — 通用层 arch hook 框架
  arch/arm64/kvm/dirty_bit.c              — HACDBS 核心实现 (411 行)

修改文件 (17):
  arch/arm64/include/asm/acpi.h           — ACPI HACDBSIRQ 声明
  arch/arm64/include/asm/cpufeature.h     — system_supports_hdbss/hacdbs()
  arch/arm64/include/asm/kvm_pgtable.h    — S2_DBM 标志位
  include/acpi/actbl2.h                   — HACDBSIRQ GICC 长度宏
  include/linux/kvm_dirty_ring.h          — dirty-ring 辅助函数公开
  include/linux/kvm_host.h                — kvm_mmu_split_huge_pages() 声明
  arch/arm64/kernel/cpufeature.c          — HDBSS + HACDBS cpufeature 注册
  arch/arm64/kvm/arm.c                    — CPU 热插拔 HACDBS 管理
  arch/arm64/kvm/hyp/pgtable.c            — S2 DBM flag 传递到页表
  arch/arm64/kvm/mmu.c                    — eager hugepage splitting + 函数去 static
  virt/kvm/dirty_ring.c                   — dirty-ring reset 插入 arch hook + 重构
  virt/kvm/kvm_main.c                     — dirty-bitmap 路径插入 arch hook
  arch/arm64/kvm/Kconfig                  — 启用 HAVE_KVM_HW_DIRTY_BIT
  arch/arm64/kvm/Makefile                 — 添加 dirty_bit.o 编译
  arch/arm64/tools/cpucaps                — HDBSS + HACDBS capability ID
  arch/arm64/tools/sysreg                 — HACDBSBR_EL2 + HACDBSCONS_EL2 定义
  virt/kvm/Kconfig                        — HAVE_KVM_HW_DIRTY_BIT config 选项
```

---

## 故障容错设计

HACDBS 实现的容错策略是 **fail-safe with software fallback**：

```
硬件加速尝试
  ├── 条件不满足 (HACDBS OFF/ERROR, S2 无 DBM)
  │     → -EPERM → 跳过 → 纯软件路径
  │
  ├── 条件满足 → 硬件清理
  │     ├── 完全成功 → 返回已清理条目数
  │     │
  │     ├── 部分失败 (dirty-bitmap)
  │     │     → hdbss_to_bitmap() 回写未处理条目
  │     │     → 返回 -EAGAIN → 通用层走软件路径
  │     │
  │     └── 部分失败 (dirty-ring)
  │           → reset_index 定位到未处理条目
  │           → 返回 -EFAULT → 软件从故障点继续
  │
  └── 内存分配失败
        → -ENOMEM → 返回 → 软件路径
```

---

## 前置条件清单

HACDBS 硬件加速实际生效需要满足所有以下条件：

1. **硬件支持**：所有 CPU 的 `ID_AA64MMFR4_EL1.HACDBS == 0b0001`
2. **HDBSS 支持**：所有 CPU 的 `ID_AA64MMFR1_EL1.HAFDBS == 0b0101` (FEAT_HDBSS)
3. **HAFDBS 支持**：`ID_AA64MMFR1_EL1.HAFDBS` 指示 DBM 支持
4. **VHE 模式**：Linux 运行在 EL2 (`is_kernel_in_hyp_mode()`)
5. **ACPI 中断**：MADT GICC 表项包含有效的 `hacdbsirq_gsi`
6. **中断注册成功**：`request_percpu_irq()` 成功
7. **Per-CPU IDLE**：当前 CPU 的 `hacdbs_pcp.status == HACDBS_IDLE`
8. **S2 DBM**：Stage-2 页表设置了 `KVM_PGTABLE_S2_DBM` flag

---

## 参考链接

- HDBSS patchset: https://lore.kernel.org/lkml/20260225040421.2683931-1-zhengtian10@huawei.com/
- HACDBSIRQ ACPI spec proposal: https://github.com/tianocore/edk2/issues/12409
- v1 patchset: https://lore.kernel.org/all/20260430111424.3479613-2-leo.bras@arm.com/
- Eager splitting improvements: https://lore.kernel.org/all/20260618131447.764085-1-leo.bras@arm.com/
