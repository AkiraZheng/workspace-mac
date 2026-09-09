# HAFDBS-only（非 HDBSS）路径正确性验证

> 问题：Leo 的系列在没有 HDBSS 的机器上，非迁移期页表是 WC、硬件自动升 WD；迁移期关掉 DBM
> 能力（HD=0）后"标脏还是依赖 S2AP 位走传统软件流程"——这条路径正确吗？
>
> 结论先行：**架构上正确**。迁移期的行为与经典（pre-DBM）流程**逐点同构**，只是"RO"的编码
> 从 `(S2AP_W=0, DBM=0)` 换成了 `(S2AP_W=0, DBM=1)`，其余 fault→标脏→放权的循环原封不动。
> 原始系列有 5 个伴生缺陷（HA 缺失、folio 记账、TLBI、VGA 悬崖、vtcr 竞态），已在
> code_v5_3_leo 分支以 F1-F4/R1 修复。

## 0. 对提问中两个表述的精确化

1. **"关掉后页表都是 WC 状态"——HD 关闭不改任何 PTE**。HD 位只是解释权的切换：同样的
   WC 编码，HD=1 时硬件读作"可写·干净"（写被放行并升 WD），HD=0 时读作"只读"（写触发
   Permission Fault）。真正把页表归一的是**随后运行的 wp**：
   - page（level 3）：清 S2AP_W，WD→**WC**（保留 DBM）
   - block（level < 3）：清 S2AP_W **和 DBM**，→**N**（不是 WC！为了逼出 lazy split 的 fault）
   - 从未写过的 WC page：`ctx->old != new` 检查跳过，零开销
2. **"标脏依赖 S2AP 位"——精确说法是三段分工**：
   - **信号** = Permission Fault（HD=0 时 WC 的 S2AP_W=0 挡住写）
   - **账本** = memslot 的 dirty bitmap（fault 处理器里 `mark_page_dirty_in_slot` 写入）
   - **放权** = relax 置回 DBM|S2AP_W（`kvm_pgtable_stage2_relax_perms`，写 fault 恒带 DIRTY）
   S2AP_W 本身不"记账"，它被清零的**副作用**（配合 HD=0）制造 fault；位图才是账本。

## 1. 四阶段状态机（HAFDBS-only 机器）

```
阶段一 非迁移 (HD=1, HA=1)
  读 fault ──compute_prot──> WC        (W 无 DIRTY)
  写 fault ──compute_prot──> WD        (W+DIRTY) 
  WC 被写 ──硬件免 fault───> WD        (S2AP_W 0→1, 无 VM exit)
  状态分布: 只有真写过的页是 WD, 其余 WC

阶段二 迁移开始 (logging on)
  kvm_arch_update_hw_dirty_mode: HD|HA 清零 + RELOAD_STAGE2 + VMID TLBI
    └─ RELOAD 的 KVM_REQUEST_WAIT 保证: 返回后无 vCPU 在 guest 里
       → wp 期间不可能发生硬件升级 (与 wp 的 WRITE_ONCE 无并发)
    └─ 翻转窗口内的写(旧 TLB 可写条目): 发生在 ioctl 返回前
       → 由 QEMU 初始全量拷贝覆盖, 迁移协议不需要这段的脏
  wp: page WD→WC, block →N (剥 DBM); 从未写过的 WC 跳过
  eager split (可选) / 留给 lazy

阶段三 迁移迭代期 (HD=0)  ← "传统软件标脏流程"
  WC ≡ RO (S2AP_W=0, 硬件不认 DBM)
  写 WC ──Permission Fault──> relax (W+DIRTY) → WD + bitmap 标脏
  读 fault ──> WC (logging ⇒ 不给 DIRTY), 保持"RO"语义等价
  CLEAR: KVM_MMU_LOCK(写) 内 [原子清位图 + wp(WD→WC)] → 锁外 flush TLB
    └─ 写 fault 与 CLEAR 的并发: 写锁互斥, 二者必居其一
       (a) fault 先: 位图已标, CLEAR 读走它  (b) wp 先: 写 fault 再标

阶段四 迁移结束 (logging 全停)
  HD|HA 回开 + VMID TLBI
  存量 WC 页(含迁移期读 fault 建的)立即恢复硬件可升级 —— 无缝回阶段一
```

## 2. 不变式验证清单

