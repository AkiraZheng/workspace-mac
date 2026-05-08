# Dirty Ring vs Dirty Bitmap 热迁移机制对比

## 概述

热迁移（Live Migration）时，需要跟踪 Guest 虚拟机哪些内存页被修改过（脏页），将这些脏页从源端传输到目标端。KVM 提供两种脏页跟踪机制：**Dirty Bitmap** 和 **Dirty Ring**。

---

## 一、核心区别

| 特性 | Dirty Ring | Dirty Bitmap |
|------|------------|--------------|
| **数据结构** | 每vCPU的环形缓冲区 (`kvm_dirty_gfn[]`) | 每个memory slot的位图 (`dirty_bitmap`) |
| **大小** | 固定64KB/VCPU | 随VM内存线性增长（128GB VM ≈ 4MB） |
| **收集方式** | 异步轮询：Reaper线程(1s) + VCPU exit通知 | 同步拉取：QEMU主动调用 `KVM_GET_DIRTY_LOG` ioctl |
| **触发时机** | ring满 / soft_limit / 定时1s | migration迭代时QEMU主动调用 |
| **数据量** | 增量，只记录实际写入 | 全量，每次copy整个bitmap |
| **内存开销** | O(vCPU数) | O(VM内存/页大小) |

---

## 二、Dirty Bitmap 机制

### 2.1 数据结构

```
Slot:  [ bitmap x 32768 bits ]  = 4KB (假设128GB VM，4KB页)
       [ 0 0 1 0 0 1 0 ... 0 ]
                 ↑     ↑
       第2页脏了  第5页脏了
```

- **大小**：整个slot的页数，线性增长
- **标记方式**：Guest写内存 → `set_bit_le(rel_gfn, memslot->dirty_bitmap)` → bit位 0→1
- **累积**：bitmap一直在累积，从不清空，除非调用 `KVM_GET_DIRTY_LOG`

### 2.2 代码流

#### QEMU侧发起
```
ram_find_and_save_block(rs)        // migration/ram.c - 迁移迭代时调用
    +-> migration_bitmap_sync_precopy(true)  // ram.c - 同步脏页
        +-> memory_global_dirty_log_sync(last_stage)  // memory.c
            +-> kvm_log_sync_global(l, last_stage)  // kvm-all.c
                +-> kvm_dirty_ring_flush()  // 可选，ring模式
                +-> for each slot:
                    +-> kvm_slot_get_dirty_log(s, mem)  // kvm-all.c
                        +-> kvm_vm_ioctl(s, KVM_GET_DIRTY_LOG, &d)  // ← 发起ioctl
```

#### Kernel侧处理
```
kvm_vm_ioctl_get_dirty_log()  // kvm_main.c - ioctl入口
    +-> kvm_get_dirty_log_protect()
        +-> kvm_get_dirty_log()
            +-> flush_tlb()  // 刷新TLB
            +-> copypage_to_user()  // ← 复制整个bitmap到用户空间
```

#### QEMU收到后处理
```
kvm_vm_ioctl() 返回
    +-> ram_find_and_save_block() 继续
        +-> for each bit set in bitmap:
            +-> ram_save_page(rs, block, offset)  // 发送脏页到目标
```

### 2.3 特点

- **整个bitmap每次都要copy**：不管有多少脏页，整个slot的bitmap都要从内核复制到用户空间
- **清除时机**：`KVM_GET_DIRTY_LOG` 会自动清除dirty位并重新保护页
- **遍历开销**：QEMU需要遍历整个bitmap（32768 bits for 128GB VM），即使只有几个脏页

---

## 三、Dirty Ring 机制

### 3.1 数据结构

```
Ring:  [ dirty_gfn entries x 65536 ]  = 64KB (固定)
       [slot:5,off:1234] [slot:5,off:5678] ...
        ↑_____________↑
           每次写入一个entry
```

