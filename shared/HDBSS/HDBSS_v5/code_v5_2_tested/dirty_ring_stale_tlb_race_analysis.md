# Dirty Ring + HDBSS 竞态窗口分析

## 问题现象

在 dirty ring 的 4KB 页测试场景 (`rand_ring2048_lazy_4k_bw800`) 中，目标 VM
在迁移后约 298 秒崩溃。huge 页和 THP 透明大页场景不受影响。不加 HDBSS 特性
的内核在相同场景下不会崩溃。

## 崩溃症状

```
[02:59:30] starting source ... vm start cost time: 1 ms
[  298.003793] recvmsg bug 2: copied BD61E65F seq 893F5899 rcvnxt BD61E664 fl 0
[  298.003932] Unable to handle kernel NULL pointer dereference at virtual address 00000000
[  298.003936] Mem abort info:
[  298.003941]   Exception class = IABT (current EL), IL = 32 bits
[  298.004097] PC is at 0x0
[  298.004098] LR is at 0x0
[  298.004099] x29: 0000000000000040
[  298.004132] x9-x14: 7878787878787878 (六个连续寄存器)
[  298.004250] Kernel panic - not syncing: Fatal exception
```

- **IABT at PC=0, LR=0**: 函数返回地址或函数指针被 corruption 成 0
- **recvmsg bug 2**: TCP 缓冲区数据页内容不正确 (序列号差距约 870MB)
- **x9-x14 = 0x78...**: 整页被某模式覆写，CPU 从该页 load 数据到寄存器
- **298s 后崩溃**: 需要多轮 dirty ring reset 累积损坏
- 崩溃发生在**目标 VM**，意味着 QEMU 拷贝了错误/陈旧的数据


## 三态脏跟踪模型 (HDBSS)

在启用 HDBSS 时 (dirty logging 开始后自动启用)，stage-2 PTE 使用由
DBM (bit 51) 和 S2AP_W/Dirty (bit 7) 控制的三态模型：

| 状态      | DBM | Dirty | 含义                              |
|-----------|-----|-------|-----------------------------------|
| N (None)  | 0   | 0     | 只读，写 → permission fault        |
| C (Clean) | 1   | 0     | 可写-干净，写 → 硬件 C→D，HDBSS 记录 |
| D (Dirty) | 1   | 1     | 可写-脏，写 → 不产生新 HDBSS 记录   |


## 完整调用栈

### 路径 1: HDBSS 脏页记录 (异步)

```
Guest 写页 P (State C: DBM=1, S2AP_W=0)
└─ 硬件 C→D 转换
   ├─ PTE: S2AP_W 0→1 (硬件设置)
   └─ HDBSS buffer 写入 P 的 GPA
      └─ [P 已脏，但 ring 里还没有 entry！]

     ┌───────────── 异步延迟窗口 ─────────────┐
     │  HDBSS buffer 中的 entry 等待 VM exit   │
     │  在此期间 P 是 State D，再写不触发 C→D   │
     └────────────────────────────────────────┘

vCPU exit (任何原因: IRQ/timer/ring full/...)
└─ kvm_flush_hdbss_buffer()              [arm.c:1490-1491]
   ├─ prod = read_sysreg_s(SYS_HDBSSPROD_EL2)
   ├─ curr_idx = HDBSSPROD_IDX(prod)
   ├─ for idx in [0, curr_idx):
   │  ├─ gpa = hdbss_buf[idx]
   │  ├─ if (gpa & HDBSS_ENTRY_VALID):
   │  │    gpa &= HDBSS_ENTRY_IPA
   │  │    └─ kvm_vcpu_mark_page_dirty(vcpu, gpa >> PAGE_SHIFT)  [dirty_bit.c:97]
   │  │       └─ mark_page_dirty_in_slot()           [kvm_main.c:3517]
   │  │          └─ kvm_dirty_ring_push(vcpu, slot, rel_gfn)      [kvm_main.c:3536]
   │  │             ├─ entry->slot = slot
   │  │             ├─ entry->offset = rel_gfn
   │  │             ├─ smp_wmb()
   │  │             ├─ kvm_dirty_gfn_set_dirtied(entry)
   │  │             ├─ ring->dirty_index++
   │  │             └─ if soft full: kvm_make_request(KVM_REQ_DIRTY_RING_SOFT_FULL)
   └─ prod &= ~INDEX_MASK; write_sysreg_s(prod, ...)  [重置 buffer index]
```

### 路径 2: 传统模式脏页记录 (同步，无 HDBSS)

```
Guest 写页 P (S2AP_W=0, DBM=1 但 inert)
└─ Permission fault (S2AP_W=0 → 不可写)
   └─ user_mem_abort()                     [mmu.c:2105]
      ├─ kvm_s2_fault_compute_prot()       [mmu.c:1966]
      │  └─ if write_fault && memslot_is_logging:
      │       *prot |= KVM_PGTABLE_PROT_W  [设为可写]
      ├─ kvm_s2_fault_map()                [mmu.c:2017]
      │  └─ kvm_pgtable_stage2_map()       [映射为 State D: DBM=1, S2AP_W=1]
      └─ mark_page_dirty_in_slot()         [mmu.c:2097 ← 同步 push 到 ring!]
         └─ kvm_dirty_ring_push()
```

### 路径 3: Dirty Ring 收割/Reset 路径