| # | 不变式 | 验证 |
|---|---|---|
| I1 | 迁移期（HD=0）无"静默可写"路径 | 硬件不认 DBM，唯一可写编码是 S2AP_W=1（WD），而 WD 只能经 relax 产生 ✓ |
| I2 | wp 与硬件升级无并发 | 模式翻转的 RELOAD(WAIT) 先于 wp，wp 期间无 vCPU 在 guest ✓ |
| I3 | wp 与 relax 无并发 | wp 走 mmu **写**锁（`stage2_apply_range` 持锁）+ 裸 WRITE_ONCE；relax 走 **读**锁（`kvm_fault_lock`）+ cmpxchg（`stage2_try_set_pte`）。读写锁互斥 ✓ |
| I4 | HD 翻转窗口的写不丢 | 全部发生在 `KVM_SET_USER_MEMORY_REGION` 返回前 → 初始全量拷贝覆盖（auto 与 manual-initially-set 两种模式均成立）✓ |
| I5 | 迁移期 WD ⟺ bitmap 已标 | WD 唯一来源是 relax，relax 的调用方（`kvm_s2_fault_map`）恒配 `mark_page_dirty_in_slot`（`dirty && !ret`，dirty=写 fault 恒真）✓ |
| I6 | CLEAR 协议保序 | `kvm_clear_dirty_log_protect`：MMU 写锁内 `atomic_long_fetch_andnot` 清位图 + `kvm_arch_mmu_enable_log_dirty_pt_masked` wp，锁外 `kvm_flush_remote_tlbs_memslot`——与经典完全一致，Leo 系列未触碰此结构 ✓ |
| I7 | S1PTW（guest 硬件更新自己的 S1 描述符）过 S2 | HD=1：隐式写被硬件放行（免 fault，**额外红利**：guest 内核 DBM 不再引发 S1PTW fault 风暴）；HD=0：S1PTW Permission Fault → `kvm_is_write_fault` 判写 → relax WD ✓ |
| I8 | 解码端对 WC 的解释与经典 RO 等价 | split 继承（WC 父→WC 子 ≡ RO 父→RO 子）；PERMS 掩码含 DBM（并发缺页过滤不受影响）；ptdump 仅显示 ✓ |
| I9 | eager split 输入正确 | split 只在 logging 语境运行，wp 先行保证 block 已是 N（无 DBM 可继承，子页 N→写 fault→lazy 恢复）✓ |

## 3. 原始系列的伴生缺陷（非路径本身错误，但该路径直接踩中）

| 缺陷 | 对该路径的影响 | 修复 |
|---|---|---|
| HD 不带 HA | 规格疑违规（S1/SMMU/HDBSS 先例都是成对开） | F1：`VTCR_EL2_HD \| VTCR_EL2_HA` |
| folio 记账缺口 | 非迁移期硬件升 WD 的页，host folio 永不标脏 → 回收丢写 | F2（fault 时投机标脏）+ harvest（unmap/wp 精确收割） |
| HD 翻转无 TLBI | 迁移**结束**方向：旧 RO 缓存翻译拖住收益兑现 | F3：翻转后 VMID TLBI（`cpu_enable_hw_dbm` 样板） |
| VGA 悬崖 | **恰恰发生在这条路径**：非 HDBSS 机器上任一 slot logging → 全局 HD off → 非 logging slot 读 fault 仍建 WC（静态能力判断）→ HD=0 下 WC=RO → 每页一 fault | F4：compute_prot 改看动态 `vtcr & VTCR_EL2_HD` |
| vtcr 无锁 RMW 竞态 | setup_vcpu 与 set_hafdbs 交错可致 HD=1+logging 并存 → 静默丢脏 | R1：纯推导状态机消灭 RMW |

注意：F4 的悬崖**只**打击非 HDBSS 机器——HDBSS 机器迁移期 HD 常开（buffer 接管记账），
天然免疫。这也解释了两条路径的分工：HDBSS = 免 fault 跟踪，HAFDBS-only = 经典 fault 跟踪
+ 编码换皮。

## 4. 这套设计的优雅之处

1. **WC 的双重性格**：同一个编码 `(DBM=1, S2AP_W=0)`，HD=1 时可写、HD=0 时只读。
   迁移边界（HD 翻转）**不需要重映射任何页表**——只翻一个 VTCR 位，所有 WC 页的语义
   自动切换。
2. **wp 的 skip 优化**：`ctx->old != new` 让从未写过的 WC 页跳过原子写。这正是 Leo
   commit message "keeping dirty only the pages that have been actually written to"
   的兑现形式：迁移开始的 wp 只碰真脏页，mmu_lock 持锁时间随实际写入量而非总页数伸缩。
3. **guest S1 DBM 的意外红利**：guest 内核开 TCR_EL1.HD 更新自己的 S1 描述符时，隐式写
   过 S2 在 HD=1 下被硬件放行——经典流程里这些 S1PTW fault 消失了。
4. **迁移结束零过渡成本**：迁移期读 fault 建的 WC 页，HD 回开后立即恢复硬件升级资格，
   无需重新 fault。

## 5. 附带关闭的疑问：HDBSS drain 的非 logging slot 条目（原 R1c）

`mark_page_dirty_in_slot`（virt/kvm/kvm_main.c）开头即检查
`kvm_slot_dirty_track_enabled(memslot)`（= `flags & KVM_MEM_LOG_DIRTY_PAGES`）——
**bitmap 和 dirty ring 两种模式都自动丢弃非 logging slot 的标脏请求**。因此 HDBSS drain
对非 logging slot 条目（如仅个别 slot 参与迁移的场景）无需显式过滤，原"VMM 侧过滤还是
drain 侧过滤"的 open question 以"已隐式过滤"关闭。

## 6. 验证环境

以上分析基于 code_v5_3_leo 分支逐点核对（F1-F4/R1 已合入）：
`kvm_arch_update_hw_dirty_mode`（mmu.c）、`stage2_wrprotect_walker`（hyp/pgtable.c）、
`kvm_s2_fault_compute_prot` 的 F4 动态判断、`kvm_fault_lock`（读锁）/`stage2_try_set_pte`
（cmpxchg）、`kvm_clear_dirty_log_protect`（CLEAR 协议）。
