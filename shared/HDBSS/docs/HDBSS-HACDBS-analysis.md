# HDBSS 与 HACDBS 技术分析

## 一、概述

| 特性 | 全称 | 作用 |
|------|------|------|
| **HDBSS** | Host Dirty Bit Storage | ARM64硬件特性，用于跟踪脏页（Dirty Page Tracking） |
| **HACDBS** | Hardware Accelerator for Clean Dirty Bit Storage | 硬件加速器，接收HDBSS entries并批量清除S2页表中的脏状态 |

**核心目的**：降低热迁移时Guest和Host的执行开销，相比现有的write-protect或扫描Stage2页表方法更高效。

---

## 二、与 Dirty Bitmap / Dirty Ring 的关系

### 2.1 层次关系

```
┌─────────────────────────────────────────────┐
│           热迁移 (Live Migration)            │
├─────────────────────────────────────────────┤
│                                             │
│   ┌─────────────┐    ┌─────────────────┐   │
│   │ Dirty Ring  │    │  Dirty Bitmap   │   │
│   │  (软件机制)  │    │   (软件机制)     │   │
│   └──────┬──────┘    └────────┬────────┘   │
│          │                    │             │
│          ▼                    ▼             │
│   ┌─────────────────────────────────────┐   │
│   │     HDBSS (硬件脏页跟踪)              │   │
│   │     提供底层脏页记录                   │   │
│   └──────────────────┬──────────────────┘   │
│                      │                      │
│                      ▼                      │
│   ┌─────────────────────────────────────┐   │
│   │     HACDBS (脏页清理硬件加速)          │   │
│   │     接收HDBSS entries，清除S2脏状态    │   │
│   └─────────────────────────────────────┘   │
│                                             │
└─────────────────────────────────────────────┘
```

### 2.2 协同工作方式

| 组件 | 职责 | 位置 |
|------|------|------|
| **Dirty Bitmap/Ring** | 向QEMU提供脏页信息用于迁移 | Kernel → QEMU |
| **HDBSS** | 硬件记录哪些页变脏了 | Guest → Hardware → Kernel |
| **HACDBS** | 接收HDBSS entries，清除S2页表中的脏状态 | Kernel → Hardware |

### 2.3 数据流对比

**传统方式 (无 HDBSS/HACDBS)**:
```
Guest写内存 → Page Fault → KVM设置dirty_bitmap位 → QEMU轮询获取
                                                      ↓
                                              迁移时扫描整个bitmap
                                                      ↓
                                              手动清除dirty位 (慢!)
```

**HDBSS + HACDBS 方式**:
```
Guest写内存 → HDBSS硬件自动记录脏页IPA → QEMU读取HDBSS buffer
                                              ↓
                               HACDBS批量清除S2页表脏状态 (快!)
```

---

## 三、HDBSS 实现详解

### 3.1 核心数据结构

```c
// 每VCPU的HDBSS状态
struct vcpu_hdbss_state {
    phys_addr_t base_phys;   // HDBSS buffer物理地址
    u32 size;                // buffer大小 (4KB-2MB)
    u32 next_index;          // 下一个待处理条目
};

// HDBSS寄存器
// HDBSSBR_EL2: Base Register - 存储buffer地址和大小
// HDBSSPROD_EL2: Producer Register - 跟踪写入位置
```

### 3.2 关键流程

#### 启用 HDBSS (通过 ioctl)
```
QEMU: KVM_CAP_ARM_HW_DIRTY_STATE_TRACK ioctl
    ↓
kvm_cap_arm_enable_hdbss()
    ↓
1. 为每个VCPU分配HDBSS buffer页
2. 设置VTCR_EL2的HD/HDBSS/HA位
3. 踢出所有VCPU使VTCR生效
```

#### HDBSS 记录脏页
```
Guest写内存 → Stage2 Page Fault
    ↓
user_mem_abort()
    ↓
如果 writable && enable_hdbss && logging_active:
    设置 PTE的DBM位 (Dirty Bit Modifier)
    ↓
DBM位让硬件自动跟踪 clean→dirty 转换
    ↓
脏页信息写入 HDBSS buffer
```