- **大小**：固定，通常64K条目
- **标记方式**：Guest写内存 → push一个entry到ring
- **FIFO**：是循环队列，写满就覆盖或触发exit

### 3.2 代码流

#### 路径1：后台 Reaper 线程（异步、主动）

```
kvm_dirty_ring_reaper_thread()  // kvm-all.c，后台每1秒跑一次
    +-> kvm_dirty_ring_reap(s, NULL)
        +-> for each vcpu:
            +-> kvm_dirty_ring_reap_one(s, cpu)  // 读取ring
                +-> while dirty_gfn_is_dirtied(entry):
                    +-> kvm_dirty_ring_mark_page()  // 设置bit到KVMSlot bitmap
                    +-> dirty_gfn_set_collected()    // 标记entry为已收集
                +-> kvm_vm_ioctl(s, KVM_RESET_DIRTY_RINGS)  // 重置ring
```

#### 路径2：VCPU Exit 通知（同步、被动）

```
VCPU exit (ring满或soft_limit)
    +-> KVM_EXIT_DIRTY_RING_FULL 退出原因
        +-> QEMU收到exit
            +-> kvm_dirty_ring_flush()
                +-> kvm_cpu_synchronize_kick_all()  // 踢所有vCPU退出guest
                +-> kvm_dirty_ring_reap()          // 同路径1的收集逻辑
```

#### Kernel侧写入（被动）

```
Guest 写内存 → Page Fault → mark_page_dirty_in_slot()
    +-> kvm_dirty_ring_push(vcpu, slot, rel_gfn)
        +-> entry->slot = slot
        +-> entry->offset = rel_gfn
        +-> smp_wmb()
        +-> kvm_dirty_gfn_set_dirtied(entry)  // 写屏障+原子设置
        +-> ring->dirty_index++
        +-> if soft_full:
            +-> kvm_make_request(KVM_REQ_DIRTY_RING_SOFT_FULL, vcpu)
            +-> vcpu exit → KVM_EXIT_DIRTY_RING_FULL
```

### 3.3 迁移迭代时读取脏页

```
ram_find_and_save_block(rs)        // migration/ram.c
    +-> migration_bitmap_sync_precopy(true)
        +-> memory_global_dirty_log_sync()
            +-> kvm_log_sync_global()
                +-> kvm_slots_lock()
                +-> for each slot:
                    +-> kvm_slot_sync_dirty_pages(mem)  // 同步到ram_list
                +-> kvm_slot_reset_dirty_pages(mem)     // 清空QEMU bitmap
                +-> kvm_slots_unlock()
        +-> 遍历KVMSlot.dirty_bmap，发送脏页
```

---

## 四、两种模式对比

### 4.1 形象比喻

| | Dirty Ring | Dirty Bitmap |
|--|------------|--------------|
| 机制 | **推送+拉取** (push + poll) | **纯拉取** (pure pull) |
| 触发 | ring满/soft_limit/定时1s | migration迭代时 |
| 角色 | 内核"喂"数据，QEMU来吃 | QEMU主动来问，内核回答 |

### 4.2 实际迁移流程

```
Dirty Ring:

  [Reaper线程 1s一次] 或 [VCPU exit时]
         ↓
  kvm_dirty_ring_reap_one() 读取ring
         ↓
  设置 KVMSlot.dirty_bmap 的对应bit
         ↓
  ram_find_and_save_block() 遍历bitmap发送脏页
         ↓
  (同时) KVM_RESET_DIRTY_RINGS 重置ring

Dirty Bitmap:

  migration迭代开始 → QEMU调用KVM_GET_DIRTY_LOG
         ↓
  内核复制整个dirty_bitmap到用户空间 + 清除脏位
         ↓
  遍历bitmap找到脏页
         ↓
  发送脏页到目标端
```

---

## 五、Ring 和 Bitmap 能同时存在吗？

### 5.1 正常情况：二选一，互斥

`mark_page_dirty_in_slot()` 是互斥的：

