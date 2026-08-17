# HDBSS v5 修改要点

基于 v4 邮件讨论（Oliver Upton、Leonardo Bras、Marc Zyngier、Inochi Amaoto 的人工 review 意见）整理。

讨论来源：`20260709104026.2612599-2-zhengtian10@huawei.com.mbx`
讨论时间：Jul 9 — Aug 10, 2026

---

## 背景与设计参考

### DBM 权限模型

- **Direct Permission**：传统读写权限机制，S2AP[1:0] 表示读写。S2AP[0]=读权限，S2AP[1]=写权限。
- **Indirect Permission**：ARM 在 FEAT_S2PIE 扩展中引入的全新间接映射机制，将页表权限交给 PIE 表管理。未来架构强制 FEAT_S2PIE 时，dirty state 管理是无条件的、与实际权限分开处理的。

HDBSS 利用 DBM 位实现硬件辅助脏页跟踪，核心状态：
- **Writable-clean (C)**：DBM=1, S2AP[1]=0 — 可写但未脏，硬件写时自动转脏并记录到 HDBSS buffer
- **Writable-dirty (D)**：DBM=1, S2AP[1]=1 — 可写且已脏

### x86 PML 参考分析

PML（Page Modification Logging）是 x86 的硬件脏页跟踪机制，HDBSS 的设计可参考其实现：

- PML buffer 在 vcpu create/destroy 时创建和释放
- PML 在 vm init 时确定是否启用，默认开启，用户通过 `kvm_intel.pml=0` 全局禁用（module param）
- PML 的 D 位对应 ARM 的 DBM 位：D 位在建立 SPTE 映射时就设上去
- PML 适配 dirty ring 时，预留 `KVM_DIRTY_RING_RSVD_ENTRIES + PML_LOG_NR_ENTRIES = 64 + 512 = 576`，`soft_limit = ring_size - 576`，确保 dirty ring 里永远至少有 512 个空位
- PML 大页处理：大页 D=1, W=0（wrprot），userspace 写时自然 trap 进来拆大页，relax W=1 后状态变为 D=1, W=1，该脏页通过传统标脏方式被标到 bitmap 或 dirty ring。下一轮迁移时，已拆大页的 leaf 页进入 `kvm_mmu_slot_leaf_clear_dirty`，清 D 标志成 D=0, W=1 的干净状态
  - D=0, W=1 = 干净状态
  - D=1, W=1 = 脏状态

**HDBSS 与 PML 的关键差异**：ARM 的 HDBSS buffer 大小可配置（多种 size），而 PML buffer 固定 512 entries。因此 HDBSS 不能像 PML 那样预分配固定大小。

### 全局 DBM 策略

类似 x86 PML：D bit 无条件设置在所有可写 SPTE 上，buffer 记录所有写，flush 时软件过滤非追踪 memslot。HDBSS 同理：全局 DBM，buffer 记录所有写，`kvm_flush_hdbss_buffer() -> mark_page_dirty_in_slot()` 在 flush 时过滤。

**无需区分 logging memslots**：加 DBM 时不区分是否为 dirty logging 页，全加。非 logging memslot 的页虽然也会被 HDBSS 记录，但在 flush 时 `mark_page_dirty_in_slot()` 会拦截非可标脏的页，不会写入 dirty ring 或 dirty bitmap。

Leo 同意此策略。v5 保持全局 DBM，重点放在正确处理大页的 DBM。

---

## 任务清单（按影响面从小到大排序）

### Phase 1：琐碎修复（单行改动，无依赖）

- [ ] 1.1 `has_vhe_hdbss()` 参数名拼写

`cope` 应为 `scope`。

- [ ] 1.2 `esr_iss2_is_hdbssf()` 返回值规范（Leo 指出）

应使用 `!!` 确保 bool 转换：

```c
return !!(ESR_ELx_ISS2(esr) & ESR_ELx_HDBSSF);
```

- [ ] 1.3 版权声明修正（Leo 指出）

`kvm_dirty_bit.h` 和 `dirty_bit.c` 的 copyright 写的是 `Copyright (C) 2026 ARM Ltd. / Author: Leonardo Bras`，但文件是你创建的，应改为你的版权。

- [ ] 1.4 commit message 更新

- `chunk_size == PAGE_SIZE` 描述不再准确
- 需反映三态模型和双 split 模式的新设计

- [ ] 1.5 包含 base commit（Leo 提醒）

使用 `git format-patch --base=<base-commit>` 自动在 cover letter 末尾生成 base 信息。
Base commit: `0e35b9b6ec0f`

- [x] 1.6 Co-developed-by 标签移除（Marc Zyngier 裁定）— 已完成

Patch 3/6 (auto DBM) 添加了 `Co-developed-by: Leonardo Bras` 和 `Signed-off-by: Leonardo Bras`。

**Marc Zyngier 明确裁定**（Jul 14）：
> "You really can't do that. Only Leo can give his SoB, you can't forge it yourself."
> "Then take the patch as is, and add to it as a separate patch. Or work out in private with Leo whether he's happy with a Co-dev. But never do that unilaterally."

**最终方案**（Tian 提议，Leo 确认可行）：
- 移除 `Co-developed-by` 和 `Signed-off-by: Leonardo Bras` 标签
- 在 commit message 中引用 Leo 的原始 patch：
  ```
  Based on Leonardo Bras's patch:
  https://lore.kernel.org/all/20260629111820.1873540-2-leo.bras@arm.com/
  ```
- Leo 回复："That works out for me!"

---

### Phase 2：小范围代码修复（单函数内，低风险）

- [-] 2.1 ISB 位置修正（S10 / S17 / S24）— 不采纳

多处 control-plane sysreg 写后缺少立即 ISB，不符合 ARM64 规则（isb 应紧跟 sysreg 写）：

- `__load_hdbss()` 中两个 sysreg 写之间缺少 ISB（S10）
- `kvm_flush_hdbss_buffer()` 中 `write_sysreg_s(0, SYS_HDBSSPROD_EL2)` 后先执行 `vcpu->arch.hdbss.hdbssprod_el2 = 0` 再 `isb()`，应调整为先 `isb()` 再做内存 store（S17）

**不采纳理由**：ARM ARM 没有要求每个 sysreg 写后紧跟 ISB。实际规则是 sysreg 写的效果不保证对后续指令可见，直到执行 ISB。可以批量写多个寄存器，末尾统一一个 ISB。同文件 `__load_stage2()`（`arch/arm64/include/asm/kvm_mmu.h:321`）就是批量写 `VTCR_EL2` + `VTTBR_EL2`，末尾一个 ISB。原始代码 `write BR; write PROD; isb()` 符合内核标准模式。详见文末「不采纳的 Sashiko 意见」section。

- [x] 2.2 物理地址 0 导致内存泄漏（S11）— 已解决

若 `alloc_pages()` 返回物理地址 0 且 order=0，`HDBSSBR_EL2` 值为 0，`kvm_arm_vcpu_free_hdbss()` 会跳过释放。

**修复**：使用独立标志位（如 `base_phys != 0` 改为 `hdbssbr_el2 != 0` 或添加 `allocated` 标志）判断 buffer 是否已分配。

**当前状态**：已改用 `struct page *hdbss_pg`（参考 x86 PML 的 `pml_pg`），用 `hdbss_pg != NULL` 判断 buffer 是否已分配。内核 `alloc_page()` 返回的 `struct page *` 指针不会为 NULL（除非分配失败），彻底消除物理地址 0 的歧义。

- [x] 2.3 vCPU 上下文切换保存 HDBSSPROD_EL2（Leo 间接提及，Sashiko 详细指出）— 已完成

`kvm_vcpu_put_vhe()` 未将 `HDBSSPROD_EL2` 保存回 `vcpu->arch.hdbss.hdbssprod_el2`，下次 load 时会用旧值覆盖硬件 producer index。

**修复**：在 `kvm_vcpu_put_vhe()` 中保存 `HDBSSPROD_EL2`。

**当前状态**：`arch/arm64/kvm/hyp/vhe/switch.c` 中 `kvm_vcpu_put_vhe()` 已添加：
```c
if (vcpu_hdbss_enabled(vcpu))
    vcpu->arch.hdbss.hdbssprod_el2 = read_sysreg_s(SYS_HDBSSPROD_EL2);
```

- [-] 2.4 `__load_hdbss()` 添加 `system_supports_hdbss()` 检查（S8）— 不采纳

仅检查 `kvm->arch.enable_hdbss`（v5 中改为 VTCR 检查），未检查 `system_supports_hdbss()`。若已启用但硬件不支持，访问 `SYS_HDBSSBR_EL2` 会 panic hypervisor。

**修复**：添加 `system_supports_hdbss()` 检查。

**不采纳理由**：`VTCR_EL2_HDBSS` bit 只在 `kvm_arm_enable_hdbss_global()` 中设置，该函数第一行就是 `if (!system_supports_hdbss()) return 0;`。因此 `VTCR_EL2_HDBSS == 1` 隐含 `system_supports_hdbss() == true`，`__load_hdbss()` 中再加一遍检查是纯冗余。详见文末「不采纳的 Sashiko 意见」section。