```
QEMU: ioctl(KVM_RESET_DIRTY_RINGS)
└─ kvm_vm_ioctl_reset_dirty_pages()               [kvm_main.c:4999]
   ├─ mutex_lock(&kvm->slots_lock)
   │
   │  ※ 没有调用 kvm_arch_sync_dirty_log()!
   │  ※ 对比 bitmap 路径 (kvm_main.c:2248) 有调用
   │  ※ 其他 vCPU 仍在 guest 中，HDBSS buffer 有未 flush 的 entry
   │
   ├─ kvm_for_each_vcpu(i, vcpu, kvm):
   │  └─ kvm_dirty_ring_reset()                    [dirty_ring.c:110]
   │     └─ while (harvested entries exist):
   │        ├─ entry = &ring->dirty_gfns[reset_index]
   │        ├─ kvm_dirty_gfn_set_invalid(entry)    [entry 标记已消费]
   │        ├─ ring->reset_index++
   │        │
   │        ├─ cond_resched()                      [dirty_ring.c:163]
   │        │  ※ 此时其他 vCPU 可能在 guest 中运行
   │        │  ※ TLB 尚未 flush (flush 在函数最末尾)
   │        │
   │        ├─ [batch coalescing: 累积 mask]
   │        │
   │        └─ kvm_reset_dirty_gfn(kvm, slot, offset, mask)  [dirty_ring.c:190]
   │           ├─ id_to_memslot()
   │           ├─ offset/npages 边界检查
   │           ├─ KVM_MMU_LOCK(kvm)                [写锁]
   │           ├─ kvm_arch_mmu_enable_log_dirty_pt_masked()  [mmu.c:1326]
   │           │  ├─ start = (base_gfn + __ffs(mask)) << PAGE_SHIFT
   │           │  ├─ end   = (base_gfn + __fls(mask)+1) << PAGE_SHIFT
   │           │  │
   │           │  ├─ kvm_stage2_wp_range(start, end)  [按范围，非按 mask]
   │           │  │  └─ stage2_attr_walker()        [pgtable.c:1231]
   │           │  │     ├─ pte &= ~S2AP_W           [清 Dirty bit]
   │           │  │     ├─ if block: pte &= ~DBM    [→ State N (RO)]
   │           │  │     └─ if page: 保留 DBM        [→ State C (W-Clean)]
   │           │  │
   │           │  ├─ kvm_mmu_split_huge_pages()     [如果 INITIALLY_SET]
   │           │  │  └─ 内部有 write_unlock + cond_resched + write_lock
   │           │  └─ kvm_nested_s2_wp()
   │           │
   │           └─ KVM_MMU_UNLOCK(kvm)
   │
   ├─ mutex_unlock(&kvm->slots_lock)
   │
   └─ kvm_flush_remote_tlbs(kvm)                    [在锁外，带 KVM_REQUEST_WAIT]
      ※ 此时才 kick vCPU 退出 guest
      ※ vCPU exit path: kvm_flush_hdbss_buffer()   [arm.c:1490]
      ※ 但 HDBSS flush 在 local_irq_enable() 之后 (IPI ack 之后)
```


## 完整竞态时序分析

```
GUEST WRITE
    │
    ▼ (DBM 硬件, State C→D)
HDBSS buffer entry (GPA + VALID bit)
    │
    ▼ (VM exit 时, arm.c:1490-1491)
kvm_flush_hdbss_buffer()
    │  for each valid entry:
    │    gpa &= HDBSS_ENTRY_IPA
    ▼
kvm_vcpu_mark_page_dirty(vcpu, gfn)     ← dirty_bit.c:97
    │
    ▼
mark_page_dirty_in_slot()               ← kvm_main.c:3517
    │  if (kvm->dirty_ring_size && vcpu):
    ▼
kvm_dirty_ring_push(vcpu, slot, rel_gfn) ← dirty_ring.c:223
    │  ring->dirty_index++
    │  if (kvm_dirty_ring_soft_full):
    │    kvm_make_request(KVM_REQ_DIRTY_RING_SOFT_FULL)
    ▼
下次 vcpu_enter_guest → check_vcpu_requests()
    │  kvm_dirty_ring_check_request()     ← arm.c:1237
    │  → vcpu->run->exit_reason = KVM_EXIT_DIRTY_RING_FULL
    │  → return 0 (exit to QEMU)
    ▼
USERSPACE: 收集 dirty ring entries, 拷贝对应页到目的端
    │  ※ 此时页仍 State D, 其他 vCPU 仍可写
    │  ※ 拷贝的是快照, 没问题——下一轮还会再拷贝
    ▼
USERSPACE: KVM_RESET_DIRTY_RINGS ioctl
    │  ※ 从拷贝到 wrprotect 期间, 页可能被重写
    │  ※ 但这些页在 ring 里已标记脏, 下一轮会重新拷贝
    ▼
kvm_vm_ioctl_reset_dirty_pages()         ← kvm_main.c:4999
    │  mutex_lock(&kvm->slots_lock)
    │  ※ 没有调用 kvm_arch_sync_dirty_log()!
    │  ※ 其他 vCPU 仍在 guest 中, HDBSS buffer 有未 flush 的 entry
    │
    │  for each vcpu:
    │    kvm_dirty_ring_reset()           ← dirty_ring.c:110
    │      → 逐个 entry: kvm_dirty_gfn_set_invalid() [标记已消费]
    │      → cond_resched()               ← dirty_ring.c:163 [yield CPU!]
    │      → kvm_reset_dirty_gfn()
    │        → KVM_MMU_LOCK
    │        → kvm_arch_mmu_enable_log_dirty_pt_masked()  ← mmu.c:1326
    │           → kvm_stage2_wp_range()    ← PTE: D→C (清 S2AP_W, 保留 DBM)
    │        → KVM_MMU_UNLOCK
    │  mutex_unlock(&kvm->slots_lock)
    │
    │  *** 竞态窗口 ***
    │  vCPU 仍在 guest 模式, TLB 缓存 State D (S2AP_W=1)
    │  写操作: TLB 说 D → 无 C→D 转换 → HDBSS 不记录
    │  ring entry 已被消费 → 无安全网
    │  cond_resched 放大了这个窗口
    │
    ▼
kvm_flush_remote_tlbs(kvm)              ← 在 slots_lock 外!
    │  TLB flush 在所有 ring reset 完成后才执行
    │  带 KVM_REQUEST_WAIT, 等 vCPU 退出 guest
    │  但 HDBSS flush 在 IPI ack 之后 (arm.c:1490 在 local_irq_enable 之后)
    │
    ▼
下一轮迭代:
    │  竞态窗口内被写的页没有新 dirty entry (HDBSS 没记录)
    │  → QEMU 认为该页 clean → 不拷贝
    │  → 目标 VM 保持旧副本
    │
    │  ※ 若 TLB flush 后该页再次被写 → C→D → HDBSS 记录 → 恢复 ✓
    │  ※ 若竞态窗口内的写是该页最后一次写 → 永久丢失 ✗
    │    (该页内容已变, 但无人知道; 传统模式同样存在此场景)
```