#### HDBSS Buffer 刷新
```
kvm_arch_sync_dirty_log() 或 vcpu_put()
    ↓
kvm_flush_hdbss_buffer(vcpu)
    ↓
读取HDBSS buffer → kvm_vcpu_mark_page_dirty()
    ↓
重置 HDBSSPROD_EL2
```

### 3.3 关键代码路径

```
arch/arm64/kvm/arm.c:
    kvm_cap_arm_enable_hdbss()     // 启用/禁用HDBSS
    kvm_arch_sync_dirty_log()      // 刷新dirty log

arch/arm64/kvm/mmu.c:
    user_mem_abort()               // 设置DBM位
    kvm_flush_hdbss_buffer()       // 刷新buffer

arch/arm64/kvm/hyp/vhe/switch.c:
    __load_hdbss()                 // 加载HDBSS寄存器

arch/arm64/kvm/hyp/pgtable.c:
    stage2_set_prot_attr()          // DBM属性设置
```

---

## 四、HACDBS 实现详解

### 4.1 核心概念

HACDBS 是 HDBSS 的**加速器**，接收HDBSS buffer中的脏页IPA列表，硬件批量清除S2页表中的脏状态。

**解决的问题**：
- HDBSS buffer 记录了哪些页变脏了，但清除这些脏状态需要遍历页表
- 传统清除脏位需要逐个页表项操作，慢！
- HACDBS 硬件批量处理 S2 页表，显著加速

### 4.2 关键数据结构

```c
// HACDBS寄存器
// HACDBSBR_EL2: Base Register - 输入buffer地址
// HACDBSCONS_EL2: Consumer Register - 输出状态/错误信息

enum hacdbs_status {
    HACDBS_OFF,      // 关闭
    HACDBS_IDLE,     // 空闲
    HACDBS_RUNNING,  // 运行中
    HACDBS_ERROR     // 错误
};

struct hacdbs {
    enum hacdbs_status status;
    int size;
};
DEFINE_PER_CPU(struct hacdbs, hacdbs_pcp);
```

### 4.3 HACDBS 清理脏页流程

**两个 buffer 的职责区分**：

| Buffer | 内容 | 谁清除 | 何时清除 |
|--------|------|--------|---------|
| **HDBSS buffer** | 脏页IPA列表 | 软件（读取后重置index） | 迁移迭代时 |
| **S2 PTE 脏状态** | 每页的DBM位 | HACDBS硬件 | HACDBS处理时 |

```
HDBSS buffer (软件管理)
    │
    │ 消耗 entries
    ▼
┌─────────────────────────────────────┐
│  HACDBS 硬件批量处理                 │
│                                     │
│  对每个IPA，遍历S2页表               │
│  清除脏位: DBM=0, S2AP_W=0           │
└─────────────────────────────────────┘
    │
    │ 清除的是 S2 PTE 中的脏状态
    ▼
  S2 PTE: Writable-Dirty → Writable-Clean
```

```c
dirty_bit_clear(kvm, hw_entries, size)
    ↓
1. preemp_disable()  // 禁用抢占（因为涉及S2页表）
2. 写HACDBS寄存器:
   - HACDBSBR_EL2 = HDBSS entries buffer地址
   - HACDBSCONS_EL2 = 0 (重置状态)
    ↓
3. HACDBS硬件遍历S2页表，清除脏状态
4. 等待HACDBSIRQ中断 (硬件完成或错误)
    ↓
5. post: 重新启用抢占
```

### 4.4 支持两种清理模式

HACDBS 可以同时加速 **Dirty Bitmap** 和 **Dirty Ring** 的清理：

#### 模式1: 加速 Dirty Bitmap 清理
```c
// kvm_get_dirty_log_protect() 或 kvm_clear_dirty_log_protect() 中调用
kvm_arch_dirty_log_clear()
    ↓
__kvm_arch_dirty_log_clear()
    ↓
bitmap → HDBSS entries → HACDBS批量处理
```

#### 模式2: 加速 Dirty Ring 清理
```c
// kvm_dirty_ring_reset() 中调用
kvm_arch_dirty_ring_clear()
    ↓
__kvm_arch_dirty_ring_clear()
    ↓
ring entries → HDBSS entries → HACDBS批量处理
```

---

## 五、架构特性要求

