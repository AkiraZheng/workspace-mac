# Sashiko AI Review 分析与回复(v5 系列)

线程:https://lore.kernel.org/all/20260929103655.85107-1-zhengtian10@huawei.com/

sashiko-bot 共回复 6 封(patch 04 / 09 / 10 / 11 / 12 / 14),合计 14 条 finding。

**结论:5 个真问题(已出修复补丁)、3 个设计项(留待 v6)、5 条误报(回复中说明理由)。**

修复补丁在 `../bugfix_patches/`(3 个,分支 `hdbss-v5_review_fixes`,
base 7.3-rc5 + v5 系列)。

---

## 一、逐条分析(中文)

### 1. [Critical] nVHE 下 host panic(patch 04 与 patch 12 各报一次,同一根因)

**Bot 的说法**:`check_vcpu_requests()` 在 host 上下文调 `__load_stage2()`,
nVHE 下 host 在 EL1,写 `vtcr_el2`/`vttbr_el2` 触发 UNDEFINED,陷入 hyp 后
panic;普通用户可经 /dev/kvm 触发 DoS。

**判定:真 bug,且触发条件比 bot 说的更宽。**

证据链(逐环核实):

1. upstream 基线(7.3-rc5)`kvm_get_vtcr()`(hyp/pgtable.c)在
   CONFIG_ARM64_HW_AFDBM(默认 y)下**无条件置 VTCR_EL2_HA**,仅 Ampere
   AC03_CPU_38 workaround 除外 → 初始 `kvm->arch.mmu.vtcr` 带 HA
2. 两个使能能力都是 VHE-only:`kvm_supports_hafdbs()`(kvm_mmu.h:393)含
   `has_vhe()`;`kvm_supports_hdbss()` 走的 ARM64_HAS_HDBSS 能力 matcher 是
   `has_vhe_hdbss()` = `is_kernel_in_hyp_mode() && ...`(cpufeature.c:2161)
   → nVHE 下派生 target 恒为 0
3. 首次 memslot commit → `kvm_arch_update_hw_dirty_mode()`:cur = HA ≠
   target = 0 → 翻转 + `kvm_make_all_cpus_request(KVM_REQ_RELOAD_STAGE2)`
   (mmu.c,唯一 setter)
4. handler(arm.c `check_vcpu_requests`)调 vhe/switch.c 的
   `__load_stage2()`;hyp/Makefile 中 `obj-$(CONFIG_KVM) += vhe/ nvhe/`,
   vhe 对象永远链进 vmlinux → nVHE **能编译通过**,纯运行时炸弹

**不需要任何 HAFDBS 硬件**——任何 CONFIG_ARM64_HW_AFDBM 的 nVHE/pKVM
系统,建 VM + 一个 memslot + 跑 vCPU 即崩。修复:见补丁 0001。

### 2. [High] Ampere AC03_CPU_38 erratum 被覆盖(patch 12)

**Bot 的说法**:`kvm_get_vtcr()` 按 erratum 屏蔽 HA,而派生 target 在
hafdbs 为真时无条件设 HA,任何 memslot 更新都会覆盖 workaround。

**判定:真 bug。** erratum 不影响 ARM64_HW_DBM 能力位,所以
`kvm_supports_hafdbs()` 在 AmpereOne 上仍为真,target HD|HA(或
HD|HA|HDBSS)把 HA 加回去。修复:`kvm_supports_hafdbs()` 增加
`!cpus_have_final_cap(ARM64_WORKAROUND_AMPERE_AC03_CPU_38)`(补丁 0001)。
附带效应:VHE 但无 DBM 硬件的系统不再静默清掉 upstream 的 HA 默认位。

### 3. [High] kvm_has_nv() 门控时序(patch 12)

**Bot 的说法**:logging memslot 先于 vCPU 创建时 `kvm_has_nv()` 为假,
HDBSS 被打开;之后 INIT HAS_EL2 不重算,HDBSS 对嵌套 VM 保持开启。

**判定:真 bug。** `kvm_has_nv()`(kvm_nested.h:10)依赖
`kvm_vcpu_has_feature(kvm, KVM_ARM_VCPU_HAS_EL2)`,而 vcpu_features 只在
首次 `KVM_ARM_VCPU_INIT` 时由 `__kvm_vcpu_set_target()`(arm.c:1753)
拷贝,该路径无任何重算。这同时说明"纯函数"的前提(kvm_has_nv 是静态量)
不成立。修复:首次 set_target 成功后重算模式(补丁 0002)。

### 4. [Medium] mmu->vtcr 数据竞争(patch 12)