## 竞态窗口的两层分析

### 第一层: stale TLB 窗口

```
wrprotect: PTE D→C (内存中)
     ↓ ← stale TLB 仍为 D
vCPU 写 P → TLB(D) → 无 C→D → HDBSS 不记录
     ↓
TLB flush → PTE C 生效
     ↓
vCPU 写 P → C→D → HDBSS 记录 → 下轮捕获 ✓
```

这是所有 dirty ring + wrprotect 的通病 (传统模式也有)。

### 第二层: HDBSS buffer 异步延迟 (延迟一轮, 可恢复)

```
TLB flush 后, vCPU 写 P → C→D → HDBSS buffer 记录
     ↓
但 vCPU 还没 exit → HDBSS entry 在 buffer 中, 不在 ring 中
     ↓
如果下一轮 KVM_RESET_DIRTY_RINGS 在 vCPU exit 之前到来:
    → P 不在 ring → 不 wrprotect → P 保持 State D
    → 后续写 P → 无 C→D → 不记录
    → 本轮 QEMU 不拷贝 P ← 本轮"丢失"
     ↓
但 vCPU 下次 exit (IRQ/timer/bitmap sync kick) 时:
    → HDBSS flush → P push 到 ring
    → 下轮 reap → P 被收割 → QEMU 拷贝 P (最新内容)
    → 恢复, 无永久丢失 ✓
```

这是 HDBSS 特有的——传统模式下写 fault 是同步 push 到 ring，没有
buffer 延迟。**但该延迟只推迟一轮收割，不产生永久丢失**（除非迁移
在 vCPU exit 前终止——而最后一轮有 kick 兜底，见 QEMU 侧分析）。


## 为什么传统模式 (无 HDBSS) 不崩溃

|              | 传统模式 (无 HDBSS)         | HDBSS 模式                  |
|--------------|------------------------------|------------------------------|
| 脏页记录方式 | write fault → 同步 push ring | C→D → HDBSS buffer → exit 时 push ring |
| 第一层窗口   | 存在 (stale TLB)             | 存在 (stale TLB)             |
| 第二层窗口   | **不存在** (同步 push)       | **存在** (等 vCPU exit)      |
| TLB flush 后写入 | 立即 fault → 立即 push ring | C→D → HDBSS buffer → 等 exit |

传统模式下，TLB flush 后的任何写入都能立即被 ring 捕获 (同步 fault +
push)，不依赖 vCPU 是否 exit。HDBSS 模式下，TLB flush 后的写入需要等
vCPU exit 才能进 ring。

> **注意**: 第二层窗口的存在是事实，但它只导致延迟一轮收割（可恢复），
> 单独不足以解释永久性数据丢失。传统模式与 HDBSS 模式的**真正差异**
> 尚未确认，见"当前分析状态与未解问题"。当前最可疑的候选是第一层
> (stale TLB) 的**触发概率差异**：HDBSS 模式下无 fault 开销、guest 全速
> 运行、reset 频率约高 25% (soft_limit 1472 vs 1984)，且每次 reset 的
> 竞态窗口被 cond_resched 放大——累积概率可能高出传统模式几个数量级。


## 为什么 dirty bitmap 模式不崩溃

dirty bitmap 路径有调用 `kvm_arch_sync_dirty_log()`:

```
kvm_get_dirty_log_protect()             [kvm_main.c:2222]
├─ kvm_arch_sync_dirty_log(kvm, memslot)  [kvm_main.c:2248]
│  └─ kvm_vcpu_kick(vcpu)               [kick 所有 vCPU 退出]
│     → vCPU exit → kvm_flush_hdbss_buffer() → set_bit_le(bitmap, gfn)
├─ xchg(&dirty_bitmap[i], 0)            [取出并清零]
├─ kvm_arch_mmu_enable_log_dirty_pt_masked()
└─ kvm_flush_remote_tlbs_memslot()
```

