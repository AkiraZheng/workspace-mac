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

### 状态迁移与 relax 路径

DBM 的设置规则 (pgtable.c:734-743, 1390-1393)：

- **映射时** (`stage2_set_prot_attr`): `PROT_W` → 同时设 S2AP_W + DBM
- **relax 时** (`kvm_pgtable_stage2_relax_perms`): `PROT_W` → 同时设
  S2AP_W + DBM。fault handler 走 relax 路径 (mmu.c:1676, 2077) 放开
  写权限时**就把 DBM 设上了**——这是 block→page 转换的关键: 2M block
  第一轮 fault 后 relax 成带 DBM 的 level-3 页，后续轮次即可走 C→D
  硬件脏跟踪 (详见"为什么 huge/THP 不出问题")
- **wrprotect 时** (`stage2_attr_walker`): 清 S2AP_W；block 剥 DBM
  (→ State N)，page 保留 DBM (→ State C)


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
      ├─ [permission fault, 粒度不变时]:
      │    kvm_pgtable_stage2_relax_perms()  [mmu.c:1676/2077]
      │    └─ set S2AP_W + set DBM          [pgtable.c:1390-1393]
      │       → State D (DBM=1, S2AP_W=1)
      │       ※ HDBSS 开启时 relax 也设 DBM → 后续轮次可走 C→D 硬件跟踪
      ├─ [需要改变映射大小时]:
      │    kvm_pgtable_stage2_map()          [mmu.c:2080]
      │    └─ 映射为 State D: DBM=1, S2AP_W=1
      └─ mark_page_dirty_in_slot()         [mmu.c:1689/2097 ← 同步 push 到 ring!]
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
    │  ※ 注: 实际时序是"标记"与"拷贝"分离——reap 只把 entry 标记到
    │    KVMSlot.dirty_bmap, 实际拷贝由迁移线程的 ram_save_iterate
    │    在 bitmap sync 之后逐页发送 (三阶段分离, 详见 QEMU 侧分析)
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

**stale TLB 对读写的影响**：stale TLB 既不阻止读也不阻止写。wrprotect
把 PTE 从 D→C 时清的是 S2AP_W (写权限)，S2AP_R 保持 1；但 stale TLB 下
CPU 看到的还是旧的 State D (S2AP_W=1, S2AP_R=1)，读写都直接命中 TLB，
不查 page table、不 fault。读无害 (不修改页内容、不需要 dirty
tracking)；**问题只在写**——stale TLB 下的写不触发 C→D，HDBSS 不记录。

**mmu_lock 与 TLB flush 是两个层面的保护**，mmu_lock 不能阻止 stale TLB
写入：

|              | mmu_lock (KVM_MMU_LOCK)       | kvm_flush_remote_tlbs      |
|--------------|-------------------------------|----------------------------|
| 层面         | **软件**自旋锁                | **硬件** TLB 失效           |
| 保护对象     | stage-2 page table 数据结构不被并发修改 | vCPU 的硬件 TLB 缓存与内存中 PTE 一致 |
| 工作方式     | KVM 线程持锁遍历/修改 PTE     | 发 IPI kick vCPU 退出 guest，让 TLB entry 失效 |

vCPU 在 guest 模式下写页的硬件路径：查 TLB → 命中 (State D) → 直接写入，
**不查 stage-2 page table、不 fault、不受 mmu_lock 影响**。mmu_lock 只
保证 KVM 改 PTE 时没有其他 CPU 同时改同一个 PTE (软件数据结构一致性)。
PTE 修改 (软件) 到 TLB flush (硬件) 之间的间隔就是 stale TLB 窗口，ring
路径中该间隔被 `cond_resched` (dirty_ring.c:163) 和锁外 flush
(kvm_main.c:5016→5019) 进一步拉长。

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
├─ xchg(&dirty_bitmap[i], 0)            [取出并清零]          [kvm_main.c:2275]
├─ kvm_arch_mmu_enable_log_dirty_pt_masked()  ← ★写保护在这里★ [kvm_main.c:2279]
└─ kvm_flush_remote_tlbs_memslot()                             [kvm_main.c:2286]
```

### 写保护的位置与"幂等"的准确含义

**注意措辞**: bitmap 的"幂等"指的是 **dirty 标记** (`set_bit_le` 的累积性
——多次设置同一个 bit 无害)，**不是写保护幂等**。写保护同样发生在
`kvm_arch_mmu_enable_log_dirty_pt_masked()` (mmu.c:1326 →
`kvm_stage2_wp_range()`，清 S2AP_W，PTE D→C)，**与 dirty ring 路径调用
的是同一个函数**。bitmap 路径同样有 stale TLB 窗口：kvm_main.c:2279
(wrprotect) 到 kvm_main.c:2286 (TLB flush) 之间，vCPU 用 stale TLB
(State D) 写页同样不触发 C→D、不被 HDBSS 记录。

### bitmap 路径的真正优势

不是"写保护幂等"，而是 **`kvm_arch_sync_dirty_log()` (kvm_main.c:2248)
在 harvest 前 kick 了所有 vCPU** (arm.c:2091-2092)，把 HDBSS buffer 先
flush 到 bitmap——快照时 HDBSS buffer 中没有遗漏的 entry。加上
`set_bit_le` 的累积性：stale TLB 窗口内被写的页，其 HDBSS entry 在下一
轮 `kvm_arch_sync_dirty_log` kick 时 flush 到 bitmap，bit 重新置位，下一
轮 harvest 捕获。

dirty ring 路径 (内核侧 `kvm_vm_ioctl_reset_dirty_pages`，kvm_main.c:5008)
**没有调用 `kvm_arch_sync_dirty_log`**——没有 harvest 前的 kick，HDBSS
buffer 中未 flush 的 entry 不在 ring 中，本轮收割不到；且 ring 是消费型
数据结构 (entry 被 `kvm_dirty_gfn_set_invalid()` 后即消失)，没有累积性
兜底。

> **补充**: QEMU 侧对 dirty ring 的补偿——迁移 bitmap sync 路径
> (`kvm_log_sync_global` → `kvm_dirty_ring_flush` →
> `kvm_cpu_synchronize_kick_all`) 在 reap 前会同步 kick 所有 vCPU，
> 效果等价于 `kvm_arch_sync_dirty_log`。但 ring full handler 和
> reaper thread 两条路径没有该补偿。详见"QEMU 侧 Dirty Ring Reap
> 路径分析"。


## 为什么 huge/THP 不出问题

### block 与 page 的 wrprotect 行为差异

`stage2_attr_walker` (pgtable.c:1254-1255) 对 block 和 page-level PTE 的
DBM 处理**不同**：

```c
if (ctx->level < KVM_PGTABLE_LAST_LEVEL)      // block (2M/1G)
    pte &= ~KVM_PTE_LEAF_ATTR_HI_S2_DBM;      // → State N (RO, DBM=0)