- [x] 2.5 `kvm_arm_vcpu_destroy()` 无条件释放 buffer（S23）— 已完成

如果 `KVM_CREATE_VCPU` 分配了 HDBSS buffer 但 `kvm_arm_disable_hdbss_global()` 在 vCPU 加入 online_vcpus 之前运行，全局 disable 循环会遗漏该 vCPU。VM 销毁时条件判断为 false，跳过清理。

**修复**：`kvm_arm_vcpu_destroy()` 无条件调用 `kvm_arm_vcpu_free_hdbss()`（其内部已检查 buffer 是否存在）。

**当前状态**：`arch/arm64/kvm/reset.c:166` 中 `kvm_vcpu_destroy()` 已无条件调用 `kvm_arm_vcpu_free_hdbss(vcpu)`，函数内部用 `if (!vcpu->arch.hdbss.hdbss_pg) return;` 保护空指针情况。

---

### Phase 3：中等正确性修复（多函数，中等风险）

- [x] 3.1 vCPU create 错误路径清理（S7 / S20）— 已完成

`kvm_arch_vcpu_create()` 中存在两个问题：
- 如果 `kvm_share_hyp()` 失败但 HDBSS 分配成功，err 被覆盖为 0
- 如果 `kvm_share_hyp()` 成功但 HDBSS 分配失败，未调用 `kvm_unshare_hyp()`，vcpu struct 内存仍标记为与 hypervisor 共享，释放回 host allocator 后违反 pKVM 信任边界

**修复**：正确处理错误路径，确保 `kvm_unshare_hyp()` 在 HDBSS 分配失败时被调用。

- [x] 3.2 `order` 参数语义分离（Leo 指出，S9 重复）— 已完成

`order` 同时用于 `alloc_pages()`（按 PAGE_SIZE 缩放）和 `HDBSSBR_EL2()`（期望硬件编码）。在 64KB 页上，order=9 会分配 32MB 但硬件配置为 2MB。

**修复**：区分 buddy order 和 HDBSSBR_EL2 size 编码。v5 中 buffer 大小改为 PAGE_SIZE-based 后，buddy order 固定为 0（分配单页），HDBSSBR_EL2 编码单独计算，避免混淆。

- [~] 3.3 ~~`KVM_DIRTY_LOG_INITIALLY_SET` 下 eager split 缺失~~（已被 Phase 6.2 覆盖，无需单独修复）

使用 `KVM_DIRTY_LOG_INITIALLY_SET` 时，`kvm_arch_commit_memory_region()` 提前返回，不调用 `kvm_mmu_split_memory_region()`。但这不是问题：

- INITIALLY_SET 的设计是：dirty bitmap 初始全 1，userspace 通过 CLEAR ioctl 逐批清除脏页
- CLEAR ioctl 路径会调用 wrprotect，Phase 6.2 的 wrprotect walk 会在此时将 block entry 的 DBM 和 W 清除（→RO），迫使首次写触发 fault → lazy split
- Level-3 page 保留 DBM、清 W（→WC），下次写时 HDBSS 记录
- 因此无论 INITIALLY_SET 是否提前返回，wrprotect 都会在 CLEAR 时正确处理 block/page 的 DBM 状态，eager split 和 lazy split 两种模式都被支持

- [-] 3.4 `kvm_arch_sync_dirty_log()` 遗漏非 guest 模式 vCPU 脏页（S14）— 不需要

`KVM_REQUEST_WAIT` 只等待 guest 模式中的 vCPU。已退出到 userspace 的 vCPU 的 HDBSS buffer 可能仍有未 flush 的脏页，导致 userspace 读取不完整的 dirty bitmap。

**修复**：确保所有 vCPU（包括已退出到 userspace 的）的 HDBSS buffer 都被 flush。

**不需要的理由**：vCPU 退出到 userspace 时，`kvm_arch_vcpu_put()` 会调用 `kvm_flush_hdbss_buffer()`，buffer 在到达 userspace 之前就已 flush。vCPU 在 userspace 期间不再运行 guest，不会产生新脏页。且 Phase 4.2 的 ABBA 死锁不成立（flush 不获取 `mmu_lock`），flush 不会从 `vcpu_put` 中移除。详见文末「不采纳的 Sashiko 意见」section。

- [x] 3.5 nVHE 模式下直接访问 EL2 寄存器崩溃（S16）— 已完成

`read_sysreg_s(SYS_HDBSSPROD_EL2)` 从 host kernel（EL1）访问 EL2 寄存器，nVHE 模式下触发未定义指令异常。`kvm_handle_hdbss_fault()` 中同样存在此问题。

**修复**：将 EL2 寄存器访问移到 hyp 代码中，或添加 nVHE/VHE 条件编译保护。

- [x] 3.6 全局 enable/disable 无锁竞态（S19）— 已解决

`kvm_arm_vcpu_alloc_hdbss()` 直接修改 `vcpu->arch.hdbss` 而未持有 `vcpu->mutex` 或使用 KVM vCPU requests 框架。并发运行的 vCPU 上下文切换（`__load_hdbss`）或 fault 路径可能读取部分更新的状态。

**修复**：使用 KVM vCPU requests 框架或持有适当锁来保护 per-vCPU 状态修改。

**当前状态**：已采用 PML-style 分配策略——buffer 在 vCPU create 时分配（`kvm_arch_vcpu_create()` → `kvm_arm_vcpu_alloc_hdbss()`），在 vCPU destroy 时释放。enable/disable 只修改 VM-level 的 `kvm->arch.mmu.vtcr`，不再触碰 per-vCPU 的 `vcpu->arch.hdbss` 结构体，消除了竞态。

---

### Phase 4：高优先级安全修复（关键正确性，系统级影响）

- [x] 4.1 `kvm_arm_disable_hdbss_global()` 硬件 UAF 风险（Leo 提出，S18 重复）— 已解决

Leo 指出：清除 VTCR 和释放 HDBSS buffer 后，vCPU 可能仍在 guest 模式运行，HDBSS 仍处于运行状态。如果此时有页面变脏，HDBSS 会尝试向已释放的 buffer 地址写入，导致 UAF 和宿主机内存损坏。

**修复**：释放 buffer 前必须先 kick 所有 vCPU 退出 guest 模式（类似 enable 路径的 `kvm_vcpu_kick()`）。

**当前状态**：已采用 PML-style 分配策略——buffer 在 vCPU create 时分配，vCPU destroy 时释放。`kvm_arm_disable_hdbss_global()` 只清除 `kvm->arch.mmu.vtcr` 中的 HDBSS bit 并 `kvm_make_all_cpus_request(KVM_REQ_OUTSIDE_GUEST_MODE)`，**不释放 buffer**。即使 vCPU 短暂仍在 guest 中运行，buffer 仍然有效，不存在 UAF。

- [-] 4.2 `kvm_arch_vcpu_put()` 中 flush 导致 ABBA 死锁（S12）— 不是问题

调度器抢占 vCPU 线程时，调用 `kvm_arch_vcpu_put()`（持有 `rq->lock`），内部调用 `kvm_flush_hdbss_buffer()` 获取 `mmu_lock`。其他路径获取 `mmu_lock` 后可能唤醒任务（获取 `rq->lock`），形成锁反转。

**修复**：将 flush 操作从 `vcpu_put()` 移到不持有 `rq->lock` 的上下文，或在 `vcpu_put()` 中使用延迟 flush（设置 request flag，在下一次 vcpu_run 入口处理）。

**不是问题的理由**：`kvm_flush_hdbss_buffer()` 的调用链为 `kvm_flush_hdbss_buffer()` → `kvm_vcpu_mark_page_dirty()` → `mark_page_dirty_in_slot()` → `set_bit_le()`，全程**不获取 `mmu_lock`**。ABBA 死锁的前提是 flush 持 `rq->lock` 的同时获取 `mmu_lock`，但实际上根本不碰 `mmu_lock`。详见文末「不采纳的 Sashiko 意见」section。

- [x] 4.3 `kvm_flush_hdbss_buffer()` 缺少 SRCU 保护（S13 / S21）— 已完成

`kvm_vcpu_mark_page_dirty()` 通过 `kvm_vcpu_gfn_to_memslot()` 访问 memslots 数组，需要 `srcu_read_lock(&kvm->srcu)`。从 `vcpu_put` 和 `check_vcpu_requests` 调用时未持有 SRCU，memslots 并发修改可能导致 UAF。

**修复**：在 `kvm_flush_hdbss_buffer()` 中添加 SRCU 保护。

**当前状态**：`arch/arm64/kvm/dirty_bit.c:67` 已添加 `srcu_idx = srcu_read_lock(&kvm->srcu);`，在 `for` 循环遍历 buffer entries 前获取，循环后 `srcu_read_unlock(&kvm->srcu, srcu_idx);` 释放。