dirty bitmap 路径有调用 `kvm_arch_sync_dirty_log`，kick vCPU 退出，flush
HDBSS buffer 到 bitmap。即使 stale TLB 窗口内写入不记录，bitmap 的累积性
(set_bit_le 幂等) 也能在下一轮捕获。

dirty ring 路径 (内核侧 `kvm_vm_ioctl_reset_dirty_pages`) 没有调用
`kvm_arch_sync_dirty_log`，且 ring 是消费型数据结构 (entry 被收割后即
消失)，没有累积性兜底。

> **补充**: QEMU 侧对 dirty ring 的补偿——迁移 bitmap sync 路径
> (`kvm_log_sync_global` → `kvm_dirty_ring_flush` →
> `kvm_cpu_synchronize_kick_all`) 在 reap 前会同步 kick 所有 vCPU，
> 效果等价于 `kvm_arch_sync_dirty_log`。但 ring full handler 和
> reaper thread 两条路径没有该补偿。详见"QEMU 侧 Dirty Ring Reap
> 路径分析"。


## 为什么 huge/THP 不出问题

- **4K 页**: ring 填满快 (每 ~8MB 脏页)，reset 频率高，HDBSS buffer 有
  未 flush 条目的概率大
- **2MB block**: ring 填满慢 (每 ~4GB 脏页)，reset 频率低，vCPU 通常已
  exit 过，buffer 已 flush


## 对比 x86

### x86 PML 模式: D-bit 不被 TLB 缓存影响

x86 EPT 的 D-bit (Dirty bit) 有特殊语义：即使 TLB 缓存了 D=1，CPU 写入时
仍会检查 EPT PTE 的 D-bit 是否为 0 来决定是否记录 PML log。EPT 的 D-bit
不被 TLB 缓存影响——这是 x86 硬件保证的。

x86 PML 模式 reset 时只清 D-bit (不清 W-bit)：

```c
// x86: PML 模式只清 D-bit, 不需要 TLB flush
if (kvm->arch.cpu_dirty_log_size)
    kvm_mmu_clear_dirty_pt_masked();   // 清 D-bit
else
    kvm_mmu_write_protect_pt_masked(); // 清 W-bit
```

```c
// spte.h:546 — x86 判断是否需要 TLB flush
static inline bool leaf_spte_change_needs_tlb_flush(u64 old, u64 new)
{
    return is_mmu_writable_spte(old) && !is_mmu_writable_spte(new);
}
```

PML 模式清 D-bit 不动 Writable bit → 返回 false → 不需要 TLB flush。

### x86 dirty ring reset 是否有同样的 sync 缺失

x86 的 `kvm_vm_ioctl_reset_dirty_pages` 同样没有调用
`kvm_arch_sync_dirty_log`。但 x86 PML buffer 在每次 VM exit 时的
`vmx_flush_pml_buffer` (vmx.c:6723) 中被 flush，且 PML 模式下 D-bit 清除
不需要 TLB flush，所以不存在 stale TLB 丢失写入的问题。

### x86 的两道防线

1. PML 模式下清 D-bit 不需要 TLB flush (D-bit 不被 TLB 缓存影响)
2. TDP MMU 的 `cond_resched` 前先 flush TLB (tdp_mmu.c:777-778)


## 修复方案 (加固措施, 非确认的根因修复)

> **注意**: 以下方案 C 消除的是"stale TLB 窗口 + HDBSS buffer 异步延迟"
> 两个已确认的竞态放大因素。但根据 QEMU 侧分析，两者单独都不足以解释
> 永久性数据丢失 (最后一轮有 kick 兜底、迭代轮延迟可恢复)。方案 C 是
> 必要的加固，但根因确认需结合"待验证的假设"中的调试手段。

### 方案 C: 调整 HDBSS flush 时机 + dirty ring reset 前加 sync

#### 改动 1: arm64 guest exit 路径 (arch/arm64/kvm/arm.c:1479-1491)

将 `kvm_flush_hdbss_buffer()` 从 `local_irq_enable()` **之后** 移到
**之前**，确保 `KVM_REQ_OUTSIDE_GUEST_MODE` 的 IPI ack 返回时 HDBSS buffer
已 flush:

**当前代码:**

```c
        guest_timing_exit_irqoff();

        local_irq_enable();          // ← IPI handler 在这里执行 (ack_kick)

        trace_kvm_exit(ret, ...);

        if (vcpu_hdbss_enabled(vcpu))
            kvm_flush_hdbss_buffer(vcpu);   // ← 在 IPI ack 之后
```

**改为:**

```c
        guest_timing_exit_irqoff();

        /*
         * Drain the HDBSS buffer before re-enabling interrupts, so
         * that KVM_REQ_OUTSIDE_GUEST_MODE callers are guaranteed the
         * buffer has been flushed to the dirty ring by the time their
         * IPI ack returns.
         */
        if (vcpu_hdbss_enabled(vcpu))
            kvm_flush_hdbss_buffer(vcpu);   // ← 在 IPI ack 之前

        local_irq_enable();          // ← IPI handler 在这里执行 (ack_kick)

        trace_kvm_exit(ret, ...);
```

#### 改动 2: dirty ring reset 路径 (virt/kvm/kvm_main.c:5008)