// page (4K, level-3): DBM 保留 → State C (W-Clean)
```

原因见代码注释：block 若保留 DBM (State C)，写会 C→D 不 fault，block
永远不会被拆成 page，而 dirty tracking 是 page 粒度的——所以 block 必须
剥 DBM 强制走 fault 路径触发拆页。

### block → page 的转换: relax 路径设 DBM

```
第 1 轮 (block, fault-based 同步跟踪):
  2M block wrprotect → State N (DBM=0, S2AP_W=0)
  → kvm_mmu_split_huge_pages() 拆页
     → stage2_split_walker (pgtable.c:1561): prot = kvm_pgtable_stage2_pte_prot(pte)
       ← 该函数 (pgtable.c:756-766) 不提取 DBM (bit 51 不在 SW bits 55-58)
       ← block 已被 wrprotect (S2AP_W=0) → 无 PROT_W → 拆出的 4K 页也无 DBM
     → 拆出的 4K 页也是 State N (RO)
  → guest 写 → permission fault → user_mem_abort() → relax_perms()
     → kvm_pgtable_stage2_relax_perms (pgtable.c:1390-1393):
        if (prot & KVM_PGTABLE_PROT_W) {
            set |= S2AP_W;
            set |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;   // ← relax 时设 DBM!
        }
     → State C (level-3, DBM=1, S2AP_W=1 即 State D)
  → mark_page_dirty_in_slot() 同步 push ring (mmu.c:1689)

第 2 轮起 (page, HDBSS 异步跟踪):
  wrprotect → level-3 保留 DBM → State C
  → guest 写 → C→D → HDBSS buffer → 异步 push ring
  → 与原生 4K 页完全相同!
```

**注意**: block 只有第一轮是 fault-based。relax 路径设上 DBM 后，后续
轮次与原生 4K 页一样走 HDBSS 异步路径。所以 huge/THP 不崩溃**不是因为
"不走 HDBSS"**。

### 粒度澄清: ring 和 bitmap 都是 4K 粒度，与页表级别无关

**先澄清一个容易搞错的问题**: dirty ring 和 dirty bitmap (内核侧与
QEMU 侧) 都是 **4K/page 粒度**，不存在"2M 粒度的 dirty entry":

- ring entry 存 `rel_gfn` (page frame number)，`kvm_dirty_ring_push(vcpu,
  slot, rel_gfn)` — 每个 4K 脏页一个 entry (dirty_ring.c:223)
- `mark_page_dirty_in_slot()` 无论 PTE 是 block 还是 page，都以 gfn
  (4K) 粒度标记 (kvm_main.c:3517)
- 内核 bitmap: `set_bit_le(bitmap, gfn)` — 4K 粒度
- QEMU 侧 bitmap: `set_bit(offset, mem->dirty_bmap)` — page offset (4K)
  粒度 (kvm-all.c:703)，`cpu_physical_memory_set_dirty_lebitmap()` 同样

因此 block 拆成 page 后，**2M/THP 与原生 4K 在后续轮次的行为完全一致**:
同样的 4K 粒度 HDBSS 跟踪、同样的 ring 填充速率 (~8MB 脏页填满
2048-entry ring)。

~~"2MB block: ring 填满慢 (每 ~4GB 脏页)"~~ — **此说法错误**，已修正。

### 那 huge/THP 为什么不崩溃? (未解)

既然拆页后 2M 与 4K 行为一致，"ring 填满慢 → reset 频率低"的解释
**不成立**。此问题目前没有确定答案，候选方向:

1. **第一轮 fault 开销**: 2M block 第一轮全部走 fault (split + relax，
   每页一次 fault + 一次 relax + 同步 push ring)，比 4K 的 HDBSS 全速
   跟踪慢得多。但这只影响第一轮——除非第一轮的减速显著改变了 guest
   的脏页产生模式，或把迁移总时间的 reset 次数压到了阈值以下。
2. **测试时长/样本不足**: 4K 场景在 ~298s 崩溃；若 2M 场景 reset 次数
   只是略少 (而非数量级差异)，可能只是还没测到崩溃。
3. **其他未识别的差异**: THP 场景下 host 内存布局、TLB 行为 (2M 映射
   的 TLB entry 覆盖范围大、hit 率高)、HDBSS 硬件对 block vs page PTE
   的 C→D 处理差异等。

**需要实验验证**: 对比 2M 场景稳定态 (第一轮之后) 的 reset 频率与 4K
场景是否相同 (trace kvm_dirty_ring_reset)，以及 2M 场景在更长时间
(>300s) 下是否也会崩溃。


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

### 是否影响 dirty bitmap 路径 (共享路径分析)

`kvm_arch_mmu_enable_log_dirty_pt_masked()` 是 dirty bitmap 和 dirty ring
都会走的**共享下游函数** (bitmap: kvm_main.c:2279, 2396；ring:
dirty_ring.c:75)，但方案 C **没有修改该函数本身**：

| 改动   | 位置                                          | 影响范围                          |
|--------|-----------------------------------------------|-----------------------------------|
| 改动 1 | arm.c exit path，HDBSS flush 移到 `local_irq_enable` 前 | 所有路径的 vCPU exit (正面影响) |
| 改动 2 | kvm_main.c:5008 `kvm_vm_ioctl_reset_dirty_pages` 加 kick | **仅 dirty ring 路径**           |

bitmap 路径 (`kvm_get_dirty_log_protect` / `kvm_clear_dirty_log_protect`)
**完全不被改动**——它们已有自己的 kick (`kvm_arch_sync_dirty_log`，
kvm_main.c:2248, 2370)。改动 2 本质是给 ring 路径补上 bitmap 路径已有
的 kick，让两者对齐；`kvm_arch_mmu_enable_log_dirty_pt_masked` 只是两条
路径共同调用的下游函数，在它之前加 kick 不改变其行为。

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

> **[2026-09-16 更新] 根因已确认并修复**: 根因是
> **KVM_REQ_RELOAD_STAGE2 打开 VTCR_EL2.HDBSS 时未编程
> HDBSSBR_EL2/HDBSSPROD_EL2**, 使能窗口内硬件把脏页 entry 写进陈旧
> buffer 地址。该结论同时解释了下面全部"未解问题"(4K+ring 独有、
> huge/THP 不崩、bitmap 不崩、方案 C 无效)。详见文末
> **"根因确认: HDBSS 使能窗口的 HDBSSBR_EL2 陈旧编程"** 一节
> (含 **"追问与深入"** 六问: BR 残留机制、装载时机不变式、两端
> 伤害形态、bitmap/INITIALLY_SET 判别、bulk 救不了的边沿触发原理);
> 本节以下内容保留作为历史分析记录。

> **[2026-09-17 定案] 修复经实测验证有效**: 打上修复
> (linux.git code_v5_2_tested `d52cdc8ea269`) 后,原崩溃场景
> (4K stage-2 + dirty ring + HDBSS 迁移) **不再复现**——根因就此
> 定案。最终结论与两个变体 (kick/RELOAD) 的完整闭环见文末
> **"根因定案与实测验证 (2026-09-17)"** 一节。

### 已确认的事实

1. 崩溃仅在 HDBSS + 4K 页 + dirty ring 场景出现
2. 无 HDBSS、或 huge/THP 场景不崩溃
3. mask-based wrprotect 不能修复 (实测)
4. 崩溃在目标 VM，说明 QEMU 拷贝了陈旧数据
5. 最后一轮迁移有 kick 兜底，安全
6. 迭代轮的 HDBSS buffer 延迟只延迟一轮，不永久丢失
7. stale TLB 窗口 (wrprotect 后到 TLB flush 前) 在 HDBSS 和传统模式下
   都存在
8. ring 和 dirty bitmap (内核侧与 QEMU 侧) 都是 4K/page 粒度，与
   stage-2 PTE 级别无关；block 拆页后 2M/THP 与原生 4K 的跟踪行为
   完全一致 (见"为什么 huge/THP 不出问题")

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
   修改 PTE (C→D 置 S2AP_W)。`stage2_try_set_pte` (pgtable.c:812-820)
   在非 shared walk 下用 `WRITE_ONCE` 无条件覆写；wrprotect 路径
   (`kvm_pgtable_stage2_wrprotect` → `stage2_update_leaf_attrs`) 确实
   未设置 `KVM_PGTABLE_WALK_SHARED`，走 WRITE_ONCE 分支。但初步分析
   该 race 是良性的: PTE 已是 State D 时无 C→D 可丢；PTE 是 State C
   时 walker 算出无变化不写，硬件更新被保留。待复核。

3. **HDBSS buffer 硬件边界行为**: buffer 满、FSC 状态、curr_idx 溢出
   等硬件边界条件是否有未处理的 case。若 guest 全速写 (4K + HDBSS
   无 fault 开销) 而 vCPU 长时间不 exit，buffer 可能填满——填满后硬件
   是停止记录、覆盖旧 entry 还是触发 VM exit，行为未知。若静默丢弃则
   是确定性丢失根因，且能解释为什么 bitmap 路径 (有 sync kick 定期
   flush buffer) 不崩溃。

4. **huge/THP 为何不崩溃**: 拆页后 2M 与 4K 跟踪行为一致 (均为 4K
   粒度 HDBSS)，"ring 填满慢"的解释不成立 (见"为什么 huge/THP 不出
   问题")。候选: 第一轮 fault 开销改变了 guest 脏页模式 / 测试时长
   不足 / 其他未识别差异 (TLB 覆盖、host 内存布局)。需 trace 对比
   2M 稳定态 reset 频率与 4K 是否相同。

### 建议的调试手段

1. 在目标 VM 崩溃时 dump 该页的迁移历史 (哪一轮拷贝、内容版本)
2. 打开 KVM trace (kvm_dirty_ring_push/reset, kvm_hdbss) 对比 HDBSS
   与非 HDBSS 模式的 entry 序列
3. 在 `kvm_arch_mmu_enable_log_dirty_pt_masked` 加计数器，统计每次
   reset 实际 wrprotect 的页数 vs QEMU reap 的页数
4. 用 bpftrace/eBPF 追踪崩溃页的 GPA 在整个迁移中的 dirty 环轨迹


## QEMU 侧 Dirty Ring Reap 路径分析

### QEMU 侧 reap 的具体代码 (mmap 读取与 bitmap 标记)

**① 从 mmap 读取 ring entries** — `kvm_dirty_ring_reap_one()` (kvm-all.c:740-774):

```c
while (true) {
    cur = &dirty_gfns[fetch % ring_size];       // 直接读 mmap 共享内存
    if (!dirty_gfn_is_dirtied(cur))              // 检查 KVM_DIRTY_GFN_F_DIRTY
        break;
    kvm_dirty_ring_mark_page(s, cur->slot >> 16, cur->slot & 0xffff,
                             cur->offset);       // → ②
    dirty_gfn_set_collected(cur);                // 置 KVM_DIRTY_GFN_F_RESET
    fetch++;
}
```

**② 标记到 QEMU 侧 dirty bitmap** — `kvm_dirty_ring_mark_page()`
(kvm-all.c:685-704):

```c
set_bit(offset, mem->dirty_bmap);   // 写 QEMU 侧的 KVMSlot.dirty_bmap
```

然后 `kvm_dirty_ring_reap_locked()` (kvm-all.c:777-805) 调：

```c
ret = kvm_vm_ioctl(s, KVM_RESET_DIRTY_RINGS);  // → 内核 wrprotect + TLB flush
```

**dirty ring 模式也维护 QEMU 侧 dirty bitmap**——ring 只是传输管道，
两条路径最终汇入同一个 `KVMSlot.dirty_bmap`:

```
Dirty Bitmap 模式:
  内核 bitmap → ioctl(KVM_GET_DIRTY_LOG, &slot->dirty_bmap) → 覆写 KVMSlot.dirty_bmap