| 特性 | 要求 | 说明 |
|------|------|------|
| **HDBSS** | VHE模式 | 必须在EL2运行Linux |
| **HACDBS** | VHE模式 + 系统级支持 | 所有CPU都需要支持 |
| **FEAT_HAFDBS** | 基础特性 | Dirty Bit相关的硬件能力 |
| **FEAT_HDBSS** | ID_AA64MMFR1_EL1.HAFDBS == 0b0100 | HDBSS CPUID |
| **FEAT_HACDBS** | ID_AA64MMFR4_EL1.HACDBS | HACDBS CPUID |

---

## 六、与热迁移的关系

### 6.1 热迁移阶段

```
┌──────────────────────────────────────────────────┐
│                   热迁移流程                       │
├──────────────────────────────────────────────────┤
│                                                  │
│  1. 预迁移阶段                                    │
│     QEMU发起 KVM_CAP_ARM_HW_DIRTY_STATE_TRACK     │
│     → 启用HDBSS，开始硬件跟踪脏页                  │
│                                                  │
│  2. 迭代迁移阶段                                  │
│     dirty_ring_reap() / KVM_GET_DIRTY_LOG        │
│     → 获取脏页信息                                │
│     → HACDBS清除S2脏状态(加速)                    │
│     → 传输脏页到目标端                            │
│                                                  │
│  3. 迁移完成                                      │
│     禁用HDBSS                                     │
│     → HACDBS停止工作                              │
│                                                  │
└──────────────────────────────────────────────────┘
```

### 6.2 性能优势

| 对比项 | 传统方式 | HDBSS + HACDBS |
|--------|---------|----------------|
| 脏页标记 | Page Fault (每次写都trap) | DBM硬件自动跟踪 |
| 脏页获取 | 全量bitmap copy | 增量HDBSS buffer |
| 脏状态清除 | 逐页表项操作 | HACDBS批量清除S2脏状态 |
| CPU开销 | 高 | 低 |
| 迁移停顿 | 长 | 短 |

---

## 七、HDBSS 与 Dirty Ring 的兼容性问题

### 7.1 核心发现

**HDBSS v3 代码在 Dirty Ring 模式下存在问题**：

| 迁移模式 | HDBSS 能用吗？ | 原因 |
|---------|----------------|------|
| **Dirty Bitmap** | ✅ 可以 | HDBSS flush 到 bitmap，QEMU 读 bitmap |
| **Dirty Ring** | ❌ 不行 | HDBSS flush 到 bitmap，但 QEMU 读 ring，ring 为空 |

### 7.2 原因分析

#### 脏页记录路径不同

**Dirty Ring 模式**：
```
Guest写内存 → kvm_dirty_ring_push() → ring entries
                                            ↑
                              QEMU 消费这里
```

**HDBSS 模式**：
```
Guest写内存 → DBM硬件自动记录 → HDBSS buffer
                                    ↓
                         kvm_flush_hdbss_buffer()
                                    ↓
                         kvm_vcpu_mark_page_dirty() → dirty bitmap
```

#### HDBSS flush 只刷到 dirty bitmap

```c
void kvm_flush_hdbss_buffer(struct kvm_vcpu *vcpu)
{
    for (idx = 0; idx < curr_idx; idx++) {
        gpa = hdbss_buf[idx];
        kvm_vcpu_mark_page_dirty(vcpu, gpa >> PAGE_SHIFT);  // ← 只刷到 bitmap
    }
}
```

#### Ring reset 消费的是 ring entries

```c
int kvm_dirty_ring_reset(struct kvm *kvm, struct kvm_dirty_ring *ring, ...)
{
    while (likely((*nr_entries_reset) < INT_MAX)) {
        entry = &ring->dirty_gfns[...];
        // 读取 ring entry...
    }
}
```

**结果**：HDBSS 模式下 ring 永远是空的！

### 7.3 数据流对比

```
Dirty Bitmap 模式 + HDBSS：
    Guest写 → HDBSS buffer → flush → dirty bitmap → QEMU读bitmap ✅

Dirty Ring 模式 + HDBSS：
    Guest写 → HDBSS buffer → flush → dirty bitmap → QEMU读ring → 空！❌
```

### 7.4 结论

**HDBSS v3 和 Dirty Ring 是互斥的**：

1. HDBSS 只支持 dirty bitmap 模式
2. Dirty Ring 模式下，HDBSS 无法向 ring 推送 entries
3. Ring reset 时没有任何东西可消费