```c
// kvm_main.c - 写入时只走一条路径
if (kvm->dirty_ring_size && vcpu)
    kvm_dirty_ring_push(vcpu, slot, rel_gfn);   // 有ring就走ring
else if (memslot->dirty_bitmap)
    set_bit_le(rel_gfn, memslot->dirty_bitmap); // 没ring才走bitmap
```

### 5.2 开启时的互斥关系

| 配置 | Dirty Ring | Dirty Bitmap |
|------|------------|-------------|
| 只开ring | ✅ 用 | ❌ 不用 |
| 只开bitmap | ❌ 不用 | ✅ 用 |
| 都不开 | ❌ | ❌ (不做脏页跟踪) |

### 5.3 `dirty_ring_with_bitmap` 特殊模式

这是某些架构下的backup机制，不是两者同时存在：

```c
if (s->kvm_dirty_ring_with_bitmap && last_stage &&
    kvm_slot_get_dirty_log(s, mem)) {
    // 某些情况下用 KVM_GET_DIRTY_LOG 作为备份
}
```

---

## 六、Dirty Ring 的优势

1. **内存效率**：Ring大小固定(~64KB/vCPU)，vs Bitmap随VM内存线性增长（128GB VM ≈ 4MB）
2. **低延迟**：不需要每次同步都调用阻塞ioctl
3. **批量收集**：Reaper线程后台收集，减少迁移停顿
4. **可预测溢出**：Soft limit机制提前退出，避免数据丢失

---

## 七、关键文件索引

### Kernel 侧
| 文件 | 作用 |
|------|------|
| `virt/kvm/dirty_ring.c` | 核心dirty ring实现 |
| `include/linux/kvm_dirty_ring.h` | ring头文件 |
| `virt/kvm/kvm_main.c` | `mark_page_dirty_in_slot()` 路由 |
| `include/linux/kvm_host.h` | `struct kvm_dirty_ring` 定义 |
| `include/uapi/linux/kvm.h` | UAPI: `kvm_dirty_gfn`, flags |

### QEMU 侧
| 文件 | 作用 |
|------|------|
| `accel/kvm/kvm-all.c` | ring初始化、reaper线程 |
| `include/system/kvm.h` | 公共API |
| `include/system/kvm_int.h` | 内部结构 |
| `migration/ram.c` | RAM迁移逻辑 |
| `migration/migration.c` | 迁移状态机 |

---

## 八、数据结构

### struct kvm_dirty_ring (Kernel)
```c
struct kvm_dirty_ring {
    u32 dirty_index;     // 下一个新dirty页的位置
    u32 reset_index;     // 下一个待重置的dirty页位置
    u32 size;            // ring大小
    u32 soft_limit;      // 软限制，触发提前退出
    struct kvm_dirty_gfn *dirty_gfns;  // ring数组
    int index;           // VCPU索引
};
```

### struct kvm_dirty_gfn (Kernel UAPI)
```c
struct kvm_dirty_gfn {
    __u32 flags;    // KVM_DIRTY_GFN_F_DIRTY (0x1) 或 KVM_DIRTY_GFN_F_RESET (0x2)
    __u32 slot;     // 内存slot ID (as_id << 16 | slot_id)
    __u64 offset;   // slot内的页偏移
};
```

### KVMState (QEMU)
```c
uint64_t kvm_dirty_ring_bytes;    // per-vcpu ring大小
uint32_t kvm_dirty_ring_size;     // ring条目数
bool kvm_dirty_ring_with_bitmap;  // 是否启用backup bitmap
struct KVMDirtyRingReaper reaper; // reaper线程状态
```

### CPUState (QEMU)
```c
struct kvm_dirty_gfn *kvm_dirty_gfns;  // mmap的ring buffer
uint32_t kvm_fetch_index;               // 已读取到的index
uint64_t dirty_pages;                   // dirty页计数
```

---

*整理时间：2026-05-07*