Dirty Ring 模式:
  ring entries → kvm_dirty_ring_reap_one() → kvm_dirty_ring_mark_page()
              → set_bit(offset, mem->dirty_bmap)   ← 同一个 KVMSlot.dirty_bmap
```

区别只在于 `KVMSlot.dirty_bmap` 怎么被填充：bitmap 模式由
`KVM_GET_DIRTY_LOG` ioctl 一次性从内核拷贝 (内核已 kick + flush HDBSS)；
ring 模式由 QEMU 逐个读 mmap ring entry 用 `set_bit` 填进去 (**没有
kick，HDBSS buffer 中的 entry 漏掉**)。

### QEMU 迁移三阶段分离 (标记与拷贝不是即时的)

reap 时标记 bitmap 和实际拷贝页是**分离的两个阶段**，甚至在不同的线程：

```
阶段 1: 收集 dirty 标记 (可由多个路径触发, 任意时机)
  ├─ KVM_EXIT_DIRTY_RING_FULL handler  (vCPU 线程)
  ├─ reaper thread                     (每秒一次)
  └─ migration bitmap sync             (迁移线程)
     → 读 mmap ring → set_bit(KVMSlot.dirty_bmap)
     → ioctl(KVM_RESET_DIRTY_RINGS): 内核 wrprotect + TLB flush

阶段 2: bitmap sync (迁移线程, 每轮迭代开头)
  migration_bitmap_sync()                           [ram.c:1154]
  └─ memory_global_dirty_log_sync()
     └─ kvm_log_sync_global()                       [kvm-all.c:1653]
        ├─ kvm_dirty_ring_flush()                   ← kick all vCPUs + reap
        └─ kvm_slot_sync_dirty_pages(mem)           [kvm-all.c:615]
           └─ cpu_physical_memory_set_dirty_lebitmap(slot->dirty_bmap, ...)
              ← 把 KVMSlot.dirty_bmap 推入全局 RAMBlock dirty bitmap

阶段 3: 扫描 bitmap 拷贝页 (迁移线程, sync 之后)
  ram_save_iterate()                                [ram.c:3791]
  └─ while (...):
     └─ ram_find_and_save_block(rs)                 [ram.c:3008]
        └─ find_dirty_block(rs, pss)                [ram.c:1574]
           └─ pss_find_next_dirty(pss)              ← 扫 RAMBlock dirty bitmap
        └─ ram_save_target_page()                   ← 实际把页数据发到对端