- [~] 4.4 chunk size 在 16KB/64KB 页大小系统上的问题（S1 / S2 / S3）— 归入 Phase 6.3

- **S1 [High]**：`256 * 1024 * PAGE_SIZE` 在 16KB 页上为 4GB，在 64KB 页上为 16GB。ARM64 不支持这些页大小的 level 1 block，超过有效最大值（32MB 和 512MB）。
- **S2 [High]**：64 位 chunk size 赋值给 32 位有符号整数。4GB 和 16GB 会截断为 0。
- **S3 [Medium]**：`KVM_CHECK_EXTENSION` 无条件返回默认值 0，但 patch 动态改变了新 VM 的默认值，全局 API 查询会误导 userspace。

**修复**：chunk size 计算需要考虑页大小，使用正确的 block size 约束；返回值使用 64 位整数；capability 查询应反映实际默认值。

---

### Phase 5：字段设计与 buffer 策略（影响数据结构，中等改动量）

- [x] 5.1 `enable_hdbss` 字段移除 → VTCR 检查（Leo 质疑，Tian 提出替代方案）— 已完成

- **移除** `enable_hdbss` 字段，改用 `kvm->arch.mmu.vtcr & VTCR_EL2_HDBSS` 检查 HDBSS 是否启用。Leo 认可此方案。
- 仍需 `system_supports_hdbss()` 用于实际 hdbss 例程（如 `__load_hdbss()` 中检查硬件支持）。

**当前状态**：`enable_hdbss` 字段已不存在。VM-level 检查用 `kvm->arch.mmu.vtcr & VTCR_EL2_HDBSS`，vCPU-level 检查用 `vcpu_hdbss_enabled(vcpu)`（检查 `hw_mmu->vtcr`，正确处理 L2 嵌套场景）。

- [ ] 5.2 `hdbss_order` 存储格式与 `HDBSS_MAX_ORDER` 定义 — 需修改

**当前状态**：`kvm->arch.hdbss_order`（`kvm_host.h:425`）是**死字段**，整个代码库零引用。`HDBSS_MAX_ORDER`（`sysreg.h:1046`，值为 `HDBSSBR_EL2_SZ_2MB = 9`）同样无引用。

**需要做**：
- 将 `hdbss_order` 重命名为 `hdbss_buffer_size`，存 entries 数量（`PAGE_SIZE / sizeof(u64)`），放在 `kvm->arch` 层级，供 per-vCPU 分配时读取
- 删除或重定义 `HDBSS_MAX_ORDER`（PAGE_SIZE-based 策略下不再需要 SZ 编码常量作为上限）
- 为 Phase 8 dirty-ring 模式铺路：ring 模式下 buffer 大小需动态计算并存入此字段

- [ ] 5.3 HDBSS buffer 大小策略重构（Leo + Inochi Amaoto 讨论）— 需微调

**当前状态**：分配已改为 PAGE_SIZE-based（`alloc_page()` 分配一个 full page）。SZ 编码用 `PAGE_SHIFT - 12`，经验证 4KB/16KB/64KB 页均正确。

**已完成的部分**：
- 废弃 `hdbss_auto_select_order()` 函数
- dirty-bitmap 模式：每个 vCPU 分配 PAGE_SIZE 作为 buffer（默认值）
- `struct page *hdbss_pg` 替代 `base_phys`

**仍需做的**：
- 将计算出的 buffer 大小（entries 数量 = `PAGE_SIZE / sizeof(u64)`）保存到 `kvm->arch.hdbss_buffer_size`，否则新创建的 vCPU 会用未初始化的值
- 为 Phase 8 dirty-ring 模式预留：ring 模式下 buffer 大小自动设为 dirty ring 大小的一半，最小 PAGE_SIZE

**Dirty-bitmap 模式（无 dirty ring）：**
- 默认为每个 vCPU 分配一个 full page（PAGE_SIZE）作为 HDBSS buffer
- 4KB 页 → 512 entries；64KB 页 → 8192 entries
- 理由：反正每个 HDBSS buffer 至少需要一页物理连续内存，不如充分利用整页
- 用户可通过 Phase 7 的 ioctl 在创建 VM 时覆盖此默认值（见 Phase 7）

**Dirty-ring 模式（见 Phase 8）：**
- HDBSS buffer 大小自动设为 dirty ring 大小的一半（entries），向下对齐到硬件支持的 order
- 最小 buffer 大小为 PAGE_SIZE（Leo 强调）

**Inochi Amaoto 的问题（Jul 21）：**
- HDBSS 最大支持 2MB buffer（256K entries），远超 dirty ring 大小
- 如果用 `kvm_cpu_dirty_log_size()` 预留，大 buffer 会导致 dirty ring 始终触发 soft limit
- Leo 回应：HDBSS 启用后大部分 dirty log 来自 HDBSS，sw dirtying 很少，应该可以接受
- 备选方案：buffer 不全放入 dirty ring 时，将剩余 entries 移到 buffer 开头并调整 index 寄存器

**必须将计算出的 buffer 大小（entries 数量）保存到 `kvm->arch` 层级**，否则新创建的 vCPU 会用未初始化的值分配错误大小的 buffer。

#### 参考实现：Leo HACDBS V3 的 buffer 定义方式

> 源文件：`v3_20260729_leo_bras_kvm_dirty_bit_cleaning_hw_accelerator_hacdbs.mbx`（Patch 4/11, 5/11, 10/11）
>
> 注意：Leo 的 V3 用途是 **dirty-bit cleaning**（用 HACDBS 硬件清除 dirty bit），我们的 v4/v5 用途是 **dirty-page logging**（用 HDBSS 硬件记录脏页写入）。两者使用同一硬件但方向不同，buffer 管理方式也不同，但 Leo 的 entries 定义和 SZ 编码方式值得参考。

**1. Entries 数量定义（Patch 4/11, 5/11）：**

Leo 直接用 `PAGE_SIZE / sizeof(u64)` 作为 entries 数量，存为局部 `const int`：

```c
const int entries_sz = PAGE_SIZE / sizeof(*hw_entries);  /* 4KB 页 → 512 entries */
```

**2. Buffer 分配方式（临时分配，用完释放）：**

```c
hw_entries = kmalloc_objs(u64, entries_sz, GFP_KERNEL);
/* ... dirty_bit_clear() ... */
kfree(hw_entries);
```

> Leo 的场景不需要 per-vCPU 持久 buffer，每次 cleaning 操作临时分配。我们的 v4/v5 需要 per-vCPU 持久 buffer（硬件在 guest 运行时实时写入），因此用 `alloc_pages()` 分配。但 entries 数量的定义方式（`PAGE_SIZE / sizeof(u64)`）可直接参考。

**3. HDBSSBR_EL2.SZ 编码动态计算（Patch 4/11 `hacdbs_start()`）：**

```c
static void hacdbs_start(u64 *hw_entries, int size)
{
    u64 br;
    int size_b = size * sizeof(hw_entries[0]);              /* entries × 8 bytes */
    int size_p2 = max(roundup_pow_of_two(size_b), PAGE_SIZE); /* 向上对齐到 2 的幂，最小 PAGE_SIZE */

    /* buffer 没用满一整页时，在末尾放 stop entry */
    if (size_b < size_p2)
        hw_entries[size] = HDBSS_ENTRY_VALID | HDBSS_ENTRY_TTWL_RESV;

    br = (virt_to_phys(hw_entries) & HACDBSBR_EL2_BADDR_MASK) |
         FIELD_PREP(HACDBSBR_EL2_SZ, ilog2(size_p2) - 12) |
         FIELD_PREP(HACDBSBR_EL2_EN, 1);

    write_sysreg_s(br, SYS_HACDBSBR_EL2);
    isb();
}
```

> 关键点：`ilog2(size_p2) - 12` 将实际分配的字节数转为硬件编码。`size_p2` 已经是 2 的幂，`ilog2()` 精确取整无向下取整问题。我们的 v5 中如果 buffer 大小始终是 PAGE_SIZE 的倍数（dirty-bitmap 模式分配整页），同理可以直接用 `ilog2(PAGE_SIZE) - 12` 作为 SZ 编码。但如果用户通过 ioctl 配置了非 PAGE_SIZE 对齐的大小，需要像 Leo 一样先 `roundup_pow_of_two()` 再 `ilog2()`。

**4. 上下文切换：用 `preempt_notifier` 而非修改 `vcpu_put`（Patch 4/11）：**

Leo 用 `preempt_notifier` 机制在 `dirty_bit_clear()` 执行期间保存/恢复 HACDBS 寄存器：