**判定:真,轻微。** 写侧在 slots_lock 下 plain RMW,读侧
`kvm_hw_dirty_enabled()` 在 fault 路径无锁读,LKMM/KCSAN 层面是数据竞争
(实际 tearing 风险极低)。修复:两侧 READ_ONCE/WRITE_ONCE(补丁 0001)。

### 5. [Low] 跨架构编译失败(patch 10,两条同根)

**判定:真 bug。** `kvm_vm_ioctl_enable_dirty_log_ring()`
(virt/kvm/kvm_main.c:4983)**无 config 门控无条件编译**;而
`kvm_arch_dirty_ring_size_updated()` 原型只在 kvm_dirty_ring.h 的
`#else /* CONFIG_HAVE_KVM_DIRTY_RING */`(启用)分支,weak 定义在
config 门控的 dirty_ring.o → 非 ring 架构(s390x/powerpc 等)隐式声明 +
链接失败。修复:补 stub(补丁 0003)。

### 6. [High] 64K 页系统 ring 尺寸 ABI 回退(patch 11)

**判定:真,属设计权衡。** ring 预留 = 64 + buffer/8 项;
`KVM_ARM_HDBSS_DEFAULT_SIZE = PAGE_SIZE`(kvm_dirty_bit.h:19)→ 64K 页
系统 buffer=64K → 预留 8256 项 → 原本合法的 64KB ring 请求被 -EINVAL。

**可选修复**:ring 模式把 buffer 钉到 SZ_4K 而非 PAGE_SIZE——分配侧
get_order(SZ_4K) 在 64K 内核仍是整页,但 HDBSSBR_EL2.SZ 编码的是逻辑
大小(2^(SZ+12),最小 4K,与内核页大小无关),预留降为 576 项,所有既有
ring 尺寸继续合法。代价是 16K/64K 系统 ring 模式下缓冲变小(每次 VM exit
都会 flush,影响有限)。留待 v6 决策。

### 7. [Medium] ring 使能静默重置 buffer size(patch 14)

**判定:设计问题。** 与反方向(先 ring 后设 size → -EINVAL)不对称。
建议 v6 改为同样报错(hook 需改返回 int)。

### 8. [Low] CHECK_EXTENSION 返回可变 VM 状态(patch 14)

**判定:可商榷。** per-VM 回读挂在 cap 查询上;可改为专用 GET ioctl,
听 maintainer 意见。

### 9. [Critical] 运行中 vCPU 持陈旧 VTCR 丢脏页(patch 14)

**判定:误报。** 陈旧窗口的行为恰好就是 !logging 的 HAFDBS 模式
(HD|HA、promote 不记 HDBSS)——系列本身已论证该模式对记账安全:

- promote 把脏状态留在 PTE(S2AP[1]=1),同一次 memslot commit 里排在
  模式翻转**之后**的 write-protect 遍历会重读 PTE 并收割 WD → 记入
  脏位图(wrprotect walker 对 S2AP[1]=1 的项调 mark_page_dirty)
- 页面被写保护后,后续写无论 VTCR 新旧都会 fault——写权限在 PTE 的
  DBM 位,不在 VTCR
- 反向翻转(HDBSS→HD|HA)期间陈旧 vCPU 仍向 buffer 记账,exit flush
  照常收敛;logging 已关,bitmap 无消费者,无害

### 10. [High] wrprotect walker 覆盖并发硬件更新(patch 14)

**判定:误报。** 代码注释已论证,构造上不相交:

- walker 只重写读到的**已脏**项(old S2AP[1]=1)或需要去 DBM 的 block;
  硬件只 promote **干净**项(S2AP[1]=0)——两者不碰同一 PTE 的同一位
- 叶表项 WC(new==old)根本不写,无碰撞面
- AF 丢失:下次访问补设,无害
- block 去 DBM 与并发 promote 竞态:该次写在 HDBSS buffer 有记录、
  folio 在 fault-in 时已标脏,双保险

### 11. [High ×2] WARN 可被 guest 触发(patch 09)

**判定:误报。** ESR_EL2 由硬件在异常时合成,guest 无法伪造 L0 的退出
ESR;非 HDBSS 硬件上 HDBSSF 为 RES0,硬件不会置位 → 两个 WARN_ON 守的是
host/硬件不变量,不是 guest 输入。unexpected FSC 的 WARN_ONCE 同理。

### 12. [High] HDBSSF 检查未按 EC 门控、IABT 会误路由(patch 09)

**判定:误报,且不门控反而是对的。** DDI 0487 M.b(p.D24-8784)在
**Instruction Abort 的 ISS2 布局里同样定义了 HDBSSF(bit 11)**,并注明
"only applies for stage 2 Permission faults,RES0 for any other fault"
——IABT 也可能是 HDBSS 引起的 fault,统一处理正确;其他 fault 该位
RES0,不存在巧合置位。