```

时序上：reap (标记 + wrprotect) → bitmap sync (KVMSlot→RAMBlock) →
ram_save_iterate (逐页发送)。标记和拷贝之间的时间差由"每轮迭代开头先
bitmap sync 再扫描发送"来弥合：reap 和发送之间若有新写入，只要下一轮
bitmap sync 能收集到，就能拷贝到最新内容。**问题在于**：路径 1/2 的 reap
没有 kick，HDBSS buffer 中未 flush 的 entry 既不在 ring 里、也没被标记到
bitmap；若迁移在下一轮带 kick 的 bitmap sync 之前终止，且最后一轮没有
kick 兜底——最后一轮实际有 kick 兜底 (见下文)，所以问题仍在迭代阶段的
无 kick reap。

QEMU 有三个 dirty ring reap 路径，kick 行为各不相同：

### 路径 1: KVM_EXIT_DIRTY_RING_FULL handler (kvm-all.c:3151-3172)

**内核侧退出机制** (`kvm_dirty_ring_check_request`, dirty_ring.c:248-262):

```c
if (kvm_check_request(KVM_REQ_DIRTY_RING_SOFT_FULL, vcpu) &&
    kvm_dirty_ring_soft_full(&vcpu->dirty_ring)) {
    kvm_make_request(KVM_REQ_DIRTY_RING_SOFT_FULL, vcpu);  // ← 重新设请求!
    vcpu->run->exit_reason = KVM_EXIT_DIRTY_RING_FULL;
    return true;   // → vcpu_enter_guest return 0 → 退回 QEMU
}
```

关键在 dirty_ring.c:258：退出前**重新设了 `KVM_REQ_DIRTY_RING_SOFT_FULL`**。
这意味着该 vCPU 下次 `KVM_RUN` 时会立刻再次退出 (ring 还满)，直到 QEMU
调 `KVM_RESET_DIRTY_RINGS` 清空 ring 后才能重新进 guest。

**注意：只阻止了 ring 满的那一个 vCPU**，其他 vCPU 完全不受影响，一直在
guest 里全速运行。

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


## 根因确认: HDBSS 使能窗口的 HDBSSBR_EL2 陈旧编程 (2026-09-16)

**状态: 已定案——2026-09-17 实测验证修复有效, 原崩溃场景不再复现。**
本节结论取代上文"当前分析状态与未解问题"中的全部未解假设——
stale TLB 窗口(假设 1)与 HDBSS buffer 硬件边界(假设 3)确实存在,
但都是次要因素,均不是 4K + dirty ring 场景独有崩溃的根因。

### 一句话结论

`KVM_REQ_RELOAD_STAGE2` 打开 `VTCR_EL2.HDBSS` 时,只重载了
VTCR/VTTBR (`__load_stage2`),**没有编程 HDBSSBR_EL2/HDBSSPROD_EL2**。
正在 KVM_RUN 中间的 vCPU 带着陈旧的 buffer 地址(上一轮测试已释放的
buffer 页被 buddy 复用后的任意页,或冷启动时的 0)重新进 guest,
硬件把脏页 GPA 条目写进错误的物理内存——既污染宿主机内存,又永久
丢失该 vCPU 的真实脏页记录。

### 证据链

**1. HDBSSBR_EL2 全内核只有一个编程点**

- `arch/arm64/kvm/hyp/vhe/switch.c:223` `__load_hdbss()`: 唯一写
  `HDBSSBR_EL2` 的地方,且 `vcpu_hdbss_enabled()` 为假时**提前 return**
- 它只被 `kvm_vcpu_load_vhe()` → `kvm_arch_vcpu_load()` 调用,即
  KVM_RUN 入口的 `vcpu_load()` 或 vCPU 线程被抢占后重新调度
  (`kvm_sched_in`, kvm_main.c:6404) 时
- `kvm_vcpu_put_vhe()` 也不清 HDBSSBR_EL2——寄存器无限期保留旧值

**2. 使能路径不经过 vcpu_load**

- 迁移开始 → QEMU 设置 memslot LOG_DIRTY →
  `kvm_arch_commit_memory_region()` (mmu.c:2586) →
  `kvm_arm_enable_hdbss_global()` (dirty_bit.c:141): 改
  `kvm->arch.mmu.vtcr` + `kvm_make_all_cpus_request(KVM_REQ_RELOAD_STAGE2)`
- vCPU 在 run loop 内处理该请求 (arm.c:1240): **只调
  `__load_stage2()`(写 VTCR/VTTBR), 不碰 HDBSSBR/HDBSSPROD**,随后
  直接重新进 guest

**3. 硬件语义 (Leo Bras 系列 patch 1/5 + dbm_lazy_split_design.md)**

writable-clean (DBM=1, S2AP[1]=0) 在 HD=1 时,guest 写由硬件**静默
升级**: 一次性原子动作 = 置 S2AP[1]=1 + 把 GPA entry 写到
`HDBSSBR_EL2.BADDR + PROD.INDEX*8`,**不产生任何 fault**。BADDR 指
错时硬件照样写——写 buffer 的是 MMU 硬件,直接写物理内存,这条路径
上没有任何 KVM 代码参与;硬件唯一的信息来源是当前 CPU 的
HDBSSBR_EL2 寄存器值 (per-CPU 状态,与 VTTBR 同类)。

**4. "buffer 是 per-vCPU 的"只对软件侧成立**

`vcpu->arch.hdbss.hdbss_pg` 是软件结构体,硬件看不见。per-vCPU
buffer 页与 HDBSSBR_EL2 寄存器的绑定**只发生在 vcpu_load 时**——
每换一次 CPU、每回一次 userspace,都要重新装一次。commit 3347d79a
的 message 写了 "the buffer must already exist by the time HDBSS
turns on"——作者解决了软件侧的页(分配提前到 vCPU 创建),漏掉了
硬件侧的寄存器: 存在 `hdbssbr_el2` 字段里的值要有人写进寄存器才算
数,而唯一写入点在 vcpu_load 里、且被 `vcpu_hdbss_enabled()` 挡着。
**页备好了,指针没插上电。**

### flush 为什么救不了 (对质疑 1 的回答)

`kvm_flush_hdbss_buffer()` (dirty_bit.c:63) 的实际数据来源:

```c
prod = read_sysreg_s(SYS_HDBSSPROD_EL2);          // INDEX 从寄存器读 ✓
hdbss_buf = page_address(vcpu->arch.hdbss.hdbss_pg); // entry 从软件页读!
gpa = hdbss_buf[idx];
```

KVM **从不回读 HDBSSBR_EL2**。窗口内硬件把 entry 写到陈旧 BR 指向
的错误物理页,而 flush 从 software 页读——**两边指的不是同一页**。
真实 entry 躺在错误物理页里,全内核没有任何代码会去读它。
PROD 的 save/restore 同理,操作的都是软件保存的值,没有一个字节能
修正 BR 里的地址。

三重伤害:

1. **真实脏页 entry 永久丢失**: 页已是 State D,不再有 C→D;
   ring 模式下 wrprotect 的唯一触发源是"entry 被收割",依赖链
   `重新武装→entry进ring→硬件记录C→D→页先回State C→重新武装`
   死循环,断在第一环,无兜底
2. **garbage 被刷进 ring**: software 页分配时未清零(修复已加
   `__GFP_ZERO`),INDEX 条残留垃圾被 push 进 ring,大部分被 VALID
   位/memslot 范围检查过滤
3. **核心伤害——错误物理页被 8 字节 entry 反复覆写**: 该页是上一轮
   测试 freed 的 buffer 页被 buddy 复用后的任意页。8 字节垃圾插进
   guest 内存 → 原样迁到 DST → redis 跑到哪炸到哪、trace 每次不同

### 为什么 dirty bitmap 没问题 (对质疑 2 的回答)

**bitmap 模式在窗口内根本不存在 writable-clean 页**,硬件从未执行
过 C→D + buffer 写。差异在 QEMU 侧一行代码 (kvm-all.c:2653):

```c
if (!s->kvm_dirty_ring_size) {   // 只有 bitmap 模式才启用 manual protect
    ... KVM_DIRTY_LOG_INITIALLY_SET ...
}
```

四种场景在"HDBSS 使能瞬间(T+0)"的页状态 (注意
`kvm_arm_hdbss_on_dirty_logging_change` 在 eager wp **之前**执行,
使能和 wp 在同一个 commit_memory_region 里连续完成):

| 场景 | eager wp? | T+0 页状态 | 窗口内硬件行为 |
|------|-----------|-----------|---------------|
| **4K + ring** | ✅(无 INITIALLY_SET→mmu.c:2612) | 全部 **State C**(L3 保留 DBM) | **全速 C→D + 写陈旧 BR** 💥 |
| **bitmap** | ❌(INITIALLY_SET→mmu.c:2605 提前 return) | 全部 **State D** | 无 C→D、不写 buffer ✓ |
| **THP/huge + ring** | ✅ wp(剥 block DBM→State N)+ split | 子页继承 **State N**(RO) | 第一轮写走 fault 软件路径;relax 直达 State D,不经 State C ✓ |
| **hdbss=off** | — | — | 无 buffer ✓ |

bitmap 模式是**侥幸安全**: 第一批 writable-clean 页要等 bulk 完成
(4G @ 800MB/s ≈ 5s)后第一次 KVM_CLEAR_DIRTY_LOG 才出现,这 5 秒内
vCPU 必然回过 userspace → vcpu_load → BR 已正确。

THP 场景也顺带解释了"为什么 huge/THP 不崩": 不是 reset 频率/概率
差异,而是第一轮根本不走硬件路径(split 子页 State N → fault →
relax 直达 State D),等第二轮 wp 造出 State-C 页时 BR 已被修正。
四个场景全部闭合,没有一个靠概率解释。

### 为什么方案 C 无效

方案 C 修的是稳态 reset 循环里的竞态(stale TLB + HDBSS 异步延迟);
本 bug 的污染发生在**使能瞬间**,不在 reset 循环里。两者正交。

### 窗口长度

窗口 = 使能到下一次 vCPU 线程的 vcpu_load(回 userspace 或被抢占
sched-in)。taskset 1:1 绑核下 busy vCPU 抢占比率低,窗口可持续到
秒级;而使能后第一批写**立即**发生——毫秒级窗口足够把错误页打满
(512 entries/页,每 entry 8 字节,flush 清 INDEX 后反复覆写)。

### 数据丢失时序

```
T0  迁移开始, VTCR.HDBSS=1 (BR 陈旧)
T1  eager wp 把页 P 从 D 刷成 C
T2  redis 写 P → PTE 变 D(正确), entry 落进错误物理页(丢失)
T3  窗口关闭 (vcpu_load 修正 BR)
T4  bulk 快照: P 的当前内容被发往 DST (到这里还是对的)
T5  redis 又写 P → P 是 State D → 无记录、无 fault、无 wp
    → QEMU 的 dirty 集合里永远没有 P → 永远不重发