在 ring reset 之前加 `KVM_REQ_OUTSIDE_GUEST_MODE`:

**当前代码:**

```c
    mutex_lock(&kvm->slots_lock);

    kvm_for_each_vcpu(i, vcpu, kvm) {
        r = kvm_dirty_ring_reset(vcpu->kvm, &vcpu->dirty_ring, &cleared);
        ...
    }

    mutex_unlock(&kvm->slots_lock);
    if (cleared)
        kvm_flush_remote_tlbs(kvm);
```

**改为:**

```c
    mutex_lock(&kvm->slots_lock);

    /*
     * Force all vCPUs out of guest mode and wait for them to exit.
     * With the HDBSS buffer drain moved before local_irq_enable() in
     * the arm64 exit path, this guarantees all hardware dirty buffers
     * are flushed to the dirty ring before harvesting entries.
     */
    kvm_make_all_cpus_request(kvm, KVM_REQ_OUTSIDE_GUEST_MODE);

    kvm_for_each_vcpu(i, vcpu, kvm) {
        r = kvm_dirty_ring_reset(vcpu->kvm, &vcpu->dirty_ring, &cleared);
        ...
    }

    mutex_unlock(&kvm->slots_lock);
    if (cleared)
        kvm_flush_remote_tlbs(kvm);
```

### 修复后的时序

```
kvm_vm_ioctl_reset_dirty_pages()
  ├─ mutex_lock(&kvm->slots_lock)
  │
  ├─ kvm_make_all_cpus_request(kvm, KVM_REQ_OUTSIDE_GUEST_MODE)
  │  │  ※ KVM_REQUEST_WAIT → smp_call_function_many(wait=true)
  │  │
  │  ├─ [对每个 IN_GUEST_MODE 的 vCPU]
  │  │  ├─ cmpxchg(IN_GUEST_MODE → EXITING_GUEST_MODE)
  │  │  ├─ 发 IPI 到 vCPU 所在 CPU
  │  │  │
  │  │  │  [vCPU 侧 exit path（改动后）]:
  │  │  │  ├─ guest exit (IPI 触发)
  │  │  │  ├─ vcpu->mode = OUTSIDE_GUEST_MODE     [arm.c:1429]
  │  │  │  ├─ PMU/VGIC/timer sync
  │  │  │  ├─ guest_timing_exit_irqoff()
  │  │  │  ├─ kvm_flush_hdbss_buffer(vcpu)         [← 改动1：在 IPI ack 之前!]
  │  │  │  │  └─ HDBSS entries → kvm_dirty_ring_push() → ring
  │  │  │  ├─ local_irq_enable()                   [← IPI handler 执行 ack_kick]
  │  │  │  └─ trace_kvm_exit(...)
  │  │  │
  │  │  └─ smp_call_function_many 返回 (ack 收到)
  │  │     ※ 此时 HDBSS buffer 已 flush 到 ring!
  │  │
  │  └─ [对已 OUTSIDE_GUEST_MODE 的 vCPU]
  │     └─ mode == OUTSIDE_GUEST_MODE → 不发 IPI，不等待
  │        ※ 见下方"残留竞态"分析
  │
  ├─ kvm_for_each_vcpu: kvm_dirty_ring_reset()
  │  └─ 所有 HDBSS 中的脏页已在 ring 里 → harvest + wrprotect
  │
  ├─ mutex_unlock(&kvm->slots_lock)
  └─ kvm_flush_remote_tlbs(kvm)
```

### kvm_flush_hdbss_buffer 在中断关闭下是否安全

`kvm_flush_hdbss_buffer` 做的操作:

| 操作                          | 中断关闭下安全性                    |
|-------------------------------|-------------------------------------|
| read_sysreg_s / write_sysreg_s | 寄存器读写，安全                    |
| page_address()                | 指针运算，安全                      |
| srcu_read_lock()              | SRCU 读锁支持中断关闭上下文 (SRCU 相比 RCU 的核心优势) |
| kvm_vcpu_mark_page_dirty()    | 写预分配 ring 内存 + kvm_make_request (置 bit)，安全 |
| srcu_read_unlock()            | 安全                                |

结论: 中断关闭下调用安全。

### 残留竞态

`kvm_request_needs_ipi` (kvm_main.c:195-196):

```c
if (req & KVM_REQUEST_WAIT)
    return mode != OUTSIDE_GUEST_MODE;
```

如果 vCPU 在 `kvm_make_all_cpus_request` 检查时已经是
`OUTSIDE_GUEST_MODE` (自行 exit 了)，不发 IPI、不等待。但此时 vCPU 可能
正在 `vcpu->mode = OUTSIDE_GUEST_MODE` (arm.c:1429) 和
`kvm_flush_hdbss_buffer` 之间:

```
vCPU 侧:
  vcpu->mode = OUTSIDE_GUEST_MODE   [arm.c:1429]  ← A
  PMU/VGIC/timer sync                ← B
  guest_timing_exit_irqoff()         ← C
  kvm_flush_hdbss_buffer()           [改动后位置]  ← D

caller 侧:
  kvm_make_all_cpus_request()
    → 检查 vcpu->mode == OUTSIDE_GUEST_MODE → 不发 IPI
  kvm_dirty_ring_reset()
    → 遍历该 vCPU 的 ring → 看不到 HDBSS 中的 entry
```

如果 caller 在 A 和 D 之间检查 vCPU 的 ring，HDBSS entry 未 flush，会漏掉。