```c
struct hacdbs_sched_save {
    struct preempt_notifier notifier;
    struct hacdbs_save save;  /* hacdbsbr_el2, hacdbscons_el2, vttbr_el2, vtcr_el2, hcr_vm_set */
};

static void hacdbs_sched_out(struct preempt_notifier *notifier, struct task_struct *next)
{
    /* 保存 HACDBSBR_EL2, HACDBSCONS_EL2, VTTBR_EL2, VTCR_EL2, HCR_EL2_VM */
    /* 禁用 HACDBS（清 EN bit），isb() */
}

static void hacdbs_sched_in(struct preempt_notifier *notifier, int cpu)
{
    /* 恢复 VTCR_EL2, VTTBR_EL2, HCR_EL2_VM, HACDBSCONS_EL2 */
    /* 注意：sched_in 不恢复 HACDBSBR_EL2（因为操作可能已在中断中 stop） */
}
```

> Leo 的 `preempt_notifier` 方案避免了在 `vcpu_put()` 中做 flush（我们 Phase 4.2 要解决的 ABBA 死锁问题），但只适用于短期 cleaning 操作。我们的 v4/v5 中 HDBSS buffer 在整个 guest 运行期间持续工作，仍需在 `vcpu_put` 中保存 `HDBSSPROD_EL2`（Phase 2.3）并处理 flush 路径。但 `preempt_notifier` 的思路可以作为备选方案参考。

---

### Phase 6：架构级重构（核心设计变更，影响面最大）

- [ ] 6.1 DBM 三态模型重构（Oliver 提出，Leo 确认可行）

Oliver 认为 DBM bit 本质上就是写权限位，建议将 dirty state 概念引入 page table library，将抽象写权限迁移到 DBM 字段，即使没有 FEAT_HAFDBS 也这样做。理由：

- 这样从 page table library 外部一切"just works"：write-protect 大页会清除 DBM，可以单独从 page descriptor 收集 dirty state
- 未来架构强制 FEAT_S2PIE 时，dirty state 管理是无条件的、与实际权限分开处理的，届时必须做此改动

三态模型：

| 状态 | DBM | S2AP[1] | 无 HTTU | 有 HTTU (HAFDBS) |
|------|-----|---------|---------|-----------------|
| Non-writable (N) | 0 | 0 | write→fault, inject | write→fault, inject |
| Writable-clean (C) | 1 | 0 | write→fault, sw C→D | write→hw C→D, no fault, HDBSS logs |
| Writable-dirty (D) | 1 | 1 | writable, no fault | writable, no fault |

具体改动：

- **移除** `KVM_PGTABLE_S2_DBM` 从 `enum kvm_pgtable_stage2_flags`
- `stage2_set_prot_attr()`：对可写页**无条件**设置 DBM（不再依赖 `pgt->flags & KVM_PGTABLE_S2_DBM`）
- `kvm_pgtable_stage2_relax_perms()`：**删除 else 分支**（不再在 W→RO 时清除 DBM）；传 !W 时不触碰 DBM
  - 注意：不管 lazy split 还是 eager split，只要通过 relax 放宽权限的可写页，都要加 DBM
  - eager split 时，拆大页是提前拆的，set_prot 时页肯定是 W 页，子页会被自然加上 DBM
  - lazy split 时，子页是 RO 页，走到 set_prot 时只设置 R 不设置 W；但如果是 relax 放宽权限（带 W），则 DBM 也会被加上
- `kvm_init_stage2_mmu()`：不再需要 `pgt->flags |= KVM_PGTABLE_S2_DBM`
- Leo 补充：可能仍需 `system_supports_hdbss()` 用于实际 hdbss 例程

- [ ] 6.2 `kvm_pgtable_stage2_wrprotect()` 区分 block/page（关键改动）

在 walker 回调 `stage2_attr_walker()` 中区分页级别：

- **Block entry（hugepage, level < KVM_PGTABLE_LAST_LEVEL）**：清除 S2AP_W **和** DBM（D→N/RO），迫使首次写触发 fault 以触发 split
- **Level-3 page（page-level）**：仅清除 S2AP_W，**保留** DBM（D→C），让 HDBSS 在下次写时重新 arm

实现示例：
```c
pte &= ~data->attr_clr;      /* wrprotect: clears S2AP_W */
pte |= data->attr_set;
if (ctx->level < KVM_PGTABLE_LAST_LEVEL)
    pte &= ~KVM_PTE_LEAF_ATTR_HI_S2_DBM;  /* strip DBM from blocks */
```

**完整生命周期（Leo Aug 10 最终方案）：**

1. Dirty-logging 开启，遍历 memslot 页表：
   - Block entry → 标记为 RO（DBM=0, S2AP_W=0）
   - Level-3 page → 标记为 WC（DBM=1, S2AP_W=0）
2. Splitting 时：将可写 block 拆分为 level-3 pages，新页面标记为 WC（DBM=1, S2AP_W=0）
3. Fault 时：split 完成后，触发 fault 的页面标记为 WD（DBM=1, S2AP_W=1）

此方案同时适用于 eager split 和 lazy split，因为 wrprotect 总是在 split 之前执行。

> Sashiko S4 已在此方案中解决：wrprotect 区分 block/page。Block 清除 DBM（→RO），page 保留 DBM（→WC）。

- [ ] 6.3 支持两种 eager split 模式（Oliver 建议，Leo 确认）

不再强制自动启用 eager splitting，而是根据用户的 eager split 设置采用不同 DBM 行为：

- **用户启用 eager splitting（chunk_size != 0）**：wrprotect 清除 block 的 DBM 和 W（→RO），然后 eager split 将 block 拆分为 level-3 pages 并标记为 WC（DBM=1, W=0）。首次写 fault 时 relax_perms 恢复 W 和 DBM（→WD），HDBSS 记录脏页。
- **用户未启用 eager splitting（chunk_size == 0，lazy split 模式）**：wrprotect 清除 block 的 DBM 和 W（→RO）。首次写 fault 时触发 lazy split，新 level-3 pages 标记为 WC，faulting page 标记为 WD。

两种模式的区别仅在于 split 时机（eager 在 dirty-logging on 时立即拆分，lazy 在首次写 fault 时拆分），但 wrprotect 对 block entry 的 DBM 清除行为一致。Leo 确认此方案不违背 Oliver 的三态模型，因为 block 被标记为 RO、page 被标记为 WC 都是有效的 "not dirty" 状态。

---

### Phase 7：Dirty-bitmap 模式 HDBSS buffer size ioctl（Leo + Inochi 已达成一致）

- [ ] 7.1 添加 `KVM_CAP_ARM_HDBSS_BUFFER_SIZE` capability

**设计决策（Leo + Inochi 已达成一致）：**
- Dirty-ring 模式：kernel 自动配置 buffer 大小，**不暴露 ioctl**
- Dirty-bitmap 模式：**允许用户在创建 VM 时通过 ioctl 配置 HDBSS buffer 大小**
- 理由（Leo + Inochi）：buffer 大小更多取决于 workload，kernel 无法预测；dirty-ring 模式下 buffer 与 ring 大小有耦合关系，不应让用户单独配置

**接口单位：entries（条目数，每个 entry 为 u64 = 8 bytes）**

选择 entries 而非 bytes 或 SZ 编码的理由：
- 与 PML 的 `PML_LOG_NR_ENTRIES` 风格一致，用户不需要知道硬件 SZ 编码
- HDBSS buffer 的有效载荷是 entries 数组，用 entries 更直观
- kernel 内部做 entries → bytes → `roundup_pow_of_two` → `ilog2()-12` = SZ 编码的转换

**与 QEMU 现有实现的差异（需要先 revert 再重实现）：**

QEMU 中已存在 4 个 HDBSS 相关 commit（`e549f32b1a`, `e8587f657f`, `d13e44fe04`, `ff64aed3c8`），使用旧设计：
- 旧 cap 号：`KVM_CAP_ARM_HW_DIRTY_STATE_TRACK 502`（自定义编号，不在 mainline）
- 旧参数：`hdbss-buffer-size` (uint8, 范围 0-9，SZ 编码值)
- 旧调用时机：迁移开始时 `kvm_update_hdbss_cap(true, sz)` / 结束时 `kvm_update_hdbss_cap(false, 0)`
- 旧设计问题：QEMU 在迁移时调用 enable/disable，但 vCPU 已经创建，buffer 分配时机与 PML-style 设计冲突

新设计改为：
- 新 cap 号：`KVM_CAP_ARM_HDBSS_BUFFER_SIZE 250`（mainline 顺序，最后是 249）
- 新参数：`hdbss-buffer-size` (uint32, entries)
- 新调用时机：VM 创建时（vCPU 创建前）设置 buffer size，迁移时不再需要调 enable/disable

#### Kernel 侧改动清单

**1. `include/uapi/linux/kvm.h` — 新增 capability 编号**

```c
#define KVM_CAP_ARM_HDBSS_BUFFER_SIZE 250
```

**2. `arch/arm64/include/asm/kvm_host.h` — 新增 per-VM 字段**

```c
struct kvm_arch {
    ...
    /* HDBSS: per-VM buffer size in entries (0 = not configured, use default) */
    u32 hdbss_buffer_size;
    ...
};
```