T6  迁移完成, DST 的 P 停在 T4 快照, T5 的写入永久丢失
```

### 追问与深入 (2026-09-16 Q&A, 根因的完整论证)

以下六问是根因确认过程中的关键质疑,每个答案都曾是假设的
"必答考题"。全部闭合后,该根因从"最可疑候选"升级为"确认"。

#### Q1: 寄存器里到底是什么?是"装载了上一个 VM 的 BR"吗?

**是残留,不是错误装载——这是遗漏型 bug,不是装载错误。**

HDBSSBR_EL2 是 per-CPU 寄存器: 没人写它,就永远保留上一次被写入
的值。宿主机上该寄存器的生命周期:

```
宿主机冷启动: BR = 0 (复位值)
之前某轮测试: 旧 VM 的 vCPU 在某 CPU 上 vcpu_load → BR = 旧 buffer 页 P_old
  → 测试结束, VM 销毁 → __free_pages(P_old) 还给 buddy
  → P_old 可能已被复用成任何页 (slab / page cache / 甚至当前 VM 的 guest RAM!)
  → 该 CPU 的 BR 仍指着 P_old ← 没有任何代码清它

当前 VM 开机 → 迁移开始前:
  每次 kvm_arch_vcpu_load() → __load_hdbss()
  → vcpu_hdbss_enabled() == false → 【提前 return】
  → 本 VM 的 buffer 地址【从未】写进过 BR

T0 迁移开始: RELOAD_STAGE2 只写 VTCR → BR 仍是残留值
  → guest 写 State-C 页 → entry 写进 P_old 💥
```

两种残留值后果不同(也是可证伪预测的基础):

| 残留值 | 硬件写 entry 到哪 | 症状 |
|--------|------------------|------|
| BR = 0 (冷启动后首轮) | PA 0 | ExternalAbort → FSC 置位 → -EFAULT → **QEMU 报错**,非静默崩溃 |
| BR = P_old (复测) | 已释放被 buddy 复用的任意页 | **静默污染**,复用成 guest RAM 页则垃圾 entry 直接进 guest 内存 |

测试反复在同一宿主机跑 SRC/DST,恰是第二种: 每轮 SRC 在跑、上轮
buffer 页刚被释放,复用概率极高。P_old 被复用成什么页决定症状——
这解释了 call trace 每次都不同。

#### Q2: `__load_hdbss()` 不是会装载吗?

**会,但守卫条件与调用时机存在结构性错位。**

```c
static void __load_hdbss(struct kvm_vcpu *vcpu)
{
    if (!vcpu_hdbss_enabled(vcpu))     // ← 守卫: HDBSS 未启用则不装载
        return;
    write_sysreg_s(vcpu->arch.hdbss.hdbssbr_el2, SYS_HDBSSBR_EL2);
    ...
}
```

装载只发生在 **vcpu_load**(KVM_RUN 入口 / 抢占后 sched-in);而
HDBSS 打开走的是第三条路——**run loop 中间的 RELOAD handler**,
处理完直接回 guest,不经过 vcpu_load。守卫条件与装载时机的矩阵:

```
装载机会:  [开机 ~~~~~~~~~ T0]  [T0 后回 userspace/被抢占 ~~~~~]
守卫条件:   恒 false ✗           恒 true ✓
                        ↑
          T0 (HDBSS 打开): 守卫刚翻转,但该时刻不经过 vcpu_load
          → BR 在 [T0, 下次 vcpu_load) 之间一直是残留值
```

**装载的时机和打开的时机永远错不开这个缝隙**——这是 bug 的结构性
成因,不是某次调用的偶然失误。

#### Q3: 使能瞬间必须装载 BR 吗?"立即生效"的精确含义?

不变式 (per-CPU, 无宽限期):

```
对任意物理 CPU, 在任意时刻:
  若 VTCR_EL2.HDBSS == 1 且该 CPU 可能执行 guest 代码
  则 HDBSSBR_EL2 必须指向当前 vCPU 的 buffer