但这个窗口极窄: A→D 之间只有 PMU/VGIC/timer sync (微秒级)，且 vCPU 在这
期间不会重入 guest (必须走完 exit path 才能回 while 循环顶部)。

### 对比当前代码的窗口

|              | 当前代码                       | 方案 C                           |
|--------------|--------------------------------|----------------------------------|
| 竞态窗口     | PTE 改完到最终 TLB flush (**秒级**，被 cond_resched 放大) | vCPU 自行 exit 的 A→D 之间 (**微秒级**) |
| HDBSS buffer sync | **完全没有**              | 有 (对 IN_GUEST_MODE 的 vCPU 完全覆盖) |
| 改善         | —                              | 窗口缩小 ~10^6 倍，且只影响自行 exit 的 vCPU |

### 是否影响 x86

`KVM_REQ_OUTSIDE_GUEST_MODE` 在 x86 上只是强制 vCPU exit guest mode，x86
的 `vmx_flush_pml_buffer` 在 `__vmx_handle_exit` 中 (IPI ack 之后) 执行。
改动 2 不会让 x86 PML buffer 在 IPI ack 前 flush——但这无害，因为 x86 PML
模式下 dirty ring reset 只清 D-bit (不清 W-bit)，stale TLB 下写入虽然不
记录 PML，但页仍然可写，下一轮会被捕获。额外的一次 IPI 只是微小性能
开销。


## 数据丢失场景分析 (已修正)

### 场景: HDBSS buffer 中的脏页在 ring reset 时未被收割

```
第 N 轮:
  1. P 被写脏 → 在 ring 里 → harvest → wrprotect → State C
  2. QEMU 拷贝 P (内容=版本A) 到目标 VM

第 N+1 轮:
  3. vCPU2 写 P → C→D → HDBSS buffer 记录 P (内容=版本B)
  4. P 在 vCPU2 的 HDBSS buffer 中, 不在 ring 中
  5. vCPU1 的 ring 满 → QEMU 调 KVM_RESET_DIRTY_RINGS (无 kick)
  6. P 不在 ring 中 → 不被 wrprotect → 仍 State D
  7. vCPU2 写 P (内容=版本C) → State D → 不记录
  8. QEMU harvest ring → P 不在 dirty set → QEMU 不拷贝 P
     ← 本轮看似"丢失"

第 N+2 轮 (兜底):
  9. vCPU2 exit (IRQ/timer/bitmap sync kick) → HDBSS flush → P push 到 ring
  10. QEMU reap → P 在 dirty set → QEMU 拷贝 P (内容=版本C, 最新)
      ← 本轮恢复, 无永久丢失 ✓
```

**结论: 该场景不致命。** HDBSS buffer 中的 entry 只延迟一轮，vCPU 下次
exit 即 flush 到 ring，下一轮 reap 恢复。QEMU 拷贝的是物理页当前内容，
包含所有中间写入。

### 为什么最后一轮也不会丢

`ram_save_complete` → `kvm_dirty_ring_flush()` →
`kvm_cpu_synchronize_kick_all()` (run_on_cpu 同步等待)，且 VM 在此之前
已被 `migration_stop_vm` 停止 (所有 vCPU 退出 KVM_RUN → HDBSS 全部
flush)。最后一轮有 kick 兜底，见"QEMU 侧 Dirty Ring Reap 路径分析"。

### 排除"最后一轮没有出口"假设

| 假设                                | 验证结果                     |
|-------------------------------------|------------------------------|
| 最后一轮缺 sync → HDBSS 页永久丢失 | **不成立**: 最后一轮有 kick + VM 已停 |
| 迭代轮 HDBSS 延迟 → 数据丢失       | **不成立**: 延迟一轮被恢复    |
| mask-based wrprotect 是根因         | **不成立**: 实测未修复        |


## 当前分析状态与未解问题

### 已确认的事实

1. 崩溃仅在 HDBSS + 4K 页 + dirty ring 场景出现
2. 无 HDBSS、或 huge/THP 场景不崩溃
3. mask-based wrprotect 不能修复 (实测)
4. 崩溃在目标 VM，说明 QEMU 拷贝了陈旧数据
5. 最后一轮迁移有 kick 兜底，安全
6. 迭代轮的 HDBSS buffer 延迟只延迟一轮，不永久丢失
7. stale TLB 窗口 (wrprotect 后到 TLB flush 前) 在 HDBSS 和传统模式下
   都存在

### 关键悖论

**同步跟踪 (fault-based) 不崩溃，异步跟踪 (HDBSS) 崩溃**——但异步延迟
本身已被证明不丢数据。两者的差异点只剩:

| 差异点                            | HDBSS (崩溃)             | 传统 (不崩溃)            |
|-----------------------------------|--------------------------|--------------------------|
| wrprotect 后 PTE 状态             | State C (W-Clean, DBM=1) | RO (S2AP_W=0, DBM inert) |
| wrprotect 后写入记录方式          | C→D → HDBSS buffer (异步)| permission fault (同步)  |
| ring 填充速度                     | 快 (无 fault 开销)        | 慢 (每次写 fault)        |
| reset 频率 (本测试)               | ~100 次/秒               | 更低                     |
| soft_limit                        | 2048-576=1472            | 2048-64=1984             |

### 待验证的假设 (按优先级)