**3. `arch/arm64/include/asm/kvm_dirty_bit.h` — MIN/MAX 定义**

```c
/* Default HDBSS buffer size: one full page per vCPU */
#define KVM_ARM_HDBSS_DEFAULT_ENTRIES  (PAGE_SIZE / sizeof(u64))

/* Maximum HDBSS buffer size: 2MB (HDBSSBR_EL2_SZ_2MB, hardware limit) */
#define KVM_ARM_HDBSS_MAX_ENTRIES      (SZ_2M / sizeof(u64))
```

**4. `arch/arm64/kvm/arm.c` — `kvm_vm_ioctl_check_extension()`**

```c
case KVM_CAP_ARM_HDBSS_BUFFER_SIZE:
    if (!system_supports_hdbss())
        r = 0;
    else if (kvm)
        r = kvm->arch.hdbss_buffer_size ?: KVM_ARM_HDBSS_DEFAULT_ENTRIES;
    else
        r = 0;  /* No global query, buffer size is per-VM */
    break;
```

**5. `arch/arm64/kvm/arm.c` — `kvm_vm_ioctl_enable_cap()`**

```c
case KVM_CAP_ARM_HDBSS_BUFFER_SIZE: {
    u32 entries = cap->args[0];

    if (!system_supports_hdbss())
        break;  /* -EINVAL */
    if (kvm->dirty_ring_size)  /* Mutually exclusive with dirty ring */
        break;
    if (entries < KVM_ARM_HDBSS_DEFAULT_ENTRIES || entries > KVM_ARM_HDBSS_MAX_ENTRIES)
        break;
    if (!is_power_of_2(entries))  /* Hardware requires power-of-2 entries */
        break;

    mutex_lock(&kvm->lock);
    if (kvm->created_vcpus) {
        r = -EINVAL;  /* Must set before vCPU creation */
    } else if (kvm->arch.hdbss_buffer_size) {
        r = -EBUSY;   /* Already configured */
    } else {
        kvm->arch.hdbss_buffer_size = entries;
        r = 0;
    }
    mutex_unlock(&kvm->lock);
    break;
}
```

**6. `arch/arm64/kvm/dirty_bit.c` — `kvm_arm_vcpu_alloc_hdbss()` 适配**

从 `kvm->arch.hdbss_buffer_size` 读取 entries，计算 buddy order 和 SZ 编码：

```c
int kvm_arm_vcpu_alloc_hdbss(struct kvm_vcpu *vcpu)
{
    struct page *hdbss_pg;
    u32 entries;
    size_t size_bytes;
    size_t size_p2;
    unsigned int buddy_order;
    u32 sz_encoded;

    if (vcpu->arch.hdbss.hdbss_pg || !system_supports_hdbss())
        return 0;

    entries = vcpu->kvm->arch.hdbss_buffer_size ?: KVM_ARM_HDBSS_DEFAULT_ENTRIES;
    size_bytes = entries * sizeof(u64);
    size_p2 = roundup_pow_of_two(size_bytes);
    /* size_p2 is guaranteed >= PAGE_SIZE since entries >= PAGE_SIZE/sizeof(u64) */
    buddy_order = get_order(size_p2);
    sz_encoded = ilog2(size_p2) - 12;

    hdbss_pg = alloc_pages(GFP_KERNEL_ACCOUNT, buddy_order);
    if (!hdbss_pg)
        return -ENOMEM;

    vcpu->arch.hdbss = (struct vcpu_hdbss_state) {
        .hdbss_pg = hdbss_pg,
        .hdbssbr_el2 = HDBSSBR_EL2(page_to_phys(hdbss_pg), sz_encoded),
        .hdbssprod_el2 = 0,
    };

    return 0;
}
```

注意：`size_p2` 可能大于 `size_bytes`（例如 entries=600 → size_bytes=4800 → size_p2=8192）。
此时 buffer 有 1024 个 entry 的空间但只用 600 个，多余的 entry 在 flush 时因 `HDBSS_ENTRY_VALID` bit 未设而被跳过。
如果需要精确控制，可在末尾放 stop entry（参考 Leo HACDBS V3 的 `HDBSS_ENTRY_TTWL_RESV`）。

**7. `arch/arm64/kvm/dirty_bit.c` — `kvm_flush_hdbss_buffer()` 适配**

flush 循环的上限改用 `kvm->arch.hdbss_buffer_size`（entries）而非 `HDBSSPROD_IDX(prod)`：

```c
void kvm_flush_hdbss_buffer(struct kvm_vcpu *vcpu)
{
    ...
    u32 entries = vcpu->kvm->arch.hdbss_buffer_size ?: KVM_ARM_HDBSS_DEFAULT_ENTRIES;
    ...
    for (idx = 0; idx < min(curr_idx, entries); idx++) {
        ...
    }
}
```

注意：`curr_idx`（硬件 PROD index）不应超过 `entries`，但加 `min()` 防御性编程以防硬件异常。

**8. `Documentation/virt/kvm/api.rst` — 新增 `7.48 KVM_CAP_ARM_HDBSS_BUFFER_SIZE`**

```rst
7.48 KVM_CAP_ARM_HDBSS_BUFFER_SIZE
----------------------------------

:Architectures: arm64
:Target: VM
:Parameters: arg[0] is the desired HDBSS buffer size in entries (number of u64 slots)
:Returns: 0 on success;
          -EINVAL if vCPUs have already been created,
          if dirty logging is already enabled,
          if dirty ring mode is enabled (kvm->dirty_ring_size != 0),
          if the system does not support HDBSS (system_supports_hdbss() == false),
          or if the requested size is out of range or not a power of two;
          -EBUSY if HDBSS buffer size is already configured.

This capability allows userspace to configure the HDBSS (Hardware Dirty
Bit State Structure) buffer size for a VM before any vCPUs are created.
HDBSS provides hardware-accelerated dirty page tracking for live migration
on ARM64 systems with FEAT_HDBSS support.

The buffer size is specified in entries, where each entry is a u64
(8 bytes). The kernel converts this to the appropriate HDBSSBR_EL2.SZ
encoding internally. Valid range:

  - Minimum: PAGE_SIZE / sizeof(u64)  (512 entries on 4KB pages)
  - Maximum: SZ_2M / sizeof(u64)      (262144 entries)
  - Must be a power of two

If not configured by userspace, the default is PAGE_SIZE / sizeof(u64)
(one full page per vCPU), which is sufficient for most workloads.

HDBSS is automatically enabled when dirty logging is turned on for any
memslot, and automatically disabled when all memslots stop dirty logging.
Userspace does not need to explicitly enable or disable HDBSS during
migration — only the buffer size needs to be configured (once, at VM
creation time).

This capability is only available in dirty-bitmap mode (not dirty ring
mode). In dirty ring mode, the buffer size is automatically derived from
the dirty ring size.

Calling KVM_CHECK_EXTENSION with this capability on a VM instance returns
the current buffer size in entries, or the default if not yet configured.
Without a VM instance, returns 0.
```

#### QEMU 侧改动清单

**Step 1: Revert 旧 HDBSS 实现**

Revert 以下 4 个 commit（按时间倒序）：
1. `ff64aed3c8` — hw/arm/virt: HDBSS: fix arm-softmmu build on x86 platform
2. `d13e44fe04` — hw/arm/virt: decouple migrate_hdbss_buffer_size() with kvm_update_hdbss_cap()
3. `e8587f657f` — hw/arm/virt: only support the HDBSS feature in aarch64
4. `e549f32b1a` — hw/arm/virt: support the HDBSS feature

涉及文件：
- `linux-headers/linux/kvm.h` — 移除 `KVM_CAP_ARM_HW_DIRTY_STATE_TRACK 502`
- `include/sysemu/kvm.h` — 移除旧 `DEFAULT_HDBSS_BUFFER_SIZE` / `MAX_HDBSS_BUFFER_SIZE` / `kvm_update_hdbss_cap()`
- `accel/kvm/kvm-all.c` — 移除 `kvm_update_hdbss_cap()` 实现
- `accel/stubs/kvm-stub.c` — 移除 stub
- `migration/migration.h` — 移除 `hdbss_buffer_size` 字段
- `migration/options.c` / `options.h` — 移除 migration parameter get/set
- `migration/migration-hmp-cmds.c` — 移除 HMP 命令
- `migration/ram.c` — 移除迁移时的 `kvm_update_hdbss_cap()` 调用
- `qapi/migration.json` — 移除 `hdbss-buffer-size` 参数

**Step 2: 重新实现新接口**