```

为什么没有任何宽限期: 威胁不是来自 KVM 代码,而是硬件的**零介入
静默动作**——guest 第一条 store 碰到 State-C 页,MMU 当场 C→D 并写
`BR + INDEX*8`,中间没有任何软件介入点。不变式只要在 guest 重入前
被破坏过一个周期,伤害已发生。

"先装弹,后开保险"的顺序纪律:

```c
kvm_vcpu_load_hdbss(vcpu);        // ① 先装 BR/PROD
__load_stage2(vcpu->arch.hw_mmu); // ② 后写 VTCR —— HDBSS 在此激活
```

不变式在 HDBSS 激活的那条写指令执行时已成立,不依赖"此刻恰好
没人用"的上下文推理。`kvm_vcpu_load_vhe()` 里现存顺序相反
(stage2 先、hdbss 后),但两写之间无 guest 执行、guest entry 前
两者都就位——同样满足不变式,只是靠上下文而非顺序。

注意 VTCR 也是 per-CPU 生效的: `kvm->arch.mmu.vtcr` 只是软件模板,
硬件在每颗 CPU 各自 `write_sysreg(vtcr)` 时才切换行为——这正是使能
要发 RELOAD request 把所有 vCPU 踢出来的原因。

#### Q4: 为什么 call trace 在迁入端 (DST),而不是迁出端启动时就崩?

**SRC 也踩空了,但两端的伤害形态不同;SRC 是肇事者,DST 是案发现场。**

窗口内两笔伤害的归属:

| 伤害 | 机制 | 可见端 |
|------|------|--------|
| A. 错误物理页被覆写 | entry 写到陈旧 BR 指向的页 | 宿主机随机页,非定向 |
| B. 真实脏页记录丢失 | 页已 State-D,无 C→D → 永不 wrprotect → 永不重发 | **DST** (陈旧页到达) |

SRC guest 不崩: 它的内存没有被写过错误内容 (伤害 A 打的是宿主机
上无关页,偶尔随机命中 SRC 自己的 RAM backing page 才有局部污染),
丢的只是"哪些页变了"的**信息**。SRC 端 redis/内核数据结构照常
在内存里正确演化。

DST 崩溃机制: 收到的内存里部分页停留在迁移中某快照版本。redis/
内核数据结构 (哈希表、TCP 序列号、函数指针、页表) 是增量演化的,
SRC 上继续演化、DST 冻结,两边发散:

- `recvmsg bug 2: copied BD61E65F seq 893F5899` —— 序列号差约
  617MB,恰是 T4 (bulk 快照) 之后 SRC 持续写入量级 (800MB/s 限速
  × 迁移持续时间的合理比例)。这不是巧合: T5 阶段丢的写 = 快照后
  的持续演化量
- IABT at PC=0x14000c0 / PC=0、`x9-x14=0x78...` 整页模式 —— 函数
  指针/返回地址/数据页陈旧化的随机显形
- 崩溃点取决于哪个页丢了写 (纯随机) → **call trace 每次不同**

DST 自身没有敞开的窗口: precopy 的 DST 在 cutover 前 vCPU 不运行,
全部停在 userspace;首次 KVM_RUN 时 vcpu_load → __load_hdbss
(守卫已真) → BR 正确。

#### Q5: 那 bitmap 为什么没问题?两种机制不是都没重装 BR 吗?

**对——bitmap 的 BR 窗口同样敞开。区别不在有无窗口,而在窗口敞开的
那一刻硬件有没有活干。**

关键差异在 QEMU 一行代码 (kvm-all.c:2653):

```c
if (!s->kvm_dirty_ring_size) {   // 只有 bitmap 模式才启用 manual protect
    ... KVM_DIRTY_LOG_INITIALLY_SET ...
}
```

于是内核 `commit_memory_region` (mmu.c) 走向不同:

```c
kvm_arm_hdbss_on_dirty_logging_change(...);   // 两种模式都在 T0 开 HDBSS (BR 陈旧)
if (kvm_dirty_log_manual_protect_and_init_set(kvm))
    return;                        // ← bitmap: 跳过 eager wp+split
kvm_mmu_wp_memory_region(...);     // ← ring: eager wp → 全部页变 State C
```

- **bitmap** (INITIALLY_SET): T0 时所有页保持 State D → 窗口内
  guest 写 State-D 页,硬件看 dirty 位=1,什么都不做 → **硬件零
  buffer 写,陈旧 BR 无从作恶**。第一批 State-C 页要等 bulk 完成
  (4G @ 800MB/s ≈ 5s+) 后首次 CLEAR ioctl 才出现;这 5 秒里 vCPU
  因 virtio MMIO/中断等频繁回 userspace → 每次 vcpu_load → BR
  早已修正。**bitmap 是侥幸安全,不是机制免疫。**
- **ring** (QEMU 跳过该 cap): eager wp 与 HDBSS 激活同瞬间发生
  (同一个 commit_memory_region 内连续执行),全部 L3 页变 State C,
  redis 第一批写零延迟命中陈旧 BR。

**eager wp 是内核写死的,不是 QEMU 可配参数**: 唯一开关是
INITIALLY_SET 标志,只由 QEMU 是否发 MANUAL_DIRTY_LOG_PROTECT2 cap
决定;用户面没有任何 eager/lazy split 命令行参数 (QEMU 树里
`kvm_eager_split_size` 写死为 0)。lazy split 只是设计文档中的方案,
未合入本树;且 lazy 方案中 wp 照做 (仅拆页推迟)。

**判别实验** (未做,预测): 把 QEMU 的 `if (!s->kvm_dirty_ring_size)`
砍掉,让 bitmap 模式也不启用 manual protect → 内核对 bitmap 做
eager wp → 预测 **bitmap + 4K 同样出现 DST 内存损坏**。若成立,则
"崩溃与否的唯一判别变量 = HDBSS 激活瞬间有无 writable-clean 页"
从推论变为实测事实,也说明该 bug 威胁面是"任何使能时刻存在
State-C 页的模式",修复对 bitmap/legacy 同样必要。

THP/huge + ring 不崩的同构解释: eager wp+split 确实做了,但 block
wp 剥 DBM → State N,split 子页继承 → State N (RO)。第一轮写走
permission fault 软件路径,relax 设 W+DBM **直达 State D,全程不经
State C 中间态** → 硬件零 buffer 写;等下一轮 wp 造出 State-C 页
时 BR 已修正。

#### Q6: dirty ring 一开始不也是全量标脏+全量拷贝吗?窗口内标错的脏不影响吧?

**bulk 确实会把窗口内 (T2) 的写入内容拷过去——这点对。但 bulk 是
一次性快照,救不了它结束之后的事。**

关键: 脏跟踪是**边沿触发** (C→D 迁移瞬间记录一次),不是电平触发。
P 在 T2 走完迁移但记录进了错误物理页,从此进入死循环:

```
要重新武装这页 (wp: D→C) → 需要它的 entry 出现在 ring 里
要 entry 进 ring            → 需要硬件记录一次 C→D
要 C→D                      → 需要这页先回到 State C
要回到 State C              → 需要重新武装这页    ← 死循环,断在第一环
```

ring 模式下 wp 的唯一触发源 = "entry 被 ring 收割" (reset →
kvm_arch_mmu_enable_log_dirty_pt_masked)。entry 不存在 → 永不
wp → P 永远 State D → T4 之后 (bulk 快照后到 cutover 前) 的**所有**
写入静默丢失。

与两个旧窗口的本质区别 (为什么旧的能自愈、这个不能):

| 窗口 | 窗口内 PTE (内存中) | 自愈路径 |
|------|:---:|------|
| stale TLB 窗口 | **仍是 C** | TLB flush 后下次写仍触发 C→D → 被记录 ✓ |
| HDBSS 异步延迟 | D, entry **在 buffer 里** | 下次 exit flush 进 ring, 延迟一轮 ✓ |
| **BR 陈旧窗口** | D, entry 在**错误物理页** | 无任何路径再碰这页 ✗ |

量级佐证: 丢的写入 = T4→cutover 期间打在"被解除武装页"上的全部
写入 ≈ 617MB (recvmsg 序列号差)。eager wp 刚把全部 4G 刷成 State C,
redis 的写打哪哪中——被解除武装的页不是少数,是整个工作集。

"bulk 先全量拷"反而解释了一个表象: 崩溃不在迁移一开始爆,而是
cutover 后 redis 跑了一段时间才炸——因为丢失的是快照之后的增量。

### 可证伪预测

- **宿主机冷启动后的第一次迁移**: BR=0(从未被写过),硬件写 PA 0 →
  ExternalAbort → FSC 置位 → QEMU 报错(症状与静默崩溃不同)
- **第二次及以后的测试**: BR 指向 freed buffer 的复用页 → 静默污染
  → guest 崩溃

如果测试日志能发现"第一轮失败方式不一样(报错),后面全是 guest
崩溃",即实锤。

### 修复 (已提交)

**主修复**——RELOAD_STAGE2 handler 在 `__load_stage2()` 之前编程
HDBSS 寄存器 (`arch/arm64/kvm/arm.c` check_vcpu_requests):

```c
local_irq_save(flags);
/*
 * The new VTCR_EL2 may be turning HDBSS on for a vCPU that is
 * mid-KVM_RUN and never went through kvm_arch_vcpu_load() with
 * the feature on.  Program the buffer registers first: hardware
 * dirty-state updates start with the VTCR write below, and would
 * otherwise be recorded through whatever stale address HDBSSBR_EL2
 * still holds.
 */
