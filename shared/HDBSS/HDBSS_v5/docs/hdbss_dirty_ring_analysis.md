# HDBSS + Dirty Ring 性能分析

## 1. 背景

HDBSS（Hardware Dirty Bit State Structure）是 ARM64 的硬件脏页跟踪机制，类似 x86 的 PML（Page Modification Logging）。HDBSS 在 guest 写 Writable-Clean 页时自动记录脏页到 buffer，减少 VM exit。

KVM 支持两种 dirty tracking 模式：
- **dirty-bitmap**：KVM 维护 per-memslot 的 bitmap，通过 `KVM_GET_DIRTY_LOG` 获取
- **dirty-ring**：per-vCPU ring buffer，通过 mmap 共享给 userspace，零拷贝

HDBSS 可以与两种模式共存：
- **HDBSS + dirty-bitmap**：flush HDBSS buffer → `set_bit_le(bitmap)`
- **HDBSS + dirty-ring**：flush HDBSS buffer → `kvm_dirty_ring_push(ring)`

## 2. Dirty Ring 的 Reservation 机制

### 核心公式

```
rsvd = KVM_DIRTY_RING_RSVD_ENTRIES + kvm_cpu_dirty_log_size(kvm)
     = 64 + hdbss_entries

soft_limit = ring_entries - rsvd

drain 触发条件：ring used >= soft_limit
```

- `rsvd`：为 HDBSS flush 预留的 ring 空间
- `soft_limit`：ring 使用到此阈值时，vCPU 退出到 userspace drain ring
- `hdbss_entries`：HDBSS buffer 容量（entries 数）

### 关键约束

HDBSS buffer 在 VM exit 时一次性 flush 到 dirty ring。如果 ring 剩余空间不足，`kvm_dirty_ring_push` 会导致 ring 溢出（`WARN_ON_ONCE(kvm_dirty_ring_full)`）。

reservation 机制确保 ring 在 HDBSS flush 前有足够空间：`rsvd >= hdbss_entries`，即 `64 + hdbss_entries >= hdbss_entries`（始终满足）。

## 3. Drain 频率分析

### 定义

- **drain**：vCPU 退出到 userspace，userspace harvest dirty ring entries 后 vCPU 重新进 guest
- **drain interval**：两次 drain 之间积累的脏页数
- **VM exit**：guest 退出到 KVM（不退出到 userspace），KVM 处理后直接回 guest

### Drain 触发条件

HDBSS buffer 满 → VM exit → flush hdbss_entries 个到 ring → 检查 soft_full

N 次 flush 后 ring used = N × hdbss_entries，触发 drain 当：
```
N × hdbss_entries >= soft_limit = ring_entries - 64 - hdbss_entries
→ N >= (ring_entries - 64 - hdbss_entries) / hdbss_entries
→ N >= (ring_entries - 64) / hdbss_entries - 1
```

drain interval = N × hdbss_entries

### 关键发现

HDBSS buffer 越大：
- rsvd 越大 → soft_limit 越小 → drain 越频繁
- 但每次 flush 量更大 → VM exit 频率更低

HDBSS buffer 越小：
- rsvd 越小 → soft_limit 越大 → drain 越少
- 但每次 flush 量更小 → VM exit 频率更高

**drain 开销远大于 VM exit 开销**（drain 要退出 userspace + harvest + 重入，VM exit 只 flush + 回 guest）。因此减少 drain 比减少 VM exit 更重要。

## 4. 不同 HDBSS buffer size 的对比

### 完整数据表（4KB 页，sizeof(u64) = 8）

| ring_entries | hdbss_entries | rsvd | soft_limit | flushes_to_drain | drain_interval |
|---|---|---|---|---|---|
| **1024** | | | | | |
| | 512 (PAGE_SIZE) | 576 | 448 | 1 | 512 |
| | 512 (auto) | 576 | 448 | 1 | 512 |
| **4096** | | | | | |
| | 512 (PAGE_SIZE) | 576 | 3520 | 7 | **3584** |
| | 2048 (auto) | 2112 | 1984 | 1 | 2048 |
| **8192** | | | | | |
| | 512 (PAGE_SIZE) | 576 | 7616 | 15 | **7680** |
| | 4096 (auto) | 4160 | 4032 | 1 | 4096 |
| **16384** | | | | | |
| | 512 (PAGE_SIZE) | 576 | 15808 | 31 | **15872** |
| | 8192 (auto) | 8256 | 8128 | 1 | 8192 |
| **32768** | | | | | |
| | 512 (PAGE_SIZE) | 576 | 32192 | 63 | **32256** |
| | 16384 (auto) | 16448 | 16320 | 1 | 16384 |
| **65536** | | | | | |
| | 512 (PAGE_SIZE) | 576 | 64960 | 127 | **65024** |
| | 32768 (auto) | 32832 | 32704 | 1 | 32768 |

### 分析

**所有 ring size 下（>= 1024），hdbss=512 的 drain_interval 都是 auto 的约 2 倍。**

- auto 算法每次都让第一次 flush 就触发 drain（flushes_to_drain = 1）
- hdbss=512 时，需要多次 flush 才 drain，中间的 flush 不退出 userspace，vCPU 直接回 guest

### 例外

- `ring_entries = 576`（最小值）：rsvd=576 >= ring=576，512 不可用。实际上 dirty ring 最小要求就是能容纳 rsvd=576 entries
- `ring_entries = 1024`：auto 算出来也是 512，两者相同

## 5. HDBSS + dirty-ring vs HDBSS + dirty-bitmap

### Flush 路径对比

**HDBSS + dirty-bitmap**：
```
VM exit → flush HDBSS buffer
  → for each entry:
      set_bit_le(rel_gfn, bitmap)     // 原子指令，不检查 soft_limit
  → 回 guest                            // 不退出 userspace
```