| 文件 | 改动 |
|------|------|
| `linux-headers/linux/kvm.h` | 新增 `#define KVM_CAP_ARM_HDBSS_BUFFER_SIZE 250` |
| `include/sysemu/kvm.h` | `DEFAULT_HDBSS_BUFFER_SIZE = 512`（entries），`MAX_HDBSS_BUFFER_SIZE = 262144`，声明 `int kvm_set_hdbss_buffer_size(KVMState *s, uint32_t entries)` |
| `accel/kvm/kvm-all.c` | 新增 `kvm_set_hdbss_buffer_size()`：调用 `kvm_vm_enable_cap(s, KVM_CAP_ARM_HDBSS_BUFFER_SIZE, 0, entries)`，在 VM init 后、vCPU 创建前调用 |
| `accel/stubs/kvm-stub.c` | 新增 stub |
| `qapi/migration.json` | `hdbss-buffer-size` 改为 `uint32`，语义为 entries |
| `migration/options.c` | 更新 get/set，类型从 uint8 改为 uint32 |
| `migration/migration-hmp-cmds.c` | 更新 HMP 命令 |
| `migration/ram.c` | **移除**迁移时的 enable/disable 调用（kernel 自动随 dirty logging 切换 VTCR）；在 VM init 路径中调用 `kvm_set_hdbss_buffer_size()` |

**关键设计变化总结：**

| | 旧设计（QEMU 已有） | 新设计 |
|---|---|---|
| 参数单位 | SZ 编码 (0-9) | entries (512 - 262144) |
| 参数类型 | uint8 | uint32 |
| Cap 号 | 502 (自定义) | 250 (mainline 顺序) |
| Cap 名称 | `KVM_CAP_ARM_HW_DIRTY_STATE_TRACK` | `KVM_CAP_ARM_HDBSS_BUFFER_SIZE` |
| 调用时机 | 迁移开始/结束时 | VM 创建时（vCPU 创建前） |
| enable/disable | QEMU 控制 | Kernel 自动（随 dirty logging on/off） |
| Buffer 分配 | 迁移时动态分配 | vCPU create 时分配（PML-style） |

#### 实现顺序

1. **先 revert QEMU 的 4 个 HDBSS commit**
2. **Kernel 侧**：
   a. `include/uapi/linux/kvm.h` — 定义 cap 号 250
   b. `arch/arm64/include/asm/kvm_host.h` — 新增 `u32 hdbss_buffer_size` 字段
   c. `arch/arm64/include/asm/kvm_dirty_bit.h` — `KVM_ARM_HDBSS_DEFAULT_ENTRIES` / `KVM_ARM_HDBSS_MAX_ENTRIES` 定义
   d. `arch/arm64/kvm/arm.c` — `kvm_vm_ioctl_check_extension()` + `kvm_vm_ioctl_enable_cap()`
   e. `arch/arm64/kvm/dirty_bit.c` — `kvm_arm_vcpu_alloc_hdbss()` 适配 + `kvm_flush_hdbss_buffer()` 适配
   f. `Documentation/virt/kvm/api.rst` — 新增 `7.48` section
3. **QEMU 侧**：
   a. `linux-headers/linux/kvm.h` — 新 cap 定义
   b. `include/sysemu/kvm.h` — 新常量和函数声明
   c. `accel/kvm/kvm-all.c` — `kvm_set_hdbss_buffer_size()` 实现
   d. `accel/stubs/kvm-stub.c` — stub
   e. `qapi/migration.json` — 参数改 uint32
   f. `migration/options.c` / `migration-hmp-cmds.c` — 适配
   g. `migration/ram.c` — 移除旧调用，新增 VM init 调用

---

### Phase 8：Dirty Ring 支持（最后一个任务）

- [ ] 8.1 `kvm_vcpu_mark_page_dirty()` 与 dirty ring 互斥（Leo 指出）

v4 明确不支持 dirty ring（`kvm_arm_enable_hdbss_global()` 中检查 `kvm->dirty_ring_size` 并拒绝启用）。但 `kvm_vcpu_mark_page_dirty()` 在 dirty ring 模式下会向 ring 写入。需在 `kvm_flush_hdbss_buffer()` 中添加注释说明此互斥关系。

**v5 目标**：实现 dirty ring 支持。

- [ ] 8.2 Dirty ring 适配方案（Leo + Inochi Amaoto 讨论）

**Buffer 大小：**
- HDBSS buffer 大小自动设为 dirty ring 大小的一半（entries），向下对齐到硬件支持的 order
- 最小 buffer 大小为 PAGE_SIZE（Leo 强调）
- 不需要修改 dirty ring 配置接口：只要在 `kvm_dirty_ring_get_rsvd_entries() -> kvm_cpu_dirty_log_size()` 中返回 HDBSS buffer entry 数，就能在 `kvm_vm_ioctl_enable_dirty_log_ring()` 配置 dirty ring 大小时拦截掉不满足条件的值

**Reservation 机制（参考 PML）：**
- 实现 `kvm_cpu_dirty_log_size()` 返回 HDBSS buffer entry 数
- `kvm_dirty_ring_get_rsvd_entries()` = `KVM_DIRTY_RING_RSVD_ENTRIES + hdbss_entries`
- `soft_limit = dirty_ring_size - rsvd_entries`，保证 HDBSS flush 有足够空间
- 当 soft_limit 被触发时，`mark_page_dirty_in_slot() -> kvm_dirty_ring_push() -> kvm_dirty_ring_soft_full` 会设置 `KVM_REQ_DIRTY_RING_FULL`，下次 `vcpu_run` 退出到 userspace 让 QEMU drain ring

**Flush 策略：**
- 在 guest_exit 时尽量 drain HDBSS 到 dirty ring
- 如果 HDBSS buffer 大于 dirty ring 剩余空间，备选方案：将剩余 entries 移到 buffer 开头并调整 index 寄存器；或保持 guest_exitting 直到所有 HDBSS entries 都写入 dirty ring

**Inochi Amaoto 的关注点（Jul 21）：**
- 大 HDBSS buffer（2MB = 256K entries）会导致 dirty ring 始终触发 soft limit
- 用户设置大 buffer 是为了减少 context switch，soft limit 频繁触发会适得其反
- 可能需要调整 dirty ring framework 的 soft limit 检查逻辑
- Leo 回应：HDBSS 启用后 sw dirtying 很少，大部分 dirty log 来自 HDBSS，应该可以接受
- Inochi 确认：HDBSS 启用时 dirty log 主要来自 HDBSS，soft limit 检查主要依赖 HDBSS 状态

**关于 soft_limit 的疑问（已解答）：**
- 问：既然 mark dirty 时会触发 request 让虚机退到 guest 去清 dirty ring，为什么还要修改 soft_limit？
- 答：因为 HDBSS flush 是在 kernel 中一次性完成的（tight loop），不会在 flush 过程中响应 soft limit。如果 dirty ring 没有预留足够空间，flush 时 ring push 会失败并静默丢弃脏页。soft_limit 的作用是确保在 flush 开始之前就有足够空间。

---

# Sashiko AI Bot 检视意见（待确认）

以下由 Sashiko AI review bot 自动生成，**尚未经人工确认是否为真实问题**。已在上方任务清单中标注解决状态的此处不再重复。

---

## Patch 1/6: Enable eager hugepage splitting if HDBSS is available

### S1. [High] chunk size 在 16KB/64KB 页大小系统上产生架构无效的 block size

> 归入 Phase 6.3（重设计 split 模式时一起修）。

### S2. [High] KVM_CHECK_EXTENSION 中整数截断

> 归入 Phase 6.3。

### S3. [Medium] 全局 capability 查询与动态默认值不同步

> 归入 Phase 6.3。

---

## Patch 3/6: Add auto DBM support for hardware dirty tracking

### S4. [Critical] `kvm_pgtable_stage2_wrprotect()` 未清除 DBM bit

> 已在 Phase 6.2 中解决。

### S5. [Medium] VTCR_EL2.HD 从未设置 — 不采纳

`kvm_get_vtcr()` 中未包含 `VTCR_EL2_HD` bit，硬件会忽略 DBM bit。

> **不采纳理由**：Sashiko 只看了 `kvm_get_vtcr()`（stage-2 初始化时调用），漏掉了运行时 enable 路径。`kvm_arm_enable_hdbss_global()`（`dirty_bit.c:141`）在 dirty logging 开启时已设置 `VTCR_EL2_HD`：
> ```c
> kvm->arch.mmu.vtcr |= VTCR_EL2_HD | VTCR_EL2_HDBSS | VTCR_EL2_HA;
> ```
> `kvm_get_vtcr()` 是初始化函数，HDBSS 的 HD/HDBSS/HA bit 在运行时由 enable 函数动态添加。Sashiko 未追溯完整调用链。

### S6. [Medium] pKVM 模式下 DBM 未启用 — 不需要

pKVM 模式下 host 的 pgt 是 dummy 结构，实际 stage-2 页表在 EL2 通过 `pkvm_guest_prepare_stage2()` 初始化，无条件传递 `flags=0`，导致 `KVM_PGTABLE_S2_DBM` 被忽略。