---

## 二、修复补丁(3 个,已放 ../bugfix_patches/)

| 补丁 | 修复 | 对应 finding |
|---|---|---|
| 0001 Keep the derived dirty mode on VHE systems | nVHE panic + Ampere erratum + VHE 无 DBM 静默清 HA + vtcr ONCE 标注 | #1 #2 #4 |
| 0002 Recompute the dirty mode at vCPU INIT | kvm_has_nv() 时序 | #3 |
| 0003 Add the dirty ring size hook stub | 跨架构编译 | #5 |

#6 #7 #8 为设计项,见上文,v6 处理。**未编译验证**(环境无内核构建配置)。

---

## 三、回复 sashiko 的文本(英文,可直接发送)

```
Thank you for the reviews. Replying to the six sashiko reports in one
go: five findings are real and fixed, four are false positives, and
three are design points I plan to settle in v6.

Real and fixed:

1. (Critical, 04/12) nVHE host panic. The reload request is handled in
   host context and calls the VHE __load_stage2(), which writes the
   EL2 registers. The trigger is even wider than suggested: on nVHE
   the derived target is always off, which is not the initial state
   either, as kvm_get_vtcr() sets VTCR_EL2.HA unconditionally. So the
   first memslot commit of every nVHE VM flips the mode and raises the
   request, no HAFDBS hardware involved. The whole mode update now
   stays out unless the HAFDBS mode is available.

2. (High, 12) Ampere AC03_CPU_38. The derived target sets HA
   unconditionally, undoing the erratum workaround on any memslot
   update. The erratum is now excluded from kvm_supports_hafdbs(),
   which also covers the HDBSS mode.

3. (High, 12) kvm_has_nv() timing. The flag only becomes true at the
   first KVM_ARM_VCPU_INIT, so a logging memslot created before that
   point derives the HDBSS mode with NV invisible, and a vCPU then
   initialized with HAS_EL2 keeps HDBSS on for a nested guest. The
   mode is now recomputed once the vCPU features are fixed.

4. (Low, 10) Cross-arch build. kvm_vm_ioctl_enable_dirty_log_ring()
   is built for every architecture, but the hook prototype and the
   weak definition are both behind CONFIG_HAVE_KVM_DIRTY_RING. The
   missing stub is added.

5. (Medium, 12) The plain VTCR_EL2 read-modify-write races with the
   lockless kvm_hw_dirty_enabled() readers; both sides now use
   READ_ONCE/WRITE_ONCE.

Design points for v6:

- (High, 11) On 64K-page systems the ring reservation grows to 8192
  entries and previously valid ring sizes are rejected. The buffer
  allocation cannot go below the page size, but HDBSSBR_EL2.SZ allows
  a 4KB buffer on any page size, so pinning the ring-mode buffer to
  SZ_4K keeps every existing ring size valid. I plan to do that.

- (Medium, 14) Enabling the ring silently resets a configured buffer
  size, which is asymmetric with the other direction rejecting with
  -EINVAL. Making the ring enable fail as well is the more predictable
  UAPI.

- (Low, 14) Returning the configured size from KVM_CHECK_EXTENSION is
  a readback on a cap interface; happy to move it to a dedicated GET
  if preferred.

False positives:

- (Critical, 14) Stale VTCR_EL2 on running vCPUs. The stale window
  behaves exactly like the !logging HAFDBS mode, which the series
  already accounts for: writes promote writable-clean PTEs to
  writable-dirty without a buffer record, and the write-protect pass
  of the same memslot commit re-reads those PTEs and harvests them
  into the dirty bitmap. Once a page is write-protected, later writes
  fault regardless of VTCR_EL2, as the write permission lives in the
  PTE (DBM), not in the VTCR.

- (High, 14) stage2_wrprotect_walker() clobbering. The walker only
  rewrites entries it observed as already dirty, while hardware only
  promotes clean entries, so the dirty updates cannot collide. A lost
  AF update is refetched on the next access, and a racing promotion
  of a block that loses its DBM is still recorded in the HDBSS buffer
  and was marked on the folio at fault-in.

- (High, 09) The WARNs guard host and hardware invariants: ESR_EL2 is
  synthesized by hardware and HDBSSF is RES0 unless hardware raised an
  HDBSS fault, so a guest cannot reach them.

- (High, 09) The HDBSSF check is deliberately not gated by the
  exception class: the architecture defines HDBSSF in the ISS2 layout
  of Instruction Aborts as well (DDI 0487 M.b), and the field is RES0
  for any other fault.

The fixes will be folded into v6.
```