1. **stale TLB 窗口 + "最后一次写"概率**: 窗口内写入若恰为该页最后一
   次写且 TLB flush 后无新写入，则永久丢失。HDBSS 模式 reset 频率高
   (~100/s)、窗口被 cond_resched 放大，概率远高于传统模式。但传统模式
   理论上同样存在，为何不崩溃需解释——可能只是概率低到测不出来。

2. **硬件 PTE 更新与软件 wrprotect 的竞争**: HDBSS 开启时硬件会自主
   修改 PTE (C→D 置 S2AP_W)。`stage2_try_set_pte` 在非 shared walk 下用
   `WRITE_ONCE` 无条件覆写，可能丢失硬件的并发 C→D 更新。需确认
   arm64 wrprotect 路径的 walk 是否 shared (cmpxchg)。

3. **HDBSS buffer 硬件边界行为**: buffer 满、FSC 状态、curr_idx 溢出
   等硬件边界条件是否有未处理的 case。

### 建议的调试手段

1. 在目标 VM 崩溃时 dump 该页的迁移历史 (哪一轮拷贝、内容版本)
2. 打开 KVM trace (kvm_dirty_ring_push/reset, kvm_hdbss) 对比 HDBSS
   与非 HDBSS 模式的 entry 序列
3. 在 `kvm_arch_mmu_enable_log_dirty_pt_masked` 加计数器，统计每次
   reset 实际 wrprotect 的页数 vs QEMU reap 的页数
4. 用 bpftrace/eBPF 追踪崩溃页的 GPA 在整个迁移中的 dirty 环轨迹


## QEMU 侧 Dirty Ring Reap 路径分析

QEMU 有三个 dirty ring reap 路径，kick 行为各不相同：

### 路径 1: KVM_EXIT_DIRTY_RING_FULL handler (kvm-all.c:3151-3172)

```c
case KVM_EXIT_DIRTY_RING_FULL:
    qemu_mutex_lock_iothread();
    if (dirtylimit_in_service()) {
        kvm_dirty_ring_reap(kvm_state, cpu);   // 只 reap 当前 vCPU
    } else {
        kvm_dirty_ring_reap(kvm_state, NULL);  // reap 所有 vCPU 的 ring
    }
    qemu_mutex_unlock_iothread();
    dirtylimit_vcpu_execute(cpu);
    ret = 0;  // vCPU 继续运行
    break;
```

**没有 kick 其他 vCPU!** reap 时其他 vCPU 的 HDBSS buffer 中的
entry 不在 ring 中，本轮不被收割。

### 路径 2: Reaper thread (kvm-all.c:1437-1474)

```c
static void *kvm_dirty_ring_reaper_thread(void *data)
{
    while (true) {
        sleep(1);
        qemu_mutex_lock_iothread();
        kvm_dirty_ring_reap(s, NULL);  // reap 所有 ring
        qemu_mutex_unlock_iothread();
    }
}
```

**每秒 reap 一次，没有 kick 其他 vCPU!**

### 路径 3: Migration bitmap sync (kvm-all.c:864-880) — 有 kick!

```
migration_bitmap_sync(rs, last_stage)              [ram.c:1154]
└─ memory_global_dirty_log_sync(last_stage)        [ram.c:1166]
   └─ memory_region_sync_dirty_bitmap(NULL, last_stage)  [memory.c:2963]
      └─ kvm_log_sync_global(l, last_stage)        [kvm-all.c:1653]
         └─ kvm_dirty_ring_flush()                 [kvm-all.c:1661]
            ├─ kvm_cpu_synchronize_kick_all()      [kvm-all.c:877] ← KICK!
            │  └─ run_on_cpu(cpu, kick_func)       [cpu-common.c:184]
            │     ├─ 在 vCPU 工作队列放 work item
            │     ├─ pthread_kill(thread, SIG_IPI) kick vCPU
            │     ├─ vCPU exit KVM_RUN
            │     │  └─ 内核 exit path: kvm_flush_hdbss_buffer()  [arm.c:1490]
            │     │     └─ HDBSS entries → kvm_dirty_ring_push() → ring
            │     └─ vCPU 线程处理 work item (qemu_wait_io_event)
            │        └─ work item done → run_on_cpu 的等待返回
            │        ※ 返回时保证该 vCPU 的 HDBSS 已 flush 到 ring!
            └─ kvm_dirty_ring_reap(kvm_state, NULL)  [reap 所有 ring]
               └─ kvm_vm_ioctl(KVM_RESET_DIRTY_RINGS) → wrprotect
```

### `run_on_cpu` 的同步保证

```c
void do_run_on_cpu(CPUState *cpu, run_on_cpu_func func,
                   run_on_cpu_data data, QemuMutex *mutex)
{
    if (qemu_cpu_is_self(cpu)) {
        func(cpu, data);
        return;
    }
    // 在 vCPU 工作队列放 work item
    queue_work_on_cpu(cpu, &wi);
    // 等待 work item 完成
    while (!qatomic_load_acquire(&wi.done)) {
        qemu_cond_wait(&qemu_work_cond, mutex);  // 释放 mutex 等待
    }
}
```

work item 在 vCPU 线程的 `qemu_wait_io_event` →
`process_queued_cpu_work` 中处理，这要求 vCPU 已退出 KVM_RUN。
而 vCPU 退出 KVM_RUN 时内核 exit path 必然执行
`kvm_flush_hdbss_buffer()` (arm.c:1490-1491)。