if (vcpu_hdbss_enabled(vcpu))
    kvm_vcpu_load_hdbss(vcpu);
__load_stage2(vcpu->arch.hw_mmu);
local_irq_restore(flags);
```

新增 `kvm_vcpu_load_hdbss()` (`arch/arm64/kvm/dirty_bit.c`),与
`__load_hdbss()` 等价的宿主上下文版本 (HDBSS 是 VHE-only 特性,
宿主上下文可直接写 EL2 寄存器)。顺序保证: **HDBSS 寄存器先于
VTCR 写入**——硬件 HDBSS 直到 VTCR 重载才真正生效,因此修复后
不存在"硬件 HDBSS 已激活但 BR 陈旧"的窗口。

其他进入路径均天然安全: vCPU 在 userspace → 下次 KVM_RUN 的
vcpu_load 先于 RELOAD handler 执行; vCPU 被抢占 → sched_in 的
kvm_arch_vcpu_load 编程 BR。

**加固**——`kvm_arm_vcpu_alloc_hdbss()` 分配改为
`GFP_KERNEL_ACCOUNT | __GFP_ZERO`: 即使 INDEX 未来再出问题,
flush 也只能读到 invalid entry(bit 0 清零),不会把残留垃圾
push 进 dirty ring。

### 验证手段

1. 修复前在 RELOAD handler 加 WARN 比对寄存器与软件值,迁移启动
   瞬间 busy vCPU 必然命中:
   ```c
   WARN_ONCE(read_sysreg_s(SYS_HDBSSBR_EL2) !=
             vcpu->arch.hdbss.hdbssbr_el2, "HDBSSBR_EL2 stale\n");
   ```
2. 对比宿主机冷启动后的第一次迁移(预期 ExternalAbort/报错)与
   连续第二次迁移(预期静默 guest 崩溃)
3. ~~修复后重跑 rand_ring2048_lazy_4k_bw800 场景 ≥300s~~
   **[2026-09-17 已完成: 通过, 崩溃不再复现, 根因定案]**

## 根因定案与实测验证 (2026-09-17)

**实测结果: 打上修复 (linux.git code_v5_2_tested `d52cdc8ea269`,
"Program HDBSS buffer registers on KVM_REQ_RELOAD_STAGE2") 后,
原崩溃场景 (4K stage-2 + dirty ring + HDBSS 迁移, redis 负载)
不再复现。根因就此定案。**

### 定案的根因 (最终表述)

HDBSS 的硬件使能 (per-CPU 的 VTCR_EL2.HDBSS 翻转) 与 per-CPU
HDBSS 缓冲寄存器 (HDBSSBR_EL2/HDBSSPROD_EL2) 的装载之间存在
**结构性缝隙**: 使能发生时, 正在 KVM_RUN 中间的 vCPU 所在 CPU 上,
这两个寄存器仍持有陈旧值 (复位值 0, 或上一个在这颗 CPU 上跑过
HDBSS 的 vCPU 的残留——其 buffer 页已释放并可能被 buddy 复用)。
而硬件对 writable-clean 页的写响应是零软件介入的静默动作
(C→D 原子升级 + entry 写入 BR.BADDR + INDEX*8), 于是:

1. **真实脏页记录永久丢失** → 页已是 State-D 无 C→D, ring 无 entry
   → 永不 wrprotect → QEMU dirty 集合永远没有该页 → bulk 快照之后的
   写入永不重发 → DST 收到部分停留在旧快照的内存, 增量发散后
   guest 随机崩溃 (call trace 每次不同)
2. **无关物理内存被 8 字节 entry 污染** (BR 指向 freed-and-reused 页时)

一句话: **使能瞬间 per-CPU 硬件状态切换不完整——VTCR 切了,
buffer 寄存器没切。**

### 同一缺陷在两个变体中的表现 (kick vs RELOAD)

排查中发现开发线上存在两个使能变体, 缺陷以两种形态出现, 修复
(d52cdc8ea269) 同时覆盖:

| 变体 | 使能方式 | 缺口表现 | 修复如何闭合 |
|------|---------|---------|------------|
| kick 变体 (origin_patches / HDBSS_V5 `f928b0b`) | 软件置 VTCR 位 + `kvm_vcpu_kick` 踢出 | vCPU 被踢出后不经过 vcpu_load, 带旧 VTCR (HD=0) 直接重入 guest; 期间 exit 路径 flush 的守卫读软件 VTCR (已 ON) → 用**上一任 vCPU 残留的 HDBSSPROD_EL2.INDEX** 去**未清零**的 buffer 页读 garbage GFN push 进 ring | `__GFP_ZERO`: buffer 页清零后, 错误 INDEX 只能读到 invalid entry (bit 0=0), 不会被当作 GFN |
| RELOAD 变体 (当前 code_v5_2_tested, `6c52858` 之后) | 软件置 VTCR 位 + `KVM_REQ_RELOAD_STAGE2` | handler 只重载 VTCR/VTTBR, **不装 BR/PROD** → vCPU 带【新 VTCR (HD=1) + 陈旧 BR】重入 guest → 硬件全速把 entry 写进陈旧地址 | `kvm_vcpu_load_hdbss()`: 在 `__load_stage2()` **之前**编程 BR/PROD——"先装弹, 后开保险", 不变式在 HDBSS 激活的写指令执行时已成立 |

两个变体的演进关系: `6c52858` 把 kick 改成 RELOAD, 关闭了
"软件 ON / 硬件 OFF" 的 VTCR 窗口, 却引入了 "硬件 ON / BR 陈旧"
的反向窗口; `d52cdc8ea269` 补齐了这半块。**两者合起来才是完整的
使能路径修复**——这也是为什么该 bug 的威胁面是"任何使能时刻存在
writable-clean 页的模式", 不只 dirty ring (bitmap/legacy 同理,
只是 INITIALLY_SET 恰好跳过 eager wp 而侥幸)。

### 定案结论清单

1. **崩溃判别变量**: HDBSS 使能瞬间 stage-2 里有无 writable-clean 页。
   4K+ring: eager wp 与使能同瞬间发生 (同一 commit_memory_region),
   L3 保留 DBM → 全 State-C, 首批写立即命中缺口 💥;
   bitmap: INITIALLY_SET 跳过 eager wp → 全 State-D, 硬件没活干 ✓;
   THP/huge: block 剥 DBM → State-N, split 子页继承 RO → 第一轮走
   fault 软件路径, 不经 State-C ✓; hdbss=off: 无硬件路径 ✓
2. **崩溃显形在迁入端**: SRC 丢的是"页在变"的信息 (guest 本身
   运行正常), 陈旧快照经迁移通道传导到 DST, 在 DST 兑现为内存发散
   (~617MB recvmsg 序列号差 ≈ bulk 快照后持续写入量)
3. **bulk 全量拷贝不构成兜底**: 脏跟踪是边沿触发, 记录丢失的页
   无法再被重新武装 (wp 依赖 entry 收割 → 死循环), bulk 快照之后到
   cutover 之间的写入全部丢失
4. **flush 救不了**: kvm_flush_hdbss_buffer() 的 entry 数据从软件侧
   hdbss_pg 读, 从不回读 BR; PROD 的 save/restore 也全是软件值,
   没有一个字节能修正 BR 里的地址
5. **方案 C (stale TLB 方向) 无效的原因**: 它修的是稳态 reset 循环
   的竞态, 污染发生在使能瞬间, 两者正交

### 修复内容 (d52cdc8ea269, 已实测验证)

1. `arch/arm64/kvm/arm.c` RELOAD_STAGE2 handler: `__load_stage2()`
   之前调 `kvm_vcpu_load_hdbss(vcpu)` (守卫 `vcpu_hdbss_enabled`)
2. `arch/arm64/kvm/dirty_bit.c` 新增 `kvm_vcpu_load_hdbss()`:
   宿主上下文写 HDBSSBR_EL2/HDBSSPROD_EL2 + isb (HDBSS 为 VHE-only)
3. `kvm_arm_vcpu_alloc_hdbss()`: 分配加 `__GFP_ZERO`

补丁文件: 本目录
`0001-KVM-arm64-Program-HDBSS-buffer-registers-on-KVM_REQ_.patch`

## 关键代码位置索引

| 代码位置                                   | 说明                              |
|--------------------------------------------|-----------------------------------|
| QEMU accel/kvm/kvm-all.c:3151 KVM_EXIT_DIRTY_RING_FULL handler | ring 满 reap（无 kick） |
| QEMU accel/kvm/kvm-all.c:740 kvm_dirty_ring_reap_one | 从 mmap 读 ring entries（无锁用户态读） |
| QEMU accel/kvm/kvm-all.c:685 kvm_dirty_ring_mark_page | set_bit 标记 KVMSlot.dirty_bmap |
| QEMU accel/kvm/kvm-all.c:777 kvm_dirty_ring_reap_locked | reap 后调 ioctl(KVM_RESET_DIRTY_RINGS) |
| QEMU accel/kvm/kvm-all.c:1437 kvm_dirty_ring_reaper_thread | 每秒 reap（无 kick） |
| QEMU accel/kvm/kvm-all.c:864 kvm_dirty_ring_flush | kick + reap（bitmap sync 路径）|
| QEMU accel/kvm/kvm-all.c:847 kvm_cpu_synchronize_kick_all | kick 所有 vCPU（run_on_cpu 等待）|
| QEMU accel/kvm/kvm-all.c:664 kvm_slot_get_dirty_log | KVM_GET_DIRTY_LOG ioctl（bitmap 模式填充）|
| QEMU accel/kvm/kvm-all.c:615 kvm_slot_sync_dirty_pages | KVMSlot.dirty_bmap → RAMBlock 全局 bitmap |
| QEMU migration/ram.c:1154 migration_bitmap_sync | 每轮迭代开头的 bitmap 同步 |
| QEMU migration/ram.c:3791 ram_save_iterate | 迭代阶段扫描 bitmap 逐页发送 |
| QEMU migration/ram.c:3008 ram_find_and_save_block | 找 dirty 页并发送 |
| QEMU migration/ram.c:3948 ram_save_complete | 最后一轮（有 kick 兜底）|
| QEMU migration/migration.c:2761 migration_completion_precopy | VM stop → final sync |
| QEMU cpu-common.c:184 do_run_on_cpu | 同步等待 work item 完成 |
| virt/kvm/kvm_main.c:4999 kvm_vm_ioctl_reset_dirty_pages | dirty ring reset 入口，缺少 sync |
| virt/kvm/kvm_main.c:2248 kvm_arch_sync_dirty_log     | bitmap 路径有调用，ring 路径没有    |
| virt/kvm/kvm_main.c:2279 (bitmap) / dirty_ring.c:75 (ring) kvm_arch_mmu_enable_log_dirty_pt_masked 调用点 | 两路径共用的 wrprotect 入口 |
| virt/kvm/dirty_ring.c:110 kvm_dirty_ring_reset       | ring reset 主体，含 cond_resched    |
| virt/kvm/dirty_ring.c:163 cond_resched              | yield CPU，放大竞态窗口              |
| virt/kvm/dirty_ring.c:190 kvm_reset_dirty_gfn       | 调用 arch wrprotect                  |
| virt/kvm/dirty_ring.c:223 kvm_dirty_ring_push       | push entry 到 ring                  |
| virt/kvm/dirty_ring.c:248 kvm_dirty_ring_check_request | ring 满退出前 re-set 请求阻止 vCPU 重入 |
| arch/arm64/kvm/mmu.c:1326 kvm_arch_mmu_enable_log_dirty_pt_masked | arm64 wrprotect 入口（两路径共享） |
| arch/arm64/kvm/hyp/pgtable.c:1231 stage2_attr_walker | PTE 修改: 清 S2AP_W, block 剥 DBM (→State N), page 保留 DBM (→State C) |
| arch/arm64/kvm/hyp/pgtable.c:1377 kvm_pgtable_stage2_relax_perms | relax 放开写权限时设 DBM (block→page 转换关键) |
| arch/arm64/kvm/hyp/pgtable.c:734 stage2_set_prot_attr | PROT_W → 同时设 S2AP_W + DBM |
| arch/arm64/kvm/hyp/pgtable.c:756 kvm_pgtable_stage2_pte_prot | 提取 prot (不含 DBM) — split 继承状态 |
| arch/arm64/kvm/hyp/pgtable.c:1515 stage2_split_walker | block 拆页，继承 block 的 prot (State N) |
| arch/arm64/kvm/mmu.c:1676/2077 relax_perms 调用点 | permission fault 走 relax (非 stage2_map) |
| arch/arm64/kvm/arm.c:1490 kvm_flush_hdbss_buffer    | HDBSS buffer flush (在 IPI ack 后) |
| arch/arm64/kvm/arm.c:2078 kvm_arch_sync_dirty_log   | HDBSS 模式下 kick 所有 vCPU |
| arch/arm64/kvm/dirty_bit.c:63 kvm_flush_hdbss_buffer | HDBSS buffer flush 实现             |
| arch/arm64/kvm/hyp/vhe/switch.c:223 __load_hdbss | HDBSSBR/PROD_EL2 唯一编程点(vcpu_load, 仅 HDBSS 已启用时) |
| arch/arm64/kvm/arm.c:1240 KVM_REQ_RELOAD_STAGE2 handler | VTCR 翻转点; 根因所在, 修复在此补 HDBSS 寄存器编程 |
| arch/arm64/kvm/dirty_bit.c kvm_vcpu_load_hdbss | 修复新增: 宿主上下文编程 HDBSS 寄存器 |
| qemu accel/kvm/kvm-all.c:2653 | dirty ring 模式跳过 MANUAL_DIRTY_LOG_PROTECT2 → eager wp → 窗口内全 State C(bitmap 模式不崩的原因) |
| include/linux/kvm_host.h:180 KVM_REQ_OUTSIDE_GUEST_MODE | 带 KVM_REQUEST_WAIT 的 kick 请求   |
| arch/x86/kvm/mmu/spte.h:546 leaf_spte_change_needs_tlb_flush | x86 判断是否需要 TLB flush     |
| arch/x86/kvm/mmu/tdp_mmu.c:777 kvm_flush_remote_tlbs | x86 cond_resched 前先 flush         |