> **不需要的理由**：HDBSS 要求 VHE 模式（`has_vhe_hdbss()` 检查 `is_kernel_in_hyp_mode()`），pKVM 运行在 nVHE 模式，`system_supports_hdbss()` 返回 false。pKVM 不调用 `kvm_arm_enable_hdbss_global()`，`VTCR_EL2.HD` 永远为 0，硬件忽略 DBM bit（无害）。Phase 6.1 后 DBM 无条件设置到 PTE 中，但 pKVM 路径 `kvm_guest_prepare_stage2()`（`mem_protect.c:296`）传 `flags=0`，不过这不会造成问题——没有 `HD=1`，硬件不会自动设 dirty bit，DBM bit 只是 PTE 中的一个被忽略的字段。pKVM 的 HDBSS 支持不在本 patch series 范围内。

---

## Patch 4/6: Add HDBSS per-vCPU buffer management

### S7. [High] vCPU create 错误路径掩盖 `kvm_share_hyp()` 失败

> 已完成。

### S8. [High] `__load_hdbss()` 在无 HDBSS 硬件上触发 UNDEFINED 异常

> 不采纳。详见文末「不采纳的 Sashiko 意见」section。

### S9. [High] `order` 参数在不同 page granule 下解释不同

> 已完成。

### S10. [Medium] `__load_hdbss()` 中两个 sysreg 写之间缺少 ISB

> 不采纳。详见文末「不采纳的 Sashiko 意见」section。

### S11. [Low] 物理地址 0 导致内存泄漏

> 已解决。改用 `struct page *hdbss_pg`，用 `hdbss_pg != NULL` 判断。详见文末「不采纳的 Sashiko 意见」section。

---

## Patch 5/6: Add HDBSS fault handling and buffer flush

### S12. [Critical] `kvm_arch_vcpu_put()` 中 flush 导致 ABBA 死锁

> 不是问题。`kvm_flush_hdbss_buffer()` 全程不获取 `mmu_lock`。详见文末「不采纳的 Sashiko 意见」section。

### S13. [High] `kvm_flush_hdbss_buffer()` 缺少 SRCU 保护

> 已完成。已添加 `srcu_read_lock(&kvm->srcu)`。

### S14. [High] `kvm_arch_sync_dirty_log()` 遗漏非 guest 模式 vCPU 的脏页

> 不需要。`vcpu_put()` 在 vCPU 到达 userspace 前已 flush。详见文末「不采纳的 Sashiko 意见」section。

### S15. [High] flush 循环可能溢出 dirty ring

> 已在 Phase 8.2 中处理（dirty ring reservation 机制）。

### S16. [High] nVHE 模式下直接访问 EL2 寄存器崩溃

> 已完成。

### S17. [Medium] `write_sysreg_s()` 和 `isb()` 之间有内存 store

> 不采纳。与 S10 同理。详见文末「不采纳的 Sashiko 意见」section。

---

## Patch 6/6: Add auto HDBSS enable/disable on dirty logging change

### S18. [Critical] `kvm_arm_disable_hdbss_global()` 同步释放 buffer 导致硬件 UAF

> 不是问题。disable 不释放 buffer（PML-style 分配）。详见文末「不采纳的 Sashiko 意见」section。

### S19. [High] 全局 enable/disable 函数无锁直接修改 per-vCPU 状态

> 已解决。PML-style 分配消除竞态，enable/disable 只改 VM-level VTCR。

### S20. [High] vCPU create 错误路径缺少 `kvm_unshare_hyp()`

> 已完成。与 S7 同一修复。

### S21. [High] flush HDBSS buffer 时未持有 SRCU 保护

> 与 S13 重复。已完成。

### S22. [Medium] 动态计算的 HDBSS buffer order 未保存

> 归入 Phase 5.2/5.3。`hdbss_auto_select_order()` 已废弃，改为 PAGE_SIZE-based 分配。需将 entries 数量保存到 `kvm->arch.hdbss_buffer_size`。

### S23. [Medium] `kvm_arm_vcpu_destroy()` 中 TOCTOU 竞态导致泄漏

> 已完成。`kvm_vcpu_destroy()` 无条件调用 `kvm_arm_vcpu_free_hdbss()`。

### S24. [Medium] control-plane sysreg 写后缺少立即 ISB

> 不采纳。与 S10、S17 同理。详见文末「不采纳的 Sashiko 意见」section。

---

## 不采纳的 Sashiko 意见及理由

以下 Sashiko AI bot 提出的意见经分析后决定不采纳（或标记为误报），记录理由如下：

### S8. [High] `__load_hdbss()` 在无 HDBSS 硬件上触发 UNDEFINED 异常 — 冗余检查，降级为误报

**Sashiko 原文**（Patch 4/6，mbox 第 2836-2841 行）：

> [Severity: High]
> Will __load_hdbss() trigger a fatal UNDEFINED exception on hardware without HDBSS? The function relies solely on kvm->arch.enable_hdbss. If it is enabled but the hardware lacks support, accessing SYS_HDBSSBR_EL2 could panic the hypervisor.

**不采纳理由**：`enable_hdbss` 只在 `kvm_arm_enable_hdbss_global()` 中被设为 `true`，而该函数第一行就是 `if (!system_supports_hdbss()) return 0;`。`system_supports_hdbss()` 是启动时检测的静态能力，运行时不变。因此 `enable_hdbss == true` 隐含 `system_supports_hdbss() == true`，`__load_hdbss()` 中再加一遍检查是冗余的。Sashiko 未追溯完整调用链。

### S10 / S17 / S24. [Medium] sysreg 写后缺少立即 ISB — ARM64 规则被过度简化

**Sashiko 原文 S10**（Patch 4/6，mbox 第 2845-2849 行）：

> [Severity: Medium]
> Is an isb() required immediately after writing to SYS_HDBSSBR_EL2? ARM64 subsystem rules state that every write to a control-plane system register must be followed by an isb() as the very next instruction.

**Sashiko 原文 S17**（Patch 5/6，mbox 第 2633-2641 行）：

> [Severity: Medium]
> Is the context synchronization event misplaced here?
>
> The architectural rules state that every write to a control-plane system register must be followed by an isb() as the very next instruction.
>
> There is a memory store (vcpu->arch.hdbss.hdbssprod_el2 = 0) placed between the write_sysreg_s() and the isb(). Could this leave the CPU operating under a stale configuration for several cycles?

**不采纳理由**：ARM ARM 没有这条规则。实际规则是：sysreg 写的效果不保证对后续指令可见，直到执行 ISB。可以批量写多个寄存器，末尾统一一个 ISB。同文件中的 `__load_stage2()`（`arch/arm64/include/asm/kvm_mmu.h:321`）就是批量写 `VTCR_EL2` + `VTTBR_EL2`，末尾一个 ISB，中间无 ISB。原始代码 `write BR; write PROD; isb()` 符合内核标准模式，额外加的中间 ISB 无害但多余，与内核风格不一致。Sashiko 对 ARM64 sysreg 语义理解不准确。

### S14. [High] `kvm_arch_sync_dirty_log()` 遗漏非 guest 模式 vCPU 脏页 — 当前代码不是问题

**Sashiko 原文**（Patch 5/6，mbox 第 2555-2565 行）：

> [Severity: High]
> Will this wait for vCPUs that have exited to userspace?
>
> The KVM_REQUEST_WAIT flag causes KVM to wait only for vCPUs that are currently executing in guest mode. If a vCPU has exited the guest to host userspace, it is not in guest mode, but its HDBSS hardware buffer might still contain unflushed dirty pages.
>
> Since the flush request is pended but not waited for, could this return immediately and cause userspace to read an incomplete dirty bitmap during live migration?

**不采纳理由**：vCPU 退出到 userspace 时，`kvm_arch_vcpu_run()` 的退出路径会调用 `vcpu_put()` → `kvm_arch_vcpu_put()` → `kvm_flush_hdbss_buffer()`。因此在 vCPU 到达 userspace **之前** buffer 就已经被 flush 了。vCPU 在 userspace 期间不再运行 guest，不会有新的脏页写入。Sashiko 没有分析 `vcpu_put()` 路径，漏掉了这步 flush。

> 注：Phase 4.2 的 ABBA 死锁经分析不成立（`kvm_flush_hdbss_buffer()` 全程不获取 `mmu_lock`），flush 不会从 `vcpu_put()` 中移除，S14 永久不是问题。

### Phase 3.3 `KVM_DIRTY_LOG_INITIALLY_SET` 下 eager split 缺失 — 已被 Phase 6.2 覆盖

**Sashiko 原文**（Patch 6/6，mbox 第 2302-2314 行）：

> [Severity: High]
> Does this early return violate the HDBSS requirement for eager page table splitting?
>
> The commit message states that enabling HDBSS requires disabling lazy split so that all block mappings are eagerly broken down before the buffer starts recording. However, if userspace utilizes KVM_DIRTY_LOG_INITIALLY_SET, this path returns early without calling kvm_mmu_split_memory_region().
>
> Since HDBSS was already globally enabled earlier in this function, could it now operate on block mappings instead of page-granularity tables, defeating the hardware expectation and corrupting the dirty log state?