所以 `kvm_cpu_synchronize_kick_all()` 返回时，**所有 vCPU 的
HDBSS buffer 已 flush 到 dirty ring**。

### 最后一轮迁移流程 (migration_completion_precopy)

```
migration_completion_precopy()                      [migration.c:2761]
├─ migration_stop_vm(RUN_STATE_FINISH_MIGRATE)      [migration.c:2775]
│  └─ vm_stop_force_state()
│     └─ pause_all_vcpus()
│        ├─ cpu->stop = true; qemu_cpu_kick(cpu)
│        ├─ vCPU exit KVM_RUN (SIG_IPI)
│        │  └─ 内核 exit path: kvm_flush_hdbss_buffer() ← HDBSS flush!
│        └─ 等待所有 vCPU stopped
│
└─ qemu_savevm_state_complete_precopy()             [migration.c:2802]
   └─ ram_save_complete()                           [ram.c:3948]
      └─ migration_bitmap_sync_precopy(rs, true)    [ram.c:3974]
         └─ kvm_dirty_ring_flush()
            ├─ kvm_cpu_synchronize_kick_all()  ← no-op (VM 已停)
            └─ kvm_dirty_ring_reap(NULL)
               └─ KVM_RESET_DIRTY_RINGS → harvest + wrprotect
```

**最后一轮是安全的**: VM 停止时所有 vCPU 退出 KVM_RUN，
HDBSS buffer 全部 flush 到 ring。`ram_save_complete` 中的
bitmap sync 再 reap 一次，所有脏页（包括 HDBSS 中的）都被收割。

### 重要结论

| Reap 路径         | kick 所有 vCPU? | HDBSS flush? | 使用场景        |
|-------------------|-----------------|--------------|-----------------|
| Ring full handler | ✗               | ✗            | ring 满时       |
| Reaper thread     | ✗               | ✗            | 每秒一次        |
| Bitmap sync       | ✓               | ✓            | 迁移 bitmap 同步 |

**用户假设"最后一轮没有出口收割所有vcpu的脏页"不成立** —
最后一轮 (`ram_save_complete` → `kvm_dirty_ring_flush`) 有
`kvm_cpu_synchronize_kick_all()` 兜底，且 VM 停止时 HDBSS 已 flush。

### 数据丢失的重新定位

如果最后一轮安全，数据丢失必然发生在**迭代阶段**（路径 1/2 的
无 kick reap）。但迭代阶段 HDBSS buffer 中的脏页只是延迟一轮，不会
永久丢失（下次 reap 会捕获）。

→ 详见前文"当前分析状态与未解问题"章节的悖论分析与待验证假设。


## 关键代码位置索引

| 代码位置                                   | 说明                              |
|--------------------------------------------|-----------------------------------|
| QEMU accel/kvm/kvm-all.c:3151 KVM_EXIT_DIRTY_RING_FULL handler | ring 满 reap（无 kick） |
| QEMU accel/kvm/kvm-all.c:1437 kvm_dirty_ring_reaper_thread | 每秒 reap（无 kick） |
| QEMU accel/kvm/kvm-all.c:864 kvm_dirty_ring_flush | kick + reap（bitmap sync 路径）|
| QEMU accel/kvm/kvm-all.c:847 kvm_cpu_synchronize_kick_all | kick 所有 vCPU（run_on_cpu 等待）|
| QEMU migration/ram.c:3948 ram_save_complete | 最后一轮（有 kick 兜底）|
| QEMU migration/migration.c:2761 migration_completion_precopy | VM stop → final sync |
| QEMU cpu-common.c:184 do_run_on_cpu | 同步等待 work item 完成 |
| virt/kvm/kvm_main.c:4999 kvm_vm_ioctl_reset_dirty_pages | dirty ring reset 入口，缺少 sync |
| virt/kvm/kvm_main.c:2248 kvm_arch_sync_dirty_log     | bitmap 路径有调用，ring 路径没有    |
| virt/kvm/dirty_ring.c:110 kvm_dirty_ring_reset       | ring reset 主体，含 cond_resched    |
| virt/kvm/dirty_ring.c:163 cond_resched              | yield CPU，放大竞态窗口              |
| virt/kvm/dirty_ring.c:190 kvm_reset_dirty_gfn       | 调用 arch wrprotect                  |
| virt/kvm/dirty_ring.c:223 kvm_dirty_ring_push       | push entry 到 ring                  |
| arch/arm64/kvm/mmu.c:1326 kvm_arch_mmu_enable_log_dirty_pt_masked | arm64 wrprotect 入口 |
| arch/arm64/kvm/hyp/pgtable.c:1231 stage2_attr_walker | PTE 修改: 清 S2AP_W, block 清 DBM  |
| arch/arm64/kvm/arm.c:1490 kvm_flush_hdbss_buffer    | HDBSS buffer flush (在 IPI ack 后) |
| arch/arm64/kvm/dirty_bit.c:63 kvm_flush_hdbss_buffer | HDBSS buffer flush 实现             |
| include/linux/kvm_host.h:180 KVM_REQ_OUTSIDE_GUEST_MODE | 带 KVM_REQUEST_WAIT 的 kick 请求   |
| arch/x86/kvm/mmu/spte.h:546 leaf_spte_change_needs_tlb_flush | x86 判断是否需要 TLB flush     |
| arch/x86/kvm/mmu/tdp_mmu.c:777 kvm_flush_remote_tlbs | x86 cond_resched 前先 flush         |