**HDBSS + dirty-ring**：
```
VM exit → flush HDBSS buffer
  → for each entry:
      kvm_dirty_ring_push(ring, ...)  // 写 entry + 检查 soft_limit
      → if soft_full: set KVM_REQ_DIRTY_RING_SOFT_FULL
  → 回 while 循环
  → check_vcpu_requests → dirty_ring_check
  → if soft_full: 退出 userspace drain   // vCPU 停顿
```

### 性能差异原因

| 因素 | dirty-bitmap | dirty-ring |
|------|-------------|-----------|
| flush 后是否退出 userspace | **否**，直接回 guest | **是**，如果触发 soft_full |
| drain 频率 | 无（userspace 主动 `KVM_GET_DIRTY_LOG`） | 取决于 soft_limit |
| flush 单条开销 | `set_bit_le`（1 条原子指令） | `kvm_dirty_ring_push`（写 entry + smp_wmb + 检查 soft_full + 可能设 request） |
| userspace 获取脏页 | `KVM_GET_DIRTY_LOG`（copy bitmap） | mmap 零拷贝读 ring |

### 实测数据（redis 高并发 + live migration）

| 模式 | 迁移前 QPS | 迁移中 QPS | 下降幅度 |
|------|-----------|-----------|---------|
| HDBSS + dirty-bitmap | 155000 | 144000 | -7% |
| HDBSS + dirty-ring (65536, auto hdbss=32768) | 155000 | 127000 | -18% |

### 原因

HDBSS + dirty-ring 性能更差的原因：

1. **HDBSS buffer 太大（32768 entries）导致 rsvd 太大（32832），soft_limit 太小（32704）**
2. **第一次 flush 就触发 drain**，之后每次 flush 都触发 drain
3. **drain 开销大**：vCPU 退出 userspace → userspace harvest → vCPU 重入
4. **dirty-bitmap 模式无 drain**：flush 完直接回 guest

### 与 x86 PML 的对比

| | x86 PML | arm64 HDBSS（auto） |
|---|---|---|
| buffer size | 固定 512 entries | 动态计算，最大 32768 entries |
| rsvd (ring=65536) | 576 | 32832 |
| soft_limit (ring=65536) | 64960 | 32704 |
| flushes_to_drain | 127 | 1 |
| drain_interval | 65024 | 32768 |

x86 PML buffer 固定 512 entries，rsvd 小，soft_limit 大，drain 频率低。HDBSS 动态算大 buffer 导致 drain 频率高。

## 6. 最优 HDBSS buffer size

### 结论

**dirty ring 模式下，HDBSS buffer = PAGE_SIZE（512 entries on 4KB page）是最优的。**

理由：
1. **drain interval 最大**：所有 ring size 下，512 的 drain_interval 都是最大的
2. **跟 x86 PML 一致**：PML 也是固定 512 entries，不动态调整
3. **VM exit 开销小于 drain 开销**：buffer 小增加 VM exit 频率，但减少 drain 频率，净收益为正
4. **简单可靠**：固定值不需要动态计算，避免"buffer 大 → rsvd 大 → drain 多"的反直觉问题

### 边界情况

- `ring_entries < 576`：dirty ring 验证阶段被拒绝（`size < rsvd * sizeof(struct kvm_dirty_gfn)`）
- `ring_entries = 576`：rsvd=576，soft_limit=0，每次 push 都触发 soft_full（性能差但功能正确）
- `ring_entries = 1024`：auto 算出来也是 512，与固定值相同
- `ring_entries >= 1024`：固定 512 的 drain_interval 始终优于 auto

### 不同页大小

| 页大小 | PAGE_SIZE | hdbss_entries (PAGE_SIZE/8) |
|--------|-----------|---------------------------|
| 4KB | 4096 | 512 |
| 16KB | 16384 | 2048 |
| 64KB | 65536 | 8192 |

16KB/64KB 页的 hdbss_entries 更大，但 rsvd 也更大。在 dirty ring 模式下仍然比动态算大值更优（因为动态值只会更大）。

## 7. 实现建议

### dirty ring 模式

`kvm_arch_dirty_ring_size_updated()` 中直接使用 `KVM_ARM_HDBSS_DEFAULT_SIZE`（PAGE_SIZE），不动态计算：

```c
void kvm_arch_dirty_ring_size_updated(struct kvm *kvm)
{
    if (!system_supports_hdbss())
        return;

    /* Keep user-configured buffer size from Phase 7 ioctl */
    if (kvm->arch.hdbss_buffer_size)
        return;

    /* Use minimum buffer size (PAGE_SIZE), same as x86 PML.
     * Larger buffer increases rsvd, reducing dirty ring soft_limit
     * and causing more frequent userspace drains.
     */
    kvm->arch.hdbss_buffer_size = KVM_ARM_HDBSS_DEFAULT_SIZE;
}
```

### dirty-bitmap 模式

用户通过 `KVM_CAP_ARM_HDBSS_BUFFER_SIZE` ioctl 自由配置（Phase 7），不受 dirty ring reservation 约束。

### 为什么不"算出最大不触发 drain 的 buffer"？

理论上可以算出 `hdbss_entries = floor((ring_entries - 64) / 2)` 使 2 次 flush 才 drain。但：

1. `rounddown_pow_of_two()` 后可能变成 3 次才 drain（如 ring=65536 → 16384 → 3 次）
2. 即使 2 次 drain，drain_interval 仍小于 hdbss=512 的值
3. 计算复杂，且对不同 ring size 的收益不稳定
4. x86 PML 用固定 512 就是最好的先例——简单且最优