**不采纳理由**：INITIALLY_SET 的设计是 dirty bitmap 初始全 1，userspace 通过 CLEAR ioctl 逐批清除脏页。CLEAR 路径会调用 wrprotect，Phase 6.2 的 wrprotect walk 会将 block entry 的 DBM 和 W 清除（→RO），迫使首次写触发 fault → lazy split；level-3 page 保留 DBM、清 W（→WC），下次写时 HDBSS 记录。因此不管 INITIALLY_SET 是否提前返回，wrprotect 都会在 CLEAR 时正确处理 block/page 的 DBM 状态，eager split 和 lazy split 两种模式都被支持。无需在 Phase 3 单独修复。

### Phase 2.2 (S11) 物理地址 0 导致内存泄漏 — 已正确修复

**Sashiko 原文**（Patch 4/6，mbox 第 2812-2815 行）：

> [Severity: Low]
> Could this leak the buffer if the buddy allocator returns physical address 0 and order is 0? The resulting HDBSSBR_EL2 value would be 0, causing this early return to intercept a valid allocation.

**修复历程**：v4 中检查 `hdbssbr_el2 != 0`，若物理地址为 0 则 `HDBSSBR_EL2` 值为 0，误判为未分配而跳过释放。中间修复改为检查 `base_phys != 0`，但 `base_phys = page_to_phys(hdbss_pg)`，物理地址 0 时同样为 0，只是搬运了同一个 bug。

**最终修复**：改用 `struct page *hdbss_pg` 指针（参考 x86 PML 的 `pml_pg`），用 `hdbss_pg != NULL` 判断 buffer 是否已分配。`alloc_page()` 成功时返回的 `struct page *` 指针不会为 NULL（即使物理地址为 0），彻底消除了物理地址 0 的歧义。`kvm_arm_vcpu_free_hdbss()` 和 `kvm_flush_hdbss_buffer()` 均已改为检查 `hdbss_pg`。

### Phase 4.1 (S18) `kvm_arm_disable_hdbss_global()` 硬件 UAF — 不是问题

**Sashiko 原文**（Patch 6/6，mbox 中 S18）：

> [Severity: Critical]
> 清除 VTCR 和释放 HDBSS buffer 后，vCPU 可能仍在 guest 模式运行，HDBSS 仍处于运行状态。如果此时有页面变脏，HDBSS 会尝试向已释放的 buffer 地址写入，导致 UAF 和宿主机内存损坏。

**不是问题的理由**：当前代码采用 PML-style 分配策略——HDBSS buffer 在 vCPU create 时分配（`kvm_arch_vcpu_create()` → `kvm_arm_vcpu_alloc_hdbss()`），在 vCPU destroy 时释放（`kvm_vcpu_destroy()` → `kvm_arm_vcpu_free_hdbss()`）。`kvm_arm_disable_hdbss_global()` 只清除 `kvm->arch.mmu.vtcr` 中的 HDBSS bit 并 `kvm_make_all_cpus_request(KVM_REQ_OUTSIDE_GUEST_MODE)` kick 所有 vCPU 退出 guest 模式，**不释放 buffer**。即使 vCPU 短暂仍在 guest 中运行，buffer 仍然有效，不存在 UAF。Leo 和 Sashiko 分析的前提（disable 同时释放 buffer）在当前代码中不成立。

### Phase 4.2 (S12) `kvm_arch_vcpu_put()` 中 flush 导致 ABBA 死锁 — 不是问题

**Sashiko 原文**（Patch 5/6，mbox 中 S12）：

> [Severity: Critical]
> 调度器抢占 vCPU 线程时，调用 `kvm_arch_vcpu_put()`（持有 `rq->lock`），内部调用 `kvm_flush_hdbss_buffer()` 获取 `mmu_lock`。其他路径获取 `mmu_lock` 后可能唤醒任务（获取 `rq->lock`），形成锁反转。

**不是问题的理由**：`kvm_flush_hdbss_buffer()` 的完整调用链为：
```
kvm_flush_hdbss_buffer()
  → kvm_vcpu_mark_page_dirty(vcpu, gfn)
    → kvm_vcpu_gfn_to_memslot(vcpu, gfn)   // SRCU 保护
    → mark_page_dirty_in_slot(kvm, memslot, gfn)
      → set_bit_le(rel_gfn, memslot->dirty_bitmap)  // 仅原子 bit 操作
```
全程**不获取 `mmu_lock`**。ABBA 死锁的前提是 flush 持 `rq->lock` 的同时获取 `mmu_lock`，但 `mark_page_dirty_in_slot()` 只做 `set_bit_le()` 原子操作和 SRCU 保护的 memslot 查找，不碰 `mmu_lock`。锁反转不存在。Sashiko 误以为 `kvm_vcpu_mark_page_dirty()` 会获取 `mmu_lock`，实际不会。

---

## 不支持嵌套虚拟化 HDBSS 的架构理由

### 背景

当前代码中 `vcpu_hdbss_enabled()` 通过检查 `hw_mmu->vtcr & VTCR_EL2_HDBSS` 在 L2 运行时正确禁用 HDBSS，L2 走传统 write-protect 进行脏页跟踪。此处说明不在软件层面对 L2 模拟 HDBSS（类似 x86 `nested_vmx_write_pml_buffer`）的架构原因。

### ARM spec 的架构限制

**1. HDBSSBR_EL2 / HDBSSPROD_EL2 是纯 EL2 寄存器，EL1 无架构接口**

ARM ARM 中 HDBSSBR_EL2（buffer 基地址 + 大小配置）和 HDBSSPROD_EL2（producer index + fault 状态）均为 EL2 寄存器。L1 guest hypervisor 运行在 EL1（通过 `HCR_EL2.NV` trap-and-emulate），**没有架构定义的方式访问这两个寄存器**。L1 如果执行 `MRS HDBSSBR_EL2`，会触发 trap 到 L0，L0 查 NV trap 表和 sysreg 描述符表均无条目，最终注入 UNDEF 异常给 L1。

**2. HDBSS fault 没有面向 EL1 的 trap 或异常接口**

HDBSS buffer 满时，硬件通过 `HDBSSPROD_EL2.FSC` 字段报告 fault 状态，这是一个 EL2 寄存器内的字段。ARM spec **没有定义** 将 HDBSS fault 作为 EL1 可见的同步异常或 trap 进行路由的机制。与 stage-2 fault（通过 ESR_EL2.ISC + HPFAR_EL2 报告，可被 L0 拦截并转发给 L1）不同，HDBSS fault 没有对应的 EL1 异常类型。

**3. 与 x86 PML 的关键架构差异**

x86 PML 的嵌套虚拟化软件模拟（`nested_vmx_write_pml_buffer`）之所以可行，是因为：

| | x86 PML | ARM HDBSS |
|---|---|---|
| L1 可见性 | VMCS 字段（`pml_address`、`guest_pml_index`）架构上对 L1 可见，L1 通过 VMREAD/VMWRITE 直接访问 | HDBSSBR_EL2/HDBSSPROD_EL2 纯 EL2，L1 无架构接口 |
| L1 配置能力 | L1 在自己的 VMCS12 中配置 PML | L1 无对应控制结构 |
| Fault 路由 | PML_FULL VM exit 有明确的 VM exit reason，L0 可注入给 L1 | HDBSS fault 走 `HDBSSPROD_EL2.FSC`（EL2 内部），无 EL1 异常接口 |
| 软件模拟可行性 | L0 读 L1 的 VMCS12 字段，直接写 L1 的 PML buffer 内存 | L1 没有"自己的 HDBSS buffer"概念，无法为 L1 模拟 |

x86 的 VMCS 是一个**架构定义的、L1 可访问的**控制结构，L0 可以读写 L1 的 VMCS12（"virtual VMCS"），因此能软件模拟 PML。ARM 的 HDBSS 寄存器没有等价的 L1 可见控制结构。

### 结论

根据 ARM spec，HDBSS 从架构设计上就是 EL2 专属功能，没有为 EL1 定义配置接口或异常路由机制。因此：

1. **无法为 L1 软件模拟 HDBSS**：L1 没有"自己的 HDBSSBR_EL2/HDBSSPROD_EL2"概念，L0 无从读写 L1 的虚拟 HDBSS 配置
2. **无法将 HDBSS fault 转发给 L1**：没有面向 EL1 的 HDBSS 异常类型
3. **L2 走 write-protect 是唯一正确选择**：`vcpu_hdbss_enabled()` 通过 `hw_mmu->vtcr` 在 L2 运行时返回 false，L2 的脏页通过 shadow stage-2 的 write-protect fault 跟踪，`kvm_nested_s2_wp()` 确保 shadow stage-2 也被正确 write-protect

如果未来 ARM spec 扩展 HDBSS 支持嵌套虚拟化（例如定义 L1 可见的虚拟 HDBSS 控制接口和 fault 路由），届时可以重新评估软件模拟方案。