### 7.5 HACDBS 能解决吗？

**不能。** HACDBS 的 dirty ring 加速存在同样的问题：

```c
__kvm_arch_dirty_ring_clear()
{
    // 从 ring entries 读取
    for (i = 0; i < ring->size; i++) {
        entry = &ring->dirty_gfns[...];
        if (!kvm_dirty_gfn_harvested(entry))
            break;  // ← 遇到空就停止
        // ...
    }
    ret = dirty_bit_clear(kvm, hw_entries, i);
}
```

**HACDBS dirty ring 加速的前提**：
- Ring 有 entries（正常 dirty ring 模式）
- HACDBS 读取 entries，用硬件加速清除

**HDBSS 模式下**：
- Ring 为空（HDBSS 不调用 `kvm_dirty_ring_push()`）
- HACDBS 读不到任何 entry
- 直接返回 `ret = 0`，fallback 到软件清除

### 7.6 根本原因

**HDBSS 和 Dirty Ring 是两套独立的追踪机制**：

| 机制 | 脏页记录 | 数据存储 | 消费者 |
|------|---------|---------|--------|
| HDBSS | DBM 硬件自动 | HDBSS buffer | flush 到 bitmap |
| Dirty Ring | kvm_dirty_ring_push() | ring entries | ring reset |

**它们不共享数据**，所以：
- HDBSS flush 只刷到 dirty bitmap，Ring 收不到
- Ring reset 只能读 ring entries，HDBSS buffer 它读不了

### 7.7 总结

| 模式组合 | 能工作吗？ | 说明 |
|----------|-----------|------|
| Dirty Bitmap（无 HDBSS/HACDBS） | ✅ | 传统方式，软件清除 |
| Dirty Bitmap + HDBSS | ✅ | HDBSS 记录 + bitmap 获取 |
| Dirty Bitmap + HDBSS + HACDBS | ✅ | 最优：快速记录 + 快速清除 |
| Dirty Ring（无 HDBSS/HACDBS） | ✅ | 传统方式，软件清除 |
| Dirty Ring + HDBSS | ❌ | Ring 为空，无法工作 |
| Dirty Ring + HACDBS | ✅ | HACDBS 加速软件清除 |
| Dirty Ring + HDBSS + HACDBS | ❌ | Ring 为空，HACDBS 无用武之地 |

---

## 八、关键文件索引

### HDBSS 实现 (Huawei)
| 文件 | 说明 |
|------|------|
| `arch/arm64/kvm/arm.c` | HDBSS ioctl启用/禁用 |
| `arch/arm64/kvm/mmu.c` | DBM位设置, buffer刷新 |
| `arch/arm64/kvm/hyp/vhe/switch.c` | HDBSS寄存器加载 |
| `arch/arm64/include/asm/kvm_host.h` | HDBSS状态结构 |

### HACDBS 实现 (ARM)
| 文件 | 说明 |
|------|------|
| `arch/arm64/kvm/dirty_bit.c` | HACDBS核心逻辑 |
| `arch/arm64/include/asm/kvm_dirty_bit.h` | HACDBS头文件 |
| `include/linux/kvm_dirty_bit.h` | 通用接口定义 |
| `virt/kvm/kvm_main.c` | dirty_log接口集成 |
| `virt/kvm/dirty_ring.c` | dirty_ring接口集成 |

---

## 九、总结

1. **HDBSS** 是ARM64v9.5引入的硬件特性，用于**高效跟踪**哪些内存页被修改
2. **HACDBS** 是配合HDBSS的硬件加速器，**消耗HDBSS entries，清除S2页表中的脏状态**
3. 两者都基于**DBM (Dirty Bit Modifier)** 位实现
4. **HDBSS 只支持 Dirty Bitmap 模式**，与 Dirty Ring 不兼容
5. **HACDBS 的 Dirty Ring 加速仅适用于非 HDBSS 模式**的 Dirty Ring
6. 根本原因：HDBSS 和 Dirty Ring 是两套独立的追踪机制，**不共享数据**
7. 如需在 Dirty Ring 模式下使用 HDBSS，需要实现两者之间的数据共享机制

---

*整理时间：2026-05-07*
*补充更新：2026-05-07 (HDBSS与Dirty Ring兼容性分析)*
